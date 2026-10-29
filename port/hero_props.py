"""Independent prop objects and rigs, arranged beside the exported hero."""
import re

import bpy
from mathutils import Vector

from deadlock_porting import rig, studio


def is_prop(name):
    words = set(re.split(r'[^a-z]+', name.lower()))
    return bool(words & {'weapon', 'weapons', 'gun', 'guns', 'prop', 'props',
                         'pistol', 'rifle', 'shotgun', 'bow', 'sword', 'knife',
                         'dagger', 'grenade', 'bomb', 'staff', 'shield'})


def detach(arm):
    """Run after prepare, before the hero control rig changes the weapon bones."""
    props = []
    collection = None
    for obj in list(rig.armature_meshes(arm)):
        if not is_prop(obj.name):
            continue
        if collection is None:
            collection = bpy.data.collections.new('Hero Props')
            bpy.context.scene.collection.children.link(collection)
        prop = bpy.data.objects.new(obj.name + '_rig', arm.data.copy())
        prop.matrix_world = arm.matrix_world.copy()
        collection.objects.link(prop)
        world = obj.matrix_world.copy()
        obj.parent = prop
        obj.matrix_world = world
        for modifier in obj.modifiers:
            if modifier.type == 'ARMATURE' and modifier.object == arm:
                modifier.object = prop
        for old in list(obj.users_collection):
            old.objects.unlink(obj)
        collection.objects.link(obj)
        obj['dl_separate_prop'] = True
        prop['dl_separate_prop'] = True

        
        groups = {g.index: g.name for g in obj.vertex_groups}
        keep = {groups[g.group] for v in obj.data.vertices for g in v.groups if g.weight > 0}
        for name in list(keep):
            bone = prop.data.bones.get(name)
            if bone:
                keep.update(b.name for b in bone.parent_recursive)
        bpy.context.view_layer.objects.active = prop
        prop.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        for bone in list(prop.data.edit_bones):
            if bone.name not in keep:
                prop.data.edit_bones.remove(bone)
        bpy.ops.object.mode_set(mode='OBJECT')
        props.append(prop)
    bpy.context.view_layer.objects.active = arm
    return props


def arrange(context, hero, props, controls=True):
    center, size = studio.hero_bounds(context, hero)
    height = max(size.z, 0.1)
    cursor = center.x + size.x / 2 + height * 0.22
    for prop in props:
        if controls:
            rig.build_prop(prop)
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.update()
        pc, ps = studio.hero_bounds(context, prop)
        
        target = Vector((cursor + ps.x / 2, center.y, center.z - size.z / 2 + ps.z / 2))
        prop.location += target - pc
        context.view_layer.update()
        cursor += ps.x + height * 0.15
        print(f'Separate prop: {prop.name}', flush=True)
    context.view_layer.objects.active = hero


def scene_bounds(context, arms):
    bounds = [studio.hero_bounds(context, arm) for arm in arms]
    lo = Vector([min(c[k] - s[k] / 2 for c, s in bounds) for k in range(3)])
    hi = Vector([max(c[k] + s[k] / 2 for c, s in bounds) for k in range(3)])
    return (lo + hi) / 2, hi - lo


def bake_static(context, props):
    """Keep the placed prop geometry, materials and UVs without any prop armatures."""
    objects = []
    context.view_layer.update()
    deps = context.evaluated_depsgraph_get()
    for prop in props:
        for obj in rig.armature_meshes(prop):
            evaluated = obj.evaluated_get(deps)
            mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=deps)
            world = obj.matrix_world.copy()
            obj.data = mesh
            obj.parent = None
            obj.matrix_world = world
            for modifier in list(obj.modifiers):
                if modifier.type == 'ARMATURE':
                    obj.modifiers.remove(modifier)
            obj.vertex_groups.clear()
            objects.append(obj)
        bpy.data.objects.remove(prop, do_unlink=True)
    return objects
