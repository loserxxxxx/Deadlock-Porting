"""Source texture parsing/decoding, extracted from the alpha helper."""
import struct
import numpy as np
import texture2ddecoder as t2d
BC7, DXT1, DXT5, RGBA8888, BGRA8888 = 20, 1, 2, 4, 28
BLOCK_BYTES = {BC7:16,DXT5:16,DXT1:8}

def parse(b):
    _, _, _, boff, bcount = struct.unpack_from('<IHHII', b, 0)
    blocks = []
    for i in range(bcount):
        o = 8 + boff + i * 12
        ro, rs = struct.unpack_from('<II', b, o + 4)
        blocks.append((b[o:o + 4], o + 4 + ro, rs))
    data = next(x for x in blocks if x[0] == b'DATA')
    d = data[1]
    flags, = struct.unpack_from('<H', b, d + 2)
    w, h, depth = struct.unpack_from('<HHH', b, d + 20)
    fmt, mips = struct.unpack_from('<BB', b, d + 26)
    exo, exc = struct.unpack_from('<II', b, d + 32)
    extras = [struct.unpack_from('<I', b, d + 32 + exo + i * 12)[0] for i in range(exc)]
    return dict(blocks=blocks, d=d, dsize=data[2], flags=flags, w=w, h=h, depth=depth,
                fmt=fmt, mips=mips, extras=extras, pix=d + data[2])

def mip_dims(w, h, m):
    return max(1, w >> m), max(1, h >> m)

def mip_size(fmt, w, h):
    if fmt in BLOCK_BYTES:
        return ((w + 3) // 4) * ((h + 3) // 4) * BLOCK_BYTES[fmt]
    return w * h * 4

def mip_offsets(t):
    """{mip: (offset, size)}; data is stored smallest mip first."""
    off, out = t['pix'], {}
    for m in reversed(range(t['mips'])):
        w, h = mip_dims(t['w'], t['h'], m)
        s = mip_size(t['fmt'], w, h)
        out[m] = (off, s)
        off += s
    return out, off

def decode(fmt, data, w, h):
    """-> (H, W, 4) uint8 RGBA (padded to block size for compressed formats)."""
    if fmt in BLOCK_BYTES:
        pw, ph = (w + 3) // 4 * 4, (h + 3) // 4 * 4
        f = {BC7: t2d.decode_bc7, DXT1: t2d.decode_bc1, DXT5: t2d.decode_bc3}[fmt]
        bgra = np.frombuffer(f(bytes(data), pw, ph), np.uint8).reshape(ph, pw, 4)
    else:
        bgra = np.frombuffer(bytes(data), np.uint8).reshape(h, w, 4)
        if fmt == RGBA8888:
            return bgra.copy()
    return bgra[..., [2, 1, 0, 3]].copy()
