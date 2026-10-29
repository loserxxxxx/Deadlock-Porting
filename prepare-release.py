import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import tomllib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

root = Path(__file__).resolve().parent
version = tomllib.loads((root / 'src-tauri/Cargo.toml').read_text(encoding='utf-8'))['package']['version']
key_path = Path(os.environ['DEADLOCK_UPDATE_SIGNING_KEY'])
key = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
if public != (root / 'src-tauri/update-public-key.txt').read_text().strip():
    raise SystemExit('Signing key does not match the public key embedded in the app')
content = (root / 'src-tauri/target/release/deadlock-porting.exe').read_bytes()
if not content.startswith(b'MZ'):
    raise SystemExit('Expected a Windows executable')
filename = f'DeadlockPorting-{version}-Windows-x64.exe'
destination = root / 'dist/release'
destination.mkdir(parents=True, exist_ok=True)
(destination / filename).write_bytes(content)
addon_version = tomllib.loads((root / 'blender_addon/deadlock_porting_live/blender_manifest.toml').read_text(encoding='utf-8'))['version']
addon_name = f'DeadlockPorting-Blender-Addon-{addon_version}.zip'
addon = root / 'package/DeadlockPorting-Blender-Addon.zip'
shutil.copy2(addon, destination / addon_name)
manifest = {'version': version, 'url': f'https://deadlockporting.app/downloads/{filename}', 'bytes': len(content),
    'signature': base64.b64encode(key.sign((version + '\n').encode() + content)).decode()}
(destination / 'windows.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
(destination / 'sha256.txt').write_text(hashlib.sha256(content).hexdigest() + '  ' + filename + '\n')
with (destination / 'sha256.txt').open('a', encoding='utf-8') as sums:
    sums.write(hashlib.sha256(addon.read_bytes()).hexdigest() + '  ' + addon_name + chr(10))
print(f'Prepared {version} in dist/release')
