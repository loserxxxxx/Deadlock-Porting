from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
from addon_install import install


class AddonInstallTests(unittest.TestCase):
    def test_missing_blender_does_not_start_an_installer(self):
        with tempfile.TemporaryDirectory() as directory, patch('addon_install.subprocess.run') as run:
            with self.assertRaises(ValueError):
                install(str(Path(directory) / 'missing.exe'))
            run.assert_not_called()

    def test_installer_result_and_private_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            binary, archive = folder / 'blender.exe', folder / 'addon.zip'
            binary.write_bytes(b'fixture')
            archive.write_bytes(b'fixture')
            def launch(command, **options):
                self.assertIn('--offline-mode', command)
                self.assertIn('--factory-startup', command)
                self.assertNotIn('PYTHONHOME', options['env'])
                self.assertIn('installer-bridge', options['env']['DEADLOCK_LIVE_DATA'])
                Path(command[-1]).write_text(json.dumps({'ok': True, 'installed': True, 'needs_enable': True}))
                return type('Result', (), {'returncode': 0})()
            with patch('addon_install.subprocess.run', side_effect=launch):
                result = install(str(binary), archive)
            self.assertTrue(result['installed'])


if __name__ == '__main__':
    unittest.main()
