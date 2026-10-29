"""Open exported interchange formats in an interactive Blender session."""
import sys
from pathlib import Path
import bpy

path = Path(sys.argv[sys.argv.index('--') + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
if path.suffix == '.fbx':
    bpy.ops.import_scene.fbx(filepath=str(path))
else:
    bpy.ops.import_scene.gltf(filepath=str(path))
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.shading.type = 'MATERIAL'
            with bpy.context.temp_override(screen=screen, area=area, region=next(r for r in area.regions if r.type == 'WINDOW')):
                bpy.ops.view3d.view_all()
