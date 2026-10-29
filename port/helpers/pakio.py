"""Read a Source 2 VPK and write a single-file addon."""
import hashlib
import struct
import zlib


def _cstr(buf, i):
    s = i[0]
    while buf[i[0]] != 0:
        i[0] += 1
    t = buf[s:i[0]].decode('utf-8', 'replace')
    i[0] += 1
    return t


class Pak:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            head = f.read(28)
            self.sig, self.ver, self.tree_size, self.data_size = struct.unpack_from('<4I', head, 0)
            f.seek(28)
            tree = f.read(self.tree_size)
        self.entries = {}
        i = [0]
        while i[0] < len(tree):
            ext = _cstr(tree, i)
            if not ext:
                break
            while True:
                directory = _cstr(tree, i)
                if not directory:
                    break
                while True:
                    name = _cstr(tree, i)
                    if not name:
                        break
                    _crc, _pre, archive, offset, length, _term = struct.unpack_from('<IHHIIH', tree, i[0])
                    i[0] += 18
                    full = f'{directory}/{name}.{ext}' if directory else f'{name}.{ext}'
                    self.entries[full] = (archive, offset, length)

    def __contains__(self, n):
        return n in self.entries

    def __iter__(self):
        return iter(self.entries)

    def read(self, n):
        archive, offset, length = self.entries[n]
        path = self.path
        base = offset
        if archive == 0x7FFF:
            base = 28 + self.tree_size + offset
        else:
            path = self.path.replace('pak01_dir.vpk', 'pak01_%03d.vpk' % archive)
        with open(path, 'rb') as f:
            f.seek(base)
            return f.read(length)


def build_vpk(files, path):
    tree = bytearray()
    by_ext = {}
    for p, blob in files.items():
        d, name = p.rsplit('/', 1)
        stem, ext = name.rsplit('.', 1)
        by_ext.setdefault(ext, {}).setdefault(d, []).append((stem, blob))
    offset = 0
    order = []
    seen = {}
    for ext, dirs in by_ext.items():
        tree += ext.encode() + b'\0'
        for d, items in dirs.items():
            tree += d.encode() + b'\0'
            for stem, blob in items:
                tree += stem.encode() + b'\0'
                key = hashlib.md5(blob).digest()
                if key not in seen:
                    seen[key] = offset
                    offset += len(blob)
                    order.append(blob)
                tree += struct.pack('<IHHIIH', zlib.crc32(blob) & 0xFFFFFFFF, 0, 0x7FFF, seen[key], len(blob), 0xFFFF)
            tree += b'\0'
        tree += b'\0'
    tree += b'\0'
    md5 = hashlib.md5()
    header = struct.pack('<IIIIIII', 0x55AA1234, 2, len(tree), offset, 0, 48, 0)
    with open(path, 'wb') as f:
        for chunk in [header, tree] + order:
            f.write(chunk)
            md5.update(chunk)
        tail = hashlib.md5(tree).digest() + hashlib.md5(b'').digest()
        md5.update(tail)
        f.write(tail + md5.digest())
