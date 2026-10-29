import hashlib
import json
from pathlib import Path
import runpy
import sys
import bpy

profile, archive, mode = sys.argv[sys.argv.index('--') + 1:]
profile, archive = Path(profile).resolve(), Path(archive).resolve()
root = Path(__file__).resolve().parents[1]
config = Path(bpy.utils.user_resource('CONFIG', create=True)).resolve()
assert config.is_relative_to(profile), 'The test must use an isolated Blender profile'
bpy.context.preferences.inputs.use_mouse_emulate_3_button = True
bpy.context.preferences.view.show_splash = False
bpy.ops.wm.save_userpref()
preferences = config / 'userpref.blend'
before = hashlib.sha256(preferences.read_bytes()).hexdigest()
sys.path.insert(0, str(root / 'port'))
import blender_sessions
blender_sessions.opened_projects = (lambda: [{'pid': 1}]) if mode == 'open' else (lambda: [])
report = profile / 'result.json'
sys.argv = ['installer', '--', str(archive), str(report)]
runpy.run_path(str(root / 'port/blender_install_addon.py'), run_name='__main__')
result = json.loads(report.read_text())
assert result['ok'] and Path(result['directory']).is_relative_to(profile)
if mode == 'open':
    assert hashlib.sha256(preferences.read_bytes()).hexdigest() == before
    assert result['needs_enable'] and not result['enabled']
else:
    assert result['enabled'] and not result['needs_enable']
    assert result['preference_backup'] and Path(result['preference_backup']).is_file()
bpy.ops.wm.read_userpref()
assert bpy.context.preferences.inputs.use_mouse_emulate_3_button
assert not bpy.context.preferences.view.show_splash
assert ('bl_ext.user_default.deadlock_porting_live' in bpy.context.preferences.addons) == (mode == 'closed')
print('INSTALL_PROFILE_VERIFIED', json.dumps({'mode': mode, 'preferences_preserved': True, 'enabled': result['enabled']}))
