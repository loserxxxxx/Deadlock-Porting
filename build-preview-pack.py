"""Render and package the curated gameplay thumbnails for first-launch display."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'port'))
import desktop
import asset_previews as previews

items = [i for i in desktop.model_catalog()['items'] if i['important_prop']]
folder = ROOT / 'port/previews'
folder.mkdir(exist_ok=True)
models = [i['model'] for i in items]
for offset in range(0, len(models), 60):
    previews.request(models[offset:offset + 60], True)
deadline = time.monotonic() + 1200
last = -1
try:
    while True:
        results = [r for offset in range(0, len(models), 60)
                   for r in previews.request(models[offset:offset + 60])]
        ready = sum(r['status'] == 'ready' for r in results)
        if ready != last:
            print(f'Preview pack: {ready}/{len(items)} ready', flush=True)
            last = ready
        failures = [r for r in results if r['status'] == 'error']
        if failures:
            raise RuntimeError(failures)
        if ready == len(items):
            break
        if time.monotonic() > deadline:
            raise RuntimeError('Preview pack render timed out')
        time.sleep(1)
    cfg = desktop.settings()
    index = {'archive_sha256': hashlib.sha256(Path(cfg['vpk']).read_bytes()).hexdigest(), 'models': {}}
    for item in items:
        model = item['model']
        filename = hashlib.sha256(model.encode()).hexdigest() + '.png'
        source = previews.CACHE / previews.cache_key(model, cfg) / 'preview.png'
        shutil.copy2(source, folder / filename)
        index['models'][model] = filename
    (folder / 'index.json').write_text(json.dumps(index, indent=2))
    print('Bundled preview pack complete', flush=True)
finally:
    previews.shutdown()
