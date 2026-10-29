import unittest
from rig_policy import character_asset


class RigPolicyTests(unittest.TestCase):
    def test_characters_keep_rigs(self):
        for path in ['models/heroes_staging/haze/haze.vmdl_c',
                     'models/npc_units/troopers/amber_trooper_01/amber_trooper_01.vmdl_c',
                     'models/npc/trooper/trooper_humanoid.vmdl_c']:
            self.assertTrue(character_asset(path), path)

    def test_objectives_and_props_never_get_rigs(self):
        for path in ['models/props_gameplay/idol_urn/idol_urn.vmdl_c',
                     'models/npc/boss_tier_02_sun_walker_v2/boss_tier_02_sun_walker.vmdl_c',
                     'models/npc/patron_amber/patron_amber.vmdl_c',
                     'models/heroes_staging/haze/haze_gun_l.vmdl_c',
                     'models/props/bottle_d.vmdl_c']:
            self.assertFalse(character_asset(path), path)


if __name__ == '__main__':
    unittest.main()
