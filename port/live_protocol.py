import hashlib
import hmac
import json
import os
from pathlib import Path
import uuid

PROTOCOL = 1


def root_path():
    override = os.environ.get('DEADLOCK_LIVE_DATA')
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local/share')
    return Path(base) / 'DeadlockPorting' / 'live'


def signature(data, token):
    payload = {k: v for k, v in data.items() if k != 'signature'}
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return hmac.new(token.encode(), raw, hashlib.sha256).hexdigest()


def authenticated(data, token):
    supplied = data.get('signature')
    return isinstance(supplied, str) and hmac.compare_digest(supplied, signature(data, token))


def read_json(path, limit=32768):
    with Path(path).open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Bridge message exceeds its size limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Invalid bridge message')
    return value


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(handle, 'w', encoding='utf-8') as target:
            json.dump(data, target, ensure_ascii=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()
