"""Render a square, transparent model thumbnail in background Blender."""
import sys
from mathutils import Vector, Matrix
import bpy

source, destination = sys.argv[sys.argv.index('--') + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
for obj in bpy.context.scene.objects:
    if obj.parent is None:
        obj.matrix_world = Matrix.Scale(.01, 4) @ obj.matrix_world
bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
points = [obj.evaluated_get(deps).matrix_world @ Vector(c)
          for obj in bpy.context.scene.objects if obj.type == 'MESH'
          for c in obj.evaluated_get(deps).bound_box]
if not points:
    raise RuntimeError('No geometry to preview')
lo = Vector([min(p[k] for p in points) for k in range(3)])
hi = Vector([max(p[k] for p in points) for k in range(3)])
center = (lo + hi) / 2
size = max(max(hi - lo), .01)
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
if hasattr(scene, 'eevee') and hasattr(scene.eevee, 'taa_render_samples'):
    scene.eevee.taa_render_samples = 16
scene.render.resolution_x = scene.render.resolution_y = 384
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.filepath = destination
scene.view_settings.view_transform = 'AgX'
camera_data = bpy.data.cameras.new('Preview Camera')
camera = bpy.data.objects.new('Preview Camera', camera_data)
scene.collection.objects.link(camera)
camera.location = center + Vector((1.25, -1.8, 1.0)).normalized() * size * 3
camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
camera_data.type = 'ORTHO'
projected = [camera.rotation_euler.to_matrix().transposed() @ (p - center) for p in points]
camera_data.ortho_scale = max(max(p.x for p in projected) - min(p.x for p in projected),
                              max(p.y for p in projected) - min(p.y for p in projected), .01) * 1.2
camera_data.clip_end = max(size * 10, 100)
camera_data.clip_start = min(size / 100, .01)
scene.camera = camera
for name, offset, power, color in [
    ('Key', (-1.5, -2, 2.5), 600, (1.0, .95, .86)),
    ('Fill', (2, -1, 1), 280, (.8, .9, 1.0)),
    ('Rim', (0, 2, 2), 800, (.86, 1.0, .75))]:
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = power * size ** 2
    data.shape = 'DISK'
    data.size = size * 1.6
    data.color = color
    light = bpy.data.objects.new(name, data)
    scene.collection.objects.link(light)
    light.location = center + Vector(offset) * size
    light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
scene.world = bpy.data.worlds.new('Preview World')
scene.world.color = (.15, .15, .15)
bpy.ops.render.render(write_still=True)
print('PREVIEW_COMPLETE', flush=True)
