from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parent
folder = root / 'blender_addon/deadlock_porting_live'
shutil.copy2(root / 'port/live_protocol.py', folder / 'protocol.py')
shutil.copy2(root / 'port/deadlock_porting/LICENSE', folder / 'LICENSE')
destination = root / 'package/DeadlockPorting-Blender-Addon.zip'
destination.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for name in ('__init__.py', 'protocol.py', 'blender_manifest.toml', 'LICENSE'):
        archive.write(folder / name, name)
print(f'Built {destination}')
