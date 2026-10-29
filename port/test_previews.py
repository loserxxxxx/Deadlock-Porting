"""Preview queue/cache regressions without launching Blender."""
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import asset_previews as previews

MODEL = 'models/props/test.vmdl_c'


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        game = self.root / 'pak01_dir.vpk'
        game.write_bytes(b'fixture')
        self.cfg = dict(vpk=str(game), blender='blender.exe', helpers='helpers', output='out')
        patches = [patch.object(previews, 'CACHE', self.root / 'cache'),
                   patch.object(previews, 'jobs', {}), patch.object(previews, 'pending', []),
                   patch.object(previews, 'stopped', False),
                   patch.object(previews, 'runner', Mock(is_alive=Mock(return_value=True))),
                   patch.object(previews.desktop, 'settings', return_value=self.cfg),
                   patch.object(previews.desktop, 'model_catalog', return_value={'items': [{'model': MODEL}]})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.temp.cleanup)

    def test_cache_returns_image_without_queuing_render(self):
        target = previews.CACHE / previews.cache_key(MODEL, self.cfg) / 'preview.png'
        target.parent.mkdir(parents=True)
        payload = b'\x89PNG\r\n\x1a\nfixture'
        target.write_bytes(payload)
        result = previews.request([MODEL], True)[0]
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(base64.b64decode(result['image'].split(',')[1]), payload)
        self.assertFalse(previews.pending)

    def test_duplicate_requests_queue_once(self):
        for _ in range(3):
            self.assertEqual(previews.request([MODEL, MODEL], True)[0]['status'], 'queued')
        self.assertEqual(len(previews.pending), 1)

    def test_selected_asset_moves_to_front_of_queue(self):
        other = 'models/props/other.vmdl_c'
        with patch.object(previews.desktop, 'model_catalog', return_value={'items':[{'model':MODEL},{'model':other}]}):
            previews.request([MODEL,other], True)
            previews.request([other], True, priority=True)
            self.assertEqual(previews.jobs[previews.pending[0]]['model'], other)
            self.assertEqual(len(previews.pending), 2)

    def test_settings_and_game_changes_invalidate_cache(self):
        original = previews.cache_key(MODEL, self.cfg)
        self.assertNotEqual(original, previews.cache_key(MODEL, self.cfg | {'blender': 'other.exe'}))
        path = Path(self.cfg['vpk'])
        import os
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10000000))
        self.assertNotEqual(original, previews.cache_key(MODEL, self.cfg))

    def test_updates_and_export_folders_do_not_invalidate_images(self):
        original = previews.cache_key(MODEL, self.cfg)
        changed = self.cfg | {'helpers': 'new-runtime/port/helpers', 'output': 'different-export-folder'}
        self.assertEqual(original, previews.cache_key(MODEL, changed))

    def test_legacy_preview_is_not_reused_after_material_changes(self):
        import hashlib, json
        identity = dict(version=1, model=MODEL, config=self.cfg,
                        game_stamp=Path(self.cfg['vpk']).stat().st_mtime_ns)
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        old = previews.CACHE / key / 'preview.png'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'cached image')
        self.assertEqual(previews.request([MODEL], True)[0]['status'], 'queued')
        self.assertEqual(len(previews.pending), 1)

    def test_bundled_thumbnail_is_ready_on_first_launch_without_render(self):
        import hashlib, json
        folder = self.root / 'previews'
        folder.mkdir()
        (folder / 'thumb.png').write_bytes(b'bundled preview')
        (folder / 'index.json').write_text(json.dumps({
            'archive_sha256':hashlib.sha256(Path(self.cfg['vpk']).read_bytes()).hexdigest(),
            'models':{MODEL:'thumb.png'}}))
        with patch.object(previews.desktop, 'ROOT', self.root):
            result = previews.request([MODEL], True)[0]
        self.assertEqual(result['status'], 'ready')
        self.assertFalse(previews.pending)
        self.assertEqual(base64.b64decode(result['image'].split(',')[1]), b'bundled preview')

    def test_no_generation_for_unknown_models_or_oversized_pages(self):
        with self.assertRaises(ValueError):
            previews.request(['../outside.vmdl_c'], True)
        with self.assertRaises(ValueError):
            previews.request([MODEL] * 61, True)
        self.assertFalse(previews.pending)


if __name__ == '__main__':
    unittest.main()
