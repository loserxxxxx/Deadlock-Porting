"""One low-priority preview renderer, cached by asset, game version and settings."""
import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from functools import lru_cache

import desktop

CACHE = desktop.DATA_ROOT / '.preview-cache'
LOCK = threading.Lock()
jobs = {}
pending = []
current_process = None
stopped = False
runner = None


def cache_key(model, cfg):
    identity = dict(version=2, model=model, game=str(Path(cfg['vpk']).resolve()).lower(),
                    blender=cfg['blender'],
                    game_stamp=Path(cfg['vpk']).stat().st_mtime_ns)
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def migrate_cached_preview(model, cfg, target):
    """Reuse compatible thumbnails from older app payload directories."""
    if seed_bundled_preview(model, cfg, target):
        return
    helpers = {cfg['helpers']}
    runtime = desktop.DATA_ROOT / 'runtime'
    if runtime.is_dir():
        helpers.update(str(p / 'port/helpers') for p in runtime.iterdir() if p.is_dir())
    for helper in helpers:
        identity = dict(version=1, model=model, config=cfg | {'helpers': helper},
                        game_stamp=Path(cfg['vpk']).stat().st_mtime_ns)
        old_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        old = CACHE / old_key / 'preview.png'
        if old.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, target)
            return


@lru_cache(maxsize=8)
def archive_fingerprint(path, stamp):
    digest = hashlib.sha256()
    with open(path, 'rb') as archive:
        for chunk in iter(lambda: archive.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=4)
def bundled_index(folder):
    try:
        return json.loads((Path(folder) / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def seed_bundled_preview(model, cfg, target):
    folder = desktop.ROOT / 'previews'
    index = bundled_index(str(folder))
    filename = index.get('models', {}).get(model)
    if not filename or Path(filename).name != filename:
        return False
    stamp = Path(cfg['vpk']).stat().st_mtime_ns
    if index.get('archive_sha256') != archive_fingerprint(cfg['vpk'], stamp):
        return False
    source = folder / filename
    if not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def snapshot(job):
    result = {k: job[k] for k in ('model', 'status')}
    if job.get('error'):
        result['error'] = job['error']
    if job['status'] == 'ready':
        result['image'] = 'data:image/png;base64,' + base64.b64encode(job['path'].read_bytes()).decode('ascii')
    return result


def request(models, generate=False, retry=False, priority=False):
    global runner
    if not isinstance(models, list) or len(models) > 60 or any(not isinstance(m, str) for m in models):
        raise ValueError('Request up to 60 model previews at a time')
    cfg = desktop.settings()
    valid = {h['model'] for h in desktop.model_catalog()['items']}
    if any(m not in valid for m in models):
        raise ValueError('Preview model is not in the game archive')
    result = []
    with LOCK:
        for model in dict.fromkeys(models):
            key = cache_key(model, cfg)
            path = CACHE / key / 'preview.png'
            if not path.is_file():
                migrate_cached_preview(model, cfg, path)
            job = jobs.setdefault(key, dict(model=model, status='missing', path=path, cfg=cfg))
            if path.is_file():
                job.update(status='ready', error=None)
            if generate and not stopped and job['status'] in (('missing', 'error') if retry else ('missing',)):
                if len(pending) >= 120:
                    result.append(dict(model=model, status='error', error='Preview queue is full. Try again after it finishes.'))
                    continue
                job.update(status='queued', error=None)
                pending.append(key)
            if priority and key in pending:
                pending.remove(key)
                pending.insert(0, key)
            result.append(snapshot(job))
        if pending and (runner is None or not runner.is_alive()):
            runner = threading.Thread(target=work, daemon=True)
            runner.start()
    return result


def run(command, env, output):
    global current_process
    with LOCK:
        if stopped:
            raise RuntimeError('Preview rendering stopped')
        process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0))
        current_process = process
    try:
        if process.wait(timeout=180):
            raise RuntimeError('Preview generation failed. See preview.log in the preview cache for details.')
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise RuntimeError('Preview generation timed out after three minutes')
    finally:
        with LOCK:
            current_process = None


def work():
    while True:
        
        with desktop.lock:
            exporting = desktop.state['busy']
        with LOCK:
            if stopped or not pending:
                return
            if not exporting:
                key = pending.pop(0)
                job = jobs[key]
                job['status'] = 'rendering'
        if exporting:
            time.sleep(.25)
            continue
        try:
            cfg, model, target = job['cfg'], job['model'], job['path']
            details = desktop._model_info(json.dumps(cfg, sort_keys=True), Path(cfg['vpk']).stat().st_mtime_ns, model)
            if not details['exportable']:
                raise RuntimeError('This asset contains no render geometry')
            if not Path(cfg['blender']).is_file():
                raise RuntimeError('Choose a valid Blender executable in Settings to generate previews')
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='work-', dir=target.parent) as workdir:
                env = os.environ | dict(DEADLOCK_VPK=cfg['vpk'], DEADLOCK_HELPERS=cfg['helpers'],
                                        DEADLOCK_OUT=workdir, PYTHONUNBUFFERED='1')
                python = str(Path(sys.executable).with_name('python.exe')) if sys.executable.lower().endswith('pythonw.exe') else sys.executable
                with (target.parent / 'preview.log').open('w', encoding='utf-8') as output:
                    run([python, str(desktop.ROOT / 'deadlock_port.py'), model], env, output)
                    stem = model.rsplit('/', 1)[-1][:-7]
                    rendered = Path(workdir) / 'preview.png'
                    run([cfg['blender'], '--background', '--python-exit-code', '1', '--python',
                         str(desktop.ROOT / 'render_preview.py'), '--',
                         str(Path(workdir) / stem / (stem + '.glb')), str(rendered)], env, output)
                if not rendered.is_file():
                    raise RuntimeError('Blender did not create a preview image')
                rendered.replace(target)
            with LOCK:
                job.update(status='ready', error=None)
        except Exception as error:
            with LOCK:
                job.update(status='error', error=str(error))


def shutdown():
    global stopped
    with LOCK:
        stopped = True
        pending.clear()
        if current_process is not None:
            current_process.kill()
    if runner is not None and runner is not threading.current_thread():
        runner.join(timeout=5)
