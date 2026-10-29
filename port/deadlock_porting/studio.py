"""One-click thumbnail scene: camera, key/fill/two rim lights, transparent PNG."""
from math import atan, tan

import bpy
from mathutils import Vector

COLLECTION = 'DL Thumbnail'

SIZES = {
    'LANDSCAPE': (1920, 1080),
    'PORTRAIT': (1080, 1920),
    'SQUARE': (1080, 1080),
}


LIGHTS = (
    ('DL Key', Vector((-0.8, -1.0, 0.7)), 450.0, (1.0, 0.95, 0.88)),
    ('DL Fill', Vector((1.0, -0.9, 0.2)), 120.0, (0.85, 0.9, 1.0)),
    ('DL Rim A', Vector((0.9, 1.1, 0.6)), 900.0, None),
    ('DL Rim B', Vector((-0.9, 1.1, 0.5)), 700.0, None),
)


def hero_bounds(context, arm):
    meshes = [o for o in bpy.data.objects if o.type == 'MESH' and (
        o.parent == arm or any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers))]
    deps = context.evaluated_depsgraph_get()
    pts = []
    for obj in meshes:
        ev = obj.evaluated_get(deps)
        pts.extend(ev.matrix_world @ Vector(c) for c in ev.bound_box)
    if not pts:
        pts = [arm.matrix_world @ b.head_local for b in arm.data.bones]
    lo = Vector([min(p[k] for p in pts) for k in range(3)])
    hi = Vector([max(p[k] for p in pts) for k in range(3)])
    return (lo + hi) / 2, hi - lo


def _collection(scene):
    col = bpy.data.collections.get(COLLECTION)
    if col is None:
        col = bpy.data.collections.new(COLLECTION)
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    return col


def _aim(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat('-Z', 'Y').to_euler()


def _object(col, name, data):
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, data)
    if obj.name not in col.objects:
        col.objects.link(obj)
    return obj


def frame(context, arm):
    scene = context.scene
    cam = scene.camera
    if cam is None:
        return
    w, h = scene.render.resolution_x, scene.render.resolution_y
    center, size = hero_bounds(context, arm)
    cam.data.sensor_fit = 'VERTICAL' if h >= w else 'HORIZONTAL'
    lens = cam.data.lens
    sensor = 36.0
    cam.data.sensor_width = cam.data.sensor_height = sensor
    fov = 2 * atan(sensor / 2 / lens)
    if h >= w:
        fov_v, fov_h = fov, 2 * atan(tan(fov / 2) * w / h)
    else:
        fov_h, fov_v = fov, 2 * atan(tan(fov / 2) * h / w)
    need_v = size.z * 1.12 / 2 / tan(fov_v / 2)
    need_h = max(size.x, size.y) * 1.2 / 2 / tan(fov_h / 2)
    distance = max(need_v, need_h) + size.y / 2
    cam.location = center + Vector((0, -distance, size.z * 0.04))
    _aim(cam, center + Vector((0, 0, size.z * 0.02)))


def apply_rim(scene):
    for name, color in (('DL Rim A', scene.dl_rim_a), ('DL Rim B', scene.dl_rim_b)):
        light = bpy.data.objects.get(name)
        if light is not None and light.type == 'LIGHT':
            light.data.color = color


def setup(context, arm):
    scene = context.scene
    try:
        scene.render.engine = 'BLENDER_EEVEE'
    except TypeError:
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x, scene.render.resolution_y = SIZES[scene.dl_thumb_size]
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'AgX'
    try:
        scene.view_settings.look = 'AgX - Medium High Contrast'
    except TypeError:
        pass

    col = _collection(scene)
    center, size = hero_bounds(context, arm)
    tall = max(size.z, 0.1)

    cam_data = bpy.data.cameras.get('DL Camera') or bpy.data.cameras.new('DL Camera')
    cam_data.lens = 50
    cam = _object(col, 'DL Camera', cam_data)
    scene.camera = cam
    frame(context, arm)

    power = (tall / 1.85) ** 2
    for name, direction, watts, color in LIGHTS:
        data = bpy.data.lights.get(name) or bpy.data.lights.new(name, 'AREA')
        data.shape = 'DISK'
        data.size = tall * 0.6
        data.energy = watts * power
        if color:
            data.color = color
        light = _object(col, name, data)
        light.location = center + direction.normalized() * tall * 1.6
        _aim(light, center)
    apply_rim(scene)

    world = scene.world or bpy.data.worlds.new('DL World')
    scene.world = world
    if hasattr(world, 'use_nodes'):
        world.use_nodes = True
    tree = world.node_tree
    bg = next((n for n in tree.nodes if n.type == 'BACKGROUND'), None) if tree else None
    if bg is not None:
        bg.inputs['Color'].default_value = (0.03, 0.03, 0.035, 1.0)
        bg.inputs['Strength'].default_value = 1.0
