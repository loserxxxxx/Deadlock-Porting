import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile
import bpy
import addon_utils

sys.path.insert(0, str(Path(__file__).parent))
from blender_sessions import opened_projects

archive, report_path = [Path(p).resolve() for p in sys.argv[sys.argv.index('--') + 1:]]
identifier = 'deadlock_porting_live'
config = Path(bpy.utils.user_resource('CONFIG', create=True))
preferences = config / 'userpref.blend'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def install():
    if bpy.app.version < (4, 2, 0):
        raise RuntimeError('Blender 4.2 or newer is required for the live add-on')
    with zipfile.ZipFile(archive) as package:
        if set(package.namelist()) != {'__init__.py', 'protocol.py', 'blender_manifest.toml', 'LICENSE'}:
            raise RuntimeError('The bundled add-on archive is invalid')
    if preferences.is_file():
        bpy.ops.wm.read_userpref()
    automatic_save = bpy.context.preferences.use_preferences_save
    bpy.context.preferences.use_preferences_save = False
    before = digest(preferences)
    repos = list(bpy.context.preferences.extensions.repos)
    installed = [repo for repo in repos if (Path(repo.directory) / identifier / 'blender_manifest.toml').is_file()]
    if len(installed) > 1:
        raise RuntimeError('Multiple add-on copies are installed. Keep one copy in Blender Preferences before updating.')
    repo = installed[0] if installed else next((r for r in repos if r.module == 'user_default' and not r.use_remote_url), None)
    if repo is None or repo.use_remote_url:
        raise RuntimeError('A local User Default extension repository is required. Open Blender Preferences once, then retry.')
    parent = Path(repo.directory).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / identifier
    if target.exists() and target.resolve().parent != parent:
        raise RuntimeError('The add-on folder points outside its extension repository')
    backup = None
    if target.is_dir():
        backup = config / 'deadlock-addon-backups' / str(time.time_ns())
        shutil.copytree(target, backup)
    try:
        result = bpy.ops.extensions.package_install_files(filepath=str(archive), repo=repo.module,
                                                        enable_on_install=False, overwrite=True)
        if 'FINISHED' not in result or not (target / '__init__.py').is_file():
            raise RuntimeError('Blender could not install the add-on')
        module = f'bl_ext.{repo.module}.{identifier}'
        bpy.utils.refresh_script_paths()
        addon_utils.modules_refresh()
        errors = []
        def failed(*_):
            errors.append(str(sys.exc_info()[1]))
        loaded = addon_utils.enable(module, default_set=True, persistent=True, handle_error=failed)
        if loaded is None or errors:
            raise RuntimeError('The installed add-on failed its activation check: ' + '; '.join(errors))
        loaded.start()
        addon_utils.disable(module, default_set=False)
        can_save = not opened_projects()
        if digest(preferences) != before:
            raise RuntimeError('Preferences changed during installation. Enable the add-on in Blender; they were not overwritten.')
        preference_backup = None
        if can_save:
            if preferences.is_file():
                preference_backup = config / ('userpref.before-deadlock-' + str(time.time_ns()) + '.blend')
                shutil.copy2(preferences, preference_backup)
            bpy.context.preferences.use_preferences_save = automatic_save
            if opened_projects() or digest(preferences) != before:
                can_save = False
            else:
                can_save = 'FINISHED' in bpy.ops.wm.save_userpref()
        return dict(ok=True, installed=True, enabled=can_save, needs_enable=not can_save,
                    blender_version='.'.join(str(n) for n in bpy.app.version[:2]), directory=str(target),
                    preference_backup=str(preference_backup) if preference_backup else None)
    except Exception:
        if backup and target.is_dir():
            for name in ('__init__.py', 'protocol.py', 'blender_manifest.toml', 'LICENSE'):
                if (backup / name).is_file():
                    shutil.copy2(backup / name, target / name)
        raise


lock = config / 'deadlock-addon-install.lock'
handle = None


def process_alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        process = kernel.OpenProcess(0x100000, False, pid)
        if not process:
            return ctypes.get_last_error() == 5
        try:
            return kernel.WaitForSingleObject(process, 0) == 258
        finally:
            kernel.CloseHandle(process)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


try:
    if lock.is_file():
        previous_pid = lock.read_text().strip()
        if previous_pid.isdigit() and int(previous_pid) > 0 and not process_alive(int(previous_pid)):
            lock.unlink()
    handle = lock.open('x', encoding='utf-8')
    handle.write(str(os.getpid()))
    handle.flush()
    result = install()
except Exception as error:
    result = dict(ok=False, error=str(error))
finally:
    if handle is not None:
        handle.close()
        lock.unlink(missing_ok=True)
report_path.write_text(json.dumps(result), encoding='utf-8')
if not result['ok']:
    raise RuntimeError(result['error'])
