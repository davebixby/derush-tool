# -*- coding: utf-8 -*-
"""
DRIFT_CLUB — Diagnostic des proxies mal liés dans DaVinci Resolve
==================================================================

Pourquoi : un "Link Proxy Media" en recherche "comprehensive" sur plusieurs
rushs à la fois a associé le mauvais fichier Sub/*.MP4 comme proxy pour
certains clips (ex: DRIFT_MAI0213 lié au proxy de DRIFT_MAI0177, sept. 2026).
Ça contamine ensuite l'Auto Sync Audio Based on Timecode, qui synchronise
correctement... mais sur le TC du mauvais proxy lié plutôt que celui du clip.

Ce script (lecture seule, ne modifie RIEN dans le projet) parcourt tout le
Media Pool et liste les clips dont le "Proxy Media Path" ne correspond pas au
nom du clip lui-même (même stem, extension différente).

UTILISATION (terminal externe, PAS la console DaVinci) :
  DaVinci Resolve doit déjà tourner avec le projet ouvert. Puis, en PowerShell,
  depuis ce dossier :
    $env:RESOLVE_SCRIPT_API = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
    $env:RESOLVE_SCRIPT_LIB  = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
    $env:PYTHONPATH = "$env:RESOLVE_SCRIPT_API\Modules\;$env:PYTHONPATH"
    python check_proxy_links_resolve.py

Pour chaque MISMATCH listé : dans le Media Pool, clic droit sur le clip →
Proxy Media → Unlink Proxy Media, puis Relink Proxy Media en pointant
manuellement le bon fichier Sub/<nom_du_clip>.mp4. Une fois TOUS les mismatchs
corrigés, refaire l'Auto Sync Audio Based on Timecode pour ces clips (le son
ingé qui en dépendait était probablement lui aussi contaminé).
"""

import os
import DaVinciResolveScript as dvr

resolve = dvr.scriptapp('Resolve')
if resolve is None:
    raise SystemExit("Impossible de se connecter à DaVinci Resolve — vérifie qu'il est lancé avec un projet ouvert.")

proj = resolve.GetProjectManager().GetCurrentProject()
if proj is None:
    raise SystemExit("Aucun projet ouvert dans DaVinci Resolve.")

print(f"Projet ouvert : {proj.GetName()}")

media_pool = proj.GetMediaPool()


def walk_folder(folder, items):
    items.extend(folder.GetClipList() or [])
    for sub in (folder.GetSubFolderList() or []):
        walk_folder(sub, items)


all_items = []
walk_folder(media_pool.GetRootFolder(), all_items)
print(f"{len(all_items)} items dans le Media Pool (tous bins confondus)\n")


def stem(path):
    if not path:
        return None
    base = os.path.basename(path)
    return os.path.splitext(base)[0].upper()


checked = 0
no_proxy = 0
mismatches = []

for item in all_items:
    props = item.GetClipProperty()
    if not props:
        continue
    if props.get('Type') not in ('Video', 'Video + Audio'):
        continue
    file_path = props.get('File Path') or ''
    if not file_path.upper().endswith(('.MXF', '.MP4', '.MOV')):
        continue
    checked += 1

    proxy_path = props.get('Proxy Media Path') or ''
    if not proxy_path.strip():
        no_proxy += 1
        continue

    own_stem = stem(file_path)
    proxy_stem = stem(proxy_path)
    if own_stem and proxy_stem and own_stem != proxy_stem:
        mismatches.append({
            'name': props.get('Clip Name', '?'),
            'file_path': file_path,
            'proxy_path': proxy_path,
            'synced_audio': props.get('Synced Audio', ''),
        })

print(f"{checked} clips vidéo examinés, {no_proxy} sans proxy lié, {len(mismatches)} MAL LIÉS\n")

if mismatches:
    print("=== MISMATCH — le proxy lié ne correspond PAS au clip ===\n")
    for m in mismatches:
        print(f"- {m['name']}")
        print(f"    fichier    : {m['file_path']}")
        print(f"    proxy lié  : {m['proxy_path']}")
        if m['synced_audio']:
            print(f"    son ingé sync (Synced Audio) : {m['synced_audio']}  <-- probablement contaminé aussi")
        print()
else:
    print("Aucun mismatch détecté.")
