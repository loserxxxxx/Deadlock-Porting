"""Model files: one rigged hero or weapon per small .blend.

A model file holds one collection with the armature, its meshes, the
control shapes and packed textures. No scene, camera or lights. Adding it
to a project appends the collection as real objects (not an instance), so
it is ready to pose. It is also marked as an asset for the Asset Browser.
"""
import os

import bpy

from . import rig


def model_name(arm):
    return arm.name[:-4] if arm.name.endswith('_rig') else arm.name


def save_model(arm, path):
    """Write `arm`, its meshes and control shapes to `path`."""
    meshes = rig.armature_meshes(arm)
    for obj in meshes:
        for slot in obj.material_slots:
            if slot.material and slot.material.node_tree:
                for node in slot.material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image and node.image.packed_file is None \
                            and node.image.source == 'FILE':
                        node.image.pack()

    
    col = bpy.data.collections.new(model_name(arm))
    wgt = None
    try:
        for obj in [arm] + meshes:
            col.objects.link(obj)
        shapes = {pb.custom_shape for pb in arm.pose.bones if pb.custom_shape}
        wgt = bpy.data.collections.new(f'WGT_{arm.name}')
        for obj in shapes:
            wgt.objects.link(obj)
        wgt.hide_viewport = wgt.hide_render = True
        col.children.link(wgt)
        col.asset_mark()
        col.asset_data.description = 'Tasty-style rig from Deadlock Porting. Append it, do not instance it'
        col.asset_data.tags.new('Deadlock Porting', skip_if_exists=True)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        bpy.data.libraries.write(path, {col}, fake_user=True, compress=True)
    finally:
        if wgt is not None:
            bpy.data.collections.remove(wgt)
        bpy.data.collections.remove(col)


def add_model(context, path):
    """Append every model in `path` to the scene. Returns the rigs."""
    with bpy.data.libraries.load(path, link=False, assets_only=False) as (src, dst):
        dst.collections = list(src.collections)
    loaded = [c for c in dst.collections if c is not None]
    children = {child for c in loaded for child in c.children}
    rigs = []
    for col in loaded:
        col.asset_clear()
        col.use_fake_user = False
        if col in children:
            continue
        context.scene.collection.children.link(col)
        rigs += [o for o in col.objects if o.type == 'ARMATURE' and (rig.is_rigged(o) or o.get('dl_prop'))]
    for obj in context.view_layer.objects:
        obj.select_set(False)
    for arm in rigs:
        arm.select_set(True)
        context.view_layer.objects.active = arm
    return rigs
