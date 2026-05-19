# Tests E2E Derush Tool

Tests Playwright qui lancent le backend Python en mode dev et vérifient les workflows critiques.

## Setup (une fois)

```bash
cd tests
npm install
npm run install-browsers   # télécharge Chromium pour Playwright
```

## Lancer les tests

```bash
npm test                   # tous les tests en mode headless
npm run test:headed        # tests avec fenêtre browser visible (debug visuel)
npm run test:ui            # UI Playwright interactive
npm run test:debug         # debugger pas-à-pas
```

## Configuration

Les tests qui nécessitent un user/projet existants lisent ces variables d'env :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `DERUSH_TEST_USER` | `Sébastien` | Username pour le login |
| `DERUSH_TEST_PASS` | _(vide)_ | Mot de passe. Si vide, les tests authentifiés sont skipés. |
| `DERUSH_TEST_PROJECT` | `drift_club` | ID du projet de test |

Exemple PowerShell :
```powershell
$env:DERUSH_TEST_PASS = "monmdp"; npm test
```

Exemple bash :
```bash
DERUSH_TEST_PASS=monmdp npm test
```

## Tests inclus

- `smoke.spec.js` — page de login charge, endpoints version/changelog OK
- `auth.spec.js` — login flow complet (skipé si pas de password)
- `markers.spec.js` — **le bug textarea** : add → write → delete → re-add → write
- `drawing.spec.js` — startDrawing → draw → validate → marker créé avec dessin
- `changelog.spec.js` — modal nouveautés via lien footer

## Que faire quand un test échoue

1. `npm run test:headed` pour voir ce qui se passe visuellement
2. Inspecter le HTML rendu : `test-results/<test-name>/`
3. Les screenshots de l'échec sont automatiques en `failure` mode
