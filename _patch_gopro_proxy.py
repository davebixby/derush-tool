"""One-shot: patch les proxy_url des GoPro dans le projet pour pointer sur les .LRV."""
import json
from pathlib import Path

PROJ = r"C:/Users/delah/.gemini/antigravity/scratch/derush_tool/projects/drift_club.derush.json"
with open(PROJ, encoding='utf-8') as f:
    p = json.load(f)

clips = p.get('clips', [])
root_path = p.get('root_path', '')
print(f"root_path projet: {root_path}")
for u in p.get('users', []):
    if u.get('root_path'):
        print(f"user {u.get('name')!r} root_path: {u['root_path']}")

updated = 0
no_lrv = 0
for c in clips:
    if c.get('proxy_url'):
        continue
    path = c.get('path', '')
    if not path: continue
    p_obj = Path(path)
    name = p_obj.name
    if not (name.startswith('GX') and name.upper().endswith('.MP4')):
        continue
    lrv = p_obj.parent / ('GL' + name[2:-4] + '.LRV')
    if not lrv.exists():
        no_lrv += 1
        continue
    rel_path = None
    for u in p.get('users', []):
        rp = u.get('root_path', '')
        if not rp: continue
        try:
            rel_path = str(lrv.relative_to(Path(rp))).replace("\\", "/")
            break
        except ValueError:
            continue
    if rel_path is None and root_path:
        try:
            rel_path = str(lrv.relative_to(Path(root_path))).replace("\\", "/")
        except ValueError:
            pass
    if rel_path is None:
        no_lrv += 1
        continue
    c['proxy_url'] = f'/proxy/{rel_path}'
    updated += 1

with open(PROJ, 'w', encoding='utf-8') as f:
    json.dump(p, f, ensure_ascii=False, indent=2)

print(f"\nGoPro proxy_url patchés: {updated}")
print(f"GoPro sans LRV ou hors root_path: {no_lrv}")

n = 0
for c in clips:
    if 'GOPRO' in (c.get('path') or '').upper():
        n += 1
        if n <= 3:
            print(f"  {c.get('stem'):20s}  proxy_url={c.get('proxy_url')!r}")
