"""Local desktop UI. No web service or account required."""
import json
import hashlib
import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get('DEADLOCK_DATA_DIR', str(ROOT)))
DATA_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / '.deps'))
CONFIG = DATA_ROOT / 'desktop-settings.json'
TOKEN = secrets.token_urlsafe(32)
DEFAULTS = dict(vpk='', helpers=str(ROOT / 'helpers'), output=str(DATA_ROOT / 'out'), blender='')
state = dict(busy=False, log='', status='Ready', error=None)
lock = threading.Lock()


def settings():
    cfg = DEFAULTS | (json.loads(CONFIG.read_text()) if CONFIG.exists() else {})
    detected = detected_installations()
    if not Path(cfg['vpk']).is_file() and detected['deadlock']:
        cfg['vpk'] = detected['deadlock'][0]['path']
    if not Path(cfg['blender']).is_file() and detected['blender']:
        cfg['blender'] = detected['blender'][0]
    cfg['helpers'] = DEFAULTS['helpers']
    return cfg


@lru_cache(maxsize=1)
def detected_installations():
    from installations import find_deadlock, find_blender
    return {'deadlock': find_deadlock(), 'blender': find_blender()}


def game_stamp(cfg):
    if not Path(cfg['vpk']).is_file():
        raise FileNotFoundError('Deadlock was not found. Scan for installations in Settings or enter the path to pak01_dir.vpk.')
    return Path(cfg['vpk']).stat().st_mtime_ns


def setup_paths(cfg):
    root = Path(cfg['helpers'])
    for p in ('', 'clarity', 'vfx', 'vfx/_py', 'noshake/_wheels/zstd',
              'heroes/_wheels', 'heroes/_wheels/texture2ddecoder', 'mono'):
        path = str(root / p)
        if path not in sys.path:
            sys.path.insert(0, path)


def catalog():
    cfg = settings()
    return _catalog(json.dumps(cfg, sort_keys=True), game_stamp(cfg))


@lru_cache(maxsize=4)
def _catalog(config_json, game_stamp):
    cfg = json.loads(config_json)
    setup_paths(cfg)
    from pakio import Pak
    pak = Pak(cfg['vpk'])
    heroes = []
    
    aliases = dict(archer='Grey Talon', astro='Holliday', bull='Abrams',
                   chrono='Paradox', digger='Mo & Krill', engineer='McGinnis',
                   forge='Rem', ghost='Lady Geist', gigawatt='Seven',
                   gunslinger='Wraith', haze='Haze', hornet='Vindicta',
                   inferno='Infernus', kelvin='Kelvin', lash='Lash',
                   magician='Sinclair', mirage='Mirage', nano='Ivy',
                   shiv='Shiv', synth='Viscous', tengu='Dynamo',
                   viscous='Viscous', warden='Warden', yamato='Yamato')
    
    import types
    sys.modules.setdefault('vpk', types.ModuleType('vpk'))
    from kv3 import KV3File
    from make_fog import data_block, unwrap
    definitions = KV3File(unwrap(data_block(pak.read('scripts/heroes.vdata_c')))).read()
    for key, data in definitions.items():
        if not isinstance(data, dict) or key == 'hero_base':
            continue
        model = data.get('m_strModelName', '') + '_c'
        if model not in pak.entries:
            continue
        key = key.removeprefix('hero_')
        icon = data.get('m_strIconImageSmall', '').split('/')[-1].rsplit('.', 1)[0]
        portrait = f'panorama/images/heroes/{icon.replace("_sm", "_vertical")}_psd.vtex_c'
        if portrait not in pak.entries:
            portrait = f'panorama/images/heroes/{icon}_psd.vtex_c'
        logo = data.get('m_strLogoImageEnglish', '').split('/')[-1].replace('.svg', '')
        display = logo.replace('_', ' ').title() if logo else aliases.get(key, key.replace('_', ' ').title())
        display = {'Mo Krill': 'Mo & Krill', 'Mcginnis': 'McGinnis'}.get(display, display)
        display_names = {
            'deadpack': 'Deadman Danny', 'familiar': 'Rem',
            'fencer': 'Apollo', 'necro': 'Graves', 'priest': 'Venator',
            'unicorn': 'Celeste', 'werewolf': 'Silver',
        }
        display = display_names.get(key, display_names.get(Path(model).name.removesuffix('.vmdl_c'), display))
        heroes.append(dict(id=key, name=display, model=model,
                           development=data.get('m_eHeroDevelopmentState') != 'EHeroDevState_Release',
                           portrait=portrait if portrait in pak.entries else ''))
    unique = {h['model']: h for h in heroes}
    return sorted(unique.values(), key=lambda h: h['name'])


def portrait(key):
    cfg = settings()
    stamp = cfg['vpk'] + str(Path(cfg['vpk']).stat().st_mtime_ns)
    cache = DATA_ROOT / '.portrait-cache' / hashlib.sha256(stamp.encode()).hexdigest()[:16]
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (key + '.png')
    if not target.exists():
        cfg = settings()
        setup_paths(cfg)
        import types
        sys.modules.setdefault('vpk', types.ModuleType('vpk'))
        from pakio import Pak
        from make_mono import parse, decode, mip_offsets
        from PIL import Image
        pak = Pak(cfg['vpk'])
        hero = next(h for h in catalog() if h['id'] == key)
        if not hero['portrait']:
            raise FileNotFoundError('No portrait')
        raw = pak.read(hero['portrait'])
        info = parse(raw)
        offsets, _ = mip_offsets(info)
        offset, size = offsets[0]
        
        image = decode(info['fmt'], raw[offset:offset + size], info['w'], info['h'])
        Image.fromarray(image).save(target)
    return target.read_bytes()


def asset_category(path):
    folder = path.split('/')[1] if '/' in path else ''
    if folder.startswith('heroes'):
        return 'heroes'
    if folder.startswith('npc'):
        return 'npcs'
    if folder.startswith('props') or folder in ('items', 'weapons', 'clutter', 'abilities', 'particle'):
        return 'props'
    if folder in ('architecture', 'hideout', 'base', 'factory', 'foliage', 'park',
                  'railings', 'waterfront', 'street', 'diner', 'wallstreet', 'pipes',
                  'backdrop', 'rooftop', 'broadway', 'map', 'terrain', 'buildings'):
        return 'map'
    return 'other'


def model_catalog():
    cfg = settings()
    return _model_catalog(json.dumps(cfg, sort_keys=True), game_stamp(cfg))


@lru_cache(maxsize=4)
def _model_catalog(config_json, stamp):
    cfg = json.loads(config_json)
    setup_paths(cfg)
    from pakio import Pak
    from curated_props import curated_prop
    heroes = {h['model']: h for h in _catalog(config_json, stamp)}
    items = []
    for path in Pak(cfg['vpk']).entries:
        if not path.endswith('.vmdl_c'):
            continue
        stem = path.rsplit('/', 1)[-1][:-7]
        item = dict(id=hashlib.sha256(path.encode()).hexdigest()[:16],
                    name=stem.replace('_', ' ').title(), model=path,
                    category=asset_category(path), roster=False, portrait='', development=False)
        if path in heroes:
            item.update(heroes[path], roster=True)
        item.update(curated_prop(path))
        items.append(item)
    items.sort(key=lambda h: (h['name'].lower(), h['model']))
    from collections import Counter
    counts = dict(Counter(h['category'] for h in items))
    counts['heroes'] = sum(h['roster'] for h in items)
    counts['props'] = sum(h['important_prop'] for h in items)
    counts['all'] = len(items)
    return {'items': items, 'counts': counts}


def model_info(model):
    cfg = settings()
    return _model_info(json.dumps(cfg, sort_keys=True), game_stamp(cfg), model)


@lru_cache(maxsize=256)
def _model_info(config_json, stamp, model):
    cfg = json.loads(config_json)
    setup_paths(cfg)
    from pakio import Pak
    from kv3 import KV3File, resource_blocks
    from make_fog import data_block, unwrap
    pak = Pak(cfg['vpk'])
    if not model.endswith('.vmdl_c') or model not in pak.entries:
        raise ValueError('Model is not in the installed game archive')
    raw = pak.read(model)
    data = KV3File(unwrap(data_block(raw))).read()
    bones = data.get('m_modelSkeleton', {}).get('m_boneName', [])
    from rig_policy import character_asset
    riggable = bool(bones) and character_asset(model)
    ctrl = next((KV3File(raw[o:o+s]).read() for t, o, s in resource_blocks(raw) if t == b'CTRL'), {})
    from deadlock_port import embedded_meshes, render_meshes
    blocks = resource_blocks(raw)
    meshes = render_meshes(data, embedded_meshes(raw, blocks, ctrl))
    exportable = any(vb['m_nElementCount'] for m in meshes for vb in m.get('m_vertexBuffers', []))
    return dict(bones=len(bones), skinned=riggable, source_skinned=bool(bones),
                controls=riggable and 'pelvis' in bones and any(n in bones for n in ('leg_upper_L', 'thigh_l')),
                meshes=len(meshes), exportable=exportable,
                model=model)


def log(line):
    with lock:
        state['log'] = (state['log'] + line)[-60000:]


def run(command, env):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace', env=env,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for line in process.stdout:
        log(line)
    if process.wait():
        raise RuntimeError('Export failed. See the activity log for details.')


def open_in_blender(destination, cfg, env, log_folder=None):
    destination = Path(destination)
    command = [cfg['blender'], str(destination)] if destination.suffix == '.blend' else [
        cfg['blender'], '--python', str(ROOT / 'blender_open.py'), '--', str(destination)]
    with (Path(log_folder or destination.parent) / 'blender-open.log').open('w', encoding='utf-8') as output:
        return subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def export(request):
    try:
        cfg = settings()
        hero = next(h for h in model_catalog()['items'] if h['model'] == request['model'])
        if not model_info(hero['model'])['exportable']:
            raise ValueError('This asset contains no render geometry to export')
        fmt = request['format']
        project = None
        if request.get('destination_mode') == 'project':
            from project_export import validate_project
            project = validate_project(request.get('project_path'), require_closed=True)
            fmt = 'blend'
        if fmt not in ('glb', 'blend', 'fbx'):
            raise ValueError('Unsupported format')
        if (fmt != 'glb' or request.get('open_blender', True)) and not Path(cfg['blender']).is_file():
            raise ValueError('Choose a valid Blender executable in Settings')
        env = os.environ | dict(DEADLOCK_VPK=cfg['vpk'], DEADLOCK_HELPERS=cfg['helpers'], DEADLOCK_OUT=cfg['output'], PYTHONUNBUFFERED='1')
        stem = hero['model'].rsplit('/', 1)[-1][:-7]
        asset_folder = Path(stem) if hero['roster'] else Path(hero['category']) / (stem + '-' + hashlib.sha256(hero['model'].encode()).hexdigest()[:8])
        folder = Path(cfg['output']) / asset_folder / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f'{stem}.{fmt}'
        if destination.exists():
            raise ValueError(f'{destination} already exists. Choose another output folder to preserve it.')
        with lock:
            state['status'] = 'Extracting model and textures'
        source = folder / f'{stem}.glb'
        
        staging = folder.parent / ('.extract-' + folder.name)
        env['DEADLOCK_OUT'] = str(staging)
        python = str(Path(sys.executable).with_name('python.exe')) if sys.executable.lower().endswith('pythonw.exe') else sys.executable
        run([python, str(ROOT / 'deadlock_port.py'), hero['model']], env)
        import shutil
        for item in (staging / stem).iterdir():
            shutil.move(str(item), str(folder / item.name))
        (staging / stem).rmdir()
        staging.rmdir()
        if fmt != 'glb':
            with lock:
                state['status'] = 'Building Blender export'
            run([cfg['blender'], '--background', '--python-exit-code', '1', '--python',
                 str(ROOT / 'blender_export.py'), '--', str(source), str(destination),
                 fmt, str(bool(request.get('controls'))).lower()], env)
        if not destination.is_file():
            raise RuntimeError('Output file was not created')
        result = destination
        backup = None
        if project is not None:
            from project_export import append_to_project
            with lock:
                state['status'] = 'Adding model to existing project'
            backup = append_to_project(project, destination, cfg, env, run, ROOT)
            result = project
        if request.get('open_blender', True):
            with lock:
                state['status'] = 'Opening Blender'
            open_in_blender(result, cfg, env, log_folder=folder)
        with lock:
            message = f'Added to project: {result}. Backup: {backup}' if project is not None else f'Export complete: {result}'
            state.update(status=message, result=str(result), asset=str(destination), project_backup=str(backup) if backup else None)
    except Exception as exc:
        log(str(exc) + '\n')
        with lock:
            state.update(status='Export failed', error=str(exc))
    finally:
        with lock:
            state['busy'] = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, value, code=200, mime='application/json'):
        data = json.dumps(value).encode() if mime == 'application/json' else value
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path == '/':
                html = (ROOT / 'desktop.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN)
                return self.send(html.encode(), mime='text/html; charset=utf-8')
            if self.path == '/api/catalog':
                return self.send(catalog())
            if self.path == '/api/settings':
                return self.send(settings())
            if self.path == '/api/state':
                with lock:
                    return self.send(dict(state))
            if self.path.startswith('/portrait/'):
                key = self.path.split('/')[-1]
                if not key.replace('_', '').isalnum():
                    raise ValueError('Invalid portrait')
                return self.send(portrait(key), mime='image/png')
            self.send({'error': 'Not found'}, 404)
        except Exception as exc:
            self.send({'error': str(exc)}, 400)

    def do_POST(self):
        if self.headers.get('X-Token') != TOKEN:
            return self.send({'error': 'Forbidden'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size < 20000:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(size))
            if self.path == '/api/settings':
                with lock:
                    if state['busy']:
                        return self.send({'error': 'Wait for the export to finish'}, 409)
                    cfg = {key: str(data.get(key, default)) for key, default in DEFAULTS.items()}
                    CONFIG.write_text(json.dumps(cfg, indent=2))
                return self.send({'ok': True})
            if self.path == '/api/export':
                with lock:
                    if state['busy']:
                        return self.send({'error': 'An export is already running'}, 409)
                    state.update(busy=True, log='', error=None, result=None, status='Preparing export')
                threading.Thread(target=export, args=(data,), daemon=True).start()
                return self.send({'ok': True})
            self.send({'error': 'Not found'}, 404)
        except Exception as exc:
            self.send({'error': str(exc)}, 400)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Deadlock Porting: {url}\nKeep this window open. Ctrl+C to quit.', flush=True)
    if '--no-browser' in sys.argv:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
    else:
        import webview
        threading.Thread(target=server.serve_forever, daemon=True).start()
        window = webview.create_window('Deadlock Porting', url, width=1320, height=900,
                                      min_size=(900, 650), background_color='#101214')
        def can_close():
            with lock:
                if state['busy']:
                    state['status'] = 'Export is running. The app can close when it finishes.'
                    return False
            return True
        window.events.closing += can_close
        webview.start(gui='edgechromium')
        server.shutdown()
        server.server_close()
