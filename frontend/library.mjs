export function filterModels(items, category, query, releasedOnly, propGroup = 'all') {
    const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return items.filter(item => (category === 'all' || (category === 'heroes' ? item.roster : category === 'props' ? item.important_prop : item.category === category)) &&
        !(category === 'props' && propGroup !== 'all' && item.prop_group !== propGroup) &&
        !(category === 'heroes' && releasedOnly && item.development) &&
        words.every(word => `${item.name} ${item.model}`.toLowerCase().includes(word))).sort((a, b) => category === 'props'
        ? (['objectives', 'shops', 'pickups', 'breakables'].indexOf(a.prop_group) - ['objectives', 'shops', 'pickups', 'breakables'].indexOf(b.prop_group) || a.name.localeCompare(b.name)) : 0);
}
export function pageModels(items, requestedPage, size = 60) {
    const pages = Math.max(1, Math.ceil(items.length / size));
    const page = Math.max(0, Math.min(requestedPage, pages - 1));
    return { page, pages, items: items.slice(page * size, (page + 1) * size) };
}
export function mergePreview(previous, incoming) {
    if (!previous)
        return incoming;
    if (previous.status === 'ready' && incoming.status !== 'ready')
        return previous;
    if (incoming.status === 'missing' && previous.status !== 'missing')
        return previous;
    if (previous.status === 'rendering' && incoming.status === 'queued')
        return previous;
    return incoming;
}
