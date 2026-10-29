"""Append a finished export to a saved project, preserving its scenes/settings."""
import sys
from pathlib import Path
import bpy
from mathutils import Matrix

project, source, destination = sys.argv[sys.argv.index('--') + 1:]
bpy.ops.wm.open_mainfile(filepath=project, load_ui=False, use_scripts=False)
scene = bpy.context.scene
if bpy.context.object and bpy.context.object.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
before = set(bpy.data.objects)
with bpy.data.libraries.load(source, link=False) as (available, imported):
    if not available.scenes:
        raise RuntimeError('The exported asset contains no scene')
    imported.scenes = [available.scenes[0]]
asset_scene = imported.scenes[0]
if asset_scene is None:
    raise RuntimeError('Could not append the exported asset')
collection = bpy.data.collections.new('Deadlock - ' + Path(source).stem)
collection['deadlock_export'] = True
scene.collection.children.link(collection)
for child in list(asset_scene.collection.children):
    collection.children.link(child)
for obj in list(asset_scene.collection.objects):
    collection.objects.link(obj)
added = [obj for obj in bpy.data.objects if obj not in before]
shapes = {bone.custom_shape for obj in added if obj.type == 'ARMATURE'
          for bone in obj.pose.bones if bone.custom_shape is not None}
visible = [obj for obj in added if obj.type in {'MESH', 'ARMATURE'} and not obj.hide_render and obj not in shapes]
if not visible:
    raise RuntimeError('The exported asset contains no visible objects')

offset = Matrix.Translation(scene.cursor.location)
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
if active.type == 'ARMATURE':
    bpy.ops.object.mode_set(mode='POSE')
    if 'root' in active.data.bones:
        active.data.bones.active = active.data.bones['root']
bpy.ops.wm.save_as_mainfile(filepath=destination, relative_remap=False)
print(f'PROJECT_APPEND_COMPLETE: {collection.name}; {len(visible)} objects', flush=True)
