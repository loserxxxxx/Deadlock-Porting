from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blender_sessions import project_from_title, describe_session
from project_export import validate_project


class BlenderSessionTests(unittest.TestCase):
    def test_saved_title_variants(self):
        for title in [r'My Scene [D:\Art\My Scene.blend] - Blender 5.2',
                      r'* My Scene [D:\Art\My Scene.blend] - Blender',
                      r'Blender [D:\Art\My Scene.blend]']:
            self.assertEqual(project_from_title(title), r'D:\Art\My Scene.blend')
        self.assertEqual(project_from_title(r'Blender [\\server\share\scene.blend]'), r'\\server\share\scene.blend')
        self.assertIsNone(project_from_title('Blender'))

    def test_unsaved_window_is_listed_without_a_file(self):
        session = describe_session(123, 'Blender*', 'blender.exe')
        self.assertIsNone(session['project_path'])
        self.assertFalse(session['saved'])
        self.assertTrue(session['modified'])

    def test_saved_path_and_protection_for_running_project(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'My Project.blend'
            project.write_bytes(b'fixture')
            session = describe_session(123, f'My Project [{project}] - Blender', 'blender.exe')
            self.assertTrue(session['saved'])
            with patch('blender_sessions.sessions_for_project', return_value=[session]):
                with self.assertRaisesRegex(ValueError, 'open in Blender'):
                    validate_project(str(project), require_closed=True)
            self.assertEqual(project.read_bytes(), b'fixture')


if __name__ == '__main__':
    unittest.main()
