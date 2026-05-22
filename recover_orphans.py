"""Recover missed multicam pairs via mtime-anchor + relaxed xcorr.
Usage: python recover_orphans.py
Writes: recover_proposals.json
"""
import json, os, sys, time, subprocess
from collections import defaultdict
sys.path.insert(0, '.')

proj = json.loads(open('projects/drift_club.derush.json', encoding='utf-8').read())
clips = {c['id']: c for c in proj.get('clips', [])}

anchors_raw = defaultdict(list)
for coll in ('multicam_groups', 'multicam_proposals'):
    for g in proj.get(coll, []):
        cids = g.get('clip_ids', [])
        if len(cids) != 2: continue
        c1, c2 = clips.get(cids[0]), clips.get(cids[1])
        if not c1 or not c2 or c1.get('day') != c2.get('day'): continue
        cam1, cam2 = c1.get('camera', ''), c2.get('camera', '')
        if cam1 == cam2 or not (cam1 and cam2): continue
        p1, p2 = c1['path'], c2['path']
        if not (os.path.exists(p1) and os.path.exists(p2)): continue
        m1, m2 = os.path.getmtime(p1), os.path.getmtime(p2)
        cams_sorted = tuple(sorted([cam1, cam2]))
        delta = (m2 - m1) if cam1 == cams_sorted[0] else (m1 - m2)
        anchors_raw[(c1['day'], cams_sorted)].append((delta, g['id']))

print('Anchors found per (day, camera_pair):', flush=True)
day_cam_trans = {}
for key, lst in sorted(anchors_raw.items()):
    sorted_deltas = sorted(d for d, _ in lst)
    median = sorted_deltas[len(sorted_deltas) // 2]
    print(f'  {key[0]} {key[1][0]} vs {key[1][1]}: {len(lst)} anchors median={median:.0f}s range=[{min(sorted_deltas):.0f}, {max(sorted_deltas):.0f}]', flush=True)
    day_cam_trans[key] = median

in_grp = set()
for coll in ('multicam_groups', 'multicam_proposals'):
    for g in proj.get(coll, []):
        for cid in g.get('clip_ids', []): in_grp.add(cid)

GRACE = 30
candidates = []
clip_list = list(clips.values())
for i, c1 in enumerate(clip_list):
    if c1['id'] in in_grp: continue
    if not c1.get('day') or not c1.get('camera') or not c1.get('path'): continue
    if not os.path.exists(c1['path']): continue
    m1 = os.path.getmtime(c1['path'])
    d1 = c1.get('duration_sec', 0)
    for c2 in clip_list[i+1:]:
        if c2['id'] in in_grp: continue
        if c1.get('day') != c2.get('day'): continue
        cam1, cam2 = c1['camera'], c2['camera']
        if cam1 == cam2: continue
        cams_sorted = tuple(sorted([cam1, cam2]))
        key = (c1['day'], cams_sorted)
        if key not in day_cam_trans: continue
        if not os.path.exists(c2['path']): continue
        m2 = os.path.getmtime(c2['path'])
        d2 = c2.get('duration_sec', 0)
        translation = day_cam_trans[key]
        if cam1 == cams_sorted[0]:
            m1_eff, m2_eff = m1 + translation, m2
        else:
            m1_eff, m2_eff = m1, m2 + translation
        s1, e1 = m1_eff - d1, m1_eff
        s2, e2 = m2_eff - d2, m2_eff
        overlap = min(e1, e2) - max(s1, s2)
        if overlap >= -GRACE:
            candidates.append((c1, c2, overlap, translation))

print(f'\n{len(candidates)} candidates with mtime overlap', flush=True)

WORKER = r'''
import json, sys, os
sys.path.insert(0, ".")
import numpy as np
from derush_server import _extract_pcm_segment, _MC_AUDIO_RATE, _MC_RATE, _MC_MIN_SAMPLES
a_id, b_id, a_path, b_path = sys.argv[1:5]
def env(pcm):
    bucket = _MC_AUDIO_RATE // _MC_RATE
    n = len(pcm) // bucket
    if n == 0: return np.array([])
    arr = pcm[:n*bucket].reshape(n, bucket)
    return np.sqrt((arr**2).mean(axis=1))
pcm_a = _extract_pcm_segment(a_path, 0, 180)
pcm_b = _extract_pcm_segment(b_path, 0, 180)
if pcm_a is None or pcm_b is None or pcm_a.size < _MC_AUDIO_RATE * 3 or pcm_b.size < _MC_AUDIO_RATE * 3:
    print(json.dumps({"error":"too_short"})); sys.exit(0)
ea, eb = env(pcm_a), env(pcm_b)
if len(ea) < _MC_MIN_SAMPLES or len(eb) < _MC_MIN_SAMPLES:
    print(json.dumps({"error":"min_samples"})); sys.exit(0)
a_n = ea - ea.mean(); b_n = eb - eb.mean()
sa, sb = a_n.std(), b_n.std()
if sa < 1e-6 or sb < 1e-6:
    print(json.dumps({"error":"flat"})); sys.exit(0)
a_n /= sa; b_n /= sb
corr = np.correlate(a_n, b_n, mode="full")
center = len(eb) - 1
max_lag = int(90 * _MC_RATE)
lo, hi = max(0, center - max_lag), min(len(corr), center + max_lag + 1)
window = corr[lo:hi]
rel = int(np.argmax(window))
best = float(window[rel])
L = (lo + rel) - center
overlap = min(len(ea), len(eb)) - abs(L)
if overlap <= 0: print(json.dumps({"error":"no_overlap"})); sys.exit(0)
score = max(0.0, min(1.0, best / overlap))
z = (best - float(window.mean())) / float(window.std()) if window.std() > 1e-9 else 0.0
delta_sec = -L / _MC_RATE
print(json.dumps({"delta":delta_sec, "score":round(score,4), "z":round(z,2),
                  "overlap_s":round(overlap/_MC_RATE,1), "len_a":len(ea), "len_b":len(eb)}))
'''

new_proposals = []
for i, (c1, c2, mtime_overlap, translation) in enumerate(candidates, 1):
    try:
        r = subprocess.run([sys.executable, '-c', WORKER, c1['id'], c2['id'], c1['path'], c2['path']],
                           capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace')
        out = r.stdout.strip().split('\n')[-1] if r.stdout else ''
        d = json.loads(out) if out else {'error': 'no_output'}
    except Exception as e:
        d = {'error': str(e)}
    if 'error' in d:
        print(f'[{i}/{len(candidates)}] FAIL {d["error"]}: {c1["id"][-25:]} / {c2["id"][-25:]}', flush=True)
        continue
    accept = (d['score'] >= 0.55 and d['z'] >= 5) or (d['z'] >= 8 and d['overlap_s'] >= 5)
    mark = 'OK' if accept else '--'
    print(f'[{i}/{len(candidates)}] {mark} mtimeov={mtime_overlap:+.0f}s xcorr={d["delta"]:+.2f}s sc={d["score"]:.3f} z={d["z"]:.1f} ov={d["overlap_s"]:.1f}s  {c1["id"][-22:]} / {c2["id"][-22:]}', flush=True)
    if accept:
        audio_lag = -d['delta']
        if audio_lag >= 0:
            new_off = {c1['id']: 0.0, c2['id']: round(audio_lag, 3)}
        else:
            new_off = {c1['id']: round(-audio_lag, 3), c2['id']: 0.0}
        new_proposals.append({
            'a': c1['id'], 'b': c2['id'], 'offsets': new_off,
            'score': d['score'], 'z': d['z'], 'overlap': d['overlap_s'],
            'mtime_overlap': mtime_overlap,
        })

with open('recover_proposals.json', 'w') as f:
    f.write(json.dumps(new_proposals, indent=2))
print(f'\n{len(new_proposals)} new proposals saved', flush=True)
