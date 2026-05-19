"""Multi-chunk validation for current multicam groups.
For each group, align clips at stored offset, split overlap into 4 chunks,
verify each chunk's xcorr lag stays near 0 (within ±200ms tolerance).
True multicam → chunks agree. False match → chunks scatter.
"""
import json, os, sys, time, subprocess
sys.path.insert(0, '.')

PROJ_FILE = 'projects/drift_club.derush.json'
OUT = 'validation_results.json'

WORKER = r'''
import json, sys, os
sys.path.insert(0, ".")
import numpy as np
from derush_server import _extract_pcm_segment, _MC_AUDIO_RATE, _MC_RATE
a_path, b_path, offset_ab_str = sys.argv[1], sys.argv[2], sys.argv[3]
offset_ab = float(offset_ab_str)  # b starts offset_ab seconds after a
# Extract up to 300s of audio from each
pcm_a = _extract_pcm_segment(a_path, 0, 300)
pcm_b = _extract_pcm_segment(b_path, 0, 300)
if pcm_a is None or pcm_b is None:
    print(json.dumps({"error":"extract_fail"})); sys.exit(0)
def env(pcm):
    bucket = _MC_AUDIO_RATE // _MC_RATE
    n = len(pcm) // bucket
    if n == 0: return np.array([])
    arr = pcm[:n*bucket].reshape(n, bucket)
    return np.sqrt((arr ** 2).mean(axis=1))
ea = env(pcm_a); eb = env(pcm_b)
dur_a = len(ea) / _MC_RATE; dur_b = len(eb) / _MC_RATE
# Overlap region in clip A timeline (clipA starts at 0, clipB starts at offset_ab in A's frame)
# A goes [0, dur_a], B in A's frame goes [offset_ab, offset_ab + dur_b]
ov_start = max(0.0, offset_ab)
ov_end = min(dur_a, offset_ab + dur_b)
ov = ov_end - ov_start
if ov < 30:
    print(json.dumps({"error":"overlap_too_short","overlap":round(ov,1)})); sys.exit(0)
# Decide chunk count based on overlap length
n_chunks = 4 if ov >= 120 else (3 if ov >= 60 else 2)
chunk_dur = ov / n_chunks
chunk_samp = int(chunk_dur * _MC_RATE)
tol_samp = int(0.2 * _MC_RATE)  # ±200ms tolerance
def xcorr(a, b, max_lag):
    if len(a) < 50 or len(b) < 50: return None, 0.0, 0.0
    a = np.asarray(a, dtype=np.float32); b = np.asarray(b, dtype=np.float32)
    a = a - a.mean(); b = b - b.mean()
    sa, sb = a.std(), b.std()
    if sa < 1e-6 or sb < 1e-6: return None, 0.0, 0.0
    a /= sa; b /= sb
    corr = np.correlate(a, b, mode="full")
    center = len(b) - 1
    lo = max(0, center - max_lag); hi = min(len(corr), center + max_lag + 1)
    w = corr[lo:hi]
    rel = int(np.argmax(w))
    best = float(w[rel])
    L = (lo + rel) - center
    overlap = min(len(a), len(b)) - abs(L)
    if overlap <= 0: return None, 0.0, 0.0
    score = max(0.0, min(1.0, best/overlap))
    z = (best - float(w.mean())) / float(w.std()) if w.std() > 1e-9 else 0.0
    return -L, score, z  # convention: returned > 0 = a delayed vs b
chunks_results = []
for i in range(n_chunks):
    a_start_sec = ov_start + i * chunk_dur
    a_end_sec = a_start_sec + chunk_dur
    b_start_sec = a_start_sec - offset_ab
    b_end_sec = a_end_sec - offset_ab
    a_chunk = ea[int(a_start_sec * _MC_RATE) : int(a_end_sec * _MC_RATE)]
    b_chunk = eb[int(b_start_sec * _MC_RATE) : int(b_end_sec * _MC_RATE)]
    delta, sc, z = xcorr(a_chunk.tolist(), b_chunk.tolist(), tol_samp + int(2 * _MC_RATE))
    if delta is None:
        chunks_results.append({"i":i,"err":"flat_or_short"}); continue
    chunks_results.append({"i":i,"delta_sec":round(delta/_MC_RATE,3),"score":round(sc,3),"z":round(z,2)})
# Validate: at least 3 chunks (or all if 2-3 chunks total) with |delta| <= 0.2s and score >= 0.3
ok = sum(1 for c in chunks_results if "delta_sec" in c and abs(c["delta_sec"]) <= 0.2 and c["score"] >= 0.3)
total = len([c for c in chunks_results if "delta_sec" in c])
verdict = "VALID" if (n_chunks >= 4 and ok >= 3) or (n_chunks < 4 and ok == total and total >= 2) else "REJECT"
print(json.dumps({"verdict":verdict,"n_chunks":n_chunks,"ok_chunks":ok,"total_chunks":total,
                  "chunks":chunks_results,"overlap":round(ov,1)}))
'''

proj = json.loads(open(PROJ_FILE, encoding='utf-8').read())
clips = {c['id']: c for c in proj.get('clips', [])}

all_groups = [(g, 'V', i) for i, g in enumerate(proj.get('multicam_groups', []))] + \
             [(g, 'P', i) for i, g in enumerate(proj.get('multicam_proposals', []))]
print(f'Validating {len(all_groups)} groups via multi-chunk consistency...', flush=True)

results = []
for n, (g, src, idx) in enumerate(all_groups, 1):
    gid = g['id']; cids = g['clip_ids']
    # Skip 3+ clip groups (would need pairwise validation)
    if len(cids) != 2:
        print(f'[{n}] {src} {gid}: skip (>=3 clips, manual review)', flush=True)
        results.append({'gid':gid,'src':src,'verdict':'SKIP_MULTI','n_clips':len(cids)})
        continue
    a_id, b_id = cids
    c_a, c_b = clips.get(a_id), clips.get(b_id)
    if not c_a or not c_b:
        print(f'[{n}] {src} {gid}: clip missing'); continue
    if not (os.path.exists(c_a['path']) and os.path.exists(c_b['path'])):
        print(f'[{n}] {src} {gid}: file missing'); continue
    off = g.get('offsets', {})
    offset_ab = off.get(b_id, 0) - off.get(a_id, 0)  # b starts this much after a
    try:
        r = subprocess.run([sys.executable, '-c', WORKER, c_a['path'], c_b['path'], str(offset_ab)],
                           capture_output=True, text=True, timeout=90, encoding='utf-8', errors='replace')
        out = r.stdout.strip().split('\n')[-1] if r.stdout else ''
        d = json.loads(out) if out else {'error':'no_output'}
    except Exception as e:
        d = {'error': str(e)}
    if 'error' in d:
        print(f'[{n}/{len(all_groups)}] {src} {gid}: ERR {d.get("error")} (ov={d.get("overlap","?")})', flush=True)
        results.append({'gid':gid,'src':src,'verdict':'ERROR','error':d.get('error')})
        continue
    print(f'[{n}/{len(all_groups)}] {src} {gid}  {d["verdict"]}  ov={d["overlap"]}s  ok={d["ok_chunks"]}/{d["total_chunks"]}/{d["n_chunks"]}  '
          f'lags={[c.get("delta_sec","?") for c in d["chunks"]]}  {a_id[-20:]} / {b_id[-20:]}', flush=True)
    results.append({'gid':gid,'src':src,'verdict':d['verdict'],'overlap':d['overlap'],
                    'ok':d['ok_chunks'],'total':d['total_chunks'],'n_chunks':d['n_chunks'],
                    'chunks':d['chunks']})

with open(OUT, 'w') as f:
    f.write(json.dumps(results, indent=2))

valid = sum(1 for r in results if r.get('verdict') == 'VALID')
reject = sum(1 for r in results if r.get('verdict') == 'REJECT')
skip = sum(1 for r in results if r.get('verdict') in ('SKIP_MULTI',))
err = sum(1 for r in results if r.get('verdict') == 'ERROR')
print(f'\n=== SUMMARY ===')
print(f'  VALID: {valid}  (3+/4 chunks agree on stored offset)')
print(f'  REJECT: {reject}  (chunks disagree -> probably ambient coincidence)')
print(f'  SKIP: {skip}  (3+ clips, needs manual review)')
print(f'  ERROR: {err}  (extraction/overlap too short)')
