from pathlib import Path
import re
import time
import uuid
from live_protocol import PROTOCOL, root_path, read_json, atomic_json, signature, authenticated, fingerprint


def session(identifier, expected_scene=None):
    if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
        raise ValueError('Choose a connected Blender session')
    try:
        current = read_json(root_path() / 'sessions' / (identifier + '.json'))
    except (OSError, ValueError):
        raise ValueError('Blender disconnected. Enable the Deadlock Porting add-on and refresh.')
    age = time.time() - float(current.get('heartbeat', 0))
    max_age = 240 if str(current.get('status', '')).startswith('Importing model') else 12
    if current.get('protocol') != PROTOCOL or current.get('id') != identifier or not -5 <= age <= max_age:
        raise ValueError('Blender is no longer connected. Refresh the session list.')
    if not re.fullmatch('[a-f0-9]{64}', current.get('token', '')):
        raise ValueError('Invalid Blender session')
    if not isinstance(current.get('scene_id'), str) or not isinstance(current.get('project_path'), str) or not isinstance(current.get('binary'), str):
        raise ValueError('Invalid Blender session metadata')
    if expected_scene is not None and current.get('scene_id') != expected_scene:
        raise ValueError('Blender changed scenes or projects. Select the current session and try again.')
    if not Path(current.get('binary', '')).is_file():
        raise ValueError('The connected Blender executable is unavailable')
    return current


def sessions():
    result = []
    folder = root_path() / 'sessions'
    if not folder.is_dir():
        return result
    for path in folder.glob('*.json'):
        try:
            current = session(path.stem)
            result.append({k: current.get(k) for k in ('id', 'pid', 'project_path', 'name', 'scene', 'scene_id', 'version', 'status')})
        except (OSError, ValueError, TypeError):
            continue
    return sorted(result, key=lambda item: (item.get('name', ''), item.get('pid', 0)))


def deliver(current, asset, label, timeout=180, update_status=None):
    fresh = session(current['id'], current['scene_id'])
    if fresh['token'] != current['token'] or fresh.get('project_path') != current.get('project_path'):
        raise ValueError('Blender changed projects or restarted during export. Export the model to the current session again.')
    asset = Path(asset).resolve()
    if asset.suffix.lower() != '.blend' or not asset.is_file():
        raise ValueError('Live imports require a completed Blender export')
    request_id = uuid.uuid4().hex
    queue = root_path() / 'queues' / current['id']
    inbox = queue / 'requests' / (request_id + '.json')
    receipt = queue / 'receipts' / (request_id + '.json')
    request = dict(protocol=PROTOCOL, request_id=request_id, session_id=current['id'],
                   expected_scene=current['scene_id'], expected_project=current.get('project_path', ''),
                   asset=str(asset), sha256=fingerprint(asset), label=str(label)[:100], expires=time.time() + timeout)
    request['signature'] = signature(request, current['token'])
    atomic_json(inbox, request)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if receipt.is_file():
                response = read_json(receipt)
                if not authenticated(response, current['token']) or response.get('request_id') != request_id or response.get('session_id') != current['id']:
                    raise RuntimeError('Blender returned an invalid import receipt')
                if not response.get('ok'):
                    raise RuntimeError(response.get('error', 'Blender could not import the model'))
                receipt.unlink(missing_ok=True)
                return response
            connected = session(current['id'], current['scene_id'])
            if update_status:
                update_status(connected.get('status') or 'Waiting for Blender to import the model')
            time.sleep(.2)
        raise TimeoutError('Blender did not confirm the import. Check its scene before retrying. Use Object or Pose Mode and keep the add-on enabled.')
    finally:
        inbox.unlink(missing_ok=True)
