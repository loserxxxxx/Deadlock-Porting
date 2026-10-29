import { filterModels, pageModels, mergePreview } from './library.mjs';
const $ = id => document.getElementById(id);
const categories = {
    heroes: { name: 'Heroes', symbol: '♟', title: 'Choose your hero.', description: 'Characters, their materials, and rigs ready to pose.' },
    props: { name: 'Props', symbol: '◇', title: 'The gameplay essentials.', description: 'Objectives, shops, pickups, and intact breakables. Complete assets without construction clutter or debris.' },
    npcs: { name: 'NPCs', symbol: '♙', title: 'Meet the rest of the cast.', description: 'NPCs, creatures, bosses, and units. Source skeletons are preserved when available.' },
    map: { name: 'Map Parts', symbol: '▥', title: 'Build your world.', description: 'Architecture, streets, foliage, and environment pieces. Exports individual models.' },
    all: { name: 'All Models', symbol: '▧', title: 'The entire model library.', description: 'Every model file in the installed game archive, including variants and development assets.' },
    other: { name: 'Other', symbol: '▧' }
};
let items = [], counts = {}, selected = null, busy = false, cfg = {}, category = 'heroes', page = 0;
let info = null, polling = false;
const portraitCache = new Map();
const previewCache = new Map();
const previewJobs = new Set();
let visibleModels = [], previewPolling = false, startupModels = [];
let blenderProjects = [], scanningProjects = false;
let liveSessions = [], scanningLive = false, addonInstalling = false;
async function api(operation, data = null) {
    return window.__TAURI__.core.invoke('backend', { operation, data });
}
async function windowAction(action) {
    try {
        await window.__TAURI__.core.invoke('window_action', { action });
    }
    catch (error) {
        $('status').textContent = `Window control unavailable: ${error}`;
    }
}
for (const button of document.querySelectorAll('[data-window-action]')) {
    button.onclick = () => windowAction(button.dataset.windowAction);
}
function headerBackground(event) {
    return !event.target.closest('button, input, select, a, nav');
}
$('windowHeader').onmousedown = event => {
    if (event.button === 0 && event.detail < 2 && headerBackground(event))
        windowAction('drag');
};
$('windowHeader').ondblclick = event => {
    if (event.button === 0 && headerBackground(event))
        windowAction('maximize');
};
function image(item) {
    if (!item.roster || !item.portrait) {
        const cached = previewCache.get(item.model);
        if (cached?.status === 'ready')
            return previewImage(item, cached.image);
        const placeholder = document.createElement('div');
        placeholder.className = 'asset-symbol';
        placeholder.dataset.previewModel = item.model;
        placeholder.textContent = categories[item.category]?.symbol || '▧';
        const label = document.createElement('small');
        label.textContent = categories[item.category]?.name || 'MODEL';
        placeholder.append(label);
        return placeholder;
    }
    const img = document.createElement('img');
    img.alt = item.name;
    img.onload = () => img.classList.add('image-ready');
    img.loading = 'lazy';
    img.onerror = () => {
        const fallback = document.createElement('div');
        fallback.className = 'initial';
        fallback.textContent = item.name.slice(0, 2).toUpperCase();
        img.replaceWith(fallback);
    };
    if (!portraitCache.has(item.id))
        portraitCache.set(item.id, api('portrait', { key: item.id }));
    portraitCache.get(item.id).then(url => {
        if (!img.classList.contains('asset-thumbnail'))
            img.src = url;
    }).catch(() => { if (!img.classList.contains('asset-thumbnail'))
        img.onerror(); });
    return img;
}
function previewImage(item, url) {
    const img = document.createElement('img');
    img.alt = item.name;
    img.className = 'asset-thumbnail';
    img.onload = () => img.classList.add('image-ready');
    img.dataset.previewModel = item.model;
    img.src = url;
    return img;
}
function previewStatus() {
    const ready = startupModels.filter(model => previewCache.get(model)?.status === 'ready').length;
    const failed = startupModels.filter(model => previewCache.get(model)?.status === 'error').length;
    $('startupPreviewStatus').textContent = !startupModels.length ? ''
        : ready === startupModels.length ? 'Gameplay previews ready'
            : `Startup previews: ${ready}/${startupModels.length} ready${failed ? ` · ${failed} unavailable` : ''}`;
    const hasPortrait = selected?.roster && selected?.portrait;
    const current = selected && previewCache.get(selected.model);
    $('previewAction').hidden = !selected || !info?.exportable || current?.status === 'ready';
    $('previewAction').disabled = !!current && ['queued', 'rendering'].includes(current.status);
    $('previewAction').textContent = current?.status === 'error' ? 'Retry preview' : 'Render preview';
    $('previewStatus').textContent = !selected ? '' : current?.status === 'ready' ? 'Model preview · cached locally'
        : current?.status === 'queued' ? 'Preview queued…'
            : current?.status === 'rendering' ? 'Rendering model preview…'
                : current?.status === 'error' ? current.error : hasPortrait ? 'Hero portrait' : '';
    const pendingOnPage = visibleModels.filter(model => previewJobs.has(model)).length;
    $('pagePreviews').disabled = !visibleModels.length || pendingOnPage > 0;
    $('pagePreviews').textContent = pendingOnPage ? `Rendering previews · ${pendingOnPage} left` : 'Generate page previews';
}
function applyPreviews(results) {
    for (const incoming of results) {
        const result = mergePreview(previewCache.get(incoming.model), incoming);
        previewCache.set(result.model, result);
        if (['queued', 'rendering'].includes(result.status))
            previewJobs.add(result.model);
        else
            previewJobs.delete(result.model);
        if (result.status === 'ready') {
            const item = items.find(item => item.model === result.model);
            if (item)
                for (const node of document.querySelectorAll('[data-preview-model]')) {
                    if (node.dataset.previewModel === result.model) {
                        if (node.tagName === 'IMG') {
                            if (node.src !== result.image) {
                                node.classList.remove('image-ready');
                                node.src = result.image;
                            }
                            node.classList.add('asset-thumbnail');
                        }
                        else
                            node.replaceWith(previewImage(item, result.image));
                    }
                }
        }
    }
    previewStatus();
}
async function requestPreviews(models, generate = false, retry = false, priority = false) {
    if (!models.length)
        return;
    try {
        applyPreviews(await api('previews', { models, generate, retry, priority }));
    }
    catch (error) {
        $('previewStatus').textContent = String(error);
    }
}
function renderTabs() {
    if (!$('tabs').children.length)
        for (const key of ['heroes', 'props', 'npcs', 'map', 'all']) {
            const button = document.createElement('button');
            button.className = 'tab';
            button.dataset.category = key;
            button.setAttribute('aria-selected', String(category === key));
            button.textContent = categories[key].name;
            const count = document.createElement('small');
            count.textContent = (counts[key] || 0).toLocaleString();
            button.append(count);
            button.onclick = () => {
                category = key;
                page = 0;
                $('search').value = '';
                selected = null;
                info = null;
                $('heroName').textContent = 'Select a model';
                $('model').textContent = 'Choose a model from this category.';
                $('modelDetails').textContent = '';
                $('modelDetails').classList.remove('ready');
                $('preview').replaceChildren();
                $('export').disabled = true;
                formatNote();
                renderTabs();
                render();
                previewStatus();
            };
            $('tabs').append(button);
        }
    for (const button of $('tabs').children) {
        button.setAttribute('aria-selected', String(button.dataset.category === category));
    }
    positionTabIndicator();
    $('libraryTitle').textContent = categories[category].title;
    $('libraryDescription').textContent = categories[category].description;
    $('filter').hidden = category !== 'heroes';
    $('propsFilter').hidden = category !== 'props';
}
function positionTabIndicator() {
    const active = $('tabs').querySelector('[aria-selected="true"]');
    if (!active)
        return;
    $('tabs').style.setProperty('--pill-x', `${active.offsetLeft}px`);
    $('tabs').style.setProperty('--pill-width', `${active.offsetWidth}px`);
}
window.addEventListener('resize', positionTabIndicator);
function revealPanel(element) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !element.animate)
        return;
    element.getAnimations?.().forEach(animation => {
        animation.finished.catch(() => { });
        animation.cancel();
    });
    const animation = element.animate([{ opacity: 0, transform: 'translateY(-5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 220, easing: 'cubic-bezier(.2,.75,.25,1)' });
    animation.finished.catch(() => { });
}
function render() {
    const matches = filterModels(items, category, $('search').value, $('filter').value === 'release', $('propsFilter').value);
    const result = pageModels(matches, page);
    page = result.page;
    $('count').textContent = `${matches.length.toLocaleString()} MODELS · LOCAL GAME LIBRARY`;
    $('grid').replaceChildren();
    for (const [index, item] of result.items.entries()) {
        const card = document.createElement('button');
        card.className = 'card is-entering' + (selected?.model === item.model ? ' selected' : '');
        card.dataset.model = item.model;
        card.style.setProperty('--enter-delay', `${Math.min(index, 11) * 16}ms`);
        card.title = item.model;
        card.setAttribute('aria-pressed', String(selected?.model === item.model));
        card.append(image(item));
        const name = document.createElement('span');
        name.textContent = item.name;
        const path = document.createElement('small');
        path.className = 'asset-path';
        path.textContent = item.model.split('/').slice(1, -1).join('/');
        card.append(name, path);
        card.onclick = () => choose(item);
        $('grid').append(card);
    }
    $('empty').hidden = matches.length > 0;
    $('empty').textContent = 'No models match your search.';
    $('pagination').hidden = result.pages <= 1;
    $('previous').disabled = page === 0;
    $('next').disabled = page === result.pages - 1;
    $('pageLabel').textContent = `Page ${page + 1} of ${result.pages}`;
    visibleModels = result.items.filter(item => !item.roster || !item.portrait).map(item => item.model);
    previewStatus();
    requestPreviews(visibleModels.filter(model => !previewCache.has(model) || previewCache.get(model).status === 'missing'), true);
}
function formatNote() {
    const glb = $('format').value === 'glb';
    $('controls').disabled = glb || !info?.controls;
    $('formatNote').textContent = !info ? 'Reading model details…' : !info.skinned
        ? 'Exports as a regular model with meshes and color textures, without an armature.'
        : glb ? 'Includes the source skeleton, skin weights, and color textures.'
            : info.controls ? 'Supports character controls. Includes source skin weights and packed textures.'
                : 'Preserves the source skeleton for posing. This model does not use the hero control rig.';
}
function exportLabel() {
    if (busy)
        return 'Exporting…';
    if ($('destinationMode').value === 'live')
        return 'Send to open Blender ↗';
    if ($('destinationMode').value === 'project')
        return 'Add to Blender project ↗';
    return $('openBlender').checked ? 'Export to Blender ↗' : 'Export model ↗';
}
$('filterToggle').onclick = () => {
    $('libraryFilters').hidden = !$('libraryFilters').hidden;
    if (!$('libraryFilters').hidden)
        revealPanel($('libraryFilters'));
    $('filterToggle').setAttribute('aria-expanded', String(!$('libraryFilters').hidden));
};
for (const button of document.querySelectorAll('[data-destination]')) {
    button.onclick = () => {
        $('destinationMode').value = button.dataset.destination;
        $('destinationMode').dispatchEvent(new Event('change'));
    };
}
$('outputSettings').onclick = () => $('settings').click();
$('destinationMode').onchange = () => {
    const existing = $('destinationMode').value === 'project';
    const live = $('destinationMode').value === 'live';
    for (const button of document.querySelectorAll('[data-destination]')) {
        button.setAttribute('aria-pressed', String(button.dataset.destination === $('destinationMode').value));
    }
    $('existingProject').hidden = !existing;
    $('liveBlender').hidden = !live;
    $('openBlender').disabled = live;
    if (live) {
        revealPanel($('liveBlender'));
        refreshLiveBlender();
    }
    if (existing)
        revealPanel($('existingProject'));
    $('format').disabled = existing || live;
    if (existing || live)
        $('format').value = 'blend';
    formatNote();
    $('export').textContent = exportLabel();
    if (existing)
        refreshBlenderProjects();
};
async function refreshLiveBlender() {
    if (scanningLive || busy || addonInstalling)
        return;
    scanningLive = true;
    $('refreshLiveBlender').disabled = true;
    const previous = $('liveBlenderSessions').value;
    try {
        liveSessions = await api('live_blender_sessions');
        const select = $('liveBlenderSessions');
        select.replaceChildren();
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = liveSessions.length ? 'Choose an open scene' : 'Enable the Blender add-on to connect';
        select.append(placeholder);
        for (const session of liveSessions) {
            const option = document.createElement('option');
            option.value = session.id;
            option.textContent = `${session.name} / ${session.scene} / Blender ${session.version}`;
            select.append(option);
        }
        if (liveSessions.some(session => session.id === previous))
            select.value = previous;
        else if (liveSessions.length === 1)
            select.value = liveSessions[0].id;
        liveSessionStatus();
    }
    catch (error) {
        $('liveBlenderStatus').textContent = String(error);
    }
    finally {
        scanningLive = false;
        $('refreshLiveBlender').disabled = false;
    }
}
function liveSessionStatus() {
    const session = liveSessions.find(session => session.id === $('liveBlenderSessions').value);
    $('liveBlenderStatus').textContent = session ? `${session.status}. Blender stays open; unsaved work is preserved.`
        : 'Enable Deadlock Porting Live in Blender, then refresh.';
}
$('liveBlenderSessions').onchange = liveSessionStatus;
$('refreshLiveBlender').onclick = refreshLiveBlender;
$('installBlenderAddon').onclick = async () => {
    if (addonInstalling || busy || updateInstalling)
        return;
    addonInstalling = true;
    $('installBlenderAddon').disabled = true;
    $('export').disabled = true;
    $('addonInstallStatus').hidden = false;
    $('addonInstallStatus').textContent = 'Installing the bundled add-on for Blender...';
    try {
        const result = await api('install_blender_addon', { session_id: $('liveBlenderSessions').value || null });
        $('addonInstallStatus').textContent = result.connected ? 'The Blender add-on is already connected.'
            : result.needs_enable ? 'Installed. In the open Blender, go to Preferences > Add-ons, Refresh Local, search Deadlock Porting Live, and enable it once. No restart needed.'
                : `Installed and enabled for Blender ${result.blender_version}. Open Blender to connect.`;
    }
    catch (error) {
        $('addonInstallStatus').textContent = `Installation failed: ${error}`;
    }
    finally {
        addonInstalling = false;
        $('installBlenderAddon').disabled = false;
        $('export').disabled = busy || updateInstalling || !selected || !info?.exportable;
        refreshLiveBlender();
    }
};
$('saveBlenderAddon').onclick = async () => {
    try {
        const path = await window.__TAURI__.core.invoke('save_blender_addon');
        if (path) {
            $('addonInstallStatus').hidden = false;
            $('addonInstallStatus').textContent = 'ZIP saved. In Blender Preferences > Add-ons, choose Install from Disk and enable Deadlock Porting Live.';
        }
    }
    catch (error) {
        $('liveBlenderStatus').textContent = String(error);
    }
};
setInterval(() => {
    if ($('destinationMode').value === 'live' && document.activeElement !== $('liveBlenderSessions'))
        refreshLiveBlender();
}, 3000);
async function refreshBlenderProjects() {
    if (scanningProjects)
        return;
    scanningProjects = true;
    $('refreshBlenderProjects').disabled = true;
    const previous = $('openedBlenderProjects').value;
    try {
        blenderProjects = await api('blender_projects');
        const select = $('openedBlenderProjects');
        select.replaceChildren();
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = blenderProjects.length ? 'Choose an open Blender project…' : 'No open Blender projects detected';
        select.append(placeholder);
        for (const session of blenderProjects) {
            const option = document.createElement('option');
            option.value = String(session.pid);
            option.textContent = `${session.name}${session.modified ? ' · unsaved changes' : ''}${!session.saved ? ' · save first' : ''} · PID ${session.pid}`;
            option.disabled = !session.saved;
            option.title = session.project_path || session.title;
            select.append(option);
        }
        if (blenderProjects.some(session => String(session.pid) === previous && session.saved)) {
            select.value = previous;
            const current = blenderProjects.find(session => String(session.pid) === previous);
            $('projectPath').value = current.project_path;
        }
        else if (!$('projectPath').value.trim()) {
            const saved = blenderProjects.filter(session => session.saved);
            if (saved.length === 1) {
                select.value = String(saved[0].pid);
                $('projectPath').value = saved[0].project_path;
            }
        }
        $('openedProjectStatus').textContent = blenderProjects.length
            ? `Found ${blenderProjects.length} Blender session(s). Choose a saved project, then save and close it before adding models.`
            : 'You can also browse to a closed .blend project below.';
    }
    catch (error) {
        $('openedProjectStatus').textContent = `Could not detect Blender sessions: ${error}`;
    }
    finally {
        scanningProjects = false;
        $('refreshBlenderProjects').disabled = false;
    }
}
$('refreshBlenderProjects').onclick = refreshBlenderProjects;
$('openedBlenderProjects').onchange = () => {
    const session = blenderProjects.find(session => String(session.pid) === $('openedBlenderProjects').value);
    if (session?.saved) {
        $('projectPath').value = session.project_path;
        $('openedProjectStatus').textContent = `Selected ${session.name}. Save and close it in Blender before exporting.`;
    }
};
$('projectPath').oninput = () => { $('openedBlenderProjects').value = ''; };
setInterval(() => {
    if ($('destinationMode').value === 'project' && document.activeElement !== $('openedBlenderProjects'))
        refreshBlenderProjects();
}, 5000);
$('browseProject').onclick = async () => {
    try {
        const path = await window.__TAURI__.core.invoke('choose_blender_project');
        if (path) {
            $('projectPath').value = path;
            $('openedBlenderProjects').value = '';
        }
    }
    catch (error) {
        $('status').textContent = String(error);
    }
};
async function choose(item) {
    selected = item;
    info = null;
    $('heroName').textContent = item.name;
    $('model').textContent = item.model;
    $('modelDetails').textContent = 'Reading model…';
    $('modelDetails').classList.remove('ready');
    const cachedPreview = previewCache.get(item.model);
    const preview = cachedPreview?.status === 'ready' ? previewImage(item, cachedPreview.image) : image(item);
    preview.dataset.previewModel = item.model;
    $('preview').replaceChildren(preview);
    $('export').disabled = true;
    formatNote();
    for (const card of $('grid').children) {
        const active = card.dataset.model === item.model;
        card.classList.toggle('selected', active);
        card.setAttribute('aria-pressed', String(active));
    }
    revealPanel(document.querySelector('.asset-heading'));
    try {
        const details = await api('model_info', { model: item.model });
        if (selected?.model !== item.model)
            return;
        info = details;
        $('modelDetails').textContent = !details.exportable ? 'This asset contains no render geometry.'
            : details.skinned ? `Character · ${details.bones} bones · Ready to export` : 'Static model · Ready to export';
        $('modelDetails').classList.toggle('ready', details.exportable);
        formatNote();
        $('export').disabled = busy || addonInstalling || !info.exportable;
        previewStatus();
        if (info.exportable)
            requestPreviews([item.model], true, false, true);
    }
    catch (error) {
        if (selected?.model === item.model) {
            $('modelDetails').textContent = String(error);
            $('export').disabled = true;
        }
    }
}
async function load() {
    try {
        const library = await api('models');
        items = library.items;
        counts = library.counts;
        startupModels = items.filter(item => item.important_prop && (!item.roster || !item.portrait)).map(item => item.model);
        renderTabs();
        render();
        for (let start = 0; start < startupModels.length; start += 60) {
            requestPreviews(startupModels.slice(start, start + 60), true);
        }
        if (!selected && items.length)
            await choose(items.find(item => item.roster && item.name === 'Haze') || items[0]);
    }
    catch (error) {
        $('count').textContent = 'LIBRARY UNAVAILABLE';
        $('empty').hidden = false;
        $('empty').textContent = `${error} — check your game and helper paths in Settings.`;
    }
}
$('search').oninput = () => { page = 0; render(); };
$('filter').onchange = () => { page = 0; render(); };
$('propsFilter').onchange = () => { page = 0; render(); };
$('previous').onclick = () => { page--; render(); };
$('next').onclick = () => { page++; render(); };
$('format').onchange = formatNote;
$('pagePreviews').onclick = () => requestPreviews(visibleModels, true, true);
$('previewAction').onclick = () => selected && requestPreviews([selected.model], true, true, true);
setInterval(async () => {
    const watch = [...new Set([...previewJobs, ...visibleModels.filter(model => ['queued', 'rendering', 'missing'].includes(previewCache.get(model)?.status))])];
    if (previewPolling || !watch.length)
        return;
    previewPolling = true;
    try {
        await requestPreviews(watch.slice(0, 60));
    }
    finally {
        previewPolling = false;
    }
}, 1200);
$('export').onclick = async () => {
    if (!selected || !info?.exportable || busy || updateInstalling || addonInstalling)
        return;
    if ($('destinationMode').value === 'project' && !$('projectPath').value.trim()) {
        $('status').textContent = 'Choose an existing Blender project first.';
        $('status').classList.add('error');
        return;
    }
    const live = $('destinationMode').value === 'live' ? liveSessions.find(session => session.id === $('liveBlenderSessions').value) : null;
    if ($('destinationMode').value === 'live' && !live) {
        $('status').textContent = 'Choose a connected Blender scene first.';
        return;
    }
    busy = true;
    $('export').classList.add('is-exporting');
    $('export').disabled = true;
    try {
        await api('export', { model: selected.model, format: $('format').value,
            controls: !$('controls').disabled && $('controls').checked, open_blender: $('openBlender').checked,
            destination_mode: $('destinationMode').value, project_path: $('projectPath').value.trim(),
            blender_session: live?.id, blender_scene: live?.scene_id });
        $('status').textContent = 'Preparing export…';
    }
    catch (error) {
        busy = false;
        $('export').classList.remove('is-exporting');
        $('status').textContent = String(error);
        $('status').classList.add('error');
    }
};
setInterval(async () => {
    if (polling)
        return;
    polling = true;
    try {
        const state = await api('state');
        busy = state.busy;
        $('export').classList.toggle('is-exporting', busy);
        $('export').disabled = updateInstalling || addonInstalling || busy || !selected || !info?.exportable;
        $('export').textContent = exportLabel();
        $('status').textContent = state.error || state.status;
        $('status').classList.toggle('error', !!state.error);
        $('log').textContent = state.log || 'No exports yet.';
    }
    catch (error) {
        $('status').textContent = `Worker unavailable: ${error}`;
        $('export').disabled = true;
    }
    finally {
        polling = false;
    }
}, 1000);
const labels = { vpk: 'Deadlock game archive · pak01_dir.vpk', output: 'Output folder', blender: 'Blender executable · blender.exe' };
$('scanInstallations').onclick = async () => {
    $('scanInstallations').disabled = true;
    $('scanResult').textContent = 'Checking Steam libraries and Blender installations…';
    try {
        const found = await api('scan_installations');
        $('detectedGames').replaceChildren();
        for (const game of found.deadlock) {
            const option = document.createElement('option');
            option.value = game.path;
            option.textContent = game.directory;
            $('detectedGames').append(option);
        }
        $('detectedGames').hidden = !found.deadlock.length;
        if (found.deadlock.length)
            $('field-vpk').value = found.deadlock[0].path;
        if (found.blender.length)
            $('field-blender').value = found.blender[0];
        $('scanResult').textContent = found.deadlock.length
            ? `Found ${found.deadlock.length} Deadlock installation(s)${found.blender.length ? ' and Blender' : ''}. Save settings to use the selected paths.`
            : 'No Deadlock installation found. Enter the archive path below; custom paths are supported.';
    }
    catch (error) {
        $('scanResult').textContent = String(error);
    }
    finally {
        $('scanInstallations').disabled = false;
    }
};
$('detectedGames').onchange = () => { $('field-vpk').value = $('detectedGames').value; };
$('settings').onclick = async () => {
    try {
        cfg = await api('settings');
        $('fields').replaceChildren();
        for (const [key, text] of Object.entries(labels)) {
            const label = document.createElement('label');
            label.textContent = text;
            label.htmlFor = 'field-' + key;
            const input = document.createElement('input');
            input.id = 'field-' + key;
            input.value = cfg[key];
            $('fields').append(label, input);
        }
        $('settingsError').textContent = '';
        $('scanResult').textContent = 'Steam libraries are detected automatically. Rescan if the game was moved or installed recently.';
        $('dialog').showModal();
    }
    catch (error) {
        $('status').textContent = String(error);
    }
};
$('close').onclick = () => $('dialog').close();
$('save').onclick = async () => {
    try {
        for (const key of Object.keys(labels))
            cfg[key] = $('field-' + key).value;
        await api('save_settings', cfg);
        portraitCache.clear();
        previewCache.clear();
        previewJobs.clear();
        $('output').textContent = cfg.output;
        $('dialog').close();
        selected = null;
        info = null;
        page = 0;
        await load();
    }
    catch (error) {
        $('settingsError').textContent = String(error);
    }
};
api('settings').then(config => { $('output').textContent = config.output; }).catch(error => { $('status').textContent = String(error); });
renderTabs();
load();
let lastPresence = '';
function syncPresence() {
    const payload = { model: selected?.name || '', category, exporting: busy };
    const key = JSON.stringify(payload);
    if (key === lastPresence)
        return;
    lastPresence = key;
    window.__TAURI__.core.invoke('update_presence', payload).catch(() => { lastPresence = ''; });
}
syncPresence();
setInterval(syncPresence, 1000);
let updateInstalling = false;
let availableUpdate = null;
let promptedUpdate = '';
let checkingUpdate = false;
function showUpdatePrompt(force = false) {
    if (!availableUpdate || busy || updateInstalling || $('updateDialog').open)
        return;
    if (!force && (promptedUpdate === availableUpdate.version || $('dialog').open))
        return;
    promptedUpdate = availableUpdate.version;
    $('updateMessage').textContent = `Deadlock Porting ${availableUpdate.version} is ready to install.`;
    $('updateProgress').textContent = 'The app will download the update and restart automatically.';
    $('updateDialog').showModal();
}
async function checkUpdates(manual = false) {
    if (updateInstalling || checkingUpdate)
        return;
    checkingUpdate = true;
    $('checkUpdates').disabled = true;
    if (manual)
        $('updateStatus').textContent = 'Checking for updates...';
    try {
        const update = await window.__TAURI__.core.invoke('check_update');
        availableUpdate = update.available ? update : null;
        $('updateApp').hidden = !update.available;
        $('updateApp').textContent = `Update to ${update.version}`;
        $('updateStatus').textContent = update.available ? `Version ${update.version} is available.` : `You're up to date (${update.current}).`;
        if (manual && update.available)
            $('dialog').close();
        showUpdatePrompt(manual);
    }
    catch (error) {
        if (manual)
            $('updateStatus').textContent = `Could not check for updates: ${error}`;
    }
    finally {
        checkingUpdate = false;
        $('checkUpdates').disabled = false;
    }
}
$('checkUpdates').onclick = () => checkUpdates(true);
$('updateApp').onclick = () => showUpdatePrompt(true);
$('updateLater').onclick = () => $('updateDialog').close();
$('updateDialog').addEventListener('cancel', event => {
    if (updateInstalling)
        event.preventDefault();
});
$('updateInstall').onclick = async () => {
    if (busy || updateInstalling)
        return;
    updateInstalling = true;
    $('export').disabled = true;
    $('updateApp').disabled = true;
    $('updateInstall').disabled = true;
    $('updateLater').disabled = true;
    $('updateInstall').textContent = 'Installing...';
    $('updateApp').textContent = 'Downloading update...';
    $('updateProgress').textContent = 'Downloading and verifying the update. The app will restart when ready.';
    try {
        await window.__TAURI__.core.invoke('install_update');
    }
    catch (error) {
        updateInstalling = false;
        $('updateApp').disabled = false;
        $('updateInstall').disabled = false;
        $('updateLater').disabled = false;
        $('updateInstall').textContent = 'Retry update';
        $('updateApp').textContent = 'Retry update';
        $('updateProgress').textContent = `Update failed: ${error}`;
        $('updateStatus').textContent = String(error);
        $('status').textContent = `Update failed: ${error}`;
    }
};
setTimeout(() => checkUpdates(), 3000);
setInterval(showUpdatePrompt, 1500);
setInterval(() => checkUpdates(), 4 * 60 * 60 * 1000);
