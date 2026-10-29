"""Control shapes, built as wire meshes.

The add-on makes its own shapes, so nobody needs another porting add-on's
data file. Shapes are drawn in armature space around the rest pose, then
moved into each bone's local space. That means one widget per control and
no guessing about bone length scaling.
"""
from math import cos, pi, sin

import bpy
from mathutils import Vector


def widget_collection(arm):
    name = f'WGT_{arm.name}'
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        parent = arm.users_collection[0] if arm.users_collection else bpy.context.scene.collection
        parent.children.link(col)
    col.hide_viewport = True
    col.hide_render = True
    return col


def make(arm, bone_name, lines):
    """Wire mesh from polylines in armature space, stored in the bone's space."""
    bone = arm.data.bones[bone_name]
    to_local = bone.matrix_local.inverted()
    verts, edges = [], []
    for line in lines:
        start = len(verts)
        verts.extend((to_local @ p)[:] for p in line)
        edges.extend((start + i, start + i + 1) for i in range(len(line) - 1))
    name = f'WGT_{arm.name}_{bone_name}'
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, [])
    obj = bpy.data.objects.new(name, mesh)
    widget_collection(arm).objects.link(obj)
    return obj


def axes(arm, bone_name):
    m = arm.data.bones[bone_name].matrix_local
    return m.col[3].xyz, m.col[0].xyz.normalized(), m.col[1].xyz.normalized(), m.col[2].xyz.normalized()


def ring(center, u, v, radius, steps=24, arc=1.0):
    count = steps if arc >= 1.0 else max(2, int(steps * arc))
    pts = [center + (u * cos(2 * pi * arc * i / count) + v * sin(2 * pi * arc * i / count)) * radius
           for i in range(count + 1)]
    return pts


def ellipse(center, u, v, ru, rv, steps=32):
    return [center + u * cos(2 * pi * i / steps) * ru + v * sin(2 * pi * i / steps) * rv
            for i in range(steps + 1)]


def stick(head, tail, radius):
    """Thin line down the bone with a small ring at the tip. Quiet on screen."""
    d = (tail - head).normalized()
    u = d.orthogonal().normalized()
    return [[head, tail], ring(tail, u, d.cross(u), radius, 10)]


def bone_ring(arm, bone_name, radius, along=0.0):
    """Circle around the bone, `along` of the way from head to tail."""
    head, x, y, z = axes(arm, bone_name)
    length = arm.data.bones[bone_name].length
    return [ring(head + y * length * along, x, z, radius)]


def box(center, x, y, z, half):
    hx, hy, hz = (x * half[0], y * half[1], z * half[2])
    c = [center + sx * hx + sy * hy + sz * hz for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    return [
        [c[0], c[1], c[3], c[2], c[0]],
        [c[4], c[5], c[7], c[6], c[4]],
        [c[0], c[4]], [c[1], c[5]], [c[2], c[6]], [c[3], c[7]],
    ]


def diamond(center, radius):
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    return [ring(center, X, Y, radius, 4), ring(center, X, Z, radius, 4), ring(center, Y, Z, radius, 4)]


def root(center, radius):
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    lines = [ring(center, X, Y, radius, 48)]
    for d in (X, -X, Y, -Y):
        side = Vector((-d.y, d.x, 0))
        tip = center + d * radius * 1.3
        base = center + d * radius * 1.05
        lines.append([base + side * radius * 0.12, tip, base - side * radius * 0.12])
    return lines


def rect(corners):
    return [list(corners) + [corners[0]]]


def foot_roll(center, size):
    """Half wheel standing up along the foot, with a cross bar for banking."""
    X, Y, Z = Vector((1, 0, 0)), Vector((0, -1, 0)), Vector((0, 0, 1))
    arc = ring(center, Y, Z, size, 16, 0.5)
    bar = [center - X * size * 0.7, center + X * size * 0.7]
    return [arc, [arc[0], arc[-1]], bar]


def finger_curl(start, end, lift, radius):
    """Line floating over the back of the finger, ring at the tip."""
    a, b = start + lift, end + lift
    d = (b - a).normalized()
    u = d.orthogonal().normalized()
    v = d.cross(u)
    return [[a, b], ring(b, u, v, radius, 12)]


def arc_over(arm, bone_name, radius):
    head, x, y, z = axes(arm, bone_name)
    length = arm.data.bones[bone_name].length
    mid = head + y * length * 0.6
    return [ring(mid, x, z, radius, 24, 0.5)]
