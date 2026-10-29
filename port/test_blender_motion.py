"""Run with Blender --background --python-exit-code 1 --python this.py -- hero.blend."""
import sys
from pathlib import Path
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from deadlock_porting import rig

bpy.ops.wm.open_mainfile(filepath=sys.argv[sys.argv.index('--') + 1])
hero = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE' and o.get('dl_rig'))


def geometry(arm):
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in rig.armature_meshes(arm):
        evaluated = obj.evaluated_get(deps)
        mesh = evaluated.to_mesh()
        try:
            co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get('co', co)
            world = np.asarray(evaluated.matrix_world)
            points.append(co.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3])
        finally:
            evaluated.to_mesh_clear()
    return np.concatenate(points)


def check(arm, name, rotate=False):
    bone = arm.pose.bones.get(name)
    if bone is None:
        return
    before = geometry(arm)
    original = bone.matrix_basis.copy()
    if rotate:
        from mathutils import Matrix
        bone.matrix_basis = original @ Matrix.Rotation(.35, 4, 'X')
    else:
        bone.location.x += .2
    arm.update_tag()
    delta = np.linalg.norm(geometry(arm) - before, axis=1).max()
    bone.matrix_basis = original
    arm.update_tag()
    bpy.context.view_layer.update()
    assert delta > 1e-5, f'{arm.name}/{name} moves no geometry'
    print(f'PASS {arm.name}/{name}: mesh moved {delta:.6f}m')


for control in ('root', 'pelvis', 'ik_hand_l', 'ik_hand_r', 'ik_foot_l', 'ik_foot_r'):
    check(hero, control)
check(hero, 'head', rotate=True)
check(hero, 'index_control_l', rotate=True)
for side in rig.SIDES:
    for finger in rig.FINGERS:
        segments = rig.finger_chain(hero.pose.bones, finger, side)[1]
        for name in segments[:3]:
            assert any(c.name == 'Fingers' and c.is_visible for c in hero.data.bones[name].collections)
            check(hero, name, rotate=True)
        if len(segments) >= 3:
            assert all(hero.data.bones[b].parent == hero.data.bones[a]
                       for a, b in zip(segments[:2], segments[1:3]))
for prop in [o for o in bpy.context.scene.objects if o.type == 'ARMATURE' and o.get('dl_prop')]:
    check(prop, 'prop')
    before = geometry(prop)
    hero.pose.bones['root'].location.x += .2
    hero.update_tag()
    assert np.max(np.abs(geometry(prop) - before)) < 1e-5, 'Hero root moves a detached prop'
    hero.pose.bones['root'].location.x -= .2
    hero.update_tag()
for prop in [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.get('dl_separate_prop')]:
    assert prop.parent is None and not any(m.type == 'ARMATURE' for m in prop.modifiers)
    before = prop.matrix_world.copy()
    hero.pose.bones['root'].location.x += .2
    hero.update_tag()
    bpy.context.view_layer.update()
    assert np.max(np.abs(np.asarray(prop.matrix_world) - np.asarray(before))) < 1e-5
    hero.pose.bones['root'].location.x -= .2
    hero.update_tag()
    print('PASS static prop stays independent:', prop.name)
print('All pose deformation checks passed')
