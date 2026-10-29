"""Tasty-style posing rig for Deadlock heroes.

Same idea as the Tasty rig that Fortnite and Rivals Porting build: IK arms
and legs with poles, a foot roll control, one curl control per finger, and
color-coded layers (red is right, blue is left). The differences:

* The switches are custom properties on the armature, shown in the sidebar.
  They still work in a .blend opened without the add-on.
* IK/FK switching matches the pose, so the limb does not jump.
* Sizes scale with the hero's height, so any import scale works.
* Every widget is generated, so no data .blend is needed.
"""
from math import radians

import bpy
from mathutils import Matrix, Vector

from . import names, widgets

SIDES = ('l', 'r')
FINGERS = names.FINGERS
UP = Vector((0, 0, 1))
FORWARD = Vector((0, -1, 0))

RIGHT_COLOR, LEFT_COLOR, CENTER_COLOR = 'THEME01', 'THEME04', 'THEME12'
ROOT_COLOR, DYNAMIC_COLOR, PROP_COLOR, EXTRA_COLOR = 'THEME03', 'THEME07', 'THEME09', 'THEME10'


BALL_BREAK = 40.0

SWITCHES = {
    'dl_arm_ik_l': (1.0, 'Left arm. 1 = IK (move the hand box), 0 = FK (rotate each bone)'),
    'dl_arm_ik_r': (1.0, 'Right arm. 1 = IK (move the hand box), 0 = FK (rotate each bone)'),
    'dl_leg_ik_l': (1.0, 'Left leg. 1 = IK (move the foot), 0 = FK (rotate each bone)'),
    'dl_leg_ik_r': (1.0, 'Right leg. 1 = IK (move the foot), 0 = FK (rotate each bone)'),
    'dl_use_poles': (1.0, 'Elbows and knees aim at the diamond pole targets'),
}

LAYERS = (
    
    
    ('Body', True),
    ('Fingers', True),
    ('Props', True),
    ('Body Details', False),
    ('Face', False),
    ('Finger Joints', False),
    ('Hair & Cloth', False),
    ('Prop Parts', False),
    ('Twist', False),
    ('Extra', False),
    ('Mechanics', False),
)


MAIN_SPINE = ('pelvis', 'spine_02', 'spine_04', 'neck_01', 'head')


def limb(kind, side):
    """FK bones, IK control and pole for one limb."""
    if kind == 'arm':
        return [f'upperarm_{side}', f'lowerarm_{side}', f'hand_{side}'], f'ik_hand_{side}', f'ik_hand_pole_{side}'
    return [f'thigh_{side}', f'calf_{side}', f'foot_{side}', f'ball_{side}'], f'ik_foot_{side}', f'ik_foot_pole_{side}'


def is_rigged(obj):
    return obj is not None and obj.type == 'ARMATURE' and bool(obj.get('dl_rig'))


def armature_meshes(arm):
    return [o for o in bpy.data.objects if o.type == 'MESH' and (
        o.parent == arm or any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers))]




def rename_bones(arm):
    count = 0
    for bone in arm.data.bones:
        new = names.ue_name(bone.name)
        if new and new != bone.name and new not in arm.data.bones:
            bone.name = new  
            count += 1
    return count


def bake_transform(arm, matrix):
    """Move the armature and its meshes by `matrix` and leave every object at identity."""
    for obj in armature_meshes(arm):
        obj.data.transform(matrix @ obj.matrix_world, shape_keys=True)
        obj.matrix_parent_inverse = Matrix()
        obj.matrix_basis = Matrix()
    arm.data.transform(matrix @ arm.matrix_world)
    arm.matrix_basis = Matrix()


def face_forward(arm):
    """Turn the hero to face -Y like UE imports. Deadlock heroes face +X."""
    bones = arm.data.bones
    foot, ball = bones.get('foot_l'), bones.get('ball_l')
    if not foot or not ball:
        return
    look = ball.head_local - foot.head_local
    look.z = 0
    if look.length < 1e-6:
        return
    turn = look.normalized().rotation_difference(FORWARD).to_matrix().to_4x4()
    bake_transform(arm, turn)


def prepare(arm, scale):
    rename_bones(arm)
    if scale != 1.0:
        bake_transform(arm, Matrix.Scale(scale, 4))
    face_forward(arm)


def is_weapon_root(bone):
    parent = bone.parent
    return bone.name.startswith('weapon_hand_') and parent is not None and parent.name.startswith('hand_')


def place_weapons(arm):
    """Stand the gun beside the hero as its own prop.

    The game stores weapons at the world origin, which puts them between the
    feet. Move each one out to its side at hip height. It gets its own
    control and does not follow the hand.
    Returns {bone name: matrix} for the edit bones still to move.
    """
    moves = {}
    tall = max((b.head_local.z for b in arm.data.bones), default=1.0)
    for bone in arm.data.bones:
        if not is_weapon_root(bone):
            continue
        
        side = -1.0 if bone.name.endswith(('_R', '_r')) else 1.0
        snap = Matrix.Translation((side * 0.45 * tall, 0.0, 0.5 * tall))
        for b in [bone] + list(bone.children_recursive):
            moves[b.name] = snap
    if not moves:
        return moves
    for obj in armature_meshes(arm):
        groups = {g.index: g.name for g in obj.vertex_groups}
        keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
        for v in obj.data.vertices:
            total, snap = 0.0, None
            for g in v.groups:
                name = groups.get(g.group)
                if name in moves:
                    total += g.weight
                    snap = moves[name]
            if snap is not None and total > 0.99:
                v.co = snap @ v.co
                for key in keys:
                    key.data[v.index].co = snap @ key.data[v.index].co
        obj.data.update()
    return moves




def measure(arm):
    """Height, ground, foot footprints, and the points each bone mostly moves."""
    meshes = armature_meshes(arm)
    lo, hi = Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
    feet = {s: [] for s in SIDES}
    weighted = set()
    clouds = {}
    for obj in meshes:
        mw = obj.matrix_world
        groups = {g.index: g.name for g in obj.vertex_groups}
        foot_groups = {i: n[-1] for i, n in groups.items()
                       if n in ('foot_l', 'ball_l', 'foot_r', 'ball_r')}
        for v in obj.data.vertices:
            co = mw @ v.co
            for k in range(3):
                lo[k] = min(lo[k], co[k])
                hi[k] = max(hi[k], co[k])
            for g in v.groups:
                if g.weight > 0.001:
                    weighted.add(groups.get(g.group))
                    if g.weight > 0.5:
                        clouds.setdefault(groups.get(g.group), []).append(co)
                    if g.group in foot_groups and g.weight > 0.3:
                        feet[foot_groups[g.group]].append(co)
    if not meshes:
        heads = [b.head_local for b in arm.data.bones]
        lo = Vector([min(h[k] for h in heads) for k in range(3)])
        hi = Vector([max(h[k] for h in heads) for k in range(3)])
    footprint = {}
    for s, pts in feet.items():
        if pts:
            footprint[s] = (min(p.x for p in pts), max(p.x for p in pts),
                            min(p.y for p in pts), max(p.y for p in pts))
    return max(hi.z - lo.z, 1e-3), lo.z, footprint, weighted, clouds




def _point(bone, target, min_len):
    if (target - bone.head).length > min_len:
        bone.tail = target
        return True
    return False


def _new(eb, name, head, tail, parent, roll_to=None):
    bone = eb.get(name) or eb.new(name)
    bone.head, bone.tail = head, tail
    bone.roll = 0.0
    if roll_to is not None:
        bone.align_roll(roll_to)
    bone.parent = eb.get(parent) if isinstance(parent, str) else parent
    bone.use_deform = False
    bone.use_connect = False
    return bone


def _copy(eb, name, source, parent):
    src = eb[source]
    bone = _new(eb, name, src.head.copy(), src.tail.copy(), parent)
    bone.roll = src.roll
    return bone


def finger_chain(eb, finger, side):
    segs = [f'{finger}_{i:02d}_{side}' for i in range(1, 5)]
    segs = [s for s in segs if s in eb]
    meta = f'{finger}_metacarpal_{side}'
    return (meta if meta in eb else None), segs


def tidy_bones(arm, H, profile, moves):
    """Point tails down the chains and set rolls so bends are predictable."""
    eb = arm.data.edit_bones
    small = 0.02 * H
    for name, snap in moves.items():
        eb[name].matrix = snap @ eb[name].matrix

    
    root = eb.get('root') or _new(eb, 'root', Vector(), Vector((0, 0.15 * H, 0)), None)
    root.tail = root.head + Vector((0, 0.15 * H, 0))
    root.roll = 0.0
    root.parent = None  
    for bone in eb:
        if (bone.parent is None and bone != root) or is_weapon_root(bone):
            bone.parent = root

    
    spine = [n for n in ('pelvis', 'spine_01', 'spine_02', 'spine_03', 'spine_04', 'spine_05',
                         'neck_01', 'neck_02', 'head') if n in eb]
    for a, b in zip(spine, spine[1:]):
        if not _point(eb[a], eb[b].head, small):
            eb[a].tail = eb[a].head + UP * 0.05 * H
    if 'head' in eb:
        end = eb.get('head_end')
        if not (end and _point(eb['head'], end.head, small)):
            eb['head'].tail = eb['head'].head + UP * 0.12 * H
    for n in spine:
        eb[n].align_roll(FORWARD)

    palms = {}
    for s in SIDES:
        
        chain = [f'clavicle_{s}', f'upperarm_{s}', f'lowerarm_{s}', f'hand_{s}']
        for a, b in zip(chain, chain[1:]):
            if a in eb and b in eb:
                _point(eb[a], eb[b].head, 1e-5)
        if f'clavicle_{s}' in eb:
            eb[f'clavicle_{s}'].align_roll(UP)
        hand = eb.get(f'hand_{s}')
        if hand:
            knuckles = [eb[n].head for n in (f'{f}_01_{s}' for f in FINGERS[1:]) if n in eb]
            if knuckles:
                mid = sum(knuckles, Vector()) / len(knuckles)
                hand.tail = hand.head + (mid - hand.head) * 0.6
        _bend_roll(eb, f'upperarm_{s}', f'lowerarm_{s}')

        
        if hand:
            a = _first_head(eb, (f'index_01_{s}', f'index_metacarpal_{s}')) - \
                _first_head(eb, (f'pinky_01_{s}', f'pinky_metacarpal_{s}', f'ring_01_{s}'))
            palm = a.cross(hand.tail - hand.head)
            if s == 'l':
                palm = -palm
            if palm.length > 1e-8:
                palm.normalize()
                palms[s] = palm
                hand.align_roll(palm)

        for f in FINGERS:
            meta, segs = finger_chain(eb, f, s)
            chain = ([meta] if meta else []) + segs
            for a, b in zip(chain, chain[1:]):
                _point(eb[a], eb[b].head, 1e-5)
            if len(chain) >= 2:
                last, prev = eb[chain[-1]], eb[chain[-2]]
                ends = [c for c in last.children if c.name.startswith('finger_')]
                if not (ends and _point(last, ends[0].head, 1e-5)):
                    last.tail = last.head + (prev.tail - prev.head).normalized() * prev.length * 0.8
            if s in palms:
                for n in chain:
                    eb[n].align_roll(palms[s])

        
        chain = [f'thigh_{s}', f'calf_{s}', f'foot_{s}', f'ball_{s}']
        for a, b in zip(chain, chain[1:]):
            if a in eb and b in eb:
                _point(eb[a], eb[b].head, 1e-5)
        ball, foot = eb.get(f'ball_{s}'), eb.get(f'foot_{s}')
        if ball and foot:
            toe = [c for c in ball.children if c.name.startswith('ball_end')]
            if not (toe and _point(ball, toe[0].head, 1e-5)):
                ahead = ball.head - foot.head
                ahead.z = 0
                ball.tail = ball.head + ahead.normalized() * max(ahead.length * 0.5, 0.01 * H)
        _bend_roll(eb, f'thigh_{s}', f'calf_{s}')
        for n in (f'foot_{s}', f'ball_{s}'):
            if n in eb:
                eb[n].align_roll(UP)

    
    for bone in eb:
        if bone.name in spine or bone == root or len(bone.children) != 1 or _is_body(bone.name):
            continue
        _point(bone, bone.children[0].head, 1e-4 * H)

    for a, b in profile.get('aim', ()):
        if a in eb and b in eb:
            bone, goal = eb[a], eb[b].head
            if (goal - bone.head).length > 1e-6:
                bone.tail = bone.head + (goal - bone.head).normalized() * bone.length
    return palms


def _is_body(name):
    body = ('clavicle', 'upperarm', 'lowerarm', 'hand', 'thigh', 'calf', 'foot', 'ball') + FINGERS
    return any(name.startswith(b + '_') for b in body) and name[-2:] in ('_l', '_r')


def _first_head(eb, options):
    for n in options:
        if n in eb:
            return eb[n].head.copy()
    return Vector()


def _bend_roll(eb, upper, lower):
    """X axis along the hinge, so bending the joint is an X rotation."""
    if upper not in eb or lower not in eb:
        return
    a, b = eb[upper], eb[lower]
    hinge = a.vector.cross(b.vector)
    if hinge.length < 1e-8:
        hinge = Vector((1, 0, 0))
    hinge.normalize()
    for bone in (a, b):
        bone.align_roll(hinge.cross(bone.vector.normalized()))


def add_controls(arm, H, ground, footprint, profile):
    eb = arm.data.edit_bones
    made = {'feet': {}}
    
    
    for _a, b in profile.get('aim', ()):
        if b in eb:
            src = eb[b]
            _new(eb, f'aim_{b}', src.head.copy(), src.head + (src.tail - src.head) * 0.2, src.parent)
    for s in SIDES:
        
        if all(n in eb for n in limb('arm', s)[0]):
            up, low, hand = (eb[n] for n in limb('arm', s)[0])
            _copy(eb, f'ik_hand_{s}', hand.name, 'root')
            pole = _pole_spot(up.head, low.head, hand.head, Vector((0, 1, 0)), H)
            _new(eb, f'ik_hand_pole_{s}', pole, pole + Vector((0, 0, 0.04 * H)), 'root')

        
        if all(n in eb for n in (f'thigh_{s}', f'calf_{s}', f'foot_{s}')):
            thigh, calf, foot = eb[f'thigh_{s}'], eb[f'calf_{s}'], eb[f'foot_{s}']
            ball = eb.get(f'ball_{s}')
            ankle = foot.head.copy()
            ball_at = ball.head.copy() if ball else foot.tail.copy()
            if s in footprint:
                x0, x1, y0, y1 = footprint[s]
            else:
                half = 0.03 * H
                x0, x1 = ankle.x - half, ankle.x + half
                y0, y1 = ball_at.y - 0.03 * H, ankle.y + 0.03 * H
            g = ground
            length = max(y1 - y0, 0.05 * H)
            stub = FORWARD * 0.03 * H

            ik = _new(eb, f'ik_foot_{s}', ankle, ankle + FORWARD * length * 0.5, 'root')
            heel = Vector((ankle.x, y1, g))
            tip = Vector((ball_at.x, y0, g))
            
            inner_x, outer_x = (x0, x1) if s == 'l' else (x1, x0)
            inner = Vector((inner_x, ball_at.y, g))
            outer = Vector((outer_x, ball_at.y, g))
            p = _new(eb, f'ik_foot_roll_back_{s}', heel, heel + stub, ik)
            p = _new(eb, f'ik_foot_roll_front_{s}', tip, tip + stub, p)
            p = _new(eb, f'ik_foot_roll_inner_{s}', inner, inner + stub, p)
            bank = _new(eb, f'ik_foot_roll_outer_{s}', outer, outer + stub, p)
            p = _new(eb, f'ik_ball_roll_{s}', ball_at, ball_at + stub, bank)
            _copy(eb, f'ik_foot_target_{s}', foot.name, p)
            if ball:
                _copy(eb, f'ik_toe_{s}', ball.name, bank)
            ctrl_at = heel + Vector((0, 0.07 * H, 0.03 * H))
            _new(eb, f'ik_foot_ctrl_{s}', ctrl_at, ctrl_at + stub, ik)
            pole = _pole_spot(thigh.head, calf.head, foot.head, FORWARD, H)
            _new(eb, f'ik_foot_pole_{s}', pole, pole + Vector((0, 0, 0.04 * H)), 'root')
            made['feet'][s] = (x0, x1, y0, y1, g)

        
        for f in FINGERS:
            meta, segs = finger_chain(eb, f, s)
            if f == 'thumb':
                if len(segs) < 2:
                    continue
                _copy(eb, f'thumb_control_{s}', segs[1], segs[0])
            elif segs:
                parent = eb[segs[0]].parent
                _copy(eb, f'{f}_control_{s}', segs[0], parent)
    return made


def _pole_spot(top, mid, end, fallback, H):
    halfway = (top + end) / 2
    bend = mid - halfway
    if bend.length < 0.005 * H:
        bend = fallback.copy()
    return mid + bend.normalized() * 0.35 * H




def _signed_angle(u, v, normal):
    angle = u.angle(v)
    if u.cross(v).angle(normal) < 1:
        angle = -angle
    return angle


def pole_angle(arm, upper, lower, pole):
    """Pole angle that keeps the chain exactly where it is at rest."""
    bones = arm.data.bones
    a, b, p = bones[upper], bones[lower], bones[pole].head_local
    normal = (b.tail_local - a.head_local).cross(p - a.head_local)
    projected = normal.cross(a.tail_local - a.head_local)
    return _signed_angle(a.matrix_local.col[0].xyz, projected, a.tail_local - a.head_local)


def drive(owner, path, expression, arm, **props):
    fcurve = owner.driver_add(path)
    driver = fcurve.driver
    driver.type = 'SCRIPTED'
    for var in list(driver.variables):
        driver.variables.remove(var)
    for name, key in props.items():
        var = driver.variables.new()
        var.name = name
        var.type = 'SINGLE_PROP'
        var.targets[0].id_type = 'OBJECT'
        var.targets[0].id = arm
        var.targets[0].data_path = f'["{key}"]'
    driver.expression = expression
    return fcurve


def add_switches(arm):
    for key, (value, text) in SWITCHES.items():
        if key not in arm:
            arm[key] = value
        ui = arm.id_properties_ui(key)
        ui.update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, description=text)


def _ik(pb, arm, target, pole, angle, ik_key):
    with_pole = pb.constraints.new('IK')
    with_pole.name = 'IK w/ Pole'
    with_pole.target, with_pole.subtarget = arm, target
    with_pole.pole_target, with_pole.pole_subtarget = arm, pole
    with_pole.pole_angle = angle
    with_pole.chain_count = 2
    drive(with_pole, 'influence', 'ik * pole', arm, ik=ik_key, pole='dl_use_poles')

    free = pb.constraints.new('IK')
    free.name = 'IK w/o Pole'
    free.target, free.subtarget = arm, target
    free.chain_count = 2
    drive(free, 'influence', 'ik * (1 - pole)', arm, ik=ik_key, pole='dl_use_poles')


def _copy_rot(pb, arm, target, space, ik_key=None, mix='REPLACE'):
    con = pb.constraints.new('COPY_ROTATION')
    con.target, con.subtarget = arm, target
    con.target_space = con.owner_space = space
    con.mix_mode = mix
    if ik_key:
        drive(con, 'influence', 'ik', arm, ik=ik_key)
    return con


def _roll(pb, arm, ctrl, axis, src, dst):
    """Map the roll control's rotation on `axis` from `src` degrees to `dst` degrees."""
    con = pb.constraints.new('TRANSFORM')
    con.name = 'Foot Roll'
    con.target, con.subtarget = arm, ctrl
    con.target_space = con.owner_space = 'LOCAL'
    con.map_from = con.map_to = 'ROTATION'
    a = axis.lower()
    setattr(con, f'map_to_{a}_from', axis)
    setattr(con, f'from_min_{a}_rot', radians(src[0]))
    setattr(con, f'from_max_{a}_rot', radians(src[1]))
    setattr(con, f'to_min_{a}_rot', radians(dst[0]))
    setattr(con, f'to_max_{a}_rot', radians(dst[1]))


def hide_when(arm, bone_name, expression, **props):
    pb = arm.pose.bones.get(bone_name)
    if pb is None:
        return
    
    
    if 'hide' in pb.bl_rna.properties:
        drive(pb, 'hide', expression, arm, **props)
    else:
        drive(arm.data, f'bones["{bone_name}"].hide', expression, arm, **props)


def add_constraints(arm):
    pose = arm.pose.bones
    for s in SIDES:
        fk, ctrl, pole = limb('arm', s)
        if ctrl in pose:
            key = f'dl_arm_ik_{s}'
            _ik(pose[fk[1]], arm, ctrl, pole, pole_angle(arm, fk[0], fk[1], pole), key)
            _copy_rot(pose[fk[2]], arm, ctrl, 'WORLD', key)
            for n in fk:
                hide_when(arm, n, 'ik > 0.5', ik=key)
            hide_when(arm, ctrl, 'ik < 0.5', ik=key)
            hide_when(arm, pole, 'ik < 0.5 or pole < 0.5', ik=key, pole='dl_use_poles')

        fk, ctrl, pole = limb('leg', s)
        if ctrl in pose:
            key = f'dl_leg_ik_{s}'
            target = f'ik_foot_target_{s}'
            _ik(pose[fk[1]], arm, target, pole, pole_angle(arm, fk[0], fk[1], pole), key)
            _copy_rot(pose[fk[2]], arm, target, 'WORLD', key)
            if f'ik_toe_{s}' in pose and fk[3] in pose:
                _copy_rot(pose[fk[3]], arm, f'ik_toe_{s}', 'WORLD', key)

            roll = f'ik_foot_ctrl_{s}'
            
            
            
            _roll(pose[f'ik_foot_roll_back_{s}'], arm, roll, 'X', (0, 90), (0, 90))
            _roll(pose[f'ik_ball_roll_{s}'], arm, roll, 'X', (-BALL_BREAK, 0), (-BALL_BREAK, 0))
            _roll(pose[f'ik_foot_roll_front_{s}'], arm, roll, 'X', (-90, -BALL_BREAK), (BALL_BREAK - 90, 0))
            
            neg_x, pos_x = (f'ik_foot_roll_inner_{s}', f'ik_foot_roll_outer_{s}') if s == 'l' else \
                (f'ik_foot_roll_outer_{s}', f'ik_foot_roll_inner_{s}')
            _roll(pose[neg_x], arm, roll, 'Y', (0, 90), (0, 90))
            _roll(pose[pos_x], arm, roll, 'Y', (-90, 0), (-90, 0))
            ctrl_pb = pose[roll]
            ctrl_pb.rotation_mode = 'XYZ'
            ctrl_pb.lock_location = (True, True, True)
            ctrl_pb.lock_rotation = (False, False, True)
            ctrl_pb.lock_scale = (True, True, True)

            for n in fk:
                hide_when(arm, n, 'ik > 0.5', ik=key)
            for n in (ctrl, roll, f'ik_toe_{s}'):
                hide_when(arm, n, 'ik < 0.5', ik=key)
            hide_when(arm, pole, 'ik < 0.5 or pole < 0.5', ik=key, pole='dl_use_poles')

        for f in FINGERS:
            control = f'{f}_control_{s}'
            if control not in pose:
                continue
            pose[control].rotation_mode = 'XYZ'
            segs = finger_chain(pose, f, s)[1]
            for n in (segs[1:] if f == 'thumb' else segs):
                _copy_rot(pose[n], arm, control, 'LOCAL', mix='ADD')

    profile = names.HEROES.get(arm.get('dl_hero', ''), {})
    for a, b in profile.get('aim', ()):
        if a in pose and f'aim_{b}' in pose:
            con = pose[a].constraints.new('DAMPED_TRACK')
            con.target, con.subtarget = arm, f'aim_{b}'




def side_color(name):
    if name.endswith(('_l', '_L')):
        return LEFT_COLOR
    if name.endswith(('_r', '_R')):
        return RIGHT_COLOR
    return CENTER_COLOR


def fitted(arm, clouds, bone, H, along=0.5, clip=True, source=None):
    """Ring that hugs the mesh around the bone, or None if the bone moves too little mesh."""
    head, x, y, z = widgets.axes(arm, bone)
    length = arm.data.bones[bone].length
    xs, zs = [], []
    for p in clouds.get(source or bone, ()):
        d = p - head
        t = d.dot(y)
        if clip and not (-0.15 * length <= t <= 1.15 * length):
            continue
        xs.append(abs(d.dot(x)))
        zs.append(abs(d.dot(z)))
    if len(xs) < 12:
        return None
    xs.sort()
    zs.sort()

    def size(values):
        return min(max(values[int(len(values) * 0.9)] * 1.15 + 0.01 * H, 0.02 * H), 0.25 * H)

    return [widgets.ellipse(head + y * length * along, x, z, size(xs), size(zs))]


def dress(arm, H, palms, feet, weighted, clouds):
    """Widgets, colors and layers."""
    data = arm.data
    while data.collections_all:
        data.collections.remove(data.collections_all[0])
    layers = {}
    for name, visible in LAYERS:
        layers[name] = data.collections.new(name)
        layers[name].is_visible = visible

    pose = arm.pose.bones
    done = set()

    def put(bone, layer, lines=None, color=None, wire=2.0):
        if bone not in pose or bone in done:
            return
        pb = pose[bone]
        layers[layer].assign(pb)
        pb.color.palette = color or side_color(bone)
        
        pb.custom_shape = None
        pb.custom_shape_scale_xyz = (1.0, 1.0, 1.0)
        pb.custom_shape_translation = (0.0, 0.0, 0.0)
        pb.custom_shape_rotation_euler = (0.0, 0.0, 0.0)
        if lines:
            pb.custom_shape = widgets.make(arm, bone, lines)
            pb.use_custom_shape_bone_size = False
            pb.custom_shape_wire_width = wire
        done.add(bone)

    def ring(bone, r, along=0.5):
        return widgets.bone_ring(arm, bone, r, along) if bone in pose else None

    def hug(bone, fallback, along=0.5, clip=True, source=None):
        if bone not in pose:
            return None
        return fitted(arm, clouds, bone, H, along, clip, source) or ring(bone, fallback, along)

    put('root', 'Body', widgets.root(Vector(), 0.35 * H), ROOT_COLOR, 3.0)
    
    hips = 'hips' if 'pelvis' not in clouds and 'hips' in clouds else None
    put('pelvis', 'Body', hug('pelvis', 0.12 * H, 0.0, clip=False, source=hips), wire=3.0)
    put('hips', 'Body Details', hug('hips', 0.1 * H, 0.0, clip=False))
    for n, r in (('spine_01', 0.1), ('spine_02', 0.1), ('spine_03', 0.1), ('spine_04', 0.1), ('spine_05', 0.1),
                 ('neck_01', 0.05), ('neck_02', 0.05), ('head', 0.08)):
        put(n, 'Body' if n in MAIN_SPINE else 'Body Details', hug(n, r * H))

    for s in SIDES:
        put(f'clavicle_{s}', 'Body', widgets.arc_over(arm, f'clavicle_{s}', 0.04 * H) if f'clavicle_{s}' in pose else None)
        
        for n in (f'upperarm_{s}', f'lowerarm_{s}', f'thigh_{s}', f'calf_{s}', f'hand_{s}'):
            put(n, 'Body', hug(n, 0.04 * H))
        put(f'foot_{s}', 'Body', hug(f'foot_{s}', 0.05 * H, 0.3))
        put(f'ball_{s}', 'Body', hug(f'ball_{s}', 0.035 * H))

        if f'ik_hand_{s}' in pose:
            head, x, y, z = widgets.axes(arm, f'ik_hand_{s}')
            length = data.bones[f'ik_hand_{s}'].length
            put(f'ik_hand_{s}', 'Body', widgets.box(head + y * length * 0.5, x, y, z,
                                                      (0.04 * H, max(length, 0.03 * H), 0.02 * H)), wire=3.0)
            put(f'ik_hand_pole_{s}', 'Body', widgets.diamond(data.bones[f'ik_hand_pole_{s}'].head_local, 0.015 * H))

        if s in feet:
            x0, x1, y0, y1, g = feet[s]
            pad = 0.015 * H
            z = g + 0.003 * H
            put(f'ik_foot_{s}', 'Body', widgets.rect([
                Vector((x0 - pad, y1 + pad, z)), Vector((x1 + pad, y1 + pad, z)),
                Vector((x1 + pad, y0 - pad, z)), Vector((x0 - pad, y0 - pad, z))]), wire=3.0)
            put(f'ik_foot_ctrl_{s}', 'Body', widgets.foot_roll(data.bones[f'ik_foot_ctrl_{s}'].head_local, 0.035 * H))
            put(f'ik_toe_{s}', 'Body', hug(f'ik_toe_{s}', 0.03 * H, source=f'ball_{s}'))
            put(f'ik_foot_pole_{s}', 'Body', widgets.diamond(data.bones[f'ik_foot_pole_{s}'].head_local, 0.015 * H))

        palm = palms.get(s, Vector((0, 0, 1)))
        for f in FINGERS:
            control = f'{f}_control_{s}'
            meta, segs = finger_chain(pose, f, s)
            if control in pose:
                first = segs[1] if f == 'thumb' else segs[0]
                start = data.bones[first].head_local
                end = data.bones[segs[-1]].tail_local
                put(control, 'Finger Joints', widgets.finger_curl(start, end, -palm * 0.015 * H, 0.008 * H))
            
            
            
            for n in segs[:3]:
                put(n, 'Fingers', ring(n, 0.006 * H))
            for n in ([meta] if meta else []) + segs[3:]:
                put(n, 'Finger Joints', ring(n, 0.008 * H))

    mechanics = [b.name for b in data.bones if b.name.startswith(('ik_foot_roll_', 'ik_ball_roll_', 'ik_foot_target_', 'aim_'))]
    for n in mechanics:
        put(n, 'Mechanics', color=EXTRA_COLOR)

    profile = names.HEROES.get(arm.get('dl_hero', ''), {})
    props = tuple(profile.get('props', ()))

    def is_prop(bone):
        return bone.name.startswith(props) or bone.name.startswith('weapon_') or \
            any(p.name.startswith('weapon_') for p in bone.parent_recursive)

    def prop_box(bone):
        """Box around everything the prop moves: gun, knife arm, relic."""
        pts = [p for b in [bone] + list(bone.children_recursive) for p in clouds.get(b.name, ())]
        if len(pts) < 12:
            return None
        lo = Vector([min(p[k] for p in pts) for k in range(3)])
        hi = Vector([max(p[k] for p in pts) for k in range(3)])
        half = (hi - lo) / 2 + Vector((0.01, 0.01, 0.01)) * H
        X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
        return widgets.box((lo + hi) / 2, X, Y, Z, half)

    def is_face(bone):
        """Jaw, eyes, brows: weighted bones under the head that are not hair."""
        loose = ('hair', 'ear', 'chain', 'cloth', 'hood', 'strap')
        return any(p.name == 'head' for p in bone.parent_recursive) and \
            not any(w in bone.name.lower() for w in loose)

    for pb in pose:
        n = pb.name
        if n in done:
            continue
        bone = data.bones[n]
        length = max(bone.length, 0.005 * H)
        if any(h in n for h in names.HELPER_PATTERNS):
            put(n, 'Extra', color=EXTRA_COLOR)
        elif n not in weighted and ('_end' in n or n.endswith('end')):
            put(n, 'Extra', color=EXTRA_COLOR)
        elif is_prop(bone):
            handle = (bone.parent is None or not is_prop(bone.parent)) and prop_box(bone)
            if handle:
                
                put(n, 'Props', handle, PROP_COLOR, 2.5)
            else:
                put(n, 'Prop Parts', ring(n, min(max(0.25 * length, 0.008 * H), 0.03 * H), 0.3), PROP_COLOR, 1.5)
        elif 'twist' in n.lower():
            put(n, 'Twist', ring(n, max(0.3 * length, 0.01 * H)))
        elif n in weighted and is_face(bone):
            put(n, 'Face', ring(n, 0.008 * H), wire=1.5)
        elif n in weighted:
            put(n, 'Hair & Cloth', widgets.stick(bone.head_local, bone.tail_local, 0.006 * H), DYNAMIC_COLOR, 1.5)
        else:
            put(n, 'Extra', color=EXTRA_COLOR)

    for layer in layers.values():
        if not layer.bones:
            data.collections.remove(layer)




def build(arm, hero=''):
    """Rig an armature that has UE bone names and faces -Y."""
    if is_rigged(arm):
        raise RuntimeError(f'{arm.name} already has the rig')
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    rename_bones(arm)
    face_forward(arm)
    if 'pelvis' not in arm.data.bones or 'thigh_l' not in arm.data.bones:
        raise RuntimeError('No pelvis or thigh bones. Is this a Deadlock hero or Valorant agent?')

    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    if hero:
        arm['dl_hero'] = hero
    profile = names.HEROES.get(arm.get('dl_hero', ''), {})

    moves = place_weapons(arm)
    H, ground, footprint, weighted, clouds = measure(arm)

    bpy.ops.object.mode_set(mode='EDIT')
    palms = tidy_bones(arm, H, profile, moves)
    made = add_controls(arm, H, ground, footprint, profile)
    bpy.ops.object.mode_set(mode='POSE')

    add_switches(arm)
    add_constraints(arm)
    dress(arm, H, palms, made['feet'], weighted, clouds)

    data = arm.data
    data.display_type = 'OCTAHEDRAL'
    data.show_bone_custom_shapes = True
    data.show_bone_colors = True
    arm.show_in_front = True
    arm['dl_rig'] = 1
    arm['dl_height'] = H
    bpy.ops.object.mode_set(mode='POSE')
    return arm


def build_prop(arm, hero=None):
    """Rig a weapon as its own model: one box moves it, parts wait on a hidden layer.

    It stands beside `hero` (the hero's right, hip height) side-on to the
    front camera, barrel pointing away from them, and is not parented to
    them, like the Deadlock guns.
    """
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)

    def bounds():
        pts = [o.matrix_world @ v.co for o in armature_meshes(arm) for v in o.data.vertices]
        lo = Vector([min(p[k] for p in pts) for k in range(3)])
        hi = Vector([max(p[k] for p in pts) for k in range(3)])
        return lo, hi

    lo, hi = bounds()
    center = (lo + hi) / 2
    muzzle = arm.data.bones.get('Muzzle')
    look = (muzzle.head_local - center) if muzzle else Vector((hi.x - lo.x, 0, 0))
    look.z = 0
    
    away = Vector((-1, 0, 0))
    turn = look.normalized().rotation_difference(away).to_matrix().to_4x4() if look.length > 1e-6 else Matrix()
    length = max(hi - lo)
    if hero is not None:
        H = hero.get('dl_height', 1.8)
        spot = hero.matrix_world.translation + Vector((-0.3 * H - 0.5 * length, 0, 0.5 * H))
    else:
        spot = Vector((0, 0, 1.0))
    bake_transform(arm, Matrix.Translation(spot) @ turn @ Matrix.Translation(-center))
    lo, hi = bounds()
    center = (lo + hi) / 2
    size = max(hi - lo)

    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    tops = [b for b in eb if b.parent is None]
    ctrl = _new(eb, 'prop', center, center + away * size * 0.3, None)
    for b in tops:
        b.parent = ctrl
    bpy.ops.object.mode_set(mode='POSE')

    data = arm.data
    while data.collections_all:
        data.collections.remove(data.collections_all[0])
    layers = {name: data.collections.new(name) for name in ('Props', 'Prop Parts', 'Extra')}
    layers['Prop Parts'].is_visible = layers['Extra'].is_visible = False
    weighted = {g.name for o in armature_meshes(arm) for g in o.vertex_groups}

    pad = Vector((0.03, 0.03, 0.03)) * size
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    for pb in arm.pose.bones:
        pb.custom_shape_scale_xyz = (1.0, 1.0, 1.0)
        if pb.name == 'prop':
            layers['Props'].assign(pb)
            pb.custom_shape = widgets.make(arm, pb.name, widgets.box(center, X, Y, Z, (hi - lo) / 2 + pad))
            pb.use_custom_shape_bone_size = False
            pb.custom_shape_wire_width = 2.5
            pb.color.palette = PROP_COLOR
        elif pb.name in weighted and pb.name not in ('Root', 'Skeleton'):
            layers['Prop Parts'].assign(pb)
            pb.custom_shape = widgets.make(arm, pb.name, widgets.bone_ring(arm, pb.name, 0.06 * size))
            pb.use_custom_shape_bone_size = False
            pb.custom_shape_wire_width = 1.5
            pb.color.palette = PROP_COLOR
        else:
            layers['Extra'].assign(pb)
            pb.color.palette = EXTRA_COLOR

    data.display_type = 'OCTAHEDRAL'
    data.show_bone_custom_shapes = True
    data.show_bone_colors = True
    arm.show_in_front = True
    arm['dl_prop'] = 1
    arm['dl_height'] = size
    data.bones.active = data.bones['prop']
    return arm


def find_hero(scene):
    return next((o for o in scene.objects if is_rigged(o)), None)


def set_switch(arm, key, value):
    arm[key] = value
    arm.update_tag()
    bpy.context.view_layer.update()


def switch(arm, kind, side, to_ik):
    """Flip one limb between IK and FK without the pose jumping."""
    pose, bones = arm.pose.bones, arm.data.bones
    fk, ctrl, pole = limb(kind, side)
    key = f'dl_{kind}_ik_{side}'
    if ctrl not in pose:
        return
    layer = bpy.context.view_layer
    if not to_ik:
        held = [(n, pose[n].matrix.copy()) for n in fk if n in pose]
        set_switch(arm, key, 0.0)
        for n, m in held:
            pose[n].matrix = m
            layer.update()
        return

    if kind == 'arm':
        pose[ctrl].matrix = pose[fk[2]].matrix.copy()
    else:
        roll = pose[f'ik_foot_ctrl_{side}']
        roll.rotation_euler = (0, 0, 0)
        rest_foot = bones[fk[2]].matrix_local
        pose[ctrl].matrix = pose[fk[2]].matrix @ rest_foot.inverted() @ bones[ctrl].matrix_local
        layer.update()
        toe = f'ik_toe_{side}'
        if toe in pose and fk[3] in pose:
            pose[toe].matrix = pose[fk[3]].matrix.copy()
    layer.update()

    top, mid, end = (pose[n].head for n in fk[:3])
    rest = bones[pole]
    reach = (rest.head_local - bones[fk[1]].head_local).length
    halfway = (top + end) / 2
    bend = mid - halfway
    if bend.length > 1e-5:
        spot = mid + bend.normalized() * reach
        m = rest.matrix_local.copy()
        m.translation = spot
        pose[pole].matrix = m
    set_switch(arm, key, 1.0)
