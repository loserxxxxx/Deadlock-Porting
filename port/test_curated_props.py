import unittest
from curated_props import curated_prop


class CuratedPropsTests(unittest.TestCase):
    def test_objectives_and_pickups_are_included(self):
        for path in ['models/props_gameplay/idol_urn/idol_urn.vmdl_c',
                     'models/npc/patron_amber/patron_amber.vmdl_c',
                     'models/props_gameplay/sinners_sacrifice_vault/sinners_sacrifice.vmdl_c',
                     'models/props_gameplay/powerup_tomes/powerup_health_tome.vmdl_c']:
            self.assertTrue(curated_prop(path)['important_prop'], path)

    def test_fragments_building_clutter_and_effects_are_excluded(self):
        for path in ['models/props/bottle_d.vmdl_c', 'models/props_endgame/wood_plank.vmdl_c',
                     'models/props_gameplay/wooden_crate_02/wooden_crate_02/piece12.vmdl_c',
                     'models/props_gameplay/powerup_tomes/powerup_health_tome/piece1.vmdl_c',
                     'models/particle/generic_swirl.vmdl_c']:
            self.assertFalse(curated_prop(path)['important_prop'], path)

    def test_whole_breakable_is_kept_without_its_debris(self):
        self.assertEqual(curated_prop('models/props_gameplay/wooden_crate_02/wooden_crate_02.vmdl_c')['prop_group'], 'breakables')

    def test_complete_walker_variants_are_objectives(self):
        for path in ['models/npc/boss_tier_02/boss_tier2_new_model.vmdl_c',
                     'models/npc/boss_tier_02_sun_walker/boss_tier_02_sun_walker.vmdl_c',
                     'models/npc/boss_tier_02_sun_walker_v2/boss_tier_02_sun_walker.vmdl_c',
                     'models/npc/t2_clock_tower/t2_clock_tower_shape.vmdl_c']:
            self.assertEqual(curated_prop(path)['prop_group'], 'objectives', path)


if __name__ == '__main__':
    unittest.main()
