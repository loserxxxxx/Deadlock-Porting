from pathlib import Path
import tempfile
import unittest

from installations import find_deadlock, steam_libraries


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def install(self, library, name='Deadlock'):
        vpk = library / 'steamapps/common' / name / 'game/citadel/pak01_dir.vpk'
        vpk.parent.mkdir(parents=True)
        vpk.write_bytes(b'fixture')
        return vpk.resolve()

    def test_finds_custom_library_and_manifest_install_folder(self):
        steam = self.root / 'Steam'
        other = self.root / 'Custom games'
        (steam / 'steamapps').mkdir(parents=True)
        escaped = str(other).replace('\\', '\\\\')
        (steam / 'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "' + escaped + '" } }')
        expected = self.install(other, 'My Deadlock Folder')
        (other / 'steamapps/appmanifest_1422450.acf').write_text('"AppState" { "installdir" "My Deadlock Folder" }')
        found = find_deadlock([steam])
        self.assertEqual([Path(g['path']) for g in found], [expected])

    def test_legacy_library_format_and_duplicate_roots(self):
        steam = self.root / 'Steam'
        other = self.root / 'Other'
        (steam / 'config').mkdir(parents=True)
        escaped = str(other).replace('\\', '\\\\')
        (steam / 'config/libraryfolders.vdf').write_text('"LibraryFolders" { "1" "' + escaped + '" }')
        expected = self.install(other, 'Project8')
        found = find_deadlock([steam, other, steam])
        self.assertEqual([Path(g['path']) for g in found], [expected])

    def test_ignores_missing_install_and_manifest_traversal(self):
        library = self.root / 'Library'
        (library / 'steamapps').mkdir(parents=True)
        (library / 'steamapps/appmanifest_1422450.acf').write_text('"installdir" "../../Outside"')
        self.assertEqual(find_deadlock([library]), [])
        self.assertEqual(steam_libraries([self.root / 'Missing']), [])


if __name__ == '__main__':
    unittest.main()
