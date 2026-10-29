"""Private JSON-lines process bridge. Tauri owns its lifetime; no HTTP server."""
import base64
import json
import sys
import threading
from pathlib import Path

import desktop
import asset_previews

protocol = sys.stdout

sys.stdout = sys.stderr


def handle(operation, data):
    if operation == 'settings':
        return desktop.settings()
    if operation == 'blender_projects':
        from blender_sessions import opened_projects
        return opened_projects()
    if operation == 'live_blender_sessions':
        from live_blender import sessions
        return sessions()
    if operation == 'install_blender_addon':
        with desktop.lock:
            if desktop.state['busy']:
                raise ValueError('Wait for the current export to finish before installing the add-on')
        from addon_install import install
        from live_blender import session, sessions
        blender = desktop.settings()['blender']
        if isinstance(data, dict) and data.get('session_id'):
            blender = session(data['session_id'])['binary']
        for candidate in sessions():
            connected = session(candidate['id'])
            if str(Path(connected['binary']).resolve()).lower() == str(Path(blender).resolve()).lower():
                return dict(ok=True, installed=True, enabled=True, needs_enable=False, connected=True)
        return install(blender)
    if operation == 'scan_installations':
        desktop.detected_installations.cache_clear()
        return desktop.detected_installations()
    if operation == 'catalog':
        return desktop.catalog()
    if operation == 'models':
        return desktop.model_catalog()
    if operation == 'model_info':
        return desktop.model_info(data['model'])
    if operation == 'previews':
        return asset_previews.request(data['models'], bool(data.get('generate')), bool(data.get('retry')), bool(data.get('priority')))
    if operation == 'shutdown':
        asset_previews.shutdown()
        return True
    if operation == 'portrait':
        key = data['key']
        if not isinstance(key, str) or not key.replace('_', '').isalnum():
            raise ValueError('Invalid portrait identifier')
        return 'data:image/png;base64,' + base64.b64encode(desktop.portrait(key)).decode('ascii')
    if operation == 'state':
        with desktop.lock:
            return dict(desktop.state)
    if operation == 'close_pending':
        with desktop.lock:
            desktop.state['status'] = 'Export is running. Close the app after it finishes.'
        return True
    if operation == 'save_settings':
        with desktop.lock:
            if desktop.state['busy']:
                raise ValueError('Wait for the export to finish')
            if not isinstance(data, dict) or any(not isinstance(data.get(k), str) for k in desktop.DEFAULTS):
                raise ValueError('Settings must contain all workspace paths')
            cfg = {key: data[key] for key in desktop.DEFAULTS}
            temporary = desktop.CONFIG.with_suffix('.tmp')
            temporary.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
            temporary.replace(desktop.CONFIG)
        return {'ok': True}
    if operation == 'export':
        if not isinstance(data, dict) or data.get('format') not in ('blend', 'fbx', 'glb'):
            raise ValueError('Invalid export request')
        if data.get('destination_mode') not in (None, 'file', 'project', 'live'):
            raise ValueError('Invalid export destination')
        if data.get('destination_mode') == 'live':
            from live_blender import session
            if not isinstance(data.get('blender_scene'), str) or not data['blender_scene']:
                raise ValueError('Choose a connected Blender scene')
            session(data.get('blender_session'), data.get('blender_scene'))
        if data.get('destination_mode') == 'project':
            from project_export import validate_project
            validate_project(data.get('project_path'), require_closed=True)
        if not any(h['model'] == data.get('model') for h in desktop.model_catalog()['items']):
            raise ValueError('Select a model from the installed game')
        if not desktop.model_info(data['model'])['exportable']:
            raise ValueError('This asset contains no render geometry to export')
        with desktop.lock:
            if desktop.state['busy']:
                raise ValueError('An export is already running')
            desktop.state.update(busy=True, log='', error=None, result=None, status='Preparing export')
        threading.Thread(target=desktop.export, args=(data,), daemon=True).start()
        return {'ok': True}
    raise ValueError('Unsupported operation')


for line in sys.stdin:
    try:
        request = json.loads(line)
        result = handle(request['operation'], request.get('data'))
        response = {'result': result}
    except Exception as exc:
        response = {'error': str(exc)}
    protocol.write(json.dumps(response, ensure_ascii=True) + '\n')
    protocol.flush()
