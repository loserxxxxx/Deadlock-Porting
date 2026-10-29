import atexit
import os
from pathlib import Path
import re
import secrets
import time
import uuid
import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix
from .protocol import PROTOCOL, root_path, read_json, atomic_json, signature, authenticated, fingerprint

_session = None
_generation = 0
_pending = {}
_results = {}
_status = 'Not connected'
_last_import = ''


def scene_id():
    return f'{_generation}:{bpy.context.scene.as_pointer()}'


def heartbeat():
    if _session is None:
        return
    project = bpy.data.filepath
    payload = dict(protocol=PROTOCOL, id=_session['id'], token=_session['token'], pid=os.getpid(),
                   heartbeat=time.time(), binary=bpy.app.binary_path, project_path=project,
                   name=Path(project).stem if project else 'Untitled', scene=bpy.context.scene.name,
                   scene_id=scene_id(), version=bpy.app.version_string, status=_status)
    atomic_json(root_path() / 'sessions' / (_session['id'] + '.json'), payload)


def append_asset(request):
    target = bpy.context.scene
    previous_active = bpy.context.view_layer.objects.active
    previous_selection = list(bpy.context.selected_objects)
    previous_mode = bpy.context.mode
    before = {name: set(getattr(bpy.data, name)) for name in ('objects', 'collections', 'scenes', 'meshes', 'armatures', 'materials', 'images', 'actions', 'node_groups')}
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        with bpy.data.libraries.load(request['asset'], link=False) as (available, imported):
            if not available.scenes:
                raise RuntimeError('The exported asset contains no scene')
            imported.scenes = [available.scenes[0]]
        asset_scene = imported.scenes[0]
        if asset_scene is None:
            raise RuntimeError('Could not append the exported scene')
        collection = bpy.data.collections.new('Deadlock - ' + request['label'])
        target.collection.children.link(collection)
        collection['deadlock_export'] = True
        collection['deadlock_request_id'] = request['request_id']
        for child in list(asset_scene.collection.children):
            collection.children.link(child)
        for obj in list(asset_scene.collection.objects):
            collection.objects.link(obj)
        added = set(bpy.data.objects) - before['objects']
        shapes = {bone.custom_shape for obj in added if obj.type == 'ARMATURE' for bone in obj.pose.bones if bone.custom_shape}
        visible = [obj for obj in added if obj.type in {'MESH', 'ARMATURE'} and not obj.hide_render and obj not in shapes]
        if not visible:
            raise RuntimeError('The exported asset contains no visible models')
        offset = Matrix.Translation(target.cursor.location)
        for obj in visible:
            if obj.parent not in added:
                obj.matrix_world = offset @ obj.matrix_world
        bpy.data.scenes.remove(asset_scene)
        bpy.context.view_layer.update()
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        active = next((obj for obj in visible if obj.type == 'ARMATURE'), visible[0])
        active.select_set(True)
        bpy.context.view_layer.objects.active = active
        return dict(collection=collection.name, objects=len(visible))
    except Exception:
        added = [item for name, existing in before.items() for item in set(getattr(bpy.data, name)) - existing]
        if added:
            bpy.data.batch_remove(ids=added)
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj in previous_selection)
        if previous_active and previous_active.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = previous_active
            if previous_mode == 'POSE':
                bpy.ops.object.mode_set(mode='POSE')
        raise


class DLP_LIVE_OT_import(bpy.types.Operator):
    bl_idname = 'deadlock_porting_live.import_asset'
    bl_label = 'Receive Deadlock model'
    bl_options = {'REGISTER', 'UNDO'}
    request_id: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        request = _pending.get(self.request_id)
        if request is None:
            return {'CANCELLED'}
        try:
            result = append_asset(request)
            _results[self.request_id] = dict(ok=True, **result)
            return {'FINISHED'}
        except Exception as error:
            _results[self.request_id] = dict(ok=False, error=str(error))
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


def process_request(path):
    global _status, _last_import
    request = read_json(path)
    identifier = request.get('request_id', '')
    if not re.fullmatch('[a-f0-9]{32}', identifier) or path.stem != identifier or not authenticated(request, _session['token']):
        path.unlink(missing_ok=True)
        return
    receipt = path.parent.parent / 'receipts' / path.name
    if receipt.is_file():
        previous = read_json(receipt)
        if authenticated(previous, _session['token']):
            path.unlink(missing_ok=True)
            return
    response = dict(protocol=PROTOCOL, request_id=identifier, session_id=_session['id'])
    try:
        if request.get('protocol') != PROTOCOL or request.get('session_id') != _session['id']:
            raise RuntimeError('Incompatible app or Blender session')
        if time.time() > request.get('expires', 0):
            raise RuntimeError('The import request expired. Export the model again.')
        if request.get('expected_scene') != scene_id() or request.get('expected_project') != bpy.data.filepath:
            raise RuntimeError('Blender changed scenes or projects during export. Select the current session and try again.')
        asset = Path(request.get('asset', ''))
        if not asset.is_absolute() or asset.suffix.lower() != '.blend' or not asset.is_file():
            raise RuntimeError('The exported Blender file is unavailable')
        if fingerprint(asset) != request.get('sha256'):
            raise RuntimeError('The exported file changed before import')
        existing = next((c for c in bpy.context.scene.collection.children if c.get('deadlock_request_id') == identifier), None)
        if existing:
            response.update(ok=True, collection=existing.name, objects=len(existing.all_objects))
        else:
            _pending[identifier] = request
            try:
                if bpy.context.preferences.edit.use_global_undo and bpy.ops.ed.undo_push.poll():
                    bpy.ops.ed.undo_push(message='Before Deadlock import')
                bpy.ops.deadlock_porting_live.import_asset('EXEC_DEFAULT', True, request_id=identifier)
                response.update(_results.get(identifier, dict(ok=False, error='The import could not start in the current Blender context')))
            finally:
                _pending.pop(identifier, None)
                _results.pop(identifier, None)
        if response.get('ok'):
            _last_import = request['label']
            _status = 'Ready to receive exports'
    except Exception as error:
        response.update(ok=False, error=str(error))
        _status = str(error)
    response['signature'] = signature(response, _session['token'])
    atomic_json(receipt, response)
    path.unlink(missing_ok=True)


def tick():
    global _status
    if _session is None:
        return None
    try:
        inbox = root_path() / 'queues' / _session['id'] / 'requests'
        pending = sorted(inbox.glob('*.json'), key=lambda p: p.stat().st_mtime) if inbox.is_dir() else []
        if pending:
            if bpy.app.is_job_running('RENDER'):
                _status = 'Waiting for the Blender render to finish'
            elif bpy.context.mode not in {'OBJECT', 'POSE'}:
                _status = 'Switch Blender to Object or Pose Mode to receive the model'
            else:
                _status = 'Importing model into the current scene'
                heartbeat()
                process_request(pending[0])
        elif _status.startswith(('Waiting', 'Switch')):
            _status = 'Ready to receive exports'
        heartbeat()
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception as error:
        _status = str(error)
    return 1.0


def start():
    global _session, _status
    if _session is not None:
        return
    _session = dict(id=uuid.uuid4().hex, token=secrets.token_hex(32))
    _status = 'Ready to receive exports'
    heartbeat()
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=.2, persistent=True)


def stop():
    global _session, _status
    if _session:
        (root_path() / 'sessions' / (_session['id'] + '.json')).unlink(missing_ok=True)
    _session = None
    _status = 'Not connected'
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)


@persistent
def loaded(_):
    global _generation
    _generation += 1
    if _session:
        heartbeat()


class DLP_LIVE_OT_toggle(bpy.types.Operator):
    bl_idname = 'deadlock_porting_live.toggle'
    bl_label = 'Toggle live exports'

    def execute(self, context):
        stop() if _session else start()
        return {'FINISHED'}


class DLP_LIVE_PT_panel(bpy.types.Panel):
    bl_label = 'Deadlock Porting'
    bl_idname = 'DLP_LIVE_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Deadlock Porting'

    def draw(self, context):
        layout = self.layout
        layout.operator('deadlock_porting_live.toggle', text='Disconnect' if _session else 'Receive exports', icon='LINKED' if _session else 'UNLINKED')
        layout.label(text=_status[:65])
        layout.label(text='Imports into the current scene at the 3D cursor.')
        layout.label(text='Save your project in Blender when ready.')
        if _last_import:
            layout.label(text='Last import: ' + _last_import[:40])


classes = (DLP_LIVE_OT_import, DLP_LIVE_OT_toggle, DLP_LIVE_PT_panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(loaded)
    start()


def unregister():
    stop()
    if loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(loaded)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


atexit.register(lambda: (root_path() / 'sessions' / (_session['id'] + '.json')).unlink(missing_ok=True) if _session else None)
