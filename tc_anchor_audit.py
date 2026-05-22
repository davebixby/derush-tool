"""Audit FS5 TC monotonicity + anchor consistency per day.
"""
import json, os, sys
from collections import defaultdict
sys.path.insert(0, '.')
from derush_server import tc_to_seconds

proj = json.loads(open('projects/drift_club.derush.json', encoding='utf-8').read())
clips = {c['id']: c for c in proj.get('clips', [])}

# Group FS5 clips by day, sorted by clip number (=filming order)
def clip_num(c):
    import re
    m = re.search(r'Clip(\d+)', c.get('stem', ''))
    return int(m.group(1)) if m else -1

fs5_by_day = defaultdict(list)
for c in clips.values():
    if c.get('camera') == 'FS5' and c.get('day'):
        fs5_by_day[c['day']].append(c)
for day in fs5_by_day:
    fs5_by_day[day].sort(key=clip_num)

print('=== FS5 TC monotonicity per day ===')
for day in sorted(fs5_by_day):
    lst = fs5_by_day[day]
    if not lst: continue
    print(f'\n{day} ({len(lst)} FS5 clips):')
    prev_sec = None
    rollovers = 0
    for c in lst:
        sec = tc_to_seconds(c.get('tc_in', ''), round(c.get('fps', 25)))
        marker = ''
        if prev_sec is not None and sec is not None and sec < prev_sec:
            marker = ' <-- ROLLOVER'
            rollovers += 1
        print(f'  {c["stem"]:12s}  TC={c.get("tc_in","---"):14s}  ({sec:8.1f}s){marker}')
        prev_sec = sec
    print(f'  -> {rollovers} rollover(s) detected')

# Now audit anchor consistency per day
print('\n\n=== Anchor consistency check ===')
def real_time_from_fx6(fx6_clip):
    p = fx6_clip['path']
    if not os.path.exists(p): return None
    return os.path.getmtime(p) - (fx6_clip.get('duration_sec', 0) or 0)

for day in sorted(fs5_by_day):
    # find anchors in this day
    anchors = []
    for coll in ('multicam_groups', 'multicam_proposals'):
        for g in proj.get(coll, []):
            cids = g.get('clip_ids', [])
            if len(cids) != 2: continue
            c1, c2 = clips.get(cids[0]), clips.get(cids[1])
            if not c1 or not c2: continue
            if c1.get('day') != day or c2.get('day') != day: continue
            # Find FS5 and FX6
            if 'FS5' in c1.get('camera','') and 'FX6' in c2.get('camera',''):
                fs5, fx6 = c1, c2
            elif 'FS5' in c2.get('camera','') and 'FX6' in c1.get('camera',''):
                fs5, fx6 = c2, c1
            else:
                continue
            fs5_tc = tc_to_seconds(fs5.get('tc_in',''), round(fs5.get('fps',25)))
            fx6_rt = real_time_from_fx6(fx6)
            if fs5_tc is None or fx6_rt is None: continue
            # FS5_TC_origin = real time when FS5 TC was 0
            origin = fx6_rt - fs5_tc
            # Account for offset in the group (offset 0 = anchor clip itself)
            anchors.append({'gid': g['id'], 'fs5_id': fs5['id'], 'fx6_id': fx6['id'],
                            'fs5_tc': fs5_tc, 'fx6_rt': fx6_rt, 'origin': origin})
    if not anchors: continue
    origins = sorted(a['origin'] for a in anchors)
    spread = origins[-1] - origins[0]
    print(f'\n{day}: {len(anchors)} anchors, origin spread={spread:.0f}s ({spread/3600:.1f}h)')
    for a in sorted(anchors, key=lambda x: x['origin']):
        print(f'  {a["gid"]}  origin={a["origin"]:.0f}  fs5={a["fs5_id"][-22:]}  fx6={a["fx6_id"][-22:]}')
