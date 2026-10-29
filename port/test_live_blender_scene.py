"""Run in Blender with --python test_live_blender_scene.py -- test_directory."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import bpy

folder = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
os.environ['DEADLOCK_LIVE_DATA'] = str(folder / 'bridge')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'blender_addon'))
import deadlock_porting_live as addon

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'empty.blend'))
bpy.ops.wm.read_factory_settings(use_empty=False)
project = folder / 'open-project.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(project))
original_digest = hashlib.sha256(project.read_bytes()).hexdigest()
cube = bpy.data.objects['Cube']
cube.location = (4, 5, 6)
cube['unsaved_work'] = 'preserve this'
scene = bpy.context.scene
scene.frame_set(17)
scene.cursor.location = (7, -3, 2)
scene.render.resolution_x, scene.render.resolution_y = 321, 123
camera, world = scene.camera, scene.world
addon.register()
addon.start()
(folder / 'ready.json').write_text(json.dumps({'pid': os.getpid()}))

try:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        addon.tick()
        if (folder / 'finish.json').is_file():
            break
        time.sleep(.05)
    else:
        raise RuntimeError('Integration test timed out')
    assert bpy.context.scene == scene
    assert tuple(cube.location) == (4, 5, 6) and cube['unsaved_work'] == 'preserve this'
    assert scene.frame_current == 17 and tuple(scene.cursor.location) == (7, -3, 2)
    assert (scene.render.resolution_x, scene.render.resolution_y) == (321, 123)
    assert scene.camera == camera and scene.world == world
    assert hashlib.sha256(project.read_bytes()).hexdigest() == original_digest, 'The open project file was unexpectedly saved'
    imports = [c for c in scene.collection.children if c.get('deadlock_export')]
    assert len(imports) == 1, 'Duplicate or failed imports leaked objects'
    rigs = [obj for obj in imports[0].all_objects if obj.type == 'ARMATURE']
    assert rigs and any('root' in obj.pose.bones for obj in rigs)
    assert any(b.custom_shape for obj in rigs for b in obj.pose.bones)
    assert any(obj.type == 'MESH' and obj.parent not in rigs for obj in imports[0].all_objects), 'Separate hero props were lost'
    assert any(abs(obj.matrix_world.translation.x - 7) < .001 for obj in rigs), 'Imported rig did not use the 3D cursor'
    (folder / 'result.json').write_text(json.dumps({'ok': True, 'same_process': os.getpid(), 'unsaved_work_preserved': True, 'project_file_unchanged': True,
                                                  'rigs': len(rigs), 'imported_collection': imports[0].name, 'objects': len(imports[0].all_objects)}))
finally:
    addon.unregister()
