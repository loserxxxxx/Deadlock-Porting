import json
import os
from pathlib import Path
import subprocess
import tempfile


def install(blender, archive=None, extra_env=None):
    root = Path(__file__).resolve().parent
    executable = Path(blender).expanduser().resolve()
    if not executable.is_file():
        raise ValueError('Choose a Blender executable in Settings first')
    if archive is None:
        archive = root / 'DeadlockPorting-Blender-Addon.zip'
        if not archive.is_file():
            archive = root.parent / 'package/DeadlockPorting-Blender-Addon.zip'
    archive = Path(archive).resolve()
    if not archive.is_file():
        raise ValueError('The bundled Blender add-on is unavailable. Update the app and retry.')
    with tempfile.TemporaryDirectory(prefix='deadlock-addon-') as temporary:
        folder = Path(temporary)
        report = folder / 'result.json'
        environment = dict(os.environ)
        environment.pop('PYTHONHOME', None)
        environment.pop('PYTHONPATH', None)
        environment.update(extra_env or {})
        environment['DEADLOCK_LIVE_DATA'] = str(folder / 'installer-bridge')
        command = [str(executable), '--background', '--factory-startup', '--disable-autoexec', '--offline-mode',
                   '--python-exit-code', '1', '--python', str(root / 'blender_install_addon.py'), '--', str(archive), str(report)]
        try:
            process = subprocess.run(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            raise RuntimeError('Blender took too long to install the add-on. Check Preferences before retrying.')
        if not report.is_file():
            raise RuntimeError('Blender could not start the installer. Check the Blender path in Settings.')
        result = json.loads(report.read_text(encoding='utf-8'))
        if process.returncode or not result.get('ok'):
            raise RuntimeError(result.get('error', 'Blender add-on installation failed'))
        return result
