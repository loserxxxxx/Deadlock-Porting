"""Deadlock Porting: import a hero exported by deadlock_port.py and pose it.

Sidebar tab "Deadlock" in the 3D view (press N).
"""
import os
from math import radians

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import library, names, rig, studio, uemodel

FIST = {'thumb': 35.0, 'index': 85.0, 'middle': 90.0, 'ring': 90.0, 'pinky': 90.0}


def active_rig(context):
    obj = context.active_object
    if obj is not None and obj.type == 'MESH' and obj.parent and obj.parent.type == 'ARMATURE':
        obj = obj.parent
    return obj if obj is not None and obj.type == 'ARMATURE' else None


class DL_OT_import_hero(bpy.types.Operator, ImportHelper):
    """Import a Deadlock hero .glb from deadlock_port.py, or a Valorant agent .uemodel from FModel, and rig it"""
    bl_idname = 'deadlock.import_hero'
    bl_label = 'Import Hero'
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = '.glb'
    filter_glob: StringProperty(default='*.glb;*.gltf;*.uemodel', options={'HIDDEN'})
    scale: FloatProperty(name='Scale', default=0.01, min=0.0001, max=10.0,
                         description='Source units to meters for .glb files. 0.01 matches the other Deadlock ports')
    add_rig: BoolProperty(name='Add Tasty-style Rig', default=True)
    chroma: StringProperty(name='Chroma', default='', options={'HIDDEN'},
                           description='Weapon color variant folder to start with, like v1')

    def execute(self, context):
        if self.filepath.lower().endswith('.uemodel'):
            return self.import_uemodel(context)
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=self.filepath)
        new = [o for o in bpy.data.objects if o not in before]
        arms = [o for o in new if o.type == 'ARMATURE']
        if not arms:
            self.report({'ERROR'}, 'No skeleton in that file')
            return {'CANCELLED'}
        arm = arms[0]
        
        for obj in new:
            if obj.type == 'MESH' and obj.name.startswith('Icosphere') and obj.parent is None:
                bpy.data.objects.remove(obj)
        hero = os.path.splitext(os.path.basename(self.filepath))[0].lower()
        arm.name = f'{hero}_rig'
        rig.prepare(arm, self.scale)
        context.view_layer.objects.active = arm
        if self.add_rig:
            try:
                rig.build(arm, hero)
            except Exception as e:  # noqa: BLE001  Keep the import, say what broke.
                self.report({'WARNING'}, f'Imported, but the rig failed: {e}')
                return {'FINISHED'}
        self.report({'INFO'}, f'{hero} is ready to pose')
        return {'FINISHED'}

    def import_uemodel(self, context):
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            arm, code, skin, kind = uemodel.load(self.filepath)
        except (ValueError, OSError) as e:
            self.report({'ERROR'}, f'Could not read that model: {e}')
            return {'CANCELLED'}
        if kind == 'static':
            self.report({'INFO'}, f'Imported {arm.name}')
            return {'FINISHED'}
        if kind == 'weapon':
            weapon = names.VALORANT_WEAPONS.get(code, code.lower())
            arm.name = f'{weapon}_{skin.lower()}' if skin else weapon
            if self.chroma and self.chroma in arm['dl_chromas'].split(','):
                uemodel.set_chroma(arm, rig.armature_meshes(arm), self.chroma)
            if self.add_rig:
                rig.build_prop(arm, rig.find_hero(context.scene))
            self.report({'INFO'}, f'{arm.name} is ready. Move the box to place it')
            return {'FINISHED'}
        hero = names.VALORANT_AGENTS.get(code, code.lower())
        arm.name = f'{hero}_rig'
        rig.prepare(arm, 1.0)
        context.view_layer.objects.active = arm
        if self.add_rig:
            try:
                rig.build(arm, hero)
            except Exception as e:  # noqa: BLE001  Keep the import, say what broke.
                self.report({'WARNING'}, f'Imported, but the rig failed: {e}')
                return {'FINISHED'}
        self.report({'INFO'}, f'{hero} is ready to pose')
        return {'FINISHED'}


class DL_OT_apply_rig(bpy.types.Operator):
    """Add the Tasty-style rig to the selected Deadlock skeleton"""
    bl_idname = 'deadlock.apply_rig'
    bl_label = 'Apply Tasty Rig'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = active_rig(context)
        return arm is not None and not rig.is_rigged(arm)

    def execute(self, context):
        arm = active_rig(context)
        hero = arm.get('dl_hero') or arm.name.split('_')[0].split('.')[0].lower()
        try:
            rig.build(arm, hero)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


def is_model(arm):
    return arm is not None and (rig.is_rigged(arm) or bool(arm.get('dl_prop')))


class DL_OT_save_model(bpy.types.Operator, ExportHelper):
    """Save this hero or weapon, rig and textures included, as its own small .blend model file"""
    bl_idname = 'deadlock.save_model'
    bl_label = 'Save as Model File'

    filename_ext = '.blend'
    filter_glob: StringProperty(default='*.blend', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return is_model(active_rig(context))

    def invoke(self, context, event):
        folder = os.path.dirname(bpy.data.filepath) or os.path.expanduser('~')
        self.filepath = os.path.join(folder, library.model_name(active_rig(context)) + '.blend')
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        arm = active_rig(context)
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        library.save_model(arm, self.filepath)
        self.report({'INFO'}, f'Saved {os.path.basename(self.filepath)}. Add it to any project with Add Model')
        return {'FINISHED'}


class DL_OT_add_model(bpy.types.Operator, ImportHelper):
    """Add a model file saved by Deadlock Porting, ready to pose"""
    bl_idname = 'deadlock.add_model'
    bl_label = 'Add Model'
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = '.blend'
    filter_glob: StringProperty(default='*.blend', options={'HIDDEN'})

    def execute(self, context):
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        rigs = library.add_model(context, self.filepath)
        if not rigs:
            self.report({'WARNING'}, 'No Deadlock Porting model in that file')
            return {'CANCELLED'}
        self.report({'INFO'}, 'Added ' + ', '.join(a.name for a in rigs))
        return {'FINISHED'}


class DL_OT_set_chroma(bpy.types.Operator):
    """Swap the weapon's textures to this color variant"""
    bl_idname = 'deadlock.set_chroma'
    bl_label = 'Chroma'
    bl_options = {'REGISTER', 'UNDO'}

    variant: StringProperty()

    def execute(self, context):
        arm = active_rig(context)
        if arm is None or not arm.get('dl_prop'):
            return {'CANCELLED'}
        if not uemodel.set_chroma(arm, rig.armature_meshes(arm), self.variant):
            self.report({'WARNING'}, 'No textures for that variant were found. Is the FModel export still there?')
        return {'FINISHED'}


class DL_OT_switch(bpy.types.Operator):
    """Switch this limb between IK and FK. The pose stays where it is"""
    bl_idname = 'deadlock.switch'
    bl_label = 'IK / FK'
    bl_options = {'REGISTER', 'UNDO'}

    kind: StringProperty()
    side: StringProperty()
    to_ik: BoolProperty()

    def execute(self, context):
        arm = active_rig(context)
        if arm is None:
            return {'CANCELLED'}
        rig.switch(arm, self.kind, self.side, self.to_ik)
        return {'FINISHED'}


class DL_OT_hand_shape(bpy.types.Operator):
    """Set every finger curl on this hand"""
    bl_idname = 'deadlock.hand_shape'
    bl_label = 'Hand Shape'
    bl_options = {'REGISTER', 'UNDO'}

    side: StringProperty()
    amount: FloatProperty(description='0 is open, 1 is a fist')

    def execute(self, context):
        arm = active_rig(context)
        for f, deg in FIST.items():
            pb = arm.pose.bones.get(f'{f}_control_{self.side}')
            if pb is not None:
                pb.rotation_euler = (radians(deg * self.amount), 0.0, 0.0)
        return {'FINISHED'}


class DL_OT_reset_pose(bpy.types.Operator):
    """Put every bone back to the rest pose. Switches stay as they are"""
    bl_idname = 'deadlock.reset_pose'
    bl_label = 'Reset Pose'
    bl_options = {'REGISTER', 'UNDO'}

    selected_only: BoolProperty(name='Selected Only', default=False)

    def execute(self, context):
        arm = active_rig(context)
        for pb in arm.pose.bones:
            if self.selected_only and not pb.bone.select:
                continue
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
            pb.rotation_axis_angle = (0, 0, 1, 0)
            pb.scale = (1, 1, 1)
        return {'FINISHED'}


class DL_OT_mirror_pose(bpy.types.Operator):
    """Copy the pose of the selected bones onto the other side"""
    bl_idname = 'deadlock.mirror_pose'
    bl_label = 'Mirror to Other Side'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'POSE'

    def execute(self, context):
        bpy.ops.pose.copy()
        bpy.ops.pose.paste(flipped=True, selected_mask=False)
        return {'FINISHED'}


class DL_OT_thumbnail(bpy.types.Operator):
    """Camera, key, fill and two rim lights around this hero, transparent PNG output"""
    bl_idname = 'deadlock.thumbnail'
    bl_label = 'Set Up Thumbnail Scene'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_rig(context) is not None

    def execute(self, context):
        studio.setup(context, active_rig(context))
        return {'FINISHED'}


class DL_OT_frame(bpy.types.Operator):
    """Move the camera so the whole hero fits in frame"""
    bl_idname = 'deadlock.frame'
    bl_label = 'Frame Hero'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_rig(context) is not None and context.scene.camera is not None

    def execute(self, context):
        studio.frame(context, active_rig(context))
        return {'FINISHED'}


def _rim_changed(scene, _context):
    studio.apply_rim(scene)


class DL_PT_panel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Deadlock'
    bl_label = 'Deadlock Porting'

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator('deadlock.import_hero', icon='IMPORT')
        row.operator('deadlock.add_model', icon='APPEND_BLEND')
        arm = active_rig(context)
        if arm is None:
            layout.label(text='Select a hero to pose it', icon='INFO')
            return
        if arm.get('dl_prop'):
            self.draw_prop(layout, arm)
            layout.operator('deadlock.save_model', icon='FILE_TICK')
            return
        if not rig.is_rigged(arm):
            layout.operator('deadlock.apply_rig', icon='ARMATURE_DATA')
            return
        pose = arm.pose.bones

        box = layout.box()
        box.label(text='IK / FK', icon='CON_KINEMATIC')
        box.label(text="Left and right are the hero's (blue = left)")
        for kind, title in (('arm', 'Arm'), ('leg', 'Leg')):
            for side, word in (('l', 'Left'), ('r', 'Right')):
                key = f'dl_{kind}_ik_{side}'
                if key not in arm:
                    continue
                on = arm[key] > 0.5
                row = box.row(align=True)
                row.label(text=f'{word} {title}')
                op = row.operator('deadlock.switch', text='FK', depress=not on)
                op.kind, op.side, op.to_ik = kind, side, False
                op = row.operator('deadlock.switch', text='IK', depress=on)
                op.kind, op.side, op.to_ik = kind, side, True
        box.prop(arm, '["dl_use_poles"]', text='Elbow/Knee Poles', slider=True)

        box = layout.box()
        box.label(text='Feet', icon='MOD_DYNAMICPAINT')
        for side, word in (('l', 'Left'), ('r', 'Right')):
            pb = pose.get(f'ik_foot_ctrl_{side}')
            if pb is None or arm.get(f'dl_leg_ik_{side}', 1) < 0.5:
                continue
            row = box.row(align=True)
            row.label(text=word)
            row.prop(pb, 'rotation_euler', index=0, text='Roll')
            row.prop(pb, 'rotation_euler', index=1, text='Bank')

        box = layout.box()
        box.label(text='Hands', icon='VIEW_PAN')
        for side, word in (('l', 'Left'), ('r', 'Right')):
            row = box.row(align=True)
            row.label(text=word)
            for label, amount in (('Open', 0.0), ('Relax', 0.3), ('Fist', 1.0)):
                op = row.operator('deadlock.hand_shape', text=label)
                op.side, op.amount = side, amount
            col = box.column(align=True)
            for f in rig.FINGERS:
                pb = pose.get(f'{f}_control_{side}')
                if pb is not None:
                    col.prop(pb, 'rotation_euler', index=0, text=f'{f.title()} Curl')

        box = layout.box()
        box.label(text='Layers', icon='GROUP_BONE')
        grid = box.grid_flow(columns=2, align=True)
        for col in arm.data.collections:
            if col.name != 'Mechanics':
                grid.prop(col, 'is_visible', text=col.name, toggle=True)
        box.prop(arm, 'show_in_front', text='Controls Through Mesh')

        box = layout.box()
        box.label(text='Pose', icon='POSE_HLT')
        row = box.row(align=True)
        row.operator('deadlock.reset_pose', text='Reset All').selected_only = False
        row.operator('deadlock.reset_pose', text='Reset Selected').selected_only = True
        box.operator('deadlock.mirror_pose', icon='MOD_MIRROR')
        layout.operator('deadlock.save_model', icon='FILE_TICK')


    @staticmethod
    def draw_prop(layout, arm):
        box = layout.box()
        box.label(text='Weapon', icon='MOD_EXPLODE')
        box.label(text='Move or rotate the orange box to place it')
        variants = [v for v in arm.get('dl_chromas', '').split(',') if v]
        if variants:
            row = box.row(align=True)
            row.label(text='Chroma')
            current = arm.get('dl_chroma', '')
            for v in [''] + variants:
                text = 'Base' if not v else f'Variant {v[1:]}' if v[1:].isdigit() else v
                row.operator('deadlock.set_chroma', text=text, depress=current == v).variant = v

        box = layout.box()
        box.label(text='Layers', icon='GROUP_BONE')
        grid = box.grid_flow(columns=2, align=True)
        for col in arm.data.collections:
            grid.prop(col, 'is_visible', text=col.name, toggle=True)
        box.operator('deadlock.reset_pose', text='Reset Pose').selected_only = False


class DL_PT_studio(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Deadlock'
    bl_label = 'Thumbnail Studio'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, 'dl_thumb_size', text='')
        layout.operator('deadlock.thumbnail', icon='SCENE')
        row = layout.row(align=True)
        row.prop(scene, 'dl_rim_a', text='')
        row.prop(scene, 'dl_rim_b', text='')
        layout.operator('deadlock.frame', icon='VIEW_CAMERA')
        layout.prop(scene.render, 'film_transparent', text='Transparent Background')
        layout.operator('render.render', text='Render Thumbnail', icon='RENDER_STILL')


classes = (
    DL_OT_import_hero, DL_OT_save_model, DL_OT_add_model, DL_OT_apply_rig, DL_OT_set_chroma, DL_OT_switch, DL_OT_hand_shape, DL_OT_reset_pose,
    DL_OT_mirror_pose, DL_OT_thumbnail, DL_OT_frame, DL_PT_panel, DL_PT_studio,
)


def menu_import(self, _context):
    self.layout.operator('deadlock.import_hero', text='Deadlock Hero (.glb)')
    self.layout.operator('deadlock.import_hero', text='Valorant Agent or Weapon (.uemodel)')
    self.layout.operator('deadlock.add_model', text='Deadlock Porting Model (.blend)')


def menu_export(self, _context):
    self.layout.operator('deadlock.save_model', text='Deadlock Porting Model (.blend)')


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dl_thumb_size = EnumProperty(
        name='Size',
        items=[('LANDSCAPE', 'YouTube 1920x1080', ''), ('PORTRAIT', 'Shorts / TikTok 1080x1920', ''),
               ('SQUARE', 'Square 1080x1080', '')],
        default='LANDSCAPE')
    bpy.types.Scene.dl_rim_a = FloatVectorProperty(
        name='Rim A', subtype='COLOR', size=3, min=0, max=1, default=(0.2, 0.75, 1.0), update=_rim_changed)
    bpy.types.Scene.dl_rim_b = FloatVectorProperty(
        name='Rim B', subtype='COLOR', size=3, min=0, max=1, default=(1.0, 0.35, 0.6), update=_rim_changed)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    for name in ('dl_thumb_size', 'dl_rim_a', 'dl_rim_b'):
        delattr(bpy.types.Scene, name)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
