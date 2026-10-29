"""Read UEFormat .uemodel files (what FModel's "Save Model" writes).

Valorant agents come out of FModel this way. The file is version 9 or 10.
Version 10 moved the counts inside each block, gave UV channels names,
added the asset path to the header, and added a scale to every bone.

This reader builds the mesh and skeleton straight away, so nobody needs the
UEFormat add-on. Materials pick up the textures FModel exported next to the
model, when it finds them.
"""
import io
import json
import os
import struct

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

MAGIC = b'UEFORMAT'
SCALE = 0.01  


class Reader:
    def __init__(self, data):
        self.f = io.BytesIO(data)

    def int(self):
        return struct.unpack('<i', self.f.read(4))[0]

    def byte(self):
        return self.f.read(1)[0]

    def str(self):
        return self.f.read(self.int()).rstrip(b'\0').decode('utf-8', 'replace')

    def floats(self, count):
        return np.frombuffer(self.f.read(4 * count), dtype='<f4').astype(np.float64)

    def tell(self):
        return self.f.tell()

    def seek(self, pos):
        self.f.seek(pos)


def _decompress(method, data, size):
    if method == 'ZSTD':
        try:
            from compression import zstd  
            return zstd.decompress(data)
        except ImportError:
            import zstandard
            return zstandard.ZstdDecompressor().decompress(data, max_output_size=size)
    if method == 'GZIP':
        import gzip
        return gzip.decompress(data)
    raise ValueError(f'Unknown compression {method}')


class Model:
    """Plain data: one LOD plus the skeleton."""

    def __init__(self):
        self.name = ''
        self.asset_path = ''
        self.verts = self.normals = self.indices = None
        self.uvs = []
        self.materials = []  
        self.weights = []    
        self.bones = []      
        self.sockets = []    
        self.content_root = (None, None)


def read(path):
    with open(path, 'rb') as fh:
        r = Reader(fh.read())
    if r.f.read(8) != MAGIC:
        raise ValueError('Not a UEFormat file')
    if r.str() != 'UEMODEL':
        raise ValueError('Not a model (.uemodel)')
    version = r.byte()
    if version < 9:
        raise ValueError(f'UEFormat version {version} is too old. Update FModel and export again')
    model = Model()
    model.name = r.str()
    if version >= 10:
        model.asset_path = r.str()
    if r.byte():
        method = r.str()
        size = r.int()
        r.int()
        r = Reader(_decompress(method, r.f.read(), size))

    if version >= 10:
        _blocks_v10(r, model, r.int())
    else:
        _blocks_v9(r, model)
    return model





def _blocks_v10(r, model, count, lod_done=None):
    lod_done = lod_done if lod_done is not None else [False]
    for _ in range(count):
        name = r.str()
        size = r.int()
        start = r.tell()
        if name == 'LODS':
            for _ in range(r.int()):
                r.str()
                if lod_done[0]:
                    break  
                _blocks_v10(r, model, r.int())
                lod_done[0] = True
        elif name == 'SKELETON':
            _blocks_v10(r, model, r.int(), lod_done)
        else:
            _section(r, model, name, r.int(), version=10)
        r.seek(start + size)





def _blocks_v9(r, model):
    end = len(r.f.getbuffer())
    while r.tell() < end:
        name = r.str()
        count = r.int()
        size = r.int()
        start = r.tell()
        if name == 'LODS':
            for i in range(count):
                r.str()
                lod_size = r.int()
                lod_start = r.tell()
                if i == 0:
                    while r.tell() < lod_start + lod_size:
                        sec, n, sec_size = r.str(), r.int(), r.int()
                        sec_start = r.tell()
                        _section(r, model, sec, n, version=9)
                        r.seek(sec_start + sec_size)
                r.seek(lod_start + lod_size)
        elif name == 'SKELETON':
            skel_end = start + size
            while r.tell() < skel_end:
                sec, n, sec_size = r.str(), r.int(), r.int()
                sec_start = r.tell()
                _section(r, model, sec, n, version=9)
                r.seek(sec_start + sec_size)
        r.seek(start + size)


def _section(r, model, name, count, version):
    flip = np.array((1.0, -1.0, 1.0))  
    if name == 'VERTICES':
        model.verts = r.floats(count * 3).reshape(count, 3) * SCALE * flip
    elif name == 'NORMALS':
        model.normals = r.floats(count * 4).reshape(count, 4)[:, 1:] * flip  
    elif name == 'INDICES':
        model.indices = np.frombuffer(r.f.read(4 * count), dtype='<i4').reshape(-1, 3)
    elif name == 'TEXCOORDS':
        for _ in range(count):
            if version >= 10:
                r.str()
            n = r.int()
            uv = r.floats(n * 2).reshape(n, 2)
            uv[:, 1] = 1.0 - uv[:, 1]
            model.uvs.append(uv)
    elif name == 'MATERIALS':
        for _ in range(count):
            model.materials.append((r.str(), r.str(), r.int(), r.int()))
    elif name == 'WEIGHTS':
        raw = np.frombuffer(r.f.read(10 * count), dtype=np.dtype([('b', '<i2'), ('v', '<i4'), ('w', '<f4')]))
        model.weights = raw
    elif name == 'SOCKETS':
        for _ in range(count):
            sock, bone = r.str(), r.str()
            pos, rot = r.floats(3), r.floats(4)
            r.floats(3)
            model.sockets.append((sock, bone, pos * SCALE * flip, rot * (1, -1, 1, -1)))
    elif name == 'BONES':
        for _ in range(count):
            bone_name = r.str()
            parent = r.int()
            pos = r.floats(3)
            rot = r.floats(4)
            if version >= 10:
                r.floats(3)  
            model.bones.append((bone_name, parent, pos * SCALE * flip, rot * (1, -1, 1, -1)))




def _matrix(pos, rot):
    x, y, z, w = rot
    return Matrix.Translation(Vector(pos)) @ Quaternion((w, x, y, z)).to_matrix().to_4x4()


def build_armature(model, name):
    """Skeleton at identity, bones in Unreal's bind pose."""
    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    bpy.context.collection.objects.link(arm)
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)

    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones
    made = []
    for bone_name, parent, pos, rot in model.bones:
        bone = eb.new(bone_name)
        bone.length = 0.03
        local = _matrix(pos, rot)
        if parent >= 0:
            bone.parent = made[parent]
            local = made[parent].matrix @ local
        bone.matrix = local
        made.append(bone)
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def build_mesh(model, name, arm=None, bind=None):
    """Mesh object, skinned to `arm`.

    `bind` is (bone name, matrix) for a static mesh that rides on one bone,
    like a magazine in its socket.
    """
    verts = model.verts
    if bind is not None:
        m = np.array(bind[1])
        verts = verts @ m[:3, :3].T + m[:3, 3]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts.tolist(), [], model.indices.tolist())
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    corners = model.indices.reshape(-1)
    for i, uv in enumerate(model.uvs):
        layer = mesh.uv_layers.new(name=f'UV{i}')
        layer.data.foreach_set('uv', uv[corners].reshape(-1))

    if model.normals is not None:
        normals = model.normals
        if bind is not None:
            normals = normals @ np.array(bind[1])[:3, :3].T
        mesh.polygons.foreach_set('use_smooth', [True] * len(mesh.polygons))
        mesh.normals_split_custom_set_from_vertices(normals.tolist())

    if len(model.weights):
        names_by_index = [b[0] for b in model.bones]
        for b in np.unique(model.weights['b']):
            group = obj.vertex_groups.new(name=names_by_index[b])
            rows = model.weights[model.weights['b'] == b]
            for w in np.unique(rows['w']):
                group.add(rows['v'][rows['w'] == w].tolist(), float(w), 'REPLACE')
    elif bind is not None:
        obj.vertex_groups.new(name=bind[0]).add(list(range(len(mesh.vertices))), 1.0, 'REPLACE')

    if model.materials:
        index = np.zeros(len(mesh.polygons), dtype=np.int32)
        slots = {}
        for mat_name, mat_path, first, faces in model.materials:
            if mat_name not in slots:
                slots[mat_name] = len(slots)
                mesh.materials.append(material(mat_name, mat_path, model.content_root))
            index[first // 3:first // 3 + faces] = slots[mat_name]
        mesh.polygons.foreach_set('material_index', index)

    mesh.update()
    if arm is not None:
        obj.parent = arm
        mod = obj.modifiers.new('Armature', 'ARMATURE')
        mod.object = arm
    return obj


def content_root(path, model):
    """Folder that holds the game's top folder ("ShooterGame") in the export."""
    if model.asset_path:
        depth = len(model.asset_path.split('/'))
        root = path
        for _ in range(depth):
            root = os.path.dirname(root)
        if os.path.isdir(root):
            return root, model.asset_path.split('/')[0]
    
    d = os.path.dirname(path)
    while os.path.dirname(d) != d:
        if os.path.basename(d) == 'Content':
            return os.path.dirname(os.path.dirname(d)), os.path.basename(os.path.dirname(d))
        d = os.path.dirname(d)
    return None, None


def find_asset(model, game_path, ext):
    """/Game/Characters/X.X -> <export>/ShooterGame/Content/Characters/X.<ext>"""
    root, game = model.content_root
    if not root or not game_path:
        return None
    rel = game_path.split('.')[0].lstrip('/')
    top, _, rest = rel.partition('/')
    top = f'{game}/Content' if top == 'Game' else 'Engine/Content' if top == 'Engine' else f'{game}/Plugins/{top}/Content'
    p = os.path.join(root, *top.split('/'), *rest.split('/')) + ext
    return p if os.path.isfile(p) else None


def load_image(path, color):
    """Load and pack, so the .blend still has its textures on another PC."""
    img = bpy.data.images.load(path, check_existing=True)
    if not color:
        img.colorspace_settings.name = 'Non-Color'
    if img.packed_file is None:
        img.pack()
    return img


def _texture(nt, model, game_path, color, location):
    p = find_asset(model, game_path, '.png') or find_asset(model, game_path, '.tga')
    if not p:
        return None
    node = nt.nodes.new('ShaderNodeTexImage')
    node.image, node.location = load_image(p, color), location
    node['dl_base'] = p  
    return node


TEX_KEYS = {
    'color': ('Albedo', 'PM_Diffuse', 'Diffuse', 'BaseColor', 'Base Color', 'OverlayTexture'),
    'normal': ('Normal', 'PM_Normals', 'Normals'),
    'mrae': ('MRAE', 'MRS', 'PM_SpecularMasks'),
    'aem': ('AEM',),
}


def material(name, game_path, root):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    holder = Model()
    holder.content_root = root
    info_path = find_asset(holder, game_path, '.json')
    if not info_path:
        return mat
    with open(info_path, encoding='utf-8') as fh:
        info = json.load(fh)
    tex = info.get('Textures', {})

    def pick(kind):
        for key in TEX_KEYS[kind]:
            if key in tex:
                return tex[key].get('ObjectPath')
        return None

    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    link = nt.links.new
    props = info.get('Properties', {}).get('BasePropertyOverrides', {})
    translucent = info.get('IsTranslucent') or 'Translucent' in str(props.get('BlendMode', ''))

    color = _texture(nt, holder, pick('color'), True, (-500, 300))
    if color:
        link(color.outputs['Color'], bsdf.inputs['Base Color'])
        if translucent:
            link(color.outputs['Alpha'], bsdf.inputs['Alpha'])
            mat.surface_render_method = 'BLENDED'
            bsdf.inputs['Roughness'].default_value = 0.1
    normal = _texture(nt, holder, pick('normal'), False, (-800, -300))
    if normal:
        
        sep = nt.nodes.new('ShaderNodeSeparateColor')
        inv = nt.nodes.new('ShaderNodeMath')
        inv.operation = 'SUBTRACT'
        inv.inputs[0].default_value = 1.0
        comb = nt.nodes.new('ShaderNodeCombineColor')
        nmap = nt.nodes.new('ShaderNodeNormalMap')
        sep.location, inv.location, comb.location, nmap.location = (-500, -300), (-330, -340), (-180, -300), (-20, -300)
        link(normal.outputs['Color'], sep.inputs[0])
        link(sep.outputs[0], comb.inputs[0])
        link(sep.outputs[1], inv.inputs[1])
        link(inv.outputs[0], comb.inputs[1])
        link(sep.outputs[2], comb.inputs[2])
        link(comb.outputs[0], nmap.inputs['Color'])
        link(nmap.outputs[0], bsdf.inputs['Normal'])
    if not translucent:
        
        mrae = _texture(nt, holder, pick('mrae'), False, (-800, 0))
        if mrae:
            sep = nt.nodes.new('ShaderNodeSeparateColor')
            sep.location = (-500, 0)
            link(mrae.outputs['Color'], sep.inputs[0])
            link(sep.outputs[0], bsdf.inputs['Metallic'])
            link(sep.outputs[1], bsdf.inputs['Roughness'])
        
        aem = _texture(nt, holder, pick('aem'), False, (-800, 600))
        if aem and color:
            sep = nt.nodes.new('ShaderNodeSeparateColor')
            gain = nt.nodes.new('ShaderNodeMath')
            sep.location, gain.location = (-500, 600), (-330, 600)
            gain.operation = 'MULTIPLY'
            gain.inputs[1].default_value = 4.0
            link(aem.outputs['Color'], sep.inputs[0])
            link(sep.outputs[1], gain.inputs[0])
            link(gain.outputs[0], bsdf.inputs['Emission Strength'])
            link(color.outputs['Color'], bsdf.inputs['Emission Color'])
    if not out.inputs['Surface'].is_linked:
        link(bsdf.outputs[0], out.inputs['Surface'])
    return mat






def skin_folder(path):
    d = os.path.dirname(path)
    for _ in range(4):
        if os.path.isdir(os.path.join(d, 'Chromas')):
            return d
        d = os.path.dirname(d)
    return None


def chromas(skin_dir):
    root = os.path.join(skin_dir or '', 'Chromas')
    if not skin_dir or not os.path.isdir(root):
        return []
    found = []
    for v in sorted(os.listdir(root)):
        if any(f.lower().endswith(('.png', '.tga')) for _, _, files in os.walk(os.path.join(root, v)) for f in files):
            found.append(v)
    return found


def chroma_texture(base, skin_dir, variant):
    stem, ext = os.path.splitext(os.path.basename(base))
    head, _, tail = stem.rpartition('_')
    want = f'{head}_{variant}_{tail}{ext}'.lower()
    for d, _, files in os.walk(os.path.join(skin_dir, 'Chromas', variant)):
        for f in files:
            if f.lower() == want:
                return os.path.join(d, f)
    return None


def set_chroma(arm, meshes, variant):
    """Swap every texture to `variant`, or back to the base look with ''."""
    skin_dir = arm.get('dl_skin_dir', '')
    swapped = 0
    copies = {}
    for obj in meshes:
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or not mat.node_tree:
                continue
            
            shared = any(o.type == 'MESH' and o not in meshes and mat.name in o.data.materials
                         for o in bpy.data.objects)
            if shared:
                if mat.name not in copies:
                    copies[mat.name] = mat.copy()
                    copies[mat.name]['dl_done'] = False
                mat = slot.material = copies[mat.name]
            if mat.get('dl_done'):
                continue
            mat['dl_done'] = True
            nodes = [n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and n.get('dl_base')]
            for node in nodes:
                path = (variant and chroma_texture(node['dl_base'], skin_dir, variant)) or node['dl_base']
                if not os.path.isfile(path):
                    continue
                color = node.image is None or node.image.colorspace_settings.name != 'Non-Color'
                node.image = load_image(path, color)
                swapped += 1
    for obj in meshes:
        for slot in obj.material_slots:
            if slot.material and 'dl_done' in slot.material:
                del slot.material['dl_done']
    arm['dl_chroma'] = variant
    return swapped




def code_name(model, path):
    """TP_Smonk_S0_Skelmesh -> Smonk, GN_AK_Ashen_Skelmesh -> AK, Ashen."""
    base = model.name or os.path.splitext(os.path.basename(path))[0]
    parts = base.split('_')
    if len(parts) > 1 and parts[0] in ('TP', 'FP', 'Default', 'SK', 'GN', 'SM'):
        parts = parts[1:]
    skin = parts[1] if len(parts) > 2 else ''
    return parts[0], skin


def is_character(model):
    names = {b[0] for b in model.bones}
    return bool(names & {'L_Hip', 'Pelvis', 'pelvis', 'thigh_l'})


def load(path):
    """Import a .uemodel. Returns (object, code, skin, kind).

    kind is 'hero' (armature), 'weapon' (armature) or 'static' (mesh).
    A weapon also picks up the static meshes saved next to it (its
    magazine) and seats each one in the matching socket.
    """
    model = read(path)
    if model.verts is None:
        raise ValueError('That file has no mesh')
    model.content_root = content_root(path, model)
    code, skin = code_name(model, path)
    if not model.bones:
        return build_mesh(model, model.name or code), code, skin, 'static'

    kind = 'hero' if is_character(model) else 'weapon'
    arm = build_armature(model, code)
    build_mesh(model, model.name or code, arm)
    if kind == 'weapon':
        _attach_parts(arm, model, path)
        arm['dl_skin_dir'] = skin_folder(path) or ''
        arm['dl_chromas'] = ','.join(chromas(arm['dl_skin_dir']))
        arm['dl_chroma'] = ''
    return arm, code, skin, kind


def _attach_parts(arm, model, path):
    sockets = sorted(model.sockets, key=lambda s: -len(s[0]))
    folder = os.path.dirname(path)
    for f in sorted(os.listdir(folder)):
        part_path = os.path.join(folder, f)
        if not f.lower().endswith('.uemodel') or os.path.samefile(part_path, path):
            continue
        try:
            part = read(part_path)
        except (ValueError, OSError):
            continue
        if part.bones or part.verts is None:
            continue
        sock = next((s for s in sockets if s[0].lower() in part.name.lower()), None)
        if sock is None or sock[1] not in arm.data.bones:
            continue
        part.content_root = content_root(part_path, part)
        seat = arm.data.bones[sock[1]].matrix_local @ _matrix(sock[2], sock[3])
        build_mesh(part, part.name, arm, (sock[1], seat))
