import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from live_protocol import atomic_json, read_json, signature, authenticated
import live_blender


class LiveBlenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {'DEADLOCK_LIVE_DATA': str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)
        self.binary = self.root / 'blender.exe'
        self.binary.write_bytes(b'fixture')
        self.current = dict(protocol=1, id=uuid.uuid4().hex, token='a' * 64, heartbeat=time.time(),
                            binary=str(self.binary), project_path='', scene_id='0:1', scene='Scene',
                            name='Untitled', version='5.2', pid=123, status='Ready')
        self.path = self.root / 'sessions' / (self.current['id'] + '.json')
        atomic_json(self.path, self.current)
        self.asset = self.root / 'hero.blend'
        self.asset.write_bytes(b'BLENDERfixture')

    def test_sessions_hide_authentication_and_allow_untitled_projects(self):
        listed = live_blender.sessions()
        self.assertEqual(listed[0]['name'], 'Untitled')
        self.assertNotIn('token', listed[0])
        self.assertEqual(live_blender.session(self.current['id'], '0:1')['project_path'], '')

    def test_stale_sessions_changed_scenes_and_path_traversal_are_rejected(self):
        with self.assertRaises(ValueError):
            live_blender.session('../outside')
        with self.assertRaisesRegex(ValueError, 'changed scenes'):
            live_blender.session(self.current['id'], 'different')
        atomic_json(self.path, self.current | {'heartbeat': time.time() - 30})
        self.assertEqual(live_blender.sessions(), [])

    def test_request_and_receipt_signatures_bind_the_asset_and_scene(self):
        data = {'asset': str(self.asset), 'scene': '0:1'}
        data['signature'] = signature(data, self.current['token'])
        self.assertTrue(authenticated(data, self.current['token']))
        self.assertFalse(authenticated(data | {'scene': 'other'}, self.current['token']))
        self.assertFalse(authenticated(data, 'b' * 64))

    def receiver(self, valid=True):
        folder = self.root / 'queues' / self.current['id']
        for _ in range(100):
            requests = list((folder / 'requests').glob('*.json'))
            if requests:
                request = read_json(requests[0])
                self.assertTrue(authenticated(request, self.current['token']))
                response = dict(request_id=request['request_id'], session_id=self.current['id'], ok=True, collection='Deadlock - Hero', objects=2)
                response['signature'] = signature(response, self.current['token'] if valid else 'wrong')
                atomic_json(folder / 'receipts' / requests[0].name, response)
                return
            time.sleep(.01)
        raise AssertionError('Request was never delivered')

    def test_authenticated_import_confirmation(self):
        worker = threading.Thread(target=self.receiver)
        worker.start()
        try:
            result = live_blender.deliver(self.current, self.asset, 'Hero', timeout=2)
            self.assertEqual(result['collection'], 'Deadlock - Hero')
        finally:
            worker.join(3)
        self.assertFalse(list((self.root / 'queues' / self.current['id'] / 'requests').glob('*.json')))

    def test_forged_receipt_is_not_treated_as_a_success(self):
        worker = threading.Thread(target=self.receiver, kwargs={'valid': False})
        worker.start()
        try:
            with self.assertRaisesRegex(RuntimeError, 'invalid import receipt'):
                live_blender.deliver(self.current, self.asset, 'Hero', timeout=2)
        finally:
            worker.join(3)

    def test_timeout_cancels_an_unclaimed_request(self):
        with self.assertRaises(TimeoutError):
            live_blender.deliver(self.current, self.asset, 'Hero', timeout=.05)
        self.assertFalse(list((self.root / 'queues' / self.current['id'] / 'requests').glob('*.json')))


if __name__ == '__main__':
    unittest.main()
