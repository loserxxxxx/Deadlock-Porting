import test from 'node:test';
import assert from 'node:assert/strict';
import { filterModels, pageModels, mergePreview } from './library.mjs';
const items = [
    { name: 'Haze', model: 'models/heroes_staging/haze/haze.vmdl_c', category: 'heroes', roster: true },
    { name: 'Variant', model: 'models/heroes_wip/haze/haze.vmdl_c', category: 'heroes', roster: false },
    { name: 'Test', model: 'models/heroes_wip/test/test.vmdl_c', category: 'heroes', roster: true, development: true },
    { name: 'Shelf', model: 'models/props/shelf.vmdl_c', category: 'props' },
    { name: 'Boss', model: 'models/npc/boss.vmdl_c', category: 'npcs', important_prop: true, prop_group: 'objectives' },
    { name: 'Urn', model: 'models/props_gameplay/idol_urn/idol_urn.vmdl_c', category: 'props', important_prop: true, prop_group: 'objectives' },
    { name: 'Pickup', model: 'models/props_gameplay/powerup/powerup.vmdl_c', category: 'props', important_prop: true, prop_group: 'pickups' },
    { name: 'Building', model: 'models/architecture/building.vmdl_c', category: 'map' }
];
test('late cache replies cannot erase queued, rendering, or ready previews', () => {
    assert.equal(mergePreview({ status: 'queued' }, { status: 'missing' }).status, 'queued');
    assert.equal(mergePreview({ status: 'rendering' }, { status: 'queued' }).status, 'rendering');
    assert.equal(mergePreview({ status: 'ready', image: 'png' }, { status: 'missing' }).image, 'png');
    assert.equal(mergePreview({ status: 'error' }, { status: 'queued' }).status, 'queued');
});
test('all models includes variants, development assets and every category', () => {
    assert.equal(filterModels(items, 'all', '', true).length, items.length);
    assert.deepEqual(filterModels(items, 'heroes', '', true).map(x => x.name), ['Haze']);
    assert.equal(filterModels(items, 'heroes', '', false).length, 2);
});
test('tabs and path search distinguish asset types and folders', () => {
    assert.equal(filterModels(items, 'props', 'urn', false)[0].name, 'Urn');
    assert.equal(filterModels(items, 'npcs', 'boss', false)[0].name, 'Boss');
    assert.equal(filterModels(items, 'map', 'architecture', false)[0].name, 'Building');
    assert.equal(filterModels(items, 'all', 'heroes_wip haze', false)[0].name, 'Variant');
});
test('Props is curated, includes NPC-folder objectives, and hides clutter', () => {
    assert.deepEqual(filterModels(items, 'props', '', false).map(x => x.name), ['Boss', 'Urn', 'Pickup']);
    assert.equal(filterModels(items, 'props', 'shelf', false).length, 0);
    assert.equal(filterModels(items, 'all', 'shelf', false).length, 1);
    assert.deepEqual(filterModels(items, 'props', '', false, 'pickups').map(x => x.name), ['Pickup']);
});
test('pagination clamps stale pages after filters reduce result count', () => {
    const list = Array.from({ length: 121 }, (_, n) => n);
    assert.deepEqual(pageModels(list, 2).items, [120]);
    assert.equal(pageModels(items, 99).page, 0);
    assert.deepEqual(pageModels([], 99), { page: 0, pages: 1, items: [] });
});
