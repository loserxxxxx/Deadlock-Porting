"""Export a Deadlock model to Blender, rig included.

Reads the installed game and writes an OBJ plus a GLB. The GLB carries the
skeleton, the skin weights, and the color textures. LOD meshes are skipped.
Animations are not exported. Import the GLB. The OBJ has no rig.

    python port/deadlock_port.py haze
    python port/deadlock_port.py models/heroes_staging/haze/haze.vmdl_c
    python port/deadlock_port.py --list
"""
import json
import os
import re
import struct
import sys
import types
from pathlib import Path

helper_root = Path(os.environ.get('DEADLOCK_HELPERS', str(Path(__file__).parent / 'helpers')))
sys.path.insert(0, str(helper_root))
sys.path.insert(0, str(Path(__file__).parent / '.deps'))
sys.modules.setdefault('vpk', types.ModuleType('vpk'))

import meshoptimizer  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from kv3 import KV3File, resource_blocks  # noqa: E402
from make_fog import data_block, unwrap  # noqa: E402
from make_mono import decode, parse  # noqa: E402
from pakio import Pak  # noqa: E402

GAME = os.environ.get('DEADLOCK_VPK', r'C:/Program Files (x86)/Steam/steamapps/common/Deadlock/game/citadel/pak01_dir.vpk')
OUT = Path(os.environ.get('DEADLOCK_OUT', str(Path(__file__).parent / 'out')))


def find_model(pak, query):
    q = query.replace('\\', '/').lower()
    if q.endswith('.vmdl_c') and q in pak.entries:
        return q
    name = q[:-5] if q.endswith('.vmdl') else q
    preferred = [
        f'models/heroes_staging/{name}/{name}.vmdl_c',
        f'models/heroes/{name}/{name}.vmdl_c',
        f'models/heroes_wip/{name}/{name}.vmdl_c',
    ]
    for path in preferred:
        if path in pak.entries:
            return path
    hits = [n for n in pak.entries if n.endswith('.vmdl_c') and n.rsplit('/', 1)[-1][:-7] == name]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit('no model named ' + query)
    raise SystemExit('more than one model:\n' + '\n'.join(hits[:20]))


def block(raw, blocks, index):
    _, off, size = blocks[index]
    return raw[off:off + size]


def indices_of(blob, count, size):
    decoded = np.asarray(meshoptimizer.decode_index_buffer(count, size, blob))
    if size == 2:
        return np.ascontiguousarray(decoded).view(np.uint16)[:count].astype(np.uint32)
    return decoded[:count].astype(np.uint32)


def vertex_buffer(blob, descriptor):
    count = descriptor['m_nElementCount']
    stride = descriptor['m_nElementSizeInBytes']
    if descriptor.get('m_bCompressedZSTD'):
        import zstandard
        blob = zstandard.ZstdDecompressor().decompress(blob, max_output_size=count * stride)
    if descriptor.get('m_bMeshoptCompressed', True):
        return np.asarray(meshoptimizer.decode_vertex_buffer(
            count, stride, blob, dtype=np.dtype((np.uint8, stride))))
    if len(blob) != count * stride:
        raise ValueError('Raw vertex buffer size does not match its descriptor')
    return np.frombuffer(blob, np.uint8).reshape(count, stride).copy()


def index_buffer(blob, descriptor):
    count = descriptor['m_nElementCount']
    size = descriptor['m_nElementSizeInBytes']
    if descriptor.get('m_bCompressedZSTD'):
        import zstandard
        blob = zstandard.ZstdDecompressor().decompress(blob, max_output_size=count * size)
    if descriptor.get('m_bMeshoptCompressed', True):
        if descriptor.get('m_bMeshoptIndexSequence'):
            return np.asarray(meshoptimizer.decode_index_sequence(count, size, blob), dtype=np.uint32)
        return indices_of(blob, count, size)
    if len(blob) != count * size:
        raise ValueError('Raw index buffer size does not match its descriptor')
    return np.frombuffer(blob, '<u2' if size == 2 else '<u4').astype(np.uint32)


def embedded_meshes(raw, blocks, ctrl):
    """Normalize legacy MBUF/VBIB and current per-buffer CTRL descriptors."""
    meshes = []
    for original in ctrl.get('embedded_meshes') or []:
        if 'm_nDataBlock' in original:
            meshes.append(original)
            continue
        mesh = dict(m_Name=original.get('name', 'mesh'), m_nMeshIndex=original.get('mesh_index', -1),
                    m_nDataBlock=original['data_block'])
        buffer_index = original.get('vbib_block', -1)
        if buffer_index < 0:
            continue
        _, base, length = blocks[buffer_index]
        buffer = raw[base:base + length]
        vertex_offset, vertex_count, index_offset, index_count = struct.unpack_from('<4I', buffer)
        for key, start, count in [('m_vertexBuffers', vertex_offset, vertex_count),
                                  ('m_indexBuffers', 8 + index_offset, index_count)]:
            descriptors = []
            for i in range(count):
                record = start + i * 24
                elements, size_flags, attr_offset, attr_count, data_offset, data_size = struct.unpack_from('<6I', buffer, record)
                stride = size_flags & 0x3FFFFFF
                offset = record + 16 + data_offset
                if offset + data_size > len(buffer):
                    raise ValueError('Legacy buffer payload is outside its resource block')
                fields = []
                for f in range(attr_count):
                    at = record + 8 + attr_offset + f * 56
                    name = buffer[at:at+32].split(b'\0', 1)[0].decode('utf-8')
                    semantic_index, fmt, field_offset, slot, slot_type, step = struct.unpack_from('<6I', buffer, at + 32)
                    fields.append(dict(m_pSemanticName=name, m_nSemanticIndex=semantic_index,
                                       m_Format=fmt, m_nOffset=field_offset, m_nSlot=slot))
                compressed = data_size < elements * stride
                descriptors.append(dict(m_nBlockIndex=len(blocks), m_nElementCount=elements,
                                        m_nElementSizeInBytes=stride,
                                        m_bMeshoptCompressed=compressed and not bool(size_flags & 0x4000000),
                                        m_bCompressedZSTD=compressed and bool(size_flags & 0x8000000),
                                        m_inputLayoutFields=fields))
                blocks.append((b'MVTX' if key == 'm_vertexBuffers' else b'MIDX', base + offset, data_size))
            mesh[key] = descriptors
        meshes.append(mesh)
    return meshes


def mesh_buffers(raw, blocks, mesh):
    """Draw calls can reference separate vertex/index buffers (e.g. Deadpack's gun)."""
    mdat = KV3File(block(raw, blocks, mesh['m_nDataBlock'])).read()
    groups = {}
    for obj in mdat['m_sceneObjects']:
        for draw in obj.get('m_drawCalls', []):
            vrefs = draw.get('m_vertexBuffers') or [{'m_hBuffer': 0}]
            iref = draw.get('m_indexBuffer') or {'m_hBuffer': 0}
            if len(vrefs) != 1 or vrefs[0].get('m_nBindOffsetBytes', 0) or iref.get('m_nBindOffsetBytes', 0):
                raise ValueError(f"Unsupported buffer binding in {mesh['m_Name']}")
            pair = (vrefs[0]['m_hBuffer'], iref['m_hBuffer'])
            groups.setdefault(pair, []).append(draw)
    for (vi, ii), draws in groups.items():
        yield mdat, mesh['m_vertexBuffers'][vi], mesh['m_indexBuffers'][ii], draws


def render_meshes(data, meshes):
    """Default bodygroups and highest available LOD, including explicitly named LOD0."""
    candidates = [m for m in meshes if 'phys_hull' not in m.get('m_Name', '').lower()]
    masks = data.get('m_refMeshGroupMasks') or []
    default = data.get('m_nDefaultMeshGroupMask', 0xFFFFFFFFFFFFFFFF)
    visible = [m for m in candidates if not (0 <= m.get('m_nMeshIndex', -1) < len(masks))
               or masks[m['m_nMeshIndex']] & default]
    
    
    candidates = visible or candidates
    def lod_key(mesh, number):
        name = mesh.get('m_Name') or f'mesh_{number}'
        match = re.search(r'_lod(\d+)', name, re.I)
        return re.sub(r'_lod\d+', '', name, flags=re.I), int(match[1]) if match else 0

    levels = {}
    for number, mesh in enumerate(candidates):
        base, level = lod_key(mesh, number)
        levels[base] = min(levels.get(base, level), level)
    return [mesh for number, mesh in enumerate(candidates)
            if lod_key(mesh, number)[1] == levels[lod_key(mesh, number)[0]]]


def attrs(verts, fields, stride, bone_remap):
    pos = uv = joints = weights = None
    index_bytes = weight_bytes = None
    for i, field in enumerate(fields):
        off = field['m_nOffset']
        width = (fields[i + 1]['m_nOffset'] if i + 1 < len(fields) else stride) - off
        name = field['m_pSemanticName'].upper()
        fmt = field.get('m_Format')
        if name == 'POSITION' and width == 12:
            pos = np.ascontiguousarray(verts[:, off:off + 12]).view(np.float32).reshape(-1, 3)
        elif name == 'TEXCOORD' and field.get('m_nSemanticIndex', 0) == 0 and width == 4 and fmt == 37:
            
            uv = np.ascontiguousarray(verts[:, off:off + 4]).view(np.int16).reshape(-1, 2).astype(np.float32)
            uv /= 32767.0
        elif name == 'TEXCOORD' and field.get('m_nSemanticIndex', 0) == 0 and width == 4:
            uv = np.ascontiguousarray(verts[:, off:off + 4]).view(np.float16).reshape(-1, 2).astype(np.float32)
        elif name == 'TEXCOORD' and field.get('m_nSemanticIndex', 0) == 0 and width >= 8:
            uv = np.ascontiguousarray(verts[:, off:off + 8]).view(np.float32).reshape(-1, 2)
        elif name == 'BLENDINDICES':
            index_bytes = np.ascontiguousarray(verts[:, off:off + width])
            layouts = {30: (np.dtype('u1'), 4), 12: (np.dtype('<u2'), 8), 14: (np.dtype('<i2'), 8),
                       3: (np.dtype('<u4'), 16), 4: (np.dtype('<i4'), 16)}
            if fmt not in layouts:
                raise ValueError(f'Unsupported bone-index format {fmt}; refusing to discard skinning')
            dtype, size = layouts[fmt]
            joints = np.ascontiguousarray(verts[:, off:off + size]).view(dtype).reshape(-1, 4).astype(np.int32)
        elif name in ('BLENDWEIGHT', 'BLENDWEIGHTS'):
            weight_bytes = np.ascontiguousarray(verts[:, off:off + width])
            layouts = {28: (np.dtype('u1'), 4, 255.0),
                       11: (np.dtype('<u2'), 8, 65535.0),
                       10: (np.dtype('<f2'), 8, 1.0),
                       2: (np.dtype('<f4'), 16, 1.0)}
            if fmt not in layouts:
                raise ValueError(f'Unsupported bone-weight format {fmt}; refusing to discard skinning')
            dtype, size, divisor = layouts[fmt]
            weights = np.ascontiguousarray(verts[:, off:off + size]).view(dtype).reshape(-1, 4).astype(np.float32) / divisor
    
    
    
    if index_bytes is not None and weight_bytes is not None and index_bytes.shape[1] == weight_bytes.shape[1] == 8:
        packed = np.all(weight_bytes.sum(axis=1) == 255)
        valid_ids = bone_remap is not None and np.all(index_bytes[weight_bytes > 0] < len(bone_remap))
        if packed and valid_ids:
            joints = index_bytes.astype(np.int32)
            weights = weight_bytes.astype(np.float32) / 255.0
    if pos is None:
        raise RuntimeError('mesh has no position')
    n = len(pos)
    if joints is None or bone_remap is None:
        joints = np.zeros((n, 4), np.uint16)
        weights = np.zeros((n, 4), np.float32)
        weights[:, 0] = 1.0
        return pos, uv, joints, weights
    if weights is None:
        
        weights = np.zeros((n, 4), np.float32)
        weights[:, 0] = 1.0
    valid = joints < len(bone_remap)
    clipped = np.clip(joints, 0, len(bone_remap) - 1)
    joints = np.where(valid, bone_remap[clipped], 0).astype(np.uint16)
    weights = np.where(valid, weights, 0.0).astype(np.float32)
    total = weights.sum(axis=1, keepdims=True)
    total[total <= 0] = 1.0
    weights /= total
    return pos, uv, joints, weights


def skeleton(data):
    skel = data.get('m_modelSkeleton') or {}
    if not skel.get('m_boneName'):
        return None
    names = list(skel['m_boneName'])
    parent = [int(p) for p in skel['m_nParent']]
    pos = np.asarray(skel['m_bonePosParent'], np.float64)
    rot = np.asarray(skel['m_boneRotParent'], np.float64)
    scale = np.asarray(skel['m_boneScaleParent'], np.float64)
    local = []
    for i in range(len(names)):
        x, y, z, w = rot[i]
        s = float(scale[i])
        xx, yy, zz = x * x, y * y, z * z
        xy, xz, yz = x * y, x * z, y * z
        wx, wy, wz = w * x, w * y, w * z
        m = np.eye(4)
        m[0, 0] = s * (1 - 2 * (yy + zz))
        m[0, 1] = s * (2 * (xy - wz))
        m[0, 2] = s * (2 * (xz + wy))
        m[1, 0] = s * (2 * (xy + wz))
        m[1, 1] = s * (1 - 2 * (xx + zz))
        m[1, 2] = s * (2 * (yz - wx))
        m[2, 0] = s * (2 * (xz - wy))
        m[2, 1] = s * (2 * (yz + wx))
        m[2, 2] = s * (1 - 2 * (xx + yy))
        m[:3, 3] = pos[i]
        local.append(m)
    world = [None] * len(names)
    for i in range(len(names)):
        world[i] = local[i] if parent[i] < 0 else world[parent[i]] @ local[i]
    inverse = [np.linalg.inv(w).astype(np.float32) for w in world]
    return names, parent, pos.astype(np.float32), rot.astype(np.float32), scale.astype(np.float32), inverse


def bone_world(rig, index):
    _names, parent, bpos, brot, bscale, _inverse = rig
    chain = []
    while index >= 0:
        chain.append(index)
        index = parent[index]
    world = None
    for bone in reversed(chain):
        local = _local_matrix(bpos[bone], brot[bone], bscale[bone])
        world = local if world is None else world @ local
    return world


def read_material(pak, vmat_path):
    path = vmat_path if vmat_path.endswith('_c') else vmat_path + '_c'
    if path not in pak.entries:
        return {}
    return KV3File(unwrap(data_block(pak.read(path)))).read()


def uses_vertex_colors(material):
    return any(p.get('m_name') in ('F_VERTEX_COLOR', 'F_PAINT_VERTEX_COLORS') and p.get('m_nValue')
               for p in material.get('m_intParams') or [])


def vertex_colors(verts, fields, stride):
    field = next((f for f in fields if f['m_pSemanticName'].upper() == 'COLOR'
                  and f.get('m_nSemanticIndex', 0) == 0), None)
    if field is None:
        return None
    fmt = field.get('m_Format')
    layouts = {28: ('u1', 4, 255.0), 87: ('u1', 4, 255.0),
               2: ('<f4', 4, 1.0), 6: ('<f4', 3, 1.0),
               10: ('<f2', 4, 1.0), 11: ('<u2', 4, 65535.0)}
    if fmt not in layouts:
        raise ValueError(f'Unsupported vertex-color format {fmt}')
    dtype, channels, divisor = layouts[fmt]
    size = np.dtype(dtype).itemsize * channels
    off = field['m_nOffset']
    if off < 0 or off + size > stride:
        raise ValueError('Vertex colors exceed the vertex stride')
    colors = np.ascontiguousarray(verts[:, off:off + size]).view(dtype).reshape(-1, channels).astype(np.float32) / divisor
    if fmt == 87:
        colors = colors[:, [2, 1, 0, 3]]
    if channels == 3:
        colors = np.column_stack((colors, np.ones(len(colors), np.float32)))
    colors = np.ascontiguousarray(np.clip(np.nan_to_num(colors), 0.0, 1.0), np.float32)
    rgb = colors[:, :3]
    colors[:, :3] = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return colors


def color_texture(pak, vmat_path, material=None):
    tint = (1.0, 1.0, 1.0, 1.0)
    tree = read_material(pak, vmat_path) if material is None else material
    for param in tree.get('m_vectorParams') or []:
        if param.get('m_name') in ('g_vColorTint', 'g_vColorTint1'):
            value = param.get('m_value') or [1, 1, 1, 1]
            tint = tuple(float(x) for x in list(value)[:3]) + (1.0,)
            break
    for param in tree.get('m_textureParams') or []:
        if param.get('m_name') in ('g_tColor', 'g_tColor1', 'g_tColor2', 'g_tAlbedo'):
            tex = param.get('m_pValue') or ''
            return (tex if tex.endswith('_c') else tex + '_c'), tint
    return None, tint


def save_png(pak, tex_path, dest):
    if not tex_path or tex_path not in pak.entries or dest.exists():
        return dest.exists()
    raw = pak.read(tex_path)
    try:
        info = parse(raw)
    except Exception:
        return False
    if info['fmt'] not in (1, 2, 4, 20, 28) or info['depth'] != 1:
        return False
    
    off = info['pix']
    for mip in reversed(range(info['mips'])):
        w, h = max(1, info['w'] >> mip), max(1, info['h'] >> mip)
        if info['fmt'] in (20, 2):
            size = ((w + 3) // 4) * ((h + 3) // 4) * 16
        elif info['fmt'] == 1:
            size = ((w + 3) // 4) * ((h + 3) // 4) * 8
        else:
            size = w * h * 4
        if mip == 0:
            rgba = decode(info['fmt'], raw[off:off + size], w, h)[:h, :w]
            Image.fromarray(rgba, 'RGBA').save(dest)
            return True
        off += size
    return False


def _pad(blob):
    return blob + b'\x00' * ((4 - len(blob) % 4) % 4)


def _quat_from_matrix(m):
    t = float(m[0, 0] + m[1, 1] + m[2, 2])
    if t > 0.0:
        s = (t + 1.0) ** 0.5 * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = (1.0 + m[0, 0] - m[1, 1] - m[2, 2]) ** 0.5 * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = (1.0 + m[1, 1] - m[0, 0] - m[2, 2]) ** 0.5 * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = (1.0 + m[2, 2] - m[0, 0] - m[1, 1]) ** 0.5 * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w], np.float64)
    q /= np.linalg.norm(q) or 1.0
    return q.astype(np.float32)


def _local_matrix(pos, rot, scale):
    x, y, z, w = (float(v) for v in rot)
    s = float(scale)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    m = np.eye(4)
    m[0, 0] = s * (1 - 2 * (yy + zz))
    m[0, 1] = s * (2 * (xy - wz))
    m[0, 2] = s * (2 * (xz + wy))
    m[1, 0] = s * (2 * (xy + wz))
    m[1, 1] = s * (1 - 2 * (xx + zz))
    m[1, 2] = s * (2 * (yz - wx))
    m[2, 0] = s * (2 * (xz - wy))
    m[2, 1] = s * (2 * (yz + wx))
    m[2, 2] = s * (1 - 2 * (xx + yy))
    m[:3, 3] = pos
    return m


def to_y_up(parts, rig):
    """glTF and Blender are Y-up. Deadlock is Z-up. Convert both so posing stays attached."""
    rot_x = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], np.float64)
    if rig is None:
        for part in parts:
            part['pos'] = (part['pos'].astype(np.float64) @ rot_x[:3, :3].T).astype(np.float32)
        return None
    names, parent, bpos, brot, bscale, _inverse = rig
    local = [_local_matrix(bpos[i], brot[i], bscale[i]) for i in range(len(names))]
    for i, p in enumerate(parent):
        if p < 0:
            local[i] = rot_x @ local[i]
    new_pos, new_rot, new_scale = [], [], []
    for m in local:
        size = float(np.linalg.norm(m[:3, 0])) or 1.0
        new_pos.append(m[:3, 3].astype(np.float32))
        new_rot.append(_quat_from_matrix(m[:3, :3] / size))
        new_scale.append(np.float32(size))
    world = [None] * len(names)
    for i in range(len(names)):
        world[i] = local[i] if parent[i] < 0 else world[parent[i]] @ local[i]
    inverse = [np.linalg.inv(w).astype(np.float32) for w in world]
    spin = rot_x[:3, :3]
    for part in parts:
        part['pos'] = (part['pos'].astype(np.float64) @ spin.T).astype(np.float32)
    return names, parent, new_pos, new_rot, new_scale, inverse


def write_glb(path, stem, parts, rig, materials):
    """One file Blender can pose. Textures are packed in. Bones hang off one armature."""
    names, parent, bpos, brot, bscale, inverse = rig if rig is not None else ([], [], [], [], [], [])
    blob = bytearray()
    views = []
    accessors = []

    def push(data, ctype, atype, count, amin=None, amax=None):
        data = _pad(data)
        view = len(views)
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(data)})
        blob.extend(data)
        acc = {'bufferView': view, 'componentType': ctype, 'count': count, 'type': atype}
        if amin is not None:
            acc['min'] = amin
            acc['max'] = amax
        accessors.append(acc)
        return len(accessors) - 1

    mat_index = {name: i for i, (name, _png, _tint) in enumerate(materials)}
    mesh_groups = {}
    for part in parts:
        primitives = mesh_groups.setdefault(part.get('name', stem), [])
        pos = np.ascontiguousarray(part['pos'], np.float32)
        uv = part['uv']
        if uv is not None:
            
            uv = np.nan_to_num(np.ascontiguousarray(uv, np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        joints = np.ascontiguousarray(part['joints'], np.uint16)
        weights = np.ascontiguousarray(part['weights'], np.float32)
        for draw_start, draw_count, mat in part['draws']:
            tris = np.ascontiguousarray(part['idx'][draw_start:draw_start + draw_count], np.uint32)
            attr = {
                'POSITION': push(pos.tobytes(), 5126, 'VEC3', len(pos),
                                 pos.min(0).tolist(), pos.max(0).tolist()),
            }
            for influence_set in range(joints.shape[1] // 4 if rig is not None else 0):
                sl = slice(influence_set * 4, influence_set * 4 + 4)
                attr[f'JOINTS_{influence_set}'] = push(np.ascontiguousarray(joints[:, sl]).tobytes(), 5123, 'VEC4', len(joints))
                attr[f'WEIGHTS_{influence_set}'] = push(np.ascontiguousarray(weights[:, sl]).tobytes(), 5126, 'VEC4', len(weights))
            if uv is not None:
                attr['TEXCOORD_0'] = push(uv.tobytes(), 5126, 'VEC2', len(uv))
            if part.get('colors') is not None and mat in part.get('vertex_color_materials', ()):
                colors = np.ascontiguousarray(part['colors'], np.float32)
                attr['COLOR_0'] = push(colors.tobytes(), 5126, 'VEC4', len(colors))
            primitives.append({
                'attributes': attr,
                'indices': push(tris.tobytes(), 5125, 'SCALAR', len(tris)),
                'material': mat_index[mat],
                'mode': 4,
            })
    if rig is not None:
        ibm = np.stack([m.flatten(order='F') for m in inverse]).astype(np.float32)
        ibm_acc = push(ibm.tobytes(), 5126, 'MAT4', len(inverse))

    nodes = []
    children = {i: [] for i in range(len(names))}
    roots = []
    for i, p in enumerate(parent):
        if p >= 0:
            children[p].append(i)
        else:
            roots.append(i)
    for i, name in enumerate(names):
        node = {
            'name': name,
            'translation': [float(x) for x in bpos[i]],
            'rotation': [float(x) for x in brot[i]],
            'scale': [float(bscale[i])] * 3,
        }
        if children[i]:
            node['children'] = children[i]
        nodes.append(node)
    mesh_nodes = []
    for index, name in enumerate(mesh_groups):
        mesh_nodes.append(len(nodes))
        nodes.append({'name': name, 'mesh': index, **({'skin': 0} if rig is not None else {})})
    armature = len(nodes)
    if rig is not None:
        nodes.append({'name': 'Armature', 'children': roots})

    images = []
    textures = []
    gl_materials = []
    for mat, png, tint in materials:
        factor = [float(x) for x in tint]
        pbr = {'baseColorFactor': factor, 'metallicFactor': 0.0, 'roughnessFactor': 1.0}
        if png:
            view = len(views)
            views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(png)})
            blob.extend(png)
            blob.extend(b'\x00' * ((4 - len(blob) % 4) % 4))
            images.append({'bufferView': view, 'mimeType': 'image/png'})
            textures.append({'source': len(images) - 1})
            pbr['baseColorTexture'] = {'index': len(textures) - 1}
        gl_materials.append({
            'name': mat,
            'doubleSided': True,
            'pbrMetallicRoughness': pbr,
        })

    gltf = {
        'asset': {'version': '2.0', 'generator': 'deadlock_port'},
        'scene': 0,
        'scenes': [{'nodes': ([armature] if rig is not None else []) + mesh_nodes}],
        'nodes': nodes,
        'meshes': [{'name': name, 'primitives': primitives} for name, primitives in mesh_groups.items()],
        'materials': gl_materials,
        'textures': textures,
        'images': images,
        'accessors': accessors,
        'bufferViews': views,
        'buffers': [{'byteLength': len(blob)}],
    }
    if rig is not None:
        gltf['skins'] = [{'name': stem + '_rig', 'skeleton': armature,
                          'joints': list(range(len(names))), 'inverseBindMatrices': ibm_acc}]
    js = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    js += b' ' * ((4 - len(js) % 4) % 4)
    bin_chunk = bytes(blob)
    bin_chunk += b'\x00' * ((4 - len(bin_chunk) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_chunk)
    path.write_bytes(
        struct.pack('<III', 0x46546C67, 2, total)
        + struct.pack('<I4s', len(js), b'JSON')
        + js
        + struct.pack('<I4s', len(bin_chunk), b'BIN\x00')
        + bin_chunk
    )


def export_model(pak, model_path, out_dir):
    raw = pak.read(model_path)
    blocks = resource_blocks(raw)
    data = KV3File(next(raw[o:o + s] for t, o, s in blocks if t == b'DATA')).read()
    ctrl = KV3File(next(raw[o:o + s] for t, o, s in blocks if t == b'CTRL')).read()
    rig = skeleton(data)
    from rig_policy import character_asset
    if not character_asset(model_path):
        rig = None
    bone_of = {name: i for i, name in enumerate(rig[0])} if rig is not None else {}
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = model_path.rsplit('/', 1)[-1][:-7]
    lines = ['# deadlock port', f'mtllib {stem}.mtl']
    mtl = []
    written = {}
    materials = []
    vertex_color_materials = set()
    parts = []
    v_base = 0
    for mesh_number, mesh in enumerate(render_meshes(data, embedded_meshes(raw, blocks, ctrl))):
        name = mesh.get('m_Name') or f'{stem}_part_{mesh_number}'
        if not mesh.get('m_vertexBuffers') or not mesh.get('m_indexBuffers'):
            continue
        for mdat, vb, ib, mesh_draws in mesh_buffers(raw, blocks, mesh):
            stride = vb['m_nElementSizeInBytes']
            count = vb['m_nElementCount']
            if not count:
                continue
            verts = vertex_buffer(block(raw, blocks, vb['m_nBlockIndex']), vb)
            mesh_bones = [b['m_boneName'] for b in mdat.get('m_skeleton', {}).get('m_bones', [])]
            remap = np.array([bone_of.get(n, 0) for n in mesh_bones], np.int32) if mesh_bones and rig is not None else None
            pos, uv, joints, weights = attrs(verts, vb['m_inputLayoutFields'], stride, remap)
            idx = index_buffer(block(raw, blocks, ib['m_nBlockIndex']), ib)
            draws = []
            lines.append(f'o {name}')
            for p in pos:
                lines.append(f'v {p[0]:.5f} {p[1]:.5f} {p[2]:.5f}')
            if uv is not None:
                for t in uv:
                    lines.append(f'vt {t[0]:.5f} {1.0 - float(t[1]):.5f}')
            for draw in mesh_draws:
                mat = (draw.get('m_material') or 'material').rsplit('/', 1)[-1].replace('.vmat', '')
                start = int(draw.get('m_nStartIndex') or 0)
                nidx = int(draw.get('m_nIndexCount') or 0)
                if nidx < 3:
                    continue
                end = start + nidx - nidx % 3
                if end > len(idx):
                    raise ValueError(f'Index range exceeds buffer in {name}')
                idx[start:end] += int(draw.get('m_nBaseVertex') or 0)
                if len(idx[start:end]) and int(idx[start:end].max()) >= count:
                    raise ValueError(f'Index exceeds vertex count in {name}')
                draws.append((start, nidx - nidx % 3, mat))
                lines.append(f'usemtl {mat}')
                lines.append(f'g {name}_{mat}')
                face = idx[start:start + nidx - nidx % 3].reshape(-1, 3)
                for tri in face:
                    a, b, c = (int(i) + 1 + v_base for i in tri)
                    if uv is not None:
                        lines.append(f'f {a}/{a} {b}/{b} {c}/{c}')
                    else:
                        lines.append(f'f {a} {b} {c}')
                if mat not in written:
                    png = mat + '.png'
                    material = read_material(pak, draw.get('m_material') or '')
                    if uses_vertex_colors(material):
                        vertex_color_materials.add(mat)
                    tex, tint = color_texture(pak, draw.get('m_material') or '', material)
                    ok = save_png(pak, tex, out_dir / png)
                    written[mat] = (png if ok else None, tint)
                    materials.append((mat, (out_dir / png).read_bytes() if ok else None, tint))
                    mtl.append(f'newmtl {mat}')
                    if ok:
                        mtl.append(f'map_Kd {png}')
                    mtl.append('')
            colored = {mat for _start, _count, mat in draws if mat in vertex_color_materials}
            colors = vertex_colors(verts, vb['m_inputLayoutFields'], stride) if colored else None
            parts.append({'name': name, 'pos': pos, 'uv': uv, 'joints': joints, 'weights': weights, 'idx': idx, 'draws': draws,
                          'colors': colors, 'vertex_color_materials': colored})
            v_base += len(pos)
            print(f'  {name}  {len(pos)} verts  {len(idx) // 3} tris')
    if not parts:
        raise SystemExit('no meshes exported')
    (out_dir / f'{stem}.obj').write_text('\n'.join(lines), encoding='utf-8')
    (out_dir / f'{stem}.mtl').write_text('\n'.join(mtl), encoding='utf-8')
    rig = to_y_up(parts, rig)
    write_glb(out_dir / f'{stem}.glb', stem, parts, rig, materials)
    print(f'wrote {out_dir / (stem + ".glb")}  {len(rig[0]) if rig is not None else 0} bones')


def list_heroes(pak):
    names = []
    for n in pak.entries:
        if not n.endswith('.vmdl_c') or not n.startswith('models/heroes'):
            continue
        stem = n.rsplit('/', 1)[-1][:-7]
        folder = n.split('/')[2] if n.count('/') >= 2 else ''
        if stem == folder or stem == folder.rstrip('0123456789'):
            names.append(n)
    for n in sorted(set(names)):
        print(n)


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: deadlock_port.py <hero or model path> | --list')
    pak = Pak(GAME)
    if sys.argv[1] == '--list':
        list_heroes(pak)
        return
    model = find_model(pak, sys.argv[1])
    print(model)
    stem = model.rsplit('/', 1)[-1][:-7]
    export_model(pak, model, OUT / stem)


if __name__ == '__main__':
    main()
