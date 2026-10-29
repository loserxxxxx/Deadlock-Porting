from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_export import append_to_project, claim_project, validate_project


class ProjectExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'Existing Project.blend'
        self.project.write_bytes(b'original project')
        self.asset = self.root / 'hero.blend'
        self.asset.write_bytes(b'hero')

    def test_commit_keeps_exact_backup(self):
        def worker(command, env):
            Path(command[-1]).write_bytes(b'merged project')
        backup = append_to_project(self.project, self.asset, {'blender':'blender.exe'}, {}, worker, self.root)
        self.assertEqual(self.project.read_bytes(), b'merged project')
        self.assertEqual(backup.read_bytes(), b'original project')
        self.assertFalse(list(self.root.glob('*.lock')))

    def test_blender_failure_leaves_original_untouched(self):
        def worker(command, env):
            raise RuntimeError('Blender failed')
        with self.assertRaises(RuntimeError):
            append_to_project(self.project, self.asset, {'blender':'blender.exe'}, {}, worker, self.root)
        self.assertEqual(self.project.read_bytes(), b'original project')
        self.assertFalse(list(self.root.glob('*.lock')))

    def test_concurrent_edit_is_not_overwritten(self):
        def worker(command, env):
            Path(command[-1]).write_bytes(b'merged project')
            self.project.write_bytes(b'user edits')
        with self.assertRaisesRegex(RuntimeError, 'changed during import'):
            append_to_project(self.project, self.asset, {'blender':'blender.exe'}, {}, worker, self.root)
        self.assertEqual(self.project.read_bytes(), b'user edits')
        self.assertFalse(list(self.root.glob('.*.deadlock-*.blend')))

    def test_project_opened_during_merge_is_not_replaced(self):
        def worker(command, env):
            Path(command[-1]).write_bytes(b'merged project')
        with patch('blender_sessions.sessions_for_project', side_effect=[[], [{'pid':123}]]):
            with self.assertRaisesRegex(ValueError, 'open in Blender'):
                append_to_project(self.project, self.asset, {'blender':'blender.exe'}, {}, worker, self.root)
        self.assertEqual(self.project.read_bytes(), b'original project')

    def test_only_saved_blend_files_and_one_import_per_project(self):
        with self.assertRaises(ValueError):
            validate_project(str(self.root / 'missing.blend'))
        with self.assertRaises(ValueError):
            validate_project('')
        with claim_project(self.project):
            with self.assertRaises(ValueError):
                with claim_project(self.project):
                    pass


if __name__ == '__main__':
    unittest.main()
