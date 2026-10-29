"""Game bone names to the UE names the Tasty rig uses.

Every Deadlock hero shares the Valve biped naming, and every Valorant agent
shares Riot's, so one table per game covers all of them. Using UE names
means Tasty pose files from Fortnite and Rivals line up with the body bones.
"""
import re

CENTER = {
    'root_motion': 'root',
    'pelvis': 'pelvis',
    'spine_0': 'spine_01',
    'spine_1': 'spine_02',
    'spine_2': 'spine_03',
    'spine_3': 'spine_04',
    'neck_0': 'neck_01',
    'neck_1': 'neck_02',
    'head': 'head',
}

SIDED = {
    'clavicle': 'clavicle',
    'arm_upper': 'upperarm',
    'arm_lower': 'lowerarm',
    'hand': 'hand',
    'leg_upper': 'thigh',
    'leg_lower': 'calf',
    'ankle': 'foot',
    'ball': 'ball',
}

FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')

_sided = re.compile(r'^(' + '|'.join(SIDED) + r')_([LR])$')
_finger = re.compile(r'^finger_(thumb|index|middle|ring|pinky)_(meta|\d)_([LR])$')



VAL_CENTER = {
    'Root': 'root',
    'Splitter': 'pelvis',
    'Pelvis': 'hips',
    'Spine1': 'spine_01',
    'Spine2': 'spine_02',
    'Spine3': 'spine_03',
    'Spine4': 'spine_04',
    'Neck': 'neck_01',
    'Head': 'head',
}

VAL_SIDED = {
    'Clavicle': 'clavicle',
    'Shoulder': 'upperarm',
    'Elbow': 'lowerarm',
    'Hand': 'hand',
    'Hip': 'thigh',
    'Knee': 'calf',
    'Foot': 'foot',
    'Toe': 'ball',
    'Shoulder_Twst1': 'upperarm_twist_01',
    'Shoulder_Twst3': 'upperarm_twist_02',
    'Elbow_Twst2': 'lowerarm_twist_01',
    'Elbow_Twst3': 'lowerarm_twist_02',
    'Hip_Twst1': 'thigh_twist_01',
    'Hip_Twst3': 'thigh_twist_02',
}

_val_sided = re.compile(r'^([LR])_(' + '|'.join(VAL_SIDED) + r')$')
_val_finger = re.compile(r'^([LR])_(Thumb|Index|Middle|Ring|Pinky)(\d)$')


VALORANT_AGENTS = {
    'Smonk': 'clove', 'Clay': 'raze', 'Pandemic': 'viper', 'Wraith': 'omen', 'Hunter': 'sova',
    'Thorne': 'sage', 'Phoenix': 'phoenix', 'Wushu': 'jett', 'Gumshoe': 'cypher', 'Sarge': 'brimstone',
    'Breach': 'breach', 'Vampire': 'reyna', 'Killjoy': 'killjoy', 'Guide': 'skye', 'Stealth': 'yoru',
    'Rift': 'astra', 'Grenadier': 'kayo', 'Deadeye': 'chamber', 'Sprinter': 'neon', 'BountyHunter': 'fade',
    'Mage': 'harbor', 'AggroBot': 'gekko', 'Cable': 'deadlock', 'Sequoia': 'iso', 'Nox': 'vyse',
    'Cashew': 'tejo',
}

VALORANT_WEAPONS = {'AK': 'vandal', 'Carbine': 'phantom'}


HELPER_PATTERNS = ('_IKTARGET', '_OFFSET', 'Hier_', 'attachWorld', '_fx', 'muzzle_',
                   'IK', 'Weapon', '_Ndl', '_Helper', 'Armpit')


def ue_name(name):
    if name in CENTER:
        return CENTER[name]
    if name in VAL_CENTER:
        return VAL_CENTER[name]
    if m := _sided.match(name):
        return f'{SIDED[m[1]]}_{m[2].lower()}'
    if m := _finger.match(name):
        finger, seg, side = m[1], m[2], m[3].lower()
        if seg == 'meta':
            return f'{finger}_metacarpal_{side}'
        return f'{finger}_{int(seg) + 1:02d}_{side}'
    if m := _val_sided.match(name):
        return f'{VAL_SIDED[m[2]]}_{m[1].lower()}'
    if m := _val_finger.match(name):
        return f'{m[2].lower()}_{int(m[3]):02d}_{m[1].lower()}'
    return None




HEROES = {
    'shiv': {
        'props': ('knifearm_', 'knife_', 'blade_', 'comb_', 'piston_', 'reliquary', 'cleaver'),
        'aim': (
            ('piston_top_0_L', 'piston_bot_0_L'),
            ('piston_bot_0_L', 'piston_top_0_L'),
            ('piston_top_0_R', 'piston_bot_0_R'),
            ('piston_bot_0_R', 'piston_top_0_R'),
        ),
    },
}
