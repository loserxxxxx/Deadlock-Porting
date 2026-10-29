"""KV3 resource decompression, extracted from the alpha helper."""
import struct
import zstandard as zstd
from kv3 import resource_blocks

def data_block(b):
    for typ, o, s in resource_blocks(b):
        if typ == b'DATA':
            return b[o:o + s]
    return None

def unwrap(blob):
    if not blob or len(blob) < 24:
        return blob
    magic, = struct.unpack_from('<I', blob, 0)
    if (magic & 0xFFFFFF00) != 0x4B563300:
        return blob
    comp, = struct.unpack_from('<I', blob, 20)
    if comp != 2:
        return blob
    version = magic & 0xFF
    dctx = zstd.ZstdDecompressor()
    if version == 4:
        uncomp, comp_sz = struct.unpack_from('<II', blob, 48)
        raw = dctx.decompress(blob[72:72 + comp_sz], max_output_size=uncomp)
        out = bytearray(blob[:72])
        struct.pack_into('<I', out, 20, 0)
        struct.pack_into('<I', out, 48, len(raw))
        struct.pack_into('<I', out, 52, len(raw))
        return bytes(out + raw + blob[72 + comp_sz:])
    u1, z1, u2, z2 = struct.unpack_from('<4I', blob, 72)
    p = 120
    raw1 = dctx.decompress(blob[p:p + z1], max_output_size=u1)
    raw2 = dctx.decompress(blob[p + z1:p + z1 + z2], max_output_size=u2)
    out = bytearray(blob[:120])
    struct.pack_into('<I', out, 20, 0)
    struct.pack_into('<I', out, 48, u1 + u2)
    struct.pack_into('<I', out, 52, u1 + u2)
    struct.pack_into('<I', out, 72, u1)
    struct.pack_into('<I', out, 76, u1)
    struct.pack_into('<I', out, 80, u2)
    struct.pack_into('<I', out, 84, u2)
    return bytes(out + raw1 + raw2 + blob[p + z1 + z2:])
