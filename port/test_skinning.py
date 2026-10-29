"""Regression: 8- and 16-bit Source skinning must retain limb influences."""
import unittest
import numpy as np
from deadlock_port import attrs


class SkinningTests(unittest.TestCase):
    def decode(self, index_format, weight_format, index_dtype, weight_dtype, weights):
        positions = np.array([[1, 2, 3]], dtype='<f4').tobytes()
        indices = np.array([[1, 2, 0, 0]], dtype=index_dtype).tobytes()
        packed_weights = np.array([weights], dtype=weight_dtype).tobytes()
        stride = len(positions + indices + packed_weights)
        fields = [dict(m_pSemanticName='POSITION', m_nOffset=0, m_Format=6),
                  dict(m_pSemanticName='BLENDINDICES', m_nOffset=12, m_Format=index_format),
                  dict(m_pSemanticName='blendweight', m_nOffset=12 + len(indices), m_Format=weight_format)]
        return attrs(np.frombuffer(positions + indices + packed_weights, np.uint8).reshape(1, stride),
                     fields, stride, np.array([0, 17, 42]))[2:]

    def test_16bit_limb_influences(self):
        joints, weights = self.decode(12, 11, '<u2', '<u2', [49151, 16384, 0, 0])
        np.testing.assert_array_equal(joints, [[17, 42, 0, 0]])
        np.testing.assert_allclose(weights, [[.75, .25, 0, 0]], atol=2e-5)

    def test_8bit_limb_influences(self):
        joints, weights = self.decode(30, 28, 'u1', 'u1', [153, 102, 0, 0])
        np.testing.assert_array_equal(joints, [[17, 42, 0, 0]])
        np.testing.assert_allclose(weights, [[.6, .4, 0, 0]], atol=1e-6)

    def test_valve_eight_influences(self):
        positions = np.array([[1, 2, 3]], dtype='<f4').tobytes()
        indices = bytes([1, 2, 3, 4, 5, 6, 7, 8])
        weights = bytes([100, 60, 40, 20, 15, 10, 5, 5])
        fields = [dict(m_pSemanticName='POSITION', m_nOffset=0, m_Format=6),
                  dict(m_pSemanticName='BLENDINDICES', m_nOffset=12, m_Format=12),
                  dict(m_pSemanticName='blendweight', m_nOffset=20, m_Format=11)]
        _, _, j, w = attrs(np.frombuffer(positions + indices + weights, np.uint8).reshape(1, 28),
                            fields, 28, np.arange(20))
        np.testing.assert_array_equal(j, [list(indices)])
        np.testing.assert_allclose(w, [np.array(list(weights)) / 255], atol=1e-6)


if __name__ == '__main__':
    unittest.main()
