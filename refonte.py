"""Refonte algo multicam : TC intra-camera + FX6 mtime anchor + audio validation.

Stages:
  1. Load project, compute FS5 corrected TC (with rollover handling).
  2. Build anchors from current groups, cluster by origin per day, reject outliers.
  3. Discovery phase for days without anchors: aggressive xcorr on long-long pairs.
  4. Recovery: for each FS5 orphan, predict real time via corrected TC + origin,
     find FX6 candidates, validate with audio xcorr.
  5. Output: cleaned anchors + new proposals.
"""
import json, os, re, sys, time, subprocess
from collections import defaultdict
sys.path.insert(0, '.')
from derush_server import tc_to_seconds

PROJ_FILE = 'projects/drift_club.derush.json'
OUT_FILE = 'refonte_result.json'

def clip_num(c):
    m = re.search(r'(\d+)', c.get('stem', ''))
    return int(m.group(1)) if m else -1

def fs5_corrected_tc(clips_by_day_cam):
    """Add 86400 for clips after midnight rollover (per camera per day)."""
    out = {}  # cid -> corrected_tc_sec
    for (day, cam), lst in clips_by_day_cam.items():
        lst_sorted = sorted(lst, key=clip_num)
        rollovers = 0
        prev_tc = None
        for c in lst_sorted:
            sec = tc_to_seconds(c.get('tc_in', ''), round(c.get('fps', 25)))
            if sec is None:
                out[c['id']] = None
                continue
            if prev_tc is not None and sec < prev_tc - 3600:  # backward jump > 1h = rollover
                rollovers += 1
            out[c['id']] = sec + 86400 * rollovers
            prev_tc = sec
    return out

def fx6_real_time(c):
    p = c.get('path', '')
    if not p or not os.path.exists(p): return None
    return os.path.getmtime(p) - (c.get('duration_sec', 0) or 0)

def cluster_origins(anchors, tolerance=120):
    """Group anchor origins by proximity (within tolerance seconds).
    Returns (consensus_origin, kept_anchor_ids, rejected_anchor_ids)."""
    if not anchors: return None, [], []
    sorted_a = sorted(anchors, key=lambda a: a['origin'])
    # Build clusters greedily
    clusters = [[sorted_a[0]]]
    for a in sorted_a[1:]:
        if abs(a['origin'] - clusters[-1][-1]['origin']) <= tolerance:
            clusters[-1].append(a)
        else:
            clusters.append([a])
    # Pick biggest cluster
    biggest = max(clusters, key=len)
    consensus = sorted(a['origin'] for a in biggest)[len(biggest)//2]  # median
    kept = [a['gid'] for a in biggest]
    rejected = [a['gid'] for a in anchors if a['gid'] not in kept]
    return consensus, kept, rejected

# ─── Phase 1+2 : load, build & cluster anchors ──────────────────────────
proj = json.loads(open(PROJ_FILE, encoding='utf-8').read())
clips = {c['id']: c for c in proj.get('clips', [])}

clips_by_day_cam = defaultdict(list)
for c in clips.values():
    if c.get('day') and c.get('camera'):
        clips_by_day_cam[(c['day'], c['camera'])].append(c)

corrected_tc = fs5_corrected_tc({k: v for k, v in clips_by_day_cam.items() if v[0].get('camera') == 'FS5'})

# Build anchors from current groups
anchors_by_day = defaultdict(list)
for coll in ('multicam_groups', 'multicam_proposals'):
    for g in proj.get(coll, []):
        cids = g.get('clip_ids', [])
        if len(cids) != 2: continue
        c1, c2 = clips.get(cids[0]), clips.get(cids[1])
        if not c1 or not c2 or c1.get('day') != c2.get('day'): continue
        if 'FS5' in c1.get('camera','') and 'FX6' in c2.get('camera',''):
            fs5, fx6 = c1, c2
        elif 'FS5' in c2.get('camera','') and 'FX6' in c1.get('camera',''):
            fs5, fx6 = c2, c1
        else:
            continue
        ftc = corrected_tc.get(fs5['id'])
        rt = fx6_real_time(fx6)
        if ftc is None or rt is None: continue
        anchors_by_day[c1['day']].append({
            'gid': g['id'], 'coll': coll,
            'fs5_id': fs5['id'], 'fx6_id': fx6['id'],
            'fs5_tc': ftc, 'fx6_rt': rt,
            'origin': rt - ftc,
        })

day_origins = {}
to_remove = set()
print('=== Anchor clustering ===')
for day, anchors in anchors_by_day.items():
    cons, kept, rejected = cluster_origins(anchors)
    n = len(anchors)
    print(f'  {day}: {n} anchors -> consensus origin={cons:.0f} ({len(kept)} kept, {len(rejected)} rejected)')
    for r in rejected:
        a = next(a for a in anchors if a['gid'] == r)
        print(f'    REJECT {r}: origin={a["origin"]:.0f} (diff {a["origin"]-cons:+.0f}s) fs5={a["fs5_id"][-20:]}')
        to_remove.add(r)
    day_origins[day] = cons

# ─── Phase 3 : discovery for days without anchors ───────────────────────
days_needing_seeds = set()
for c in clips.values():
    if c.get('camera') == 'FS5' and c.get('day') and c['day'] not in day_origins:
        days_needing_seeds.add(c['day'])

print(f'\n=== Days without anchors ({len(days_needing_seeds)}): need discovery ===')
for d in sorted(days_needing_seeds): print(f'  - {d}')

# Helper: xcorr two clips via worker subprocess
WORKER = r'''
import json, sys, os
sys.path.insert(0, ".")
import numpy as np
from derush_server import _extract_pcm_segment, _MC_AUDIO_RATE, _MC_RATE
a_path, b_path = sys.argv[1:3]
def env(pcm):
    bucket = _MC_AUDIO_RATE // _MC_RATE
    n = len(pcm) // bucket
    if n == 0: return np.array([])
    arr = pcm[:n*bucket].reshape(n, bucket)
    return np.sqrt((arr**2).mean(axis=1))
pcm_a = _extract_pcm_segment(a_path, 0, 180)
pcm_b = _extract_pcm_segment(b_path, 0, 180)
if pcm_a is None or pcm_b is None or pcm_a.size < _MC_AUDIO_RATE * 5 or pcm_b.size < _MC_AUDIO_RATE * 5:
    print(json.dumps({"error":"short"})); sys.exit(0)
ea, eb = env(pcm_a), env(pcm_b)
a_n, b_n = ea - ea.mean(), eb - eb.mean()
sa, sb = a_n.std(), b_n.std()
if sa < 1e-6 or sb < 1e-6: print(json.dumps({"error":"flat"})); sys.exit(0)
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
print(json.dumps({"delta":-L/_MC_RATE, "score":round(score,4), "z":round(z,2), "overlap_s":round(overlap/_MC_RATE,1)}))
'''

def xcorr_pair(a_path, b_path):
    try:
        r = subprocess.run([sys.executable, '-c', WORKER, a_path, b_path],
                           capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace')
        out = r.stdout.strip().split('\n')[-1] if r.stdout else ''
        return json.loads(out) if out else {'error': 'no_output'}
    except Exception as e:
        return {'error': str(e)}

new_seeds = []  # discovered anchors
for day in sorted(days_needing_seeds):
    print(f'\n  Discovery for {day}...', flush=True)
    fs5_long = [c for c in clips_by_day_cam.get((day, 'FS5'), []) if c.get('duration_sec', 0) >= 60]
    fx6_long = [c for c in clips_by_day_cam.get((day, 'ILME-FX6V'), []) if c.get('duration_sec', 0) >= 60]
    if not fs5_long or not fx6_long:
        print(f'    no long clips on both cams, skip')
        continue
    # Sort by descending duration, try top pairs first
    fs5_long.sort(key=lambda c: -c.get('duration_sec', 0))
    fx6_long.sort(key=lambda c: -c.get('duration_sec', 0))
    # Try top-3 × top-3 combinations
    found = False
    for fs5 in fs5_long[:3]:
        if found: break
        if not os.path.exists(fs5['path']): continue
        for fx6 in fx6_long[:3]:
            if not os.path.exists(fx6['path']): continue
            d = xcorr_pair(fs5['path'], fx6['path'])
            if 'error' in d:
                print(f'    {fs5["stem"]} x {fx6["stem"]}: FAIL {d["error"]}')
                continue
            ok = d['score'] >= 0.85 and d['z'] >= 10 and d['overlap_s'] >= 30
            mark = 'SEED!' if ok else '----'
            print(f'    {mark} {fs5["stem"]} x {fx6["stem"]}: delta={d["delta"]:+.2f} sc={d["score"]:.3f} z={d["z"]:.1f} ov={d["overlap_s"]:.1f}s')
            if ok:
                ftc = corrected_tc.get(fs5['id'])
                rt = fx6_real_time(fx6)
                if ftc is not None and rt is not None:
                    origin = rt - ftc
                    day_origins[day] = origin
                    new_seeds.append({'day': day, 'fs5_id': fs5['id'], 'fx6_id': fx6['id'],
                                       'delta_sec': d['delta'], 'score': d['score'], 'origin': origin})
                    found = True
                    break

print(f'\nDiscovery found {len(new_seeds)} new seeds')

# ─── Phase 4 : recovery for all FS5 orphans ─────────────────────────────
in_grp = set()
for coll in ('multicam_groups', 'multicam_proposals'):
    for g in proj.get(coll, []):
        if g['id'] in to_remove: continue
        for cid in g.get('clip_ids', []): in_grp.add(cid)
# Include new seeds as anchored too
for s in new_seeds:
    in_grp.add(s['fs5_id'])
    in_grp.add(s['fx6_id'])

print(f'\n=== Recovery phase: scanning FS5 orphans ===')
GRACE = 30  # seconds tolerance for mtime overlap
candidates = []
for c1 in clips.values():
    if c1['id'] in in_grp: continue
    if c1.get('camera') != 'FS5' or not c1.get('day'): continue
    if c1['day'] not in day_origins: continue
    ftc1 = corrected_tc.get(c1['id'])
    if ftc1 is None: continue
    predicted_rt1 = day_origins[c1['day']] + ftc1  # real start time of FS5 clip
    predicted_end1 = predicted_rt1 + (c1.get('duration_sec', 0) or 0)
    # Find FX6 partners on same day with mtime overlap
    for c2 in clips_by_day_cam.get((c1['day'], 'ILME-FX6V'), []):
        if c2['id'] in in_grp: continue
        if not os.path.exists(c2['path']): continue
        rt2 = fx6_real_time(c2)
        if rt2 is None: continue
        end2 = os.path.getmtime(c2['path'])
        overlap = min(predicted_end1, end2) - max(predicted_rt1, rt2)
        if overlap >= -GRACE:
            candidates.append((c1, c2, overlap, predicted_rt1, rt2))

print(f'{len(candidates)} candidates via TC-anchor mtime overlap', flush=True)

new_proposals = []
for i, (c1, c2, mtime_ov, prt1, rt2) in enumerate(candidates, 1):
    if not os.path.exists(c1['path']):
        print(f'[{i}/{len(candidates)}] FAIL path missing'); continue
    d = xcorr_pair(c1['path'], c2['path'])
    if 'error' in d:
        print(f'[{i}/{len(candidates)}] FAIL {d["error"]}: {c1["id"][-22:]} / {c2["id"][-22:]}')
        continue
    # With strong prior (mtime overlap from TC anchor), accept lower thresholds
    # but require z-score sanity
    accept = (d['score'] >= 0.55 and d['z'] >= 5) or (d['z'] >= 8 and d['overlap_s'] >= 5)
    mark = 'OK' if accept else '--'
    print(f'[{i}/{len(candidates)}] {mark} mtimeov={mtime_ov:+.0f}s delta={d["delta"]:+.2f}s sc={d["score"]:.3f} z={d["z"]:.1f} ov={d["overlap_s"]:.1f}s  {c1["id"][-22:]} / {c2["id"][-22:]}', flush=True)
    if accept:
        audio_lag = -d['delta']
        if audio_lag >= 0:
            new_off = {c1['id']: 0.0, c2['id']: round(audio_lag, 3)}
        else:
            new_off = {c1['id']: round(-audio_lag, 3), c2['id']: 0.0}
        new_proposals.append({
            'a': c1['id'], 'b': c2['id'], 'offsets': new_off,
            'score': d['score'], 'z': d['z'], 'overlap': d['overlap_s'],
        })

# ─── Save results ──────────────────────────────────────────────────────
result = {
    'day_origins': day_origins,
    'new_seeds': new_seeds,
    'to_remove': list(to_remove),
    'new_proposals': new_proposals,
}
with open(OUT_FILE, 'w') as f:
    f.write(json.dumps(result, indent=2, default=str))
print(f'\n=== DONE ===')
print(f'  Anchors to remove (outliers): {len(to_remove)}')
print(f'  New seeds discovered: {len(new_seeds)}')
print(f'  New orphan proposals: {len(new_proposals)}')
print(f'  Saved to: {OUT_FILE}')
