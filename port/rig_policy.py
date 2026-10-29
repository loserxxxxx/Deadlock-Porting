"""Only character assets keep skeletons; objectives and ordinary props are static."""
import re
from curated_props import curated_prop


def character_asset(model):
    path = model.replace('\\', '/').lower()
    parts = path.split('/')
    stem = parts[-1].removesuffix('.vmdl_c')
    if curated_prop(path)['important_prop']:
        return False
    if re.search(r'(?:^|/)(?:piece\d*|.*gibs?.*|.*fragment.*)(?:/|\.)', path):
        return False
    if re.match(r'(?:piece|head|face|staff|glass|upperbody|lowerbody|[lr]_(?:arm|leg))\d', stem):
        return False
    if path.startswith(('models/npc/', 'models/npc_units/')):
        folder = parts[2] if len(parts) > 2 else ''
        return not folder.startswith(('boss_', 'patron_', 'core_', 'shrine_', 'effigy_', 'end_core', 't2_', 'titan', 'trooper_gibs')) and '/particle/' not in path
    if path.startswith(('models/heroes/', 'models/heroes_wip/', 'models/heroes_staging/')):
        words = set(re.split(r'[^a-z]+', stem))
        return not bool(words & {'gun', 'weapon', 'pistol', 'rifle', 'knife', 'sword', 'grenade', 'prop', 'armor', 'book'}) and '/_prefabs/' not in path
    return False
