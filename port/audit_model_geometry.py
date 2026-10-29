"""Audit real archive geometry without writing thousands of exported assets."""
import argparse
import json
import random
from pathlib import Path
import deadlock_port as d

parser = argparse.ArgumentParser()
parser.add_argument('--all', action='store_true')
parser.add_argument('--sample', type=int, default=150)
parser.add_argument('--report', type=Path, default=Path(__file__).parent / 'out/gui-validation/model-audit.json')
args = parser.parse_args()
pak = d.Pak(d.GAME)
models = sorted(n for n in pak.entries if n.endswith('.vmdl_c'))
if not args.all:
    models = random.Random(91).sample(models, min(args.sample, len(models)))
failures = []
passed = 0
for index, path in enumerate(models):
    try:
        raw = pak.read(path)
        blocks = d.resource_blocks(raw)
        data = d.KV3File(d.unwrap(d.data_block(raw))).read()
        ctrl = next((d.KV3File(raw[o:o+s]).read() for t, o, s in blocks if t == b'CTRL'), {})
        skeleton = d.skeleton(data)
        bones = {n: i for i, n in enumerate(skeleton[0])} if skeleton else {}
        render_draws = 0
        for mesh in d.render_meshes(data, d.embedded_meshes(raw, blocks, ctrl)):
            for md, vb, ib, draws in d.mesh_buffers(raw, blocks, mesh):
                if not vb['m_nElementCount']:
                    continue
                vertices = d.vertex_buffer(d.block(raw, blocks, vb['m_nBlockIndex']), vb)
                meshbones = md.get('m_skeleton', {}).get('m_bones', [])
                remap = d.np.array([bones.get(b['m_boneName'], 0) for b in meshbones]) if skeleton and meshbones else None
                pos, uv, joints, weights = d.attrs(vertices, vb['m_inputLayoutFields'], vb['m_nElementSizeInBytes'], remap)
                indices = d.index_buffer(d.block(raw, blocks, ib['m_nBlockIndex']), ib)
                assert d.np.isfinite(pos).all(), 'Non-finite positions'
                for draw in draws:
                    start, count = draw.get('m_nStartIndex', 0), draw.get('m_nIndexCount', 0)
                    if count:
                        assert start + count <= len(indices), 'Index range outside buffer'
                        assert int(indices[start:start+count].max()) + draw.get('m_nBaseVertex', 0) < len(pos), 'Index outside vertices'
                        render_draws += 1
        assert render_draws, 'No render mesh draw calls in model'
        passed += 1
    except Exception as error:
        failures.append({'model': path, 'error': str(error)})
    if (index + 1) % 500 == 0:
        print(f'Audited {index + 1}/{len(models)}: {passed} passed, {len(failures)} failed', flush=True)
report = {'total': len(models), 'passed': passed, 'failed': failures}
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(report, indent=2))
from collections import Counter
print(f'Geometry audit: {passed}/{len(models)} passed', flush=True)
print(dict(Counter(f['error'] for f in failures)), flush=True)
