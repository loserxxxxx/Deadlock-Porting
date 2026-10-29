"""Build the private runtime ZIP embedded into the Rust executable."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
subprocess.run([sys.executable, str(ROOT / 'build-blender-addon.py')], check=True)
PACKAGE = ROOT / 'package'
PACKAGE.mkdir(exist_ok=True)
if not (ROOT / 'port/previews/index.json').is_file():
    raise RuntimeError('Run build-preview-pack.py before packaging the standalone runtime')
archive = PACKAGE / 'python-3.12.10-embed-amd64.zip'
url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
if not archive.is_file():
    urllib.request.urlretrieve(url, archive)
verification = json.load(urllib.request.urlopen(url + '.sigstore'))
digest = verification['messageSignature']['messageDigest']['digest']
assert hashlib.sha256(archive.read_bytes()).digest() == base64.b64decode(digest), 'Python download digest mismatch'
webview = PACKAGE / 'MicrosoftEdgeWebview2Setup.exe'
if not webview.is_file():
    urllib.request.urlretrieve('https://go.microsoft.com/fwlink/p/?LinkId=2124703', webview)
subprocess.run([shutil.which('pwsh') or 'powershell.exe', '-NoProfile', '-File', str(ROOT / 'verify-microsoft-signature.ps1'), '-Path', str(webview)], check=True)

with tempfile.TemporaryDirectory(prefix='payload-', dir=PACKAGE) as temporary:
    stage = Path(temporary)
    runtime = stage / 'runtime'
    runtime.mkdir()
    with zipfile.ZipFile(archive) as embedded:
        embedded.extractall(runtime)
    shutil.copy2(webview, runtime / webview.name)
    (runtime / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n../port\nimport site\n')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                    '--target', str(runtime / 'Lib/site-packages'), '-r', str(ROOT / 'port/requirements-bundled.txt')], check=True)
    port = stage / 'port'
    port.mkdir()
    for name in ('desktop.py', 'tauri_bridge.py', 'installations.py', 'curated_props.py', 'rig_policy.py', 'deadlock_port.py',
                 'blender_export.py', 'blender_open.py', 'blender_append.py', 'blender_sessions.py', 'project_export.py', 'hero_props.py',
                 'asset_previews.py', 'render_preview.py', 'live_blender.py', 'live_protocol.py',
                 'addon_install.py', 'blender_install_addon.py'):
        shutil.copy2(ROOT / 'port' / name, port / name)
    shutil.copy2(ROOT / 'package/DeadlockPorting-Blender-Addon.zip', port / 'DeadlockPorting-Blender-Addon.zip')
    for name in ('helpers', 'deadlock_porting', 'previews'):
        shutil.copytree(ROOT / 'port' / name, port / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    requirements = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze', '--path', str(runtime / 'Lib/site-packages')], text=True)
    (stage / 'DEPENDENCIES.txt').write_text(requirements, encoding='utf-8')
    (stage / 'README.txt').write_text('Deadlock Porting private runtime. Python LICENSE.txt and package licenses are retained with the runtime.\nRendered preview thumbnails are included. No game model files, source textures or Blender binary are included.\n', encoding='utf-8')
    payload = PACKAGE / 'payload.zip'
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for file in sorted(stage.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                output.write(file, file.relative_to(stage).as_posix())
    fingerprint = hashlib.sha256(payload.read_bytes()).hexdigest()
    (PACKAGE / 'payload.sha256').write_text(fingerprint)
    print(f'Runtime payload: {payload.stat().st_size / 1024 / 1024:.1f} MiB; SHA256 {fingerprint}')
