# Audit technique — Derush Tool

Audit réalisé le 22 mai 2026 sur la base d'une revue structurée du code
(serveur Python ~5160 lignes, UI ~3450 lignes, modules JS, script de sync PHP).
Passage ciblé sur les points à plus forte valeur — pas une revue exhaustive
ligne à ligne.

Niveaux : 🔴 critique · 🟠 important · 🟡 moyen · 🟢 amélioration / idée.

---

## 1. Stabilité

### 🔴 1.1 — Écritures concurrentes sur le fichier projet
Le serveur est multithread (`ThreadedHTTPServer`). Le schéma partout est
`load_project()` → modifier → `save_project()`. Deux requêtes simultanées sur le
même projet (deux users qui annotent, ou un save de notes + une sync de fond)
lisent chacune le fichier, modifient leur copie, réécrivent → **la dernière
écrase l'autre**. Aucun verrou.
→ *Correctif* : un verrou par projet (`RLock`) couvrant tout le cycle
load-modifie-save.

### 🔴 1.2 — `save_project` écrit de façon non atomique
`f.write_text(...)` réécrit directement par-dessus le fichier. Un crash ou une
coupure en plein milieu = fichier projet tronqué et illisible.
→ *Correctif* : écrire dans un `.tmp` puis `os.replace()` (atomique).

### 🟠 1.3 — Pas de gestion d'erreur au niveau requête
`do_GET`/`do_POST` n'ont pas de `try/except` global. Une exception dans un
endpoint = connexion coupée brutalement, pas de réponse 500 propre.
→ *Correctif* : envelopper le dispatch, renvoyer un 500 JSON et logguer.

### ✅ 1.4 — `except:` nus (~15) — *corrigé le 22 mai*
Les 15 `except:` nus (qui avalaient aussi `KeyboardInterrupt`/`SystemExit`) sont
passés en `except Exception:`.

## 2. Sécurité

### 🔴 2.1 — Mots de passe hachés en SHA-256 sans sel
`hash_password = sha256(pw).hexdigest()` : hash rapide non salé → vulnérable aux
rainbow tables et au brute-force.
→ *Correctif* : PBKDF2 (`hashlib.pbkdf2_hmac`, stdlib) avec sel par user +
≥200 000 itérations. Migration transparente au prochain login réussi.

### 🟠 2.2 — Clé de sync faible et exposée
`SECRET_KEY` en clair dans le PHP, et passée en **paramètre d'URL**
(`?key=...`) → finit dans les logs Apache.
→ *Correctif* : clé longue aléatoire, passée en **header HTTP** (le PHP accepte
header *ou* query pour rester rétrocompatible le temps du déploiement).

### 🟠 2.3 — Tout en HTTP clair sur le LAN
Serveur sur `0.0.0.0`, tokens de session et identifiants circulent en clair →
sniffables sur le réseau local. Acceptable sur un LAN de confiance, à assumer.

### 🟡 2.4 — Pas de limitation des tentatives de login
Brute-force possible. → Throttle après N échecs. *(non traité dans cette passe)*

### 🟡 2.5 — Liens de review publics sans expiration
Token de 72 bits (OK), mais pas de date d'expiration ni de mot de passe
optionnel. *(non traité dans cette passe)*

## 3. Performance

Déjà bien optimisé (sémaphore ffmpeg, déduplication, numpy, PyInstaller onedir).
Restes :

### 🟡 3.1 — `load_project` relit et reparse le fichier à chaque requête
416 Ko × polling notes 60 s × WebSocket × N users.
→ *Correctif* : cache mémoire invalidé par `mtime`+taille du fichier.

### 🟡 3.2 — `_index_project_db` relancé à chaque `save_project`
Sur des saves rapprochés, des threads d'indexation FTS s'empilent.
→ *Correctif* : *debounce* (comme `_schedule_sync_push`).

## 4. Qualité / maintenabilité

- 🔧 `derush_server.py` = monolithe ; `do_GET`/`do_POST` en chaînes `if/elif`
  géantes. → **Découpage en modules en cours.** Étape 1 ✅ : `derush_core.py`
  (utilitaires purs : hachage, timecode, clés users). Étapes suivantes : exports
  FCPXML/EDL, multicam, décodeur LTC, puis routeur par table de routes.
- 🟡 Modèle de données `notes` fragile (clés dédoublées, IDs de clip orphelins —
  cf. pièges #11/#12 de CLAUDE.md). → Schéma strict + validation au `load_project`.
- ✅ Tests E2E Playwright + **tests unitaires Python** (`tests/test_server_units.py`,
  20 cas : hachage, timecodes, `merge_projects`, résolveur de chemins, clés
  users) — *ajoutés le 22 mai.* Reste à couvrir : export FCPXML, décodeur LTC.

## 5. Limites fonctionnelles (conception)

- ✅ **La sync ne supprime jamais une note** — *corrigé le 22 mai.*
  `merge_projects` laissait chaque machine réécrire les notes de **tous** les
  users (y compris sa copie périmée de celles des autres) → une suppression
  faite ailleurs « revenait ». Désormais une machine ne publie que les notes de
  **son propre utilisateur** (`_own_note_key` + `merge_projects(own_uid=…)`) ;
  pour les autres elle garde la version du cloud. Les suppressions se propagent.
- 🟠 **Un même user sur deux machines en parallèle = perte de notes** (racine du
  bug `6714b070`/`Sebastien`).

## 6. Nouvelles fonctionnalités envisageables

- 🟢 Undo / historique des annotations.
- 🟢 Recherche globale dans l'UI (l'index SQLite FTS5 existe déjà côté serveur).
- 🟢 Présence temps réel : voir qui édite quel clip (WebSocket déjà en place).
- 🟢 Export OpenTimelineIO + préréglages de timeline nommés.
- 🟢 Mode hors-ligne explicite avec file d'attente de sync.
- 🟢 Signature / notarization Apple (supprimer le clic-droit-Ouvrir).

---

## Suivi des corrections — 22 mai 2026

| Point | Statut |
|---|---|
| 1.1 verrou par projet | ✅ corrigé |
| 1.2 écriture atomique | ✅ corrigé |
| 1.3 handler 500 | ✅ corrigé |
| 2.1 PBKDF2 | ✅ corrigé |
| 2.2 clé de sync (header) | ⏳ code prêt — activation ci-dessous |
| 3.1 cache load_project | ✅ corrigé |
| 3.2 debounce indexation | ✅ corrigé |
| 2.4 anti-brute-force login | ✅ corrigé |
| 2.5 expiration liens de review | ✅ corrigé |
| §5 sync : propagation des suppressions | ✅ corrigé |
| §4 tests unitaires Python | ✅ ajoutés (20 cas) |
| 1.4 `except:` nus | ✅ corrigé |
| §4 découpage en modules | 🔧 en cours — étape 1/N (`derush_core.py`) |
| 2.3 · §5 (multi-device) · §6 (features) | à planifier |

### Détail des corrections appliquées

**1.1 — Verrou par projet.** `_project_lock(pid)` (RLock). `do_POST` détient le
verrou du projet ciblé pendant tout le dispatch → les écritures d'endpoints sont
sérialisées. Les jobs de fond (LTC, multicam, auto-détection) et `sync_project`
rechargent le projet sous verrou avant d'écrire (plus de lost-update). Résidu
mineur : `pull_share_comments` sérialise son écriture sans recharger (à affiner).

**1.2 — Écriture atomique.** `save_project` écrit dans un `.tmp` puis
`os.replace()` → plus de fichier projet tronqué en cas de crash.

**1.3 — Handler 500.** `do_GET`/`do_POST` enveloppent le dispatch ; toute
exception non gérée → réponse 500 JSON propre + trace dans stderr.

**2.1 — PBKDF2.** `hash_password` produit `pbkdf2$<iters>$<sel>$<hash>`
(200 000 itérations, sel par mot de passe). `verify_password` gère les deux
formats ; les anciens hash SHA-256 sont re-hachés en PBKDF2 au prochain login
réussi (migration transparente).

**3.1 — Cache load_project.** Cache mémoire invalidé par (mtime, taille) du
fichier → plus de relecture/parsing de 400 Ko à chaque requête. Robuste aux
écritures externes (sync).

**3.2 — Debounce indexation.** L'indexation FTS est *debouncée* (2 s) : une
rafale de saves ne déclenche qu'un seul réindex.

**2.4 — Anti-brute-force login.** Au-delà de 8 échecs de connexion en 5 min
depuis une même IP, `/api/login` répond 429 (« Trop de tentatives »). Le
compteur est remis à zéro à la connexion réussie.

**2.5 — Expiration des liens de review.** À la création d'un lien de partage,
un `expires_at` (création + 30 jours) est embarqué dans le package.
`derush_sync.php` refuse de servir un lien périmé (HTTP 410). Re-partager un
projet réétend le délai.

**§5 — Sync : propagation des suppressions.** `merge_projects` ne laisse plus
chaque machine réécrire les notes de tous les users. Une machine ne publie que
les notes de **son propre utilisateur** (`_own_note_key`) ; pour les autres elle
conserve la version du cloud. Une suppression de marqueur faite par un user se
propage donc partout et ne peut plus « revenir ». Limite restante : un même user
sur deux machines en parallèle (§5, 2ᵉ point) — non couvert.

### 2.2 — Activation de la clé en en-tête

Le serveur envoie désormais la clé de sync dans l'en-tête HTTP `X-Sync-Key`
(en plus de `?key=`, pour ne rien casser). `derush_sync.example.php` lit
l'en-tête en priorité (comparaison `hash_equals` à temps constant).
**Pour activer** : redéployer `derush_sync.php` sur l'hébergement à partir du
template à jour. Ensuite on pourra retirer `?key=` des URLs côté Python (1 ligne)
→ la clé ne transitera plus dans les logs du serveur web. À cette occasion,
remplacer la clé `drift2026` par une clé longue aléatoire (rotation à coordonner
sur les 3 machines).
