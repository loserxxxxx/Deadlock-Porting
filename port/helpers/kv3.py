"""Binary KV3 reader/patcher for Deadlock resources (version 4 and 5, raw or LZ4)."""
import struct

import lz4.block

NULL, BOOLEAN = 1, 2
INT64, UINT64, DOUBLE = 3, 4, 5
STRING, ARRAY, OBJECT, ARRAY_TYPED = 6, 8, 9, 10
INT32, UINT32, BOOLEAN_TRUE, BOOLEAN_FALSE = 11, 12, 13, 14
INT64_ZERO, INT64_ONE, DOUBLE_ZERO, DOUBLE_ONE = 15, 16, 17, 18
FLOAT, INT16, UINT16, INT32_AS_BYTE = 19, 20, 21, 23
ARRAY_TYPE_BYTE_LENGTH, ARRAY_TYPE_AUXILIARY_BUFFER = 24, 25

_NUM = {INT32, UINT32, INT32_AS_BYTE, INT16, UINT16, FLOAT, DOUBLE}


def _align(off, n):
    return (off + n - 1) & ~(n - 1)


def resource_blocks(src):
    _, _, _, boff, bcount = struct.unpack_from('<IHHII', src, 0)
    blocks = []
    for i in range(bcount):
        o = 8 + boff + i * 12
        ro, rs = struct.unpack_from('<II', src, o + 4)
        blocks.append((src[o:o + 4], o + 4 + ro, rs))
    return blocks


def replace_block(src, new_data, which=b'DATA'):
    blocks = resource_blocks(src)
    _, hdr_ver, res_ver, _, _ = struct.unpack_from('<IHHII', src, 0)
    last = max(o + s for _, o, s in blocks)
    blobs = [(typ, new_data if typ == which else src[o:o + s]) for typ, o, s in blocks]
    head = 16 + 12 * len(blobs)
    pos = (head + 15) // 16 * 16
    layout = []
    for i, (typ, blob) in enumerate(blobs):
        layout.append((typ, pos, blob))
        last_i = i == len(blobs) - 1
        pos = pos + len(blob) if last_i else (pos + len(blob) + 15) // 16 * 16
    out = bytearray(pos)
    struct.pack_into('<IHHII', out, 0, pos + (len(src) - last), hdr_ver, res_ver, 8, len(blobs))
    for i, (typ, p, blob) in enumerate(layout):
        e = 16 + i * 12
        out[e:e + 4] = typ
        struct.pack_into('<II', out, e + 4, p - (e + 4), len(blob))
        out[p:p + len(blob)] = blob
    return bytes(out) + src[last:]


class _View:
    def __init__(self, raw, base, c1, c2, c4, c8):
        self.raw = raw
        o = base
        self.off1 = self.off2 = self.off4 = self.off8 = o
        self.n1 = self.n2 = self.n4 = self.n8 = 0
        if c1:
            self.off1 = o
            self.n1 = c1
            o += c1
        if c2:
            o = _align(o, 2)
            self.off2 = o
            self.n2 = c2 * 2
            o += self.n2
        if c4:
            o = _align(o, 4)
            self.off4 = o
            self.n4 = c4 * 4
            o += self.n4
        if c8:
            o = _align(o, 8)
            self.off8 = o
            self.n8 = c8 * 8
            o += self.n8
        self.end = o
        self.i1 = self.i2 = self.i4 = self.i8 = 0

    def u8(self):
        v = self.raw[self.off1 + self.i1]
        self.i1 += 1
        return int(v)

    def i16(self):
        v, = struct.unpack_from('<h', self.raw, self.off2 + self.i2)
        self.i2 += 2
        return v

    def u16(self):
        v, = struct.unpack_from('<H', self.raw, self.off2 + self.i2)
        self.i2 += 2
        return v

    def i32(self):
        v, = struct.unpack_from('<i', self.raw, self.off4 + self.i4)
        self.i4 += 4
        return v

    def u32(self):
        v, = struct.unpack_from('<I', self.raw, self.off4 + self.i4)
        self.i4 += 4
        return v

    def f32(self):
        v, = struct.unpack_from('<f', self.raw, self.off4 + self.i4)
        self.i4 += 4
        return v

    def i64(self):
        v, = struct.unpack_from('<q', self.raw, self.off8 + self.i8)
        self.i8 += 8
        return v

    def u64(self):
        v, = struct.unpack_from('<Q', self.raw, self.off8 + self.i8)
        self.i8 += 8
        return v

    def f64(self):
        v, = struct.unpack_from('<d', self.raw, self.off8 + self.i8)
        self.i8 += 8
        return v


def _strings(buf, start, n):
    out = []
    p = start
    for _ in range(n):
        end = buf.find(b'\0', p)
        if end < 0:
            raise ValueError('unterminated string')
        out.append(buf[p:end].decode('utf-8', 'replace'))
        p = end + 1
    return out, p - start


def _decomp(raw, size, compression):
    if compression == 0:
        return raw
    return lz4.block.decompress(raw, uncompressed_size=size)


def _recomp(raw, compression):
    if compression == 0:
        return raw
    return lz4.block.compress(raw, store_size=False)


def _is_color_key(name):
    n = name.lower()
    if not any(s in n for s in ('color', 'colour', 'tint')):
        return False
    if any(s in n for s in ('mode', 'type', 'blend', 'scale', 'brightness', 'seed', 'field', 'attribute')):
        return False
    if n.startswith(('m_n', 'm_b', 'm_fl')):
        return False
    return True


def _width(sub):
    return {INT32_AS_BYTE: 1, INT16: 2, UINT16: 2, INT32: 4, UINT32: 4, FLOAT: 4, DOUBLE: 8}[sub]


def _color_white(vals, sub):
    """White at the original brightness. Jumping a dim colour up to 255 blows the sprite out into a black square."""
    peak = max(0.0, max(float(v) for v in vals[:3]))
    if peak > 40:
        peak *= 0.7
    if sub in (FLOAT, DOUBLE):
        return peak
    return int(round(peak))


def _near_white(vals):
    """Neutral and bright enough to be a white light, not a gold or black tint."""
    rgb = [float(v) for v in vals[:3]]
    peak = max(rgb)
    if peak <= 0:
        return False
    if peak <= 1.5 and peak < 0.2:
        return False
    if peak > 1.5 and peak < 30:
        return False
    return min(rgb) >= peak * 0.72


def _is_glow(vals):
    """A real light colour: byte RGB or a 0-255 float, not a 0-1 direction."""
    return max(float(v) for v in vals[:3]) >= 40


def _as_red(vals, sub):
    """Same brightness, hue pulled onto red."""
    peak = max(0.0, max(float(v) for v in vals[:3]))
    if sub in (FLOAT, DOUBLE):
        return (peak, peak * 0.06, peak * 0.03)
    p = int(round(peak))
    return (p, int(round(p * 0.06)), int(round(p * 0.03)))


def _looks_like_color(vals):
    if any(isinstance(v, float) for v in vals):
        return all(-0.05 <= float(v) <= 255.5 for v in vals)
    return all(isinstance(v, int) and 0 <= v <= 255 for v in vals)


def _poke(buf, sub, back, value):
    if sub == INT32_AS_BYTE:
        buf.raw[buf.off1 + buf.i1 - back] = int(value) & 0xFF
    elif sub in (INT16, UINT16):
        struct.pack_into('<H', buf.raw, buf.off2 + buf.i2 - back, int(value) & 0xFFFF)
    elif sub in (INT32, UINT32):
        struct.pack_into('<I', buf.raw, buf.off4 + buf.i4 - back, int(value) & 0xFFFFFFFF)
    elif sub == FLOAT:
        struct.pack_into('<f', buf.raw, buf.off4 + buf.i4 - back, float(value))
    else:
        struct.pack_into('<d', buf.raw, buf.off8 + buf.i8 - back, float(value))


class KV3File:
    def __init__(self, blob):
        self.blob = bytes(blob)
        magic, = struct.unpack_from('<I', blob, 0)
        version = magic & 0xFF
        if (magic & 0xFFFFFF00) != 0x4B563300 or version not in (4, 5):
            raise ValueError(f'unsupported kv3 {magic:#x}')
        self.version = version
        self.compression, = struct.unpack_from('<I', blob, 20)
        if self.compression not in (0, 1):
            raise ValueError(f'compression {self.compression}')
        c1, c4, c8, self.ctypes = struct.unpack_from('<4I', blob, 28)
        self.c2, = struct.unpack_from('<I', blob, 64)
        uncomp, comp, self.blocks, self.blob_bytes = struct.unpack_from('<4I', blob, 48)
        self.blens = []
        self.bi = 0
        self.tail = b''
        self.changed = 0
        self.do_whiten = False
        self.oi = 0
        self.ti = 0
        if version == 4:
            raw = blob[72:72 + (comp if self.compression else uncomp)]
            self.buf = bytearray(_decomp(raw, uncomp, self.compression))
            self.aux_raw = None
            self.main = _View(self.buf, 0, c1, self.c2, c4, c8)
            end = self.main.end if c8 else _align(self.main.end, 8)
            nstrings = self.main.i32()
            self.strings, consumed = _strings(self.buf, end, nstrings)
            t0 = end + consumed
            types_len = self.ctypes - consumed
            self.types_base = t0
            self.types = self.buf[t0:t0 + types_len]
            after = t0 + types_len
            if self.blocks:
                self.blens = list(struct.unpack_from('<' + 'i' * self.blocks, self.buf, after))
                after += self.blocks * 4
            trailer, = struct.unpack_from('<I', self.buf, after)
            if trailer != 0xFFEEDD00:
                raise ValueError(f'v4 trailer {trailer:#x}')
            pay = comp if self.compression else uncomp
            self.tail = bytes(blob[72 + pay:])
            self.obj_lengths = None
            self.cur = self.main
            self.aux = None
        else:
            u1, z1, u2, z2, c1b, c2b, c4b, c8b, _, obj2, _, _ = struct.unpack_from('<12I', blob, 72)
            if uncomp != u1 + u2:
                raise ValueError('size mismatch')
            p = 120
            n1 = z1 if self.compression else u1
            n2 = z2 if self.compression else u2
            self.aux_raw = bytearray(_decomp(blob[p:p + n1], u1, self.compression))
            self.buf = bytearray(_decomp(blob[p + n1:p + n1 + n2], u2, self.compression))
            self.aux = _View(self.aux_raw, 0, c1, self.c2, c4, c8)
            nstrings = self.aux.i32()
            self.strings, consumed = _strings(self.aux_raw, self.aux.off1, nstrings)
            self.aux.i1 = consumed
            self.obj_lengths = list(struct.unpack_from('<' + 'i' * obj2, self.buf, 0)) if obj2 else []
            self.main = _View(self.buf, obj2 * 4, c1b, c2b, c4b, c8b)
            t0 = self.main.end
            self.types_base = t0
            self.types = self.buf[t0:t0 + self.ctypes]
            after = t0 + self.ctypes
            if self.blocks:
                self.blens = list(struct.unpack_from('<' + 'i' * self.blocks, self.buf, after))
                after += self.blocks * 4
            trailer, = struct.unpack_from('<I', self.buf, after)
            if trailer != 0xFFEEDD00:
                raise ValueError(f'v5 trailer {trailer:#x}')
            self.tail = bytes(blob[120 + n1 + n2:])
            self.cur = self.main
        self.do_whiten = False
        self._paint_rgb = None
        self._red_whites = False
        self._red_glow = False
        self._pending = ''
        self._snap = []
        for buf in (self.main, self.aux):
            if buf is not None:
                self._snap.append((buf, buf.i1, buf.i2, buf.i4, buf.i8))

    def whiten_colors(self):
        self.changed = 0
        self.do_whiten = True
        self._paint_rgb = None
        self._red_whites = False
        self._red_glow = False
        self._vec_pred = None
        self._reset_cursors()
        typ, _ = self._type()
        self._value(typ)
        self.do_whiten = False
        self._paint_rgb = None
        self._red_whites = False
        self._red_glow = False
        return self.changed

    def redden_whites(self):
        """Turn near-white colour vectors red, keeping each one's brightness. Gold stays gold."""
        self.changed = 0
        self.do_whiten = True
        self._paint_rgb = None
        self._vec_pred = None
        self._red_whites = True
        self._red_glow = False
        self._reset_cursors()
        typ, _ = self._type()
        self._value(typ)
        self.do_whiten = False
        self._red_whites = False
        self._red_glow = False
        return self.changed

    def redden_glow(self):
        """Pull bright colour vectors onto red. Leaves black and 0-1 multipliers alone."""
        self.changed = 0
        self.do_whiten = True
        self._paint_rgb = None
        self._vec_pred = None
        self._red_whites = False
        self._red_glow = True
        self._reset_cursors()
        typ, _ = self._type()
        self._value(typ)
        self.do_whiten = False
        self._red_glow = False
        return self.changed

    def zero_flags(self, names):
        """Set named m_intParams / m_floatParams to 0. names are the m_name strings."""
        self.changed = 0
        self._zero_names = set(names)
        self._pending = ''
        self._reset_cursors()
        typ, _ = self._type()
        self._value(typ)
        self._zero_names = None
        return self.changed

    def _retag(self, ti0, new_typ):
        i = self.types_base + ti0
        self.buf[i] = (self.buf[i] & ~0x3F) | new_typ
        self.changed += 1

    def _force_zero(self, typ, ti0):
        buf = self.cur
        if typ == BOOLEAN_TRUE:
            self._retag(ti0, BOOLEAN_FALSE)
            return False
        if typ == INT64_ONE:
            self._retag(ti0, INT64_ZERO)
            return 0
        if typ == DOUBLE_ONE:
            self._retag(ti0, DOUBLE_ZERO)
            return 0.0
        if typ in (NULL, BOOLEAN_FALSE, INT64_ZERO, DOUBLE_ZERO):
            return 0
        if typ == BOOLEAN:
            if buf.u8():
                buf.raw[buf.off1 + buf.i1 - 1] = 0
                self.changed += 1
            return 0
        if typ == INT64:
            if buf.i64():
                struct.pack_into('<q', buf.raw, buf.off8 + buf.i8 - 8, 0)
                self.changed += 1
            return 0
        if typ == FLOAT:
            if buf.f32() != 0.0:
                struct.pack_into('<f', buf.raw, buf.off4 + buf.i4 - 4, 0.0)
                self.changed += 1
            return 0.0
        if typ == DOUBLE:
            if buf.f64() != 0.0:
                struct.pack_into('<d', buf.raw, buf.off8 + buf.i8 - 8, 0.0)
                self.changed += 1
            return 0.0
        if typ in (INT32, UINT32):
            v = buf.i32() if typ == INT32 else buf.u32()
            if v:
                struct.pack_into('<i', buf.raw, buf.off4 + buf.i4 - 4, 0)
                self.changed += 1
            return 0
        return self._value(typ)

    def paint_vectors(self, predicate, rgb=None):
        """Set the RGB of m_vectorParams whose m_name matches predicate.

        rgb is 0..1. None keeps each vector's own brightness and only removes the hue.
        """
        self.changed = 0
        self.do_whiten = False
        self._paint_rgb = None if rgb is None else tuple(rgb)
        self._vec_pred = predicate
        self._pending = ''
        self._reset_cursors()
        typ, _ = self._type()
        self._value(typ)
        self._paint_rgb = None
        self._vec_pred = None
        return self.changed

    def read(self):
        self.do_whiten = False
        self._reset_cursors()
        typ, _ = self._type()
        return self._value(typ)

    def _reset_cursors(self):
        self.ti = 0
        self.oi = 0
        self.bi = 0
        self.cur = self.main
        for buf, i1, i2, i4, i8 in self._snap:
            buf.i1, buf.i2, buf.i4, buf.i8 = i1, i2, i4, i8

    def pack(self):
        if self.version == 4:
            comp = _recomp(bytes(self.buf), self.compression)
            out = bytearray(self.blob[:72]) + comp + self.tail
            if self.compression:
                struct.pack_into('<I', out, 52, len(comp))
            return bytes(out)
        c1 = _recomp(bytes(self.aux_raw), self.compression)
        c2 = _recomp(bytes(self.buf), self.compression)
        out = bytearray(self.blob[:120]) + c1 + c2 + self.tail
        if self.compression:
            struct.pack_into('<I', out, 76, len(c1))
            struct.pack_into('<I', out, 84, len(c2))
            struct.pack_into('<I', out, 52, len(c1) + len(c2))
        return bytes(out)

    def _type(self):
        b = self.types[self.ti]
        self.ti += 1
        if b & 0x80:
            b &= 0x3F
            self.ti += 1
        return b, 0

    def _scalar(self, sub):
        buf = self.cur
        if sub == INT32_AS_BYTE:
            return buf.u8()
        if sub == INT16:
            return buf.i16()
        if sub == UINT16:
            return buf.u16()
        if sub == INT32:
            return buf.i32()
        if sub == UINT32:
            return buf.u32()
        if sub == FLOAT:
            return buf.f32()
        if sub == DOUBLE:
            return buf.f64()
        raise ValueError(sub)

    def _paint(self, sub, n):
        buf = self.cur
        vals = [self._scalar(sub) for _ in range(n)]
        if not _looks_like_color(vals):
            return vals
        if getattr(self, '_red_whites', False):
            if not _near_white(vals):
                return vals
            target = _as_red(vals, sub)
        elif getattr(self, '_red_glow', False):
            if not _is_glow(vals):
                return vals
            target = _as_red(vals, sub)
        elif self._paint_rgb is None:
            white = _color_white(vals, sub)
            target = (white, white, white)
        else:
            target = self._paint_rgb
            if sub not in (FLOAT, DOUBLE):
                target = tuple(int(round(c if c > 1 else c * 255)) for c in target)
        width = _width(sub)
        for i in range(min(3, n)):
            want = target[i]
            if vals[i] == want:
                continue
            _poke(buf, sub, width * (n - i), want)
            vals[i] = want
            self.changed += 1
        return vals

    def _value(self, typ, whiten=False):
        buf = self.cur
        if typ == NULL:
            return None
        if typ == BOOLEAN_TRUE:
            return True
        if typ == BOOLEAN_FALSE:
            return False
        if typ == INT64_ZERO:
            return 0
        if typ == INT64_ONE:
            return 1
        if typ == DOUBLE_ZERO:
            return 0.0
        if typ == DOUBLE_ONE:
            return 1.0
        if typ == 26:  
            return 0
        if typ == 27:  
            return 1
        if typ == BOOLEAN:
            return buf.u8() == 1
        if typ == INT64:
            return buf.i64()
        if typ == UINT64:
            return buf.u64()
        if typ == DOUBLE:
            return buf.f64()
        if typ in _NUM:
            return self._scalar(typ)
        if typ == 7:  
            self.bi += 1
            return b''
        if typ == STRING:
            i = buf.i32()
            return '' if i < 0 else self.strings[i]
        if typ == ARRAY:
            n = buf.i32()
            return [self._elem() for _ in range(n)]
        if typ in (ARRAY_TYPED, ARRAY_TYPE_BYTE_LENGTH):
            n = buf.u8() if typ == ARRAY_TYPE_BYTE_LENGTH else buf.i32()
            sub, _ = self._type()
            if whiten and sub in _NUM and n in (3, 4):
                return self._paint(sub, n)
            return [self._value(sub) for _ in range(n)]
        if typ == ARRAY_TYPE_AUXILIARY_BUFFER:
            n = buf.u8()
            sub, _ = self._type()
            prev = self.cur
            self.cur = self.aux
            try:
                if whiten and sub in _NUM and n in (3, 4):
                    return self._paint(sub, n)
                return [self._value(sub) for _ in range(n)]
            finally:
                self.cur = prev
        if typ == OBJECT:
            if self.version >= 5:
                n = self.obj_lengths[self.oi]
                self.oi += 1
            else:
                n = buf.i32()
            return dict(self._field() for _ in range(n))
        raise ValueError(f'unknown type {typ}')

    def _elem(self):
        typ, _ = self._type()
        return self._value(typ)

    def _field(self):
        ti0 = self.ti
        typ, _ = self._type()
        sid = self.cur.i32()
        name = '' if sid < 0 else self.strings[sid]
        zeroing = getattr(self, '_zero_names', None)
        vec = getattr(self, '_vec_pred', None)
        if zeroing and name in ('m_nValue', 'm_flValue') and getattr(self, '_pending', '') in zeroing:
            val = self._force_zero(typ, ti0)
        elif vec and name == 'm_value' and vec(self._pending):
            val = self._value(typ, whiten=True)
        else:
            val = self._value(typ, whiten=self.do_whiten and _is_color_key(name))
        if name == 'm_name' and isinstance(val, str):
            self._pending = val
        fmap = getattr(self, '_float_map', None)
        if fmap and name in fmap:
            want = fmap[name]
            if typ == FLOAT:
                if val != float(want):
                    struct.pack_into('<f', self.cur.raw, self.cur.off4 + self.cur.i4 - 4, float(want))
                    val = float(want)
                    self.changed += 1
            elif typ == DOUBLE:
                if val != float(want):
                    struct.pack_into('<d', self.cur.raw, self.cur.off8 + self.cur.i8 - 8, float(want))
                    val = float(want)
                    self.changed += 1
            elif typ == DOUBLE_ONE and float(want) == 0.0:
                self._retag(ti0, DOUBLE_ZERO)
                val = 0.0
            elif typ == 27 and not want:  
                self._retag(ti0, 26)
                val = 0
            elif typ == BOOLEAN_TRUE and not want:
                self._retag(ti0, BOOLEAN_FALSE)
                val = False
            elif typ == BOOLEAN and not want and val:
                self.cur.raw[self.cur.off1 + self.cur.i1 - 1] = 0
                val = False
                self.changed += 1
        return name, val

