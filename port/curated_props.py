"""Whole gameplay assets for the Props shelf; raw archive access stays separate."""

OBJECTIVES = {
    'models/npc/boss_tier_01_brazier_guardian/boss_tier_01_brazier_guardian.vmdl_c': 'Brazier Guardian',
    'models/npc/boss_tier_02_sun_walker_v2/boss_tier_02_sun_walker.vmdl_c': 'Sun Walker',
    'models/npc/boss_tier_02_sun_walker/boss_tier_02_sun_walker.vmdl_c': 'Sun Walker (Original)',
    'models/npc/boss_tier_02/boss_tier2_new_model.vmdl_c': 'Walker (Mechanical)',
    'models/npc/t2_clock_tower/t2_clock_tower_shape.vmdl_c': 'Clock Tower Walker',
    'models/npc/boss_defense/boss_defense.vmdl_c': 'Defense Boss',
    'models/npc/boss_temple/boss_temple.vmdl_c': 'Temple Boss',
    'models/npc/midboss/midboss.vmdl_c': 'Mid Boss',
    'models/npc/patron_amber/patron_amber.vmdl_c': 'Amber Patron',
    'models/npc/patron_sapphire/patron_sapphire.vmdl_c': 'Sapphire Patron',
    'models/npc/core_amber/core_amber.vmdl_c': 'Amber Core',
    'models/npc/core_sapphire/core_sapphire.vmdl_c': 'Sapphire Core',
    'models/npc/shrine_amber/shrine_amber.vmdl_c': 'Amber Shrine',
    'models/npc/shrine_sapphire/shrine_sapphire.vmdl_c': 'Sapphire Shrine',
    'models/npc/effigy_amber/effigy_amber_model.vmdl_c': 'Amber Effigy',
    'models/npc/effigy_sapphire/effigy_sapphire_model.vmdl_c': 'Sapphire Effigy',
    'models/props_gameplay/base_core.vmdl_c': 'Base Core',
    'models/props_gameplay/idol_urn/idol_urn.vmdl_c': 'Soul Urn',
    'models/props_gameplay/golden_idol.vmdl_c': 'Golden Idol',
    'models/props_gameplay/rejuv/rejuv.vmdl_c': 'Rejuvenator',
    'models/props_gameplay/rejuv/rejuv_crystal.vmdl_c': 'Rejuvenator Crystal',
    'models/props_gameplay/sinners_sacrifice_vault/sinners_sacrifice.vmdl_c': "Sinner's Sacrifice",
    'models/props_gameplay/neutral_vault/neutral_vault.vmdl_c': 'Neutral Vault',
    'models/props_gameplay/payload/payload.vmdl_c': 'Payload',
}
SHOPS = {
    'models/props_gameplay/shop/shop_model.vmdl_c': 'Curiosity Shop',
    'models/props_gameplay/shop/shop_01.vmdl_c': 'Shop Stand',
    'models/props_gameplay/gun_shop/gun_shop.vmdl_c': 'Gun Shop',
    'models/props_gameplay/ammo_stand/ammo_stand.vmdl_c': 'Ammo Stand',
    'models/props_gameplay/shop/shop_curiosity_sign_01.vmdl_c': 'Curiosity Shop Sign',
    'models/props_gameplay/zip_tower_base.vmdl_c': 'Zipline Tower Base',
    'models/props_gameplay/zip_tower_hover.vmdl_c': 'Zipline Tower Hover',
    'models/props_gameplay/zip_tower_top.vmdl_c': 'Zipline Tower Top',
    'models/props_gameplay/generator_charger/generator_charger.vmdl_c': 'Generator Charger',
}
PICKUPS = {
    'models/props_gameplay/gold_crate.vmdl_c': 'Gold Crate',
    'models/props_gameplay/gold_crate_parachute.vmdl_c': 'Gold Crate Parachute',
    'models/props_gameplay/coin/gold_coin.vmdl_c': 'Gold Coin',
    'models/props_gameplay/ult_pickup.vmdl_c': 'Ultimate Pickup',
    'models/props_gameplay/powerup/powerup_01.vmdl_c': 'Powerup',
    'models/props_gameplay/powerup_cursed_apple/powerup_cursed_apple.vmdl_c': 'Cursed Apple',
}
BREAKABLES = {
    'models/props_gameplay/item_container_breakable/item_container.vmdl_c': 'Item Container',
    'models/props_gameplay/jar_01/jar_01.vmdl_c': 'Breakable Jar',
    'models/props_gameplay/sake_barrel_01/sake_barrel_01.vmdl_c': 'Breakable Barrel',
    'models/props_gameplay/wooden_crate_02/wooden_crate_02.vmdl_c': 'Breakable Crate',
    'models/props_gameplay/wooden_crate_03/wooden_crate_03.vmdl_c': 'Breakable Crate (Alternate)',
    'models/items/crystal_crate.vmdl_c': 'Crystal Crate',
    'models/items/item_crate.vmdl_c': 'Item Crate',
    'models/items/item_crate_tough.vmdl_c': 'Reinforced Item Crate',
}


def curated_prop(path):
    for group, assets in [('objectives', OBJECTIVES), ('shops', SHOPS), ('pickups', PICKUPS), ('breakables', BREAKABLES)]:
        if path in assets:
            return {'name': assets[path], 'prop_group': group, 'important_prop': True}
    
    for folder in ('models/props_gameplay/powerup_tomes/', 'models/props_gameplay/powerup_idol/'):
        if path.startswith(folder) and '/' not in path[len(folder):]:
            name = path[len(folder):-7].removeprefix('powerup_').replace('_', ' ').title()
            return {'name': name, 'prop_group': 'pickups', 'important_prop': True}
    return {'important_prop': False, 'prop_group': None}
