"""Background Blender worker for the desktop export interface."""
import sys
from pathlib import Path

import bpy

source, destination, output_format, controls = sys.argv[sys.argv.index('--') + 1:]
sys.path.insert(0, str(Path(__file__).parent))
from deadlock_porting import rig, studio
import hero_props

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
arm = next((o for o in bpy.context.scene.objects if o.type == 'ARMATURE'), None)
model = Path(source).stem
props = []
character_controls = False
if arm is not None:
    arm.name = model + '_rig'
    bpy.context.view_layer.objects.active = arm
    rig.prepare(arm, 0.01)
    biped = 'pelvis' in arm.data.bones and 'thigh_l' in arm.data.bones
    if biped:
        props = hero_props.detach(arm)
        if controls == 'true':
            rig.build(arm, model)
            character_controls = True
        hero_props.arrange(bpy.context, arm, props, False)
    else:
        print('Preserving source skeleton; this model does not use the hero biped rig', flush=True)
    static_props = hero_props.bake_static(bpy.context, props)
    props = []
    export_objects = {arm, *rig.armature_meshes(arm), *static_props}
else:
    from mathutils import Matrix
    for obj in bpy.context.scene.objects:
        if obj.parent is None:
            obj.matrix_world = Matrix.Scale(0.01, 4) @ obj.matrix_world
    export_objects = {o for o in bpy.context.scene.objects if o.type == 'MESH'}
    if not export_objects:
        raise RuntimeError('The exported model contains no render meshes')
    print('Exporting static model without an armature', flush=True)
bpy.context.view_layer.update()
active = arm if arm is not None else next(iter(export_objects))
if output_format == 'blend':
    
    for image in bpy.data.images:
        if image.source == 'FILE' and not image.packed_file:
            image.pack()
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in bpy.context.scene.objects:
        obj.select_set(obj == active)
    bpy.context.view_layer.objects.active = active
    from mathutils import Vector
    deps = bpy.context.evaluated_depsgraph_get()
    points = [obj.evaluated_get(deps).matrix_world @ Vector(c)
              for obj in export_objects if obj.type == 'MESH'
              for c in obj.evaluated_get(deps).bound_box]
    lo = Vector([min(p[k] for p in points) for k in range(3)])
    hi = Vector([max(p[k] for p in points) for k in range(3)])
    center, size = (lo + hi) / 2, hi - lo
    from mathutils import Quaternion
    from math import pi
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.type = 'MATERIAL'
                view = area.spaces.active.region_3d
                view.view_location = center
                view.view_distance = max(size) * 1.7
                view.view_rotation = Quaternion((1, 0, 0), pi / 2)
    if arm is not None:
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='DESELECT')
        control_name = 'root' if character_controls else arm.data.bones[0].name
        pb = arm.pose.bones.get(control_name)
        if pb is not None:
            if hasattr(pb, 'select'):
                pb.select = True
            else:
                pb.bone.select = True
        arm.data.bones.active = arm.data.bones.get(control_name)
    bpy.ops.wm.save_as_mainfile(filepath=destination)
elif output_format == 'fbx':
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    for obj in export_objects:
        obj.select_set(True)
    bpy.ops.export_scene.fbx(filepath=destination, use_selection=True,
                             add_leaf_bones=False, bake_anim=False,
                             path_mode='COPY', embed_textures=True)
else:
    raise ValueError(output_format)
if not Path(destination).is_file():
    raise RuntimeError('Blender did not create the requested file')
print('EXPORT_COMPLETE', flush=True)
