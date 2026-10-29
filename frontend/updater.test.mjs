import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const source = readFileSync(new URL('app.js', import.meta.url), 'utf8').split('let updateInstalling = false;')[1];
function harness() {
    const elements = new Map();
    const $ = id => { if (!elements.has(id))
        elements.set(id, { open: false, disabled: false, textContent: '', showModal() { this.open = true; this.shows = (this.shows || 0) + 1; }, close() { this.open = false; }, addEventListener() { } }); return elements.get(id); };
    const calls = [];
    const context = vm.createContext({ $, busy: false, setTimeout() { }, setInterval() { }, window: { __TAURI__: { core: { async invoke(name) { calls.push(name); if (name === 'check_update')
                        return { available: true, version: '99.0.0', current: '0.10.13' }; throw 'test download failure'; } } } } });
    vm.runInContext('let updateInstalling = false;' + source, context);
    return { $, context, calls };
}
test('Startup check opens a popup once, and installing calls the updater without another confirmation', async () => {
    const { $, context, calls } = harness();
    await vm.runInContext('checkUpdates()', context);
    assert.equal($('updateDialog').open, true);
    $('updateLater').onclick();
    vm.runInContext('showUpdatePrompt()', context);
    assert.equal($('updateDialog').open, false);
    $('updateApp').onclick();
    assert.equal($('updateDialog').open, true);
    await $('updateInstall').onclick();
    assert(calls.includes('install_update'));
    assert.match($('updateProgress').textContent, /test download failure/);
    assert.equal($('updateInstall').disabled, false);
});
test('An update popup waits until an export finishes', async () => {
    const { $, context } = harness();
    context.busy = true;
    await vm.runInContext('checkUpdates()', context);
    assert.equal($('updateDialog').open, false);
    context.busy = false;
    vm.runInContext('showUpdatePrompt()', context);
    assert.equal($('updateDialog').open, true);
});
