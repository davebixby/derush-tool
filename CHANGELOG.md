# Changelog

Toutes les évolutions notables de Derush Tool. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

---

## [0.3.36] — 2026-07-28

### 🔧 Modifié
- **La recherche ne porte plus sur le nom de fichier des clips** : chercher un tag comme « drift » remontait aussi tous les clips dont le nom de fichier contient « drift » (cas réel sur DRIFT_CLUB, clips nommés `DRIFT_avril00xx`), noyant les vrais résultats. La recherche (barre de recherche + indexation FTS serveur) ne matche plus que sur ce que l'équipe a écrit : tags, notes, descriptions de marker, réponses. Pour retrouver un clip par son nom, utiliser les filtres caméra/jour ou faire défiler la liste.

## [0.3.35] — 2026-07-28

### ✨ Ajouté
- **Tags visibles pour toute l'équipe, colorés par auteur** : jusqu'ici les tags étaient strictement privés (comme les notes/ratings). Ils apparaissent désormais aussi sous le clip actif (section « Tags de l'équipe ») et directement dans la liste des clips, chaque tag teinté de la couleur du collaborateur qui l'a écrit — on sait qui a écrit quoi sans ouvrir chaque clip.
- **Filtre par tags cochable dans la sidebar** : nouveau bouton « 🏷 Tags » à côté des filtres caméra/jour, ouvrant une liste à cocher de tous les tags du projet (toute l'équipe confondue). Se reconstruit automatiquement dès qu'un collaborateur crée un nouveau tag (poll 15s + WebSocket), sans avoir à rouvrir le menu.

## [0.3.34] — 2026-07-28

### 🐛 Corrigé
- **Un tag tapé sans validation semblait « coller » au clip suivant** : le champ de saisie des tags n'était jamais vidé au changement de clip. Un tag tapé puis quitté sans appuyer sur Entrée/virgule restait visible dans le champ en changeant de clip, donnant l'impression qu'il s'appliquait au nouveau clip — alors qu'il n'avait en réalité jamais été enregistré nulle part (d'où son absence totale en recherche). Le champ est maintenant vidé à chaque sélection de clip.
- **Latence de recherche après ajout d'un tag** : un tag ajouté n'était poussé au serveur (et donc indexé pour la recherche) qu'à la prochaine sauvegarde périodique (jusqu'à 30s). Ajout/suppression de tag déclenche désormais une sauvegarde immédiate.

## [0.3.33] — 2026-07-28

### 🐛 Corrigé
- **Son entendu uniquement sur le canal droit (Mac)** : signalé sur le Mac de Paola, jamais reproduit sur Windows, indépendant des écouteurs branchés. Le lecteur principal, le comparateur et le viewer multicam construisent tous un graphe WebAudio (`MediaElementSource` → `ChannelSplitter`/`Merger` → destination) sans jamais fixer explicitement le nombre de canaux de la destination. Sur un Mac dont la sortie audio (haut-parleurs « spatial audio » des MacBook Pro récents, ou une sortie agrégée) expose plus de 2 canaux au navigateur, un signal stéréo brut connecté tel quel se fait up-mixer par Chromium selon un layout de haut-parleurs qui ne correspond pas au signal réellement envoyé — le son peut alors se retrouver entièrement sur un seul canal de sortie. Fix : nouvelle fonction `_pinStereoDestination(ctx)` qui force `destination.channelCount = 2` (`channelCountMode: 'explicit'`) sur chaque `AudioContext` créé (lecteur, comparateur, multicam). Sans effet sur une sortie 2 canaux standard (le cas normal) — nécessite un rebuild Mac + retest pour confirmer que c'est bien la cause exacte, pas de machine Mac disponible ici pour vérifier directement.

---

## [0.3.32] — 2026-07-28

### ✨ Ajouté
- **Fil de discussion façon forum sous l'avis général (rating + note) de chaque collaborateur** : jusqu'ici on ne pouvait répondre qu'aux markers d'un collaborateur, pas à son avis global sur le clip. Chaque bloc « Avis de X » dans le panneau « Avis des autres » a maintenant son propre fil de réponses, y compris quand ce collaborateur n'a pas encore annoté (pour pouvoir le relancer). Réutilise le mécanisme de réponse déjà existant (même endpoint, même sync/merge) — zéro changement serveur.

---

## [0.3.31] — 2026-07-28

### ✨ Ajouté
- **Cliquer sur un marker d'un collaborateur (panneau « Avis des autres ») déplace la lecture au bon endroit** : jusqu'ici seuls vos propres markers (liste + pins de la timeline) faisaient sauter le lecteur au clic ; ceux des autres, affichés avec leurs réponses dans le panneau « Avis des autres », n'étaient que du texte. Un clic dessus positionne maintenant la tête de lecture exactement au TC du marker — le clic dans le mini-formulaire de réponse imbriqué reste sans effet sur la lecture.

---

## [0.3.30] — 2026-07-27

### 🐛 Corrigé
- **Sync systématiquement hors ligne sur macOS (`SSL: CERTIFICATE_VERIFY_FAILED`)** : constaté sur le MacBook Pro M2 de Paola — dot ☁️ rouge malgré une clé et une connexion internet correctes. Le Python embarqué dans un build PyInstaller n'a pas accès au trousseau de certificats racine du système comme un Python installé normalement, donc toute requête HTTPS (`urllib.request`, utilisée par toute la sync cloud) échoue à la vérification du certificat SSL. Fix : bundle du CA de `certifi` + `SSL_CERT_FILE` pointé dessus au démarrage, avant toute requête réseau. N'affecte pas Windows (déjà fonctionnel), corrige macOS sans configuration supplémentaire — juste un rebuild.

---

## [0.3.29] — 2026-07-27

### 🐛 Corrigé
- **« Effacer les commentaires » (retours externes) incomplet — un commentaire revenait toujours, jamais supprimé sur les autres machines** : le bouton (v0.3.22) ne vidait que le cache local de la machine cliquée — le fichier persistant côté serveur (`derush_sync.php`, JSONL par lien de partage) n'était jamais purgé, sauf par « Révoquer » qui tue le lien entier. Résultat : un pull ultérieur (automatique ou manuel), sur **n'importe quelle machine** de l'équipe, retéléchargeait les commentaires soi-disant effacés depuis ce fichier toujours intact. Le mécanisme de pull lui-même (`pull_share_comments`) ne faisait par ailleurs qu'ajouter les nouveaux commentaires sans jamais retirer les anciens du cache local — une suppression ne pouvait donc structurellement jamais se propager, même en corrigeant le premier point seul.
- Fix : nouvelle action serveur `clear_comments` dans `derush_sync.php` (purge le fichier JSONL du lien sans le révoquer) — **nécessite de réuploader `derush_sync.php` sur l'hébergement pour prendre effet**. `clear_share_comments()` l'appelle en plus de vider le cache local. `pull_share_comments()` retélécharge désormais l'intégralité des commentaires à chaque pull et **remplace** le cache local au lieu de le compléter — un commentaire supprimé côté serveur disparaît donc bien de toutes les machines dès leur prochain pull, automatique ou manuel.

---

## [0.3.28] — 2026-07-27

### 🐛 Corrigé
- **Notes/ratings d'un compte legacy invisibles pour tous les autres collaborateurs** : `GET /api/project/<pid>/config` (source exclusive de `currentProject.users` côté frontend) retirait le champ `id` de chaque utilisateur en le traitant à tort comme une donnée sensible (seuls `password_hash` et la valeur d'`invite_key` le sont réellement). Pour un compte historique identifié par `id` plutôt que par `username` (le seul cas dans ce projet : le compte admin d'origine), le frontend recalculait `u.id || u.username || u.name` sans jamais voir `id` — et retombait sur `name`, une clé différente de celle où ses notes sont réellement stockées (`user_note_key()`, qui priorise `id`). Résultat : ses ratings/marqueurs étaient invisibles dans le panneau « Avis des autres » et les chips de la sidebar pour absolument tous les autres collaborateurs, sur n'importe quelle machine — lui-même ne voyait jamais le problème puisque sa propre session résout sa clé côté serveur, indépendamment de ce payload. Fix : `id` n'est plus retiré de la réponse. Un seul point de code concerné, vérifié qu'il n'y en a pas d'autre.

---

## [0.3.27] — 2026-07-27

### 🐛 Corrigé
- **Vignette cassée (⚠) sur les clips très courts (< ~1s)** : le calcul de l'offset ffmpeg pour générer une vignette visait un minimum de 1 seconde par défaut (`max(1.0, durée × 0.15)`), sans jamais vérifier que ce point tombe bien dans la durée réelle du clip. Un clip GoPro de 0,96s (déclenchement accidentel de la caméra) faisait donc viser 1s — au-delà de sa propre fin — ffmpeg ne trouvait aucune frame à cet instant, le `.jpg` n'était jamais créé, 404 silencieux → icône ⚠ dans la sidebar sans raison apparente. Offset désormais plafonné sous la durée réelle du clip (`durée − 0.05s`). Vérifié directement contre le fichier concerné : la vignette se génère maintenant correctement.

---

## [0.3.26] — 2026-07-27

### 🔧 Amélioré
- **Poll de sync local accéléré (60s → 15s)** : `startNotesPolling()` (pull-only cloud + relecture `/notes`/`/discussions`) tourne maintenant toutes les 15 secondes au lieu de 60 — les annotations des collaborateurs apparaissent 4× plus vite sans action manuelle. Sans impact perceptible pour une petite équipe (aucune limitation de fréquence côté `derush_sync.php`, poll silencieux tant que rien n'a changé). La sauvegarde auto locale reste à 30s, inchangée.

---

## [0.3.25] — 2026-07-27

### ✨ Ajouté
- **Build macOS au format `.dmg`** en plus du `.zip` existant : nouvelle target `dmg` dans `electron/package.json` (arm64). Installation par glisser-déposer dans `/Applications` plutôt que dézipper manuellement. Même limitation que le zip côté Gatekeeper (app non signée — clic droit → Ouvrir au premier lancement). `build_mac.sh` rapporte désormais les deux artefacts produits (zip + dmg) avec leurs instructions respectives.

---

## [0.3.24] — 2026-07-27

### ✨ Ajouté
- **Build "prêt à l'emploi" pour la sync cloud** : jusqu'ici, chaque nouvelle machine (ex. celle d'un collaborateur) devait saisir manuellement `sync_url`/`sync_key` dans ⚙️ Configuration après installation, sinon elle retombait sur le placeholder public (`drift2026`, rejeté par le serveur). Nouveau fichier `derush_config.seed.json` (gitignored, comme `derush_sync.php`) contenant la vraie clé : si présent sur la machine qui build, il est bundlé dans l'exe/app et sert de valeur par défaut pour toute machine qui n'a pas encore de config — le collaborateur n'a plus rien à saisir. Priorité : config déjà présente sur la machine > seed bundlé > placeholder public (pour quiconque build depuis les sources publiques sans le seed).

---

## [0.3.23] — 2026-07-27

### 🐛 Corrigé
- **Sync cloud en erreur 403 sur toutes les machines** : la clé sync avait été régénérée côté hébergement (`derush_sync.php`), mais il n'existait **aucun champ dans l'assistant de configuration** pour la modifier — et `POST /api/setup` écrasait le fichier de config sans jamais préserver `sync_url`/`sync_key`, qui retombaient donc systématiquement sur l'ancienne valeur codée en dur (`drift2026`) à chaque nouvelle sauvegarde des réglages de base. Confirmé par test direct contre le serveur réel : ancienne clé → 403, nouvelle clé → 200.
- Fix : `/api/setup` accepte et préserve désormais `sync_url`/`sync_key` (un champ vide dans la requête garde la valeur déjà en config au lieu de l'effacer). Nouveaux champs "URL de sync cloud" / "Clé de sync cloud" (optionnels) dans l'assistant ⚙️ Configuration, pré-remplis avec la valeur actuelle — modifiables sans toucher au fichier JSON à la main.
- Message d'erreur générique "Erreur serveur 403" du sync principal remplacé par le message explicite déjà utilisé ailleurs ("Clé sync incorrecte. Vérifie SYNC_KEY dans ⚙️ Configuration…").

---

## [0.3.22] — 2026-07-27

### ✨ Ajouté
- **Suppression des commentaires externes (retours du lien de review)** : jusqu'ici, une fois reçus, les commentaires du lien de partage public restaient dans le projet indéfiniment — seul le lien lui-même pouvait être révoqué (📤 Exporter → 🔗 Lien de review). Nouveau bouton « 🗑 Effacer les commentaires » dans cette même modale, visible dès qu'il y a au moins un commentaire reçu. Confirmation par re-clic sous 8s (pas de `confirm()` natif, cf. bug de focus Electron déjà documenté). N'affecte pas le lien actif ni les futurs commentaires : seuls ceux déjà reçus sont supprimés, sans être re-téléchargés au prochain pull automatique.

---

## [0.3.21] — 2026-07-27

### 🐛 Corrigé
- **Réponse à un marqueur pas rafraîchie en direct dans votre propre liste « Marqueurs »** : la réception WebSocket `discussion_updated` ne rafraîchissait que le panneau « Avis des autres » (`renderMultiUser`), pas la liste de vos propres marqueurs (`renderMarkers`) — un collaborateur qui répondait à un de VOS marqueurs pendant que vous étiez sur ce clip ne voyait sa réponse apparaître qu'au poll suivant (jusqu'à 60s), pas immédiatement. Les deux panneaux se rafraîchissent désormais ensemble sur cet évènement.

### ✨ Ajouté
- **Ratings des autres visibles directement sur la vignette** : les points de couleur discrets (visibles seulement au survol via `title`) sont remplacés par des chips visibles en permanence — nom du collaborateur + étoiles (⭐/⭐⭐/⭐⭐⭐) ou ❌ rejet — sous chaque clip dès qu'au moins un autre membre de l'équipe l'a noté. Les rejets (X) ressortent avec un fond rouge distinct.

---

## [0.3.20] — 2026-07-26

### 🐛 Corrigé
- **Redémarrage nécessaire après « 🎶 Décoder LTC » pour entendre le bon son** : le décodage LTC met à jour `ltc_tc_in_sec` côté serveur, mais le client gardait en mémoire la liste des clips chargée à l'entrée du projet (donc `ltc_tc_in_sec` toujours `null`) — le silencing automatique de la piste TC (audio FS5 mono-R) ne se réactivait qu'après un redémarrage complet forçant un rechargement des clips. La liste des clips est désormais rechargée automatiquement dès que le décodage se termine, et le routage audio du clip actif est réappliqué immédiatement si besoin — plus besoin de redémarrer.

### 🔧 Amélioré
- **Rescan toujours lent (~15 min) après le fix 0.3.18, même sans blocage infini** : diagnostic en direct (`py-spy`, dump des threads du process réel pendant que le scan tournait) — pas de blocage, mais un fichier après l'autre mettait jusqu'à 20s (la limite du fix 0.3.17) alors que le même fichier sondé directement en ligne de commande répond en 0,1s. Cause : `scan_media_folder()` sonde chaque fichier via la même sémaphore partagée (8 slots) que les vignettes/strips/waveform — quand un gros lot de clips neufs génère ses aperçus en tâche de fond en même temps qu'un rescan, les sondages rapides du scan font la queue derrière des extractions bien plus lourdes (décodage vidéo réel) au lieu de passer en priorité.
- Fix : nouvelle sémaphore dédiée (`_ffprobe_meta_sem`, 16 slots) réservée aux requêtes `ffprobe` de métadonnées seules (utilisées uniquement par le scan) — indépendante de celle des vignettes/strips/waveform. Un rescan que l'utilisateur attend activement ne peut plus se faire ralentir par de la pré-génération d'aperçus en arrière-plan.

---

## [0.3.18] — 2026-07-26

### 🐛 Corrigé
- **Le fix 0.3.17 ne suffisait toujours pas — la vraie fuite était dans la sémaphore ffmpeg partagée** : `_ffprobe_metadata_bounded` (0.3.17) bornait bien l'attente de *l'appelant* à 20s par fichier, mais le thread interne bloqué sur un `ffprobe.exe` zombie continuait de tenir un permis de `_ffmpeg_sem` (la sémaphore qui limite à 8 le nombre de processus ffmpeg/ffprobe simultanés — partagée par **toutes** les fonctionnalités : vignettes, strips, waveform, LTC, etc.) indéfiniment, puisque `with _ffmpeg_sem:` ne se libère qu'au retour de `subprocess.run()`, qui ne revient jamais pour un processus vraiment bloqué. Si plusieurs fichiers du lot se retrouvent dans cet état (plausible si l'antivirus scanne plusieurs des 102 nouveaux proxys à la suite), les 8 permis finissent tous par fuiter — et l'ancien `with _ffmpeg_sem:` (sans délai) faisait alors bloquer indéfiniment **tout nouvel appel ffmpeg/ffprobe de l'app entière**, pas seulement le scan en cours. Reproduit et confirmé par simulation directe : les 8 permis "fuités" à la main, un nouvel appel bloquait indéfiniment avec l'ancien code ; avec le fix, il échoue proprement après quelques secondes.
- Fix : `_ffmpeg_run()` acquiert désormais la sémaphore avec son propre délai (`timeout + 5` s) au lieu d'un `with` bloquant sans limite — si aucun permis ne se libère à temps, l'appel échoue proprement (`TimeoutError`, absorbée comme toute autre erreur ffprobe) au lieu de bloquer indéfiniment. Le compromis reste le même qu'en 0.3.17 : un permis peut rester perdu pour de bon si son détenteur est un processus véritablement zombie, mais plus aucun appelant ne peut rester bloqué indéfiniment à cause de ça.

---

## [0.3.17] — 2026-07-26

### 🐛 Corrigé
- **`/scan` toujours bloqué même après le fix 0.3.16, cette fois pour une vraie raison système** : diagnostic en direct chez l'utilisateur (Gestionnaire des tâches pendant le blocage) — un processus `ffprobe.exe` restait présent à **0% CPU** indéfiniment, bien au-delà du timeout de 30s censé le tuer. Un processus bloqué dans une attente I/O noyau ininterruptible (disque externe qui répond mal, antivirus qui retient un fichier tout juste écrit — exactement le cas des 102 proxys FS5 fraîchement générés) peut être « impossible à tuer » : `TerminateProcess()` ne revient pas tant que l'I/O sous-jacente ne se termine pas, ce qui peut prendre très longtemps voire jamais. Un seul fichier dans cet état gelait toute la boucle du scan — et via le verrou par projet tenu pendant toute la requête, ça gelait en cascade toutes les autres écritures sur ce projet (sauvegarde de notes, etc.), exactement le symptôme observé.
- Fix : `scan_media_folder()` sonde désormais chaque fichier via un thread avec une limite de temps « mur » (`_ffprobe_metadata_bounded`, 20s) — si un fichier ne répond pas dans ce délai, le scan continue avec les métadonnées vides pour ce clip au lieu d'attendre indéfiniment un sous-processus qui ne se terminera peut-être jamais. Dans le pire cas (rarissime), un thread et un slot de la sémaphore ffmpeg restent occupés jusqu'à ce que l'OS libère enfin le processus bloqué — mais le scan et le reste de l'app ne sont plus jamais gelés par un seul fichier problématique.
- Fix additionnel (même classe de bug que 0.3.16, trouvée en creusant) : `/api/crash` lisait lui aussi le corps de la requête une deuxième fois — supprimé, même s'il n'a pas été observé en cause dans cet incident.

---

## [0.3.16] — 2026-07-26

### 🐛 Corrigé
- **`/scan` restait bloqué indéfiniment (« sablier » qui ne se termine jamais)** : le handler du rescan lisait le corps de la requête POST **deux fois** (une fois dans le dispatcher partagé, une deuxième fois — redondante — dans le handler lui-même). La deuxième lecture bloquait indéfiniment sur le socket en attendant des octets déjà consommés par la première, qui n'arriveraient jamais. Bug reproduit en conditions réelles (requête HTTP authentifiée contre le serveur réel) : la requête restait « pending » indéfiniment, sans jamais atteindre `scan_media_folder()`. Supprimée la lecture redondante — même test, réponse propre en 51,9s. C'était très probablement la vraie cause des plantages précédents (0.3.14/0.3.15) : le corps mort tenait aussi le verrou par projet, bloquant en cascade toute autre sauvegarde sur ce projet.

---

## [0.3.15] — 2026-07-26

### 🐛 Corrigé
- **Le fix du 0.3.14 ne couvrait que le rescan** : l'app a pu se fermer à nouveau, cette fois après une navigation normale (pas de rescan, pas de décodage LTC en cours) sur un lot de ~100 clips jamais ouverts auparavant — même mécanisme (watchdog heartbeat trop court face à une rafale de charge légitime : génération de vignettes/waveforms/strips pour des clips neufs). Deux changements, plus généraux que le fix précédent : (1) **toute** requête HTTP entrante (pas seulement `/api/heartbeat`) prouve désormais que le navigateur est actif et rafraîchit le heartbeat — une rafale de requêtes vignettes/proxy/waveform pendant la navigation compte comme preuve de vie ; (2) marge portée de 12 à **30 secondes** pour absorber les à-coups de charge sans changer la détection (raisonnablement rapide) d'un onglet réellement fermé.

---

## [0.3.14] — 2026-07-26

### 🐛 Corrigé
- **Rescan qui pouvait faire fermer l'application** (grave) : sur un gros projet (400+ clips), un rescan complet peut légitimement prendre 30 à 60+ secondes (ffprobe par fichier). Le watchdog anti-fuite (fermeture auto si l'onglet est fermé) ne tolérait que 12 secondes sans heartbeat client — un scan un peu long pouvait déclencher une fermeture silencieuse du serveur (`os._exit(0)`, aucune trace dans le journal des erreurs). Le scan rafraîchit désormais lui-même le heartbeat à chaque fichier traité, prouvant sa propre activité indépendamment du client. Reproduit et vérifié : un scan de 428 clips (~65s) qui tuait le process avant le fix se termine maintenant normalement.

---

## [0.3.13] — 2026-07-26

### 🐛 Corrigé
- **Comparateur — reprise sur une position obsolète** : ouvrir ⚡ Comparer chargeait le slot gauche avec la dernière position mémorisée d'une session comparateur précédente sur ce clip (ex. 3/4 de la timeline), au lieu de la position réelle en cours dans le lecteur principal. Ouvrir Comparer synchronise désormais le slot 0 sur l'endroit exact où était le lecteur principal.
- **Comparateur — barre de progression figée** : charger un nouveau clip dans un slot pouvait laisser la barre de progression affichée à la position du clip précédent tant qu'aucun `timeupdate` n'avait refiré (typiquement un clip qui démarre à 0 et reste en pause). La barre et le TC sont désormais réinitialisés immédiatement au chargement.

### ✨ Ajouté
- **Miniatures dans le sélecteur de clips du comparateur** : le menu déroulant de chaque slot affiche désormais une vignette devant chaque nom de fichier pour repérer les clips plus facilement. Remplace le `<select>` natif par un combo custom (le `<select>` est gardé caché comme source de vérité pour le reste du code).

---

## [0.3.12] — 2026-07-26

### ✨ Ajouté
- **Reprise de la position de lecture par clip** : quitter un clip en cours de lecture (dans le lecteur principal, un slot du comparateur, ou le viewer multicam) puis y revenir replace la tête de lecture là où elle avait été laissée, au lieu de repartir du début. Mémorisation en mémoire pour la session en cours (`_clipResumeTime` par `clip.id`, `_mcGroupResumeTime` par groupe multicam) — pas de persistance entre relances de l'app.

---

## [0.3.11] — 2026-07-26

### 🐛 Corrigé
- **Perte de clips au rescan** (grave) : un scan lancé avec un chemin de rushs momentanément invalide (ex. lettre de lecteur d'un disque externe qui a changé) ne trouvait aucun fichier et **écrasait silencieusement** la liste de clips existante du projet — 428 clips perdus en un clic dans un cas réel. `POST /api/project/<pid>/scan` refuse désormais d'appliquer un résultat qui contiendrait moins de la moitié des clips existants (HTTP 409, rien n'est modifié) ; il faut relancer explicitement avec `force:true` pour confirmer un vidage volontaire. Le bouton 🔄 Rescanner du frontend affiche l'avertissement en toast et permet de forcer en recliquant dans les 15 secondes — aucun `confirm()` natif utilisé (cf. bug focus Electron déjà connu).

---

## [0.3.10] — 2026-07-26

### 🐛 Corrigé
- **Timeline invisible en plein écran** : `⤢ Plein écran` ne mettait en fullscreen que la vidéo elle-même (`#videoWrapper`) — la barre de transport et la timeline (avec les marqueurs) restaient en dehors et disparaissaient. Un nouveau conteneur (`#playerFsWrap`) englobe désormais la vidéo + la barre de contrôle + la timeline, donc les marqueurs restent visibles et cliquables en plein écran. Le comparateur avait déjà ses marqueurs sur la timeline de chaque slot (`renderCmpMarkers`) — si un exécutable installé ne les affiche pas, c'est probablement un build antérieur à cette fonctionnalité, pas un bug du code actuel : redéployer depuis les sources courantes.

### 🎨 Interface
- **Bouton 💾 Sauver** déplacé de la barre d'outils flottante vers la barre du bas (`player-controls`), à côté du statut de sauvegarde — toujours visible sans ouvrir la colonne d'icônes.

---

## [0.3.9] — 2026-06-04

### 🎨 Interface
- **Réorganisation des contrôles du lecteur** : la barre du bas ne garde plus que la lecture (timer, sauts, ⏯, vitesses 1×→2×). Tous les outils (Comparer, Cadre, LUT, Multi-cam, Session, Exporter, Partager, Santé, Stats, Sync, Sauver) passent dans une **barre d'icônes verticale flottante** en haut à droite de la vidéo.
- **Cadre / format appliqué partout** : le format choisi (4:3, 2.39:1…) s'applique maintenant aussi dans le **comparateur** (les deux clips) et dans le **viewer multi-cam** (tous les angles), pas seulement sur le lecteur principal.
- **Comparateur — hauteurs égales** : les deux clips s'affichent désormais exactement à la même taille (colonnes forcées égales via `min-width: 0`, affichage `object-fit: contain`).
- **Bandes noires incrustées rognées automatiquement** : les rushs tournés avec un cache cinéma baké dans l'image (ex. matte 1.9:1 des FX6 du J01) sont détectés (ffmpeg côté serveur) et affichés **sans les bandes**, dans le lecteur, le comparateur et le multi-cam. Une FX6 mattée s'aligne donc en hauteur avec une FS5 plein cadre. Le cadre/format (4:3, 2.39:1…) se cale aussi sur l'image réelle.

### 🐛 Corrigé
- **Sync en cours de session** : les notes et commentaires des autres collaborateurs apparaissent maintenant automatiquement (en ≤ 60 s) sans avoir à cliquer sur « Synchroniser » ni à rouvrir le projet. Le rafraîchissement automatique faisait jusqu'ici une simple relecture locale ; il déclenche désormais un *pull* léger depuis le cloud.
- **Cadre / format d'image** : le cadre se délimite désormais sur l'**image réelle**. Si un rush a des bandes noires incrustées (master letterboxé), un format comme 4:3 ne calera plus son haut/bas dans ces bandes — il les détecte et s'aligne sur l'image visible.

### 🏗️ Interne
- `sync_project(pid, push=False)` : mode *pull-only* (ramène + fusionne sans renvoyer vers le cloud), n'écrit le fichier projet que si la fusion change réellement quelque chose (plus de rotation inutile des backups locaux).
- Nouvel endpoint `POST /api/sync/pull`.
- Détection client-side des bandes noires incrustées (`_detectContentInsets` / `_contentInsets` par clip, accumulation du minimum, seuil luma 24).

---

## [0.3.8] — 2026-06-01

### ✨ Ajouté
- **Mode sombre / clair** : bouton 🌙/☀️ dans la sidebar header, toggle persisté en localStorage.
- **Jauge de progression par utilisateur** : petites barres sous le badge utilisateur montrant combien de clips chaque collaborateur a annotés (ex. Paola 45/200).
- **Filtres sauvegardés (smart bins)** : bouton "+ Sauver" qui apparaît dès qu'un filtre non-défaut est actif. Les presets sont nommés automatiquement (⭐⭐⭐ · 📷 FX6 · 📅 J04), stockés par projet en localStorage, et rappelés par un clic.
- **Notifications @mention** : si un collaborateur écrit `@Sébastien` dans une discussion de marker, une notification desktop s'affiche (demande de permission au premier chargement d'un projet). Fonctionne via WebSocket temps réel et polling.

---

## [0.3.6] — 2026-05-22

### 🔒 Stabilité & sécurité (audit technique)
- **Verrou par projet** : fin des écritures concurrentes qui pouvaient s'écraser entre elles (perte d'annotations).
- **Écriture atomique** des fichiers projet (`.tmp` + `os.replace`) : plus de fichier tronqué en cas de crash.
- **Hachage des mots de passe en PBKDF2** salé (au lieu de SHA-256 nu), migration transparente au login.
- **Anti-brute-force** sur le login (429 après trop d'échecs) ; **expiration** des liens de review (30 j).
- Réponse 500 propre sur erreur serveur ; clé de sync transmissible par en-tête HTTP.

### 🐛 Corrigé
- **Sync** : une suppression de marqueur ne « revient » plus (chaque machine ne publie que ses propres notes).
- **Marqueur perdu** après synchronisation : alignement de la clé de notes entre UI, serveur et export.
- L'utilisateur ne se voit plus lui-même dans « Avis des autres ».
- Barre de génération des aperçus : va jusqu'au bout au lieu de rester bloquée.
- Export FCPXML : timeline complète (fin du dédoublement de clés de notes).

### 🏗️ Interne
- Cache de chargement des projets, indexation FTS debouncée.
- Découpage du serveur en modules (`derush_core`, `derush_exports`) ; tests unitaires Python.

---

## [0.3.5] — 2026-05-19 (soir)

### ✨ Ajouté
- **Support Mac Apple Silicon** (arm64) : `derush.spec` cross-platform, `build_mac.sh` auto-vérificateur, `BUILD_MAC.md` guide complet français, script bash qui vérifie Xcode CLT/Homebrew/Python/Node/ffmpeg et compile le `.app` + zip distribuable.
- **Résolveur de chemins tolérant** : `_resolve_relpath_tolerant()` walk segment par segment avec variantes numériques (`01↔1↔001`) et case-insensitive. Fix le cas SSD copié entre PCs où les noms de slot perdent leur zéro de tête.
- **Skeleton shimmer + barre de progression** des thumbnails : feedback visuel pendant la génération initiale (5+ min sur fresh install). Compteur dédoublonné « X / 428 aperçus prêts ».
- **Spinner sur le player vidéo** + écran d'erreur explicite (chemin demandé + code HTTP) si le proxy est introuvable.
- **Placeholder ⚠ rouge** sur les vignettes en 404 (au lieu de l'icône image-cassée du browser).
- **Bouton 📁 Parcourir** dans le setup wizard pour pointer le dossier projets via dialog natif.
- **Messages d'erreur sync clairs** : « Clé sync incorrecte », « Aucun projet trouvé », « Serveur injoignable » au lieu des codes HTTP bruts.
- **Distribution zip Windows** (au lieu de portable .exe auto-extractible) : démarrage 3–5s au lieu de 1 min.

### 🐛 Corrigé
- **Tombstone bug** : un user supprimé puis re-créé disparaissait à chaque sync car le tombstone le re-filtrait. Fix dans `authorize_user` (lift local) et `merge_projects` (un user vivant en local lève le tombstone globalement).
- **URL encoding sync** : crash `URL can't contain control characters` quand le pid contient un espace. Fix `_urlquote()` + validation locale `re.match(r'^[a-zA-Z0-9_\-]+$')`.
- **tkinter folder picker sur Mac** : hangue silencieux car tkinter doit tourner sur le main thread. Remplacé par `osascript` natif macOS (NSOpenPanel via AppleScript). Windows garde tkinter.
- **« Rejoindre un projet » sur la page de login** : retiré (contre-intuitif, on ne peut pas rejoindre sans être connecté). Reste visible uniquement après login.
- **403 « Accès refusé » silencieux** sur set_root_path : message diagnostique explicite (« L'utilisateur X n'est pas inscrit sur ce projet. Users actuels : … »).

---

## [0.3.0] — 2026-05-19

### ✨ Ajouté
- **Auto-détection de plans** : bouton 🔍 Auto-plans qui scanne les rushs via ffmpeg scene change et propose des markers candidats. Clic gauche = accepter, droit = rejeter.
- **Session live** : un utilisateur peut diriger la session et ses actions (clip select, seek, play/pause) sont diffusées aux autres en temps réel via WebSocket. Bouton 🎬 Diriger / 👁 Suivre.
- **Édition collaborateurs** : bouton ✏️ dans la gestion utilisateurs pour modifier rôle, couleur, ou régénérer une clé d'invitation perdue.
- **Stats dashboard** 📊 : modal avec cards totaux, progression %, distribution ratings/markers/caméras/jours, top tags, activité par utilisateur.
- **Modal À propos** ℹ️ : logo + version + liens GitHub/Releases/Guide.
- **Splash window amélioré** : logo embarqué + animation breath + barre progress, fond gradient.
- **Icône taskbar Electron** : icône custom dans la barre Windows + barre titre.

### 🐛 Corrigé
- **Auto-détection 0 candidats** : `-loglevel info` masquait les lignes showinfo de ffmpeg → 0 résultats. Passé à `verbose` + regex stricte pour éliminer le faux positif à t=0 venant du log graph.
- **Bouton 🔑 invite key cassé** : `JSON.stringify(uname)` dans attribut HTML double-quoted → guillemets imbriqués → onclick invalide. Fix : attribut single-quoted.

### 🧪 Stabilité
- **Tests E2E auto-detect + session-live** : 9 tests supplémentaires (Playwright), total 23/23 passants.

---

## [0.2.0] — 2026-05-19

### ✨ Ajouté
- **Son ingé sur player single** : bouton 🔊 Son ingé qui apparaît automatiquement quand un BWF couvre le clip. Sync TC parfait avec le video. Cohérent visuellement avec celui du multicam (vert éclatant = ingé / barré = caméra).
- **BWF multipistes** : downmix WebAudio API de toutes les pistes (jusqu'à 8) vers stéréo. Tu entends toutes les pistes mélangées au lieu des 2 premières seulement.
- **Lien de review partageable** : bouton 🔗 Partager → URL publique unique qui montre annotations + 4 previews HD 640×360 par clip + formulaire commentaires. Pas besoin d'installer quoi que ce soit côté client/réal.
- **Retours externes** : les commentaires postés via le lien partagé arrivent dans Derush, affichés sous chaque clip dans la section "🔗 Retours externes".
- **Crash reporter** : capture des exceptions Python + JS, journal `%APPDATA%\DerushTool\crashes.jsonl`, viewer "🐞 Journal des erreurs" depuis l'écran projets.
- **Export Adobe Premiere XML** (Final Cut Pro 7 XML) : nouveau bouton dans le modal Export, supporte markers + ratings + zones X coupées.
- **LUT scoping par caméra** : à l'ouverture d'un .cube, popup pour choisir les caméras concernées (ou "ce rush uniquement"). Activation/désactivation auto selon le clip.
- **Réglages LUT** : panneau intensité (0-100%), exposition (-2/+2 EV), saturation (0-200%). Pipeline GPU expo→LUT→intensité→satu→dithering.
- **Dithering anti-banding** : bruit sub-pixel ±0.5/255 dans le shader LUT, casse les bandes visibles sur les ciels/dégradés sans perception consciente.
- **Sync cloud hardening** : pull au moment d'ouvrir un projet + push debounced 3s après chaque save (au lieu d'attendre 10 min).
- **Swap multicam** : bouton 🔄 Swap qui intervertit physiquement les emplacements gauche/droite des vidéos.
- **Login pré-rempli** : checkbox "Se souvenir de moi", credentials sauvegardés dans localStorage.

### 🎨 Amélioré
- **LUT preview** : passage Canvas 2D nearest-neighbour 480px → WebGL2 + sampler3D + interpolation trilinéaire HW pleine résolution. Plus de pixelisation ni de banding.
- **Timeline** : passe de 48 → 88px. Markers compacts (12×12) avec stacking vertical anti-overlap (3 niveaux). Chaque pin reste cliquable même en cluster.
- **Shapes markers** différenciées : 1/2/3 cercle, T (problème image) carré, S (problème son) triangle, D (note) losange, X (à couper) croix.
- **Labels** : "Image"/"Son" → "Problème image"/"Problème son" (plus explicite).
- **4 previews HD share** : 640×360 lanczos q=3 (vs 320×180 fast_bilinear avant).
- **Splash window Electron** au démarrage avec barre de progression CSS pendant le boot du backend.
- **Scrollbar custom** fine violet translucide dans toute l'app.

### 🐛 Corrigé
- **Bug textarea popup marker** : `confirm()` natif cassait le focus state Chromium → textarea inéditable après suppression d'un marker. Tous les `confirm()` virés et remplacés par toast.
- **Bug saveDrawing** : `prompt()` désactivé dans Electron renvoyait null silencieusement → le bouton Valider ne créait pas le marker. Réutilise le popup marker existant.
- **Bug navigateur double** : le bundle PyInstaller ouvrait Firefox en plus d'Electron au démarrage. `--no-browser` honoré dans `derush_launcher.py`.
- **Bug ratio LUT** : `object-fit: contain` sur le canvas LUT pour matcher l'aspect du video.
- **Bug commentaires dupliqués share** : pull concurrent → N copies. Lock per-pid + dédoublonnage rétroactif.
- **Bug commentaire `since=None`** : comparaison alphanumérique `'2026-' <= 'None'` → tous les commentaires filtrés.
- **Bug scroll viewer share** : div #root sans flex/height → aside ne pouvait pas scroller.
- **Caret invisible** : textarea créée hors du popup display:none → Chromium n'initialisait pas le caret. Création maintenant après popup visible (double RAF).
- **Head timeline derrière waveform** : isolation stacking context + z-index head 20.

### ⚡ Performance
- **PyInstaller passage onefile → onedir** : startup quasi instantané au 2e lancement (cache portable). 226 MB → 183 MB.
- **Custom ffmpeg semaphore** : max 8 ffmpeg concurrents globaux, throttle interne `compute_strip` à 3 workers.
- **Dedup compute** : 2 requêtes simultanées sur même clip = 1 seul ffmpeg.
- **Waveform numpy-isé** : 10× moins RAM, 100× plus rapide.

---

## [0.1.0] — 2026-05-18

### 🎉 Première release portable
- Wrapper Electron + PyInstaller onefile (226 MB).
- Toutes les features de base : login, projets, scan, ratings, markers, drawings, tags, notes, exports DaVinci, sync cloud, multicam, BWF.
