import json
from pathlib import Path
import struct
import tempfile
import unittest
import numpy as np
from deadlock_port import vertex_colors, uses_vertex_colors, write_glb


class VertexColorTests(unittest.TestCase):
    def test_normalized_rgba_and_bgra(self):
        fields = [{'m_pSemanticName': 'COLOR', 'm_nSemanticIndex': 0, 'm_Format': 28, 'm_nOffset': 0}]
        vertices = np.array([[31, 29, 100, 255], [231, 7, 229, 128]], np.uint8)
        expected = vertices.astype(np.float32) / 255.0
        rgb = expected[:, :3]
        expected[:, :3] = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
        np.testing.assert_allclose(vertex_colors(vertices, fields, 4), expected)
        fields[0]['m_Format'] = 87
        np.testing.assert_allclose(vertex_colors(vertices, fields, 4), expected[:, [2, 1, 0, 3]])

    def test_srgb_midpoint_and_alpha_are_not_interchangeable(self):
        fields = [{'m_pSemanticName': 'COLOR', 'm_Format': 28, 'm_nOffset': 0}]
        vertices = np.array([[128, 10, 255, 128]], np.uint8)
        np.testing.assert_allclose(vertex_colors(vertices, fields, 4),
                                   [[0.2158605, 0.00303527, 1.0, 0.5019608]], rtol=1e-5)

    def test_material_flag_is_required(self):
        self.assertFalse(uses_vertex_colors({}))
        self.assertFalse(uses_vertex_colors({'m_intParams': [{'m_name': 'F_VERTEX_COLOR', 'm_nValue': 0}]}))
        self.assertTrue(uses_vertex_colors({'m_intParams': [{'m_name': 'F_VERTEX_COLOR', 'm_nValue': 1}]}))

    def test_glb_retains_colors_only_for_materials_that_use_them(self):
        colors = np.array([[.1, .2, .3, 1], [.4, .5, .6, 1], [.7, .8, .9, 1]], np.float32)
        part = {'name': 'fixture', 'pos': np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
                'uv': None, 'joints': np.zeros((3, 4), np.uint16), 'weights': np.zeros((3, 4), np.float32),
                'idx': np.array([0, 1, 2, 0, 2, 1], np.uint32),
                'draws': [(0, 3, 'painted'), (3, 3, 'plain')], 'colors': colors, 'vertex_color_materials': {'painted'}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.glb'
            write_glb(path, 'fixture', [part], None, [('painted', None, (1, 1, 1, 1)), ('plain', None, (1, 1, 1, 1))])
            raw = path.read_bytes()
        json_size = struct.unpack_from('<I', raw, 12)[0]
        tree = json.loads(raw[20:20 + json_size])
        painted, plain = tree['meshes'][0]['primitives']
        self.assertIn('COLOR_0', painted['attributes'])
        self.assertNotIn('COLOR_0', plain['attributes'])
        accessor = tree['accessors'][painted['attributes']['COLOR_0']]
        view = tree['bufferViews'][accessor['bufferView']]
        offset = 20 + json_size + 8 + view.get('byteOffset', 0)
        decoded = np.frombuffer(raw, '<f4', count=12, offset=offset).reshape(3, 4)
        np.testing.assert_array_equal(decoded, colors)


if __name__ == '__main__':
    unittest.main()
