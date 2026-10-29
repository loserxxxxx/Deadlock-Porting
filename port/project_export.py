"""Save-project append transaction: preserve original until Blender finishes."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import uuid


def validate_project(path, require_closed=False):
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Choose an existing Blender project')
    project = Path(path).expanduser().resolve()
    if project.suffix.lower() != '.blend' or not project.is_file():
        raise ValueError('Choose an existing .blend file')
    if require_closed:
        from blender_sessions import sessions_for_project
        if sessions_for_project(project):
            raise ValueError('This project is open in Blender. Save and close it, then export again.')
    return project


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def claim_project(project):
    lock = project.with_name(project.name + '.deadlock-import.lock')
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError:
        raise ValueError('Another import is using this project. Wait for it to finish.')
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def append_to_project(project, asset, cfg, env, run, scripts):
    project = validate_project(str(project), require_closed=True)
    with claim_project(project):
        before = fingerprint(project)
        temporary = project.with_name(f'.{project.stem}.deadlock-{uuid.uuid4().hex}.blend')
        try:
            run([cfg['blender'], '--background', '--disable-autoexec', '--python-exit-code', '1',
                 '--python', str(scripts / 'blender_append.py'), '--', str(project),
                 str(asset), str(temporary)], env)
            if not temporary.is_file():
                raise RuntimeError('Blender did not create the merged project')
            validate_project(str(project), require_closed=True)
            if fingerprint(project) != before:
                raise RuntimeError('The project changed during import. Your project was left untouched; retry after closing it in Blender.')
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            backup = project.with_name(f'{project.stem}.before-deadlock-{stamp}.blend')
            with project.open('rb') as source, backup.open('xb') as target:
                shutil.copyfileobj(source, target)
            if fingerprint(project) != before or fingerprint(backup) != before:
                raise RuntimeError('The project changed while making its backup. Import was not committed.')
            os.replace(temporary, project)
            return backup
        finally:
            temporary.unlink(missing_ok=True)
