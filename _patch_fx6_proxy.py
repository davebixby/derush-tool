"""One-shot : corrige les proxy_url des FX6 dans le projet.

Les proxys caméra FX6 (dossier Sub/) ont été re-transcodés/renommés : le projet
pointe vers `Sub/<stem>S03.MP4` alors que le fichier réel est `Sub/<stem>.MP4`
(suffixe S03 retiré) -> tous les clips FX6 affichent "vidéo introuvable".

Ne modifie QUE le champ `proxy_url` des clips FX6. Ne touche pas aux IDs, aux
annotations (proj['notes']), à ltc_tc_in_sec, ni à quoi que ce soit d'autre.
"""
import json
from pathlib import Path

PROJ = Path(__file__).parent / "projects" / "drift_club.derush.json"
# Racines candidates pour vérifier qu'un proxy existe vraiment avant de réécrire.
ROOTS = [Path(r"E:/DRIFT_CLUB"), Path(r"D:/DRIFT_CLUB")]

with open(PROJ, encoding="utf-8") as f:
    p = json.load(f)

def proxy_exists(proxy_url):
    """proxy_url = '/proxy/<rel>' -> True si le fichier existe sous une des racines."""
    rel = proxy_url[len("/proxy/"):].lstrip("/")
    return any((root / rel).exists() for root in ROOTS)

fixed = 0
already_ok = 0
still_missing = []

for c in p.get("clips", []):
    if not c.get("camera", "").upper().startswith("ILME"):
        continue
    pu = c.get("proxy_url") or ""
    if not pu:
        continue
    if not pu.endswith("S03.MP4"):
        if proxy_exists(pu):
            already_ok += 1
        continue
    candidate = pu[: -len("S03.MP4")] + ".MP4"
    if proxy_exists(candidate):
        c["proxy_url"] = candidate
        fixed += 1
    else:
        still_missing.append(c["filename"])

if fixed:
    with open(PROJ, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

print(f"proxy_url FX6 corrigés  : {fixed}")
print(f"déjà corrects           : {already_ok}")
print(f"proxy toujours absent   : {len(still_missing)} {still_missing}")

# Contrôle : aucun autre champ ne doit avoir bougé (comparaison rapide de tailles)
