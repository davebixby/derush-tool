# -*- coding: utf-8 -*-
"""
DRIFT_CLUB — Re-tamponne le Start Timecode des rushes FS5 dans DaVinci Resolve
============================================================================

Pourquoi : l'horloge interne de la FS5 est fausse (dérive + remises à zéro en
cours de journée), donc le TC écrit dans les métadonnées MXF ne correspond pas
au TC de l'ingé son. Le VRAI timecode a été enregistré en LTC sur une piste
audio de la FS5 et décodé par Derush. Ce script réinjecte ces valeurs.

Après ça : sélectionne les clips FS5 + les WAV dans le Media Pool →
clic droit → Auto Sync Audio → « Based on Timecode ».

------------------------------------------------------------------------------
UTILISATION
  1. Ouvre le projet dans DaVinci Resolve, rushes FS5 présents dans le Media Pool.
  2. Menu  Workspace ▸ Console  →  bascule l'onglet sur « Py3 »
     →  colle TOUT ce fichier  →  Entrée.
     (variante : enregistre ce .py dans
        %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility\\
      puis lance-le via  Workspace ▸ Scripts)
  3. Il tourne d'abord en DRY-RUN (n'écrit rien, affiche ce qu'il ferait).
     Vérifie la liste, puis passe  DRY_RUN = False  ci-dessous et relance.
  4. Fais l'Auto Sync Audio « Based on Timecode ».

Ne touche QU'AUX 127 clips listés dans TC (ceux dont le LTC a été décodé).
Les 20 restants (tout J06 + Clip0001 J02 + Clip0016/0029 J04) n'ont pas de LTC
exploitable → clap ou Auto Sync « Based on Waveform » pour ceux-là.

Idempotent : relançable sans risque, il réécrit simplement la même valeur.
"""

DRY_RUN = True   # <-- passe à False pour appliquer réellement

import re

# ── "<dossier jour>/<fichier>" -> vrai Start TC (HH:MM:SS:FF @ 25 fps) ──────────
TC = {
  "J02_2026_04_08/Clip0002.MXF": "17:14:18:01",
  "J02_2026_04_08/Clip0003.MXF": "17:21:24:19",
  "J02_2026_04_08/Clip0004.MXF": "17:50:25:13",
  "J03_2026_04_09/Clip0001.MXF": "11:01:50:12",
  "J03_2026_04_09/Clip0002.MXF": "11:11:40:06",
  "J03_2026_04_09/Clip0003.MXF": "11:12:59:13",
  "J03_2026_04_09/Clip0004.MXF": "11:45:52:10",
  "J03_2026_04_09/Clip0005.MXF": "11:49:42:19",
  "J03_2026_04_09/Clip0006.MXF": "11:54:39:19",
  "J03_2026_04_09/Clip0007.MXF": "11:57:52:00",
  "J03_2026_04_09/Clip0008.MXF": "12:01:11:13",
  "J03_2026_04_09/Clip0009.MXF": "12:09:49:15",
  "J03_2026_04_09/Clip0010.MXF": "12:43:43:09",
  "J03_2026_04_09/Clip0011.MXF": "12:45:19:13",
  "J03_2026_04_09/Clip0012.MXF": "12:48:45:08",
  "J03_2026_04_09/Clip0013.MXF": "12:52:21:16",
  "J03_2026_04_09/Clip0014.MXF": "13:16:09:19",
  "J03_2026_04_09/Clip0015.MXF": "13:22:45:23",
  "J03_2026_04_09/Clip0016.MXF": "15:46:47:13",
  "J03_2026_04_09/Clip0017.MXF": "15:59:45:17",
  "J03_2026_04_09/Clip0018.MXF": "16:01:18:04",
  "J03_2026_04_09/Clip0019.MXF": "16:11:50:04",
  "J03_2026_04_09/Clip0020.MXF": "16:44:19:01",
  "J03_2026_04_09/Clip0021.MXF": "16:54:43:15",
  "J03_2026_04_09/Clip0022.MXF": "17:01:23:19",
  "J03_2026_04_09/Clip0023.MXF": "17:01:46:24",
  "J03_2026_04_09/Clip0024.MXF": "17:09:52:21",
  "J03_2026_04_09/Clip0025.MXF": "17:14:22:22",
  "J03_2026_04_09/Clip0026.MXF": "17:21:21:06",
  "J04_2026_04_10/Clip0001.MXF": "11:45:12:19",
  "J04_2026_04_10/Clip0002.MXF": "11:59:32:03",
  "J04_2026_04_10/Clip0003.MXF": "12:01:24:03",
  "J04_2026_04_10/Clip0004.MXF": "12:02:12:00",
  "J04_2026_04_10/Clip0005.MXF": "12:05:29:12",
  "J04_2026_04_10/Clip0006.MXF": "12:16:09:24",
  "J04_2026_04_10/Clip0007.MXF": "12:18:53:24",
  "J04_2026_04_10/Clip0008.MXF": "12:20:03:14",
  "J04_2026_04_10/Clip0009.MXF": "12:29:20:00",
  "J04_2026_04_10/Clip0010.MXF": "12:30:58:06",
  "J04_2026_04_10/Clip0011.MXF": "12:42:42:20",
  "J04_2026_04_10/Clip0012.MXF": "12:51:26:20",
  "J04_2026_04_10/Clip0013.MXF": "12:59:12:06",
  "J04_2026_04_10/Clip0014.MXF": "13:00:58:19",
  "J04_2026_04_10/Clip0015.MXF": "14:58:23:14",
  "J04_2026_04_10/Clip0017.MXF": "15:10:27:16",
  "J04_2026_04_10/Clip0018.MXF": "15:12:24:07",
  "J04_2026_04_10/Clip0019.MXF": "15:13:45:23",
  "J04_2026_04_10/Clip0020.MXF": "15:16:30:16",
  "J04_2026_04_10/Clip0021.MXF": "15:19:38:22",
  "J04_2026_04_10/Clip0022.MXF": "15:29:12:19",
  "J04_2026_04_10/Clip0023.MXF": "15:36:48:12",
  "J04_2026_04_10/Clip0024.MXF": "15:38:34:24",
  "J04_2026_04_10/Clip0025.MXF": "15:55:40:19",
  "J04_2026_04_10/Clip0026.MXF": "16:32:06:23",
  "J04_2026_04_10/Clip0027.MXF": "16:32:36:17",
  "J04_2026_04_10/Clip0028.MXF": "16:36:31:23",
  "J04_2026_04_10/Clip0030.MXF": "16:40:55:06",
  "J04_2026_04_10/Clip0031.MXF": "16:42:02:16",
  "J04_2026_04_10/Clip0032.MXF": "16:42:43:07",
  "J04_2026_04_10/Clip0033.MXF": "16:44:52:09",
  "J04_2026_04_10/Clip0034.MXF": "16:47:11:17",
  "J04_2026_04_10/Clip0035.MXF": "16:51:58:21",
  "J04_2026_04_10/Clip0036.MXF": "16:52:46:02",
  "J04_2026_04_10/Clip0037.MXF": "16:59:09:05",
  "J04_2026_04_10/Clip0038.MXF": "17:57:10:18",
  "J04_2026_04_10/Clip0039.MXF": "17:58:00:20",
  "J04_2026_04_10/Clip0040.MXF": "18:01:12:18",
  "J05_2026_04_11/Clip0001.MXF": "13:58:13:13",
  "J05_2026_04_11/Clip0002.MXF": "14:29:45:11",
  "J05_2026_04_11/Clip0003.MXF": "14:30:11:07",
  "J05_2026_04_11/Clip0004.MXF": "14:31:07:24",
  "J05_2026_04_11/Clip0005.MXF": "15:53:58:00",
  "J05_2026_04_11/Clip0006.MXF": "16:03:40:05",
  "J05_2026_04_11/Clip0007.MXF": "17:10:53:23",
  "J05_2026_04_11/Clip0008.MXF": "17:12:24:11",
  "J05_2026_04_11/Clip0009.MXF": "17:13:24:02",
  "J05_2026_04_11/Clip0010.MXF": "17:15:46:10",
  "J05_2026_04_11/Clip0011.MXF": "17:18:08:07",
  "J05_2026_04_11/Clip0012.MXF": "17:32:26:06",
  "J05_2026_04_11/Clip0013.MXF": "17:44:05:23",
  "J05_2026_04_11/Clip0014.MXF": "17:45:19:12",
  "J05_2026_04_11/Clip0015.MXF": "18:07:28:21",
  "J07_2026_05_04/Clip0001.MXF": "13:33:40:18",
  "J07_2026_05_04/Clip0002.MXF": "13:42:11:21",
  "J07_2026_05_04/Clip0003.MXF": "14:10:13:13",
  "J07_2026_05_04/Clip0004.MXF": "14:21:23:12",
  "J07_2026_05_04/Clip0005.MXF": "14:27:22:14",
  "J07_2026_05_04/Clip0006.MXF": "14:29:50:03",
  "J07_2026_05_04/Clip0007.MXF": "14:31:53:14",
  "J07_2026_05_04/Clip0008.MXF": "14:34:23:21",
  "J07_2026_05_04/Clip0009.MXF": "14:45:47:17",
  "J07_2026_05_04/Clip0010.MXF": "14:57:52:24",
  "J07_2026_05_04/Clip0011.MXF": "14:59:36:04",
  "J07_2026_05_04/Clip0012.MXF": "15:02:13:01",
  "J07_2026_05_04/Clip0013.MXF": "15:04:31:12",
  "J07_2026_05_04/Clip0014.MXF": "15:05:09:24",
  "J07_2026_05_04/Clip0015.MXF": "15:08:10:05",
  "J07_2026_05_04/Clip0016.MXF": "15:11:33:13",
  "J07_2026_05_04/Clip0017.MXF": "15:15:13:13",
  "J07_2026_05_04/Clip0018.MXF": "15:25:01:12",
  "J07_2026_05_04/Clip0019.MXF": "15:26:23:14",
  "J07_2026_05_04/Clip0020.MXF": "15:45:03:19",
  "J07_2026_05_04/Clip0021.MXF": "15:51:52:02",
  "J07_2026_05_04/Clip0022.MXF": "16:05:06:10",
  "J07_2026_05_04/Clip0023.MXF": "16:06:43:08",
  "J10_2026_05_07/Clip0001.MXF": "13:48:47:03",
  "J10_2026_05_07/Clip0002.MXF": "13:49:45:22",
  "J10_2026_05_07/Clip0003.MXF": "13:51:09:06",
  "J10_2026_05_07/Clip0004.MXF": "14:02:53:11",
  "J10_2026_05_07/Clip0005.MXF": "14:42:58:04",
  "J10_2026_05_07/Clip0006.MXF": "14:44:55:17",
  "J10_2026_05_07/Clip0007.MXF": "14:52:47:17",
  "J10_2026_05_07/Clip0008.MXF": "15:01:22:15",
  "J10_2026_05_07/Clip0009.MXF": "15:03:13:15",
  "J10_2026_05_07/Clip0010.MXF": "15:25:12:02",
  "J10_2026_05_07/Clip0011.MXF": "15:30:54:05",
  "J10_2026_05_07/Clip0012.MXF": "15:31:59:08",
  "J10_2026_05_07/Clip0013.MXF": "15:38:01:07",
  "J11_2026_05_08/Clip0001.MXF": "10:39:32:22",
  "J11_2026_05_08/Clip0002.MXF": "10:48:54:05",
  "J11_2026_05_08/Clip0003.MXF": "10:52:51:05",
  "J11_2026_05_08/Clip0004.MXF": "10:55:38:12",
  "J11_2026_05_08/Clip0005.MXF": "11:17:28:07",
  "J11_2026_05_08/Clip0006.MXF": "11:24:49:21",
  "J11_2026_05_08/Clip0007.MXF": "16:37:12:17",
  "J11_2026_05_08/Clip0008.MXF": "16:42:04:23",
  "J11_2026_05_08/Clip0009.MXF": "16:45:27:13",
}

DAY_RE = re.compile(r"(J\d\d_\d{4}_\d\d_\d\d)")


def get_resolve():
    try:
        return resolve  # déjà injecté dans la Console de Resolve
    except NameError:
        pass
    try:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp("Resolve")
    except Exception:
        try:
            return bmd.scriptapp("Resolve")  # noqa: F821
        except Exception:
            return None


def walk(folder, out):
    for c in folder.GetClipList():
        out.append(c)
    for sub in folder.GetSubFolderList():
        walk(sub, out)


def main():
    R = get_resolve()
    if R is None:
        print("ERREUR : API Resolve inaccessible. Lance le script depuis la Console de Resolve.")
        return
    proj = R.GetProjectManager().GetCurrentProject()
    if not proj:
        print("ERREUR : aucun projet ouvert.")
        return

    clips = []
    walk(proj.GetMediaPool().GetRootFolder(), clips)
    print("Media Pool : %d entrées" % len(clips))
    print("Mode : %s\n" % ("DRY-RUN (rien n'est écrit)" if DRY_RUN else "APPLICATION"))

    done = same = fail = nolutc = 0
    seen = set()
    for c in clips:
        fp = (c.GetClipProperty("File Path") or "").replace("\\", "/")
        if not fp.lower().endswith(".mxf"):
            continue
        name = fp.split("/")[-1]
        m = DAY_RE.search(fp)
        if not m:
            continue
        key = m.group(1) + "/" + name
        if key not in TC:
            if "fs5" in fp.lower():
                nolutc += 1
                print("  · sans LTC (clap/waveform)      : %s" % key)
            continue
        seen.add(key)
        target = TC[key]
        cur = c.GetClipProperty("Start TC") or "?"
        if cur == target:
            same += 1
            print("  = déjà bon   %-30s  %s" % (key, target))
            continue
        if DRY_RUN:
            done += 1
            print("  → écrirait   %-30s  %s  ->  %s" % (key, cur, target))
            continue
        ok = c.SetClipProperty("Start TC", target)
        if ok:
            done += 1
            print("  ✓ écrit      %-30s  %s  ->  %s" % (key, cur, target))
        else:
            fail += 1
            print("  ✗ ÉCHEC API  %-30s  (cible %s)" % (key, target))

    missing = sorted(set(TC) - seen)
    print("\n=== Bilan ===")
    print("  %s : %d" % ("à écrire" if DRY_RUN else "écrits", done))
    print("  déjà corrects            : %d" % same)
    print("  échecs API               : %d" % fail)
    print("  FS5 sans LTC (hors table): %d" % nolutc)
    if missing:
        print("  dans la table mais PAS trouvés dans le Media Pool : %d" % len(missing))
        for k in missing:
            print("      %s" % k)
    if fail:
        print("\n  SetClipProperty('Start TC') refusé par ta version de Resolve.")
        print("  → applique le CSV à la main (Clip Attributes ▸ Timecode) ou")
        print("    Auto Sync Audio « Based on Waveform » (isole le canal micro d'abord).")
    if DRY_RUN and done:
        print("\n  OK pour toi ? repasse  DRY_RUN = False  en haut du script et relance.")


main()
