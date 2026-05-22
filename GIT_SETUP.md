# Connecter une nouvelle machine à GitHub

Ce guide explique comment installer le code de Derush Tool sur un **nouvel
ordinateur** (Windows ou Mac) et pouvoir récupérer / envoyer le code.

**Dépôt** : https://github.com/davebixby/derush-tool

Une fois en place, la synchro du code se fait avec **un seul script** :
`sync.ps1` (Windows) ou `sync.sh` (Mac) — voir la fin de ce guide.

---

## 1. Installer git

- **Windows** : télécharge l'installeur sur https://git-scm.com/download/win
  et installe-le (tout par défaut).
- **Mac** : git est déjà là si tu as installé les Xcode Command Line Tools
  (`xcode-select --install`). Sinon : `brew install git`.

Vérifie dans un terminal : `git --version`.

## 2. Installer GitHub CLI (le plus simple pour s'identifier)

- **Windows** : installeur sur https://cli.github.com/
- **Mac** : `brew install gh`

## 3. S'identifier auprès de GitHub (une fois par machine)

Dans un terminal :

```
gh auth login
```

Réponds aux questions :
- *What account do you want to log into?* → **GitHub.com**
- *Preferred protocol?* → **HTTPS**
- *Authenticate Git with your GitHub credentials?* → **Yes**
- *How would you like to authenticate?* → **Login with a web browser**

Un code à 8 caractères s'affiche → copie-le. Le navigateur s'ouvre : colle le
code et autorise. C'est mémorisé : tu n'as plus jamais à le refaire sur cette
machine.

> ⚠️ Connecte-toi avec un compte GitHub qui a les **droits d'écriture** sur
> `davebixby/derush-tool` (le compte propriétaire, ou un compte invité comme
> collaborateur).

## 4. Récupérer le projet

Choisis où mettre le dossier, puis clone :

```
# Mac
cd ~/Documents
git clone https://github.com/davebixby/derush-tool.git
cd derush-tool

# Windows (PowerShell)
cd $HOME\Documents
git clone https://github.com/davebixby/derush-tool.git
cd derush-tool
```

Tu as maintenant tout le code, à jour.

## 5. Dire à git qui tu es (une fois)

```
git config --global user.name "Sebastien Delahaye"
git config --global user.email "delahaye.sebastien@gmail.com"
```

## 6. Au quotidien : le script `sync`

Plus besoin de retenir les commandes git. Depuis le dossier du projet :

- **Windows** : `.\sync.ps1`
- **Mac** : `./sync.sh` (la toute première fois : `chmod +x sync.sh`)

Le script fait tout : il **commite** tes modifs, **récupère** celles des autres
machines, et **renvoie** le tout sur GitHub.

Tu peux préciser un message :
```
.\sync.ps1 "ajout du bouton export"
./sync.sh  "ajout du bouton export"
```

> Encore plus simple : demande à Claude Code « **commite et pousse** » ou
> « **récupère les dernières modifs** » — il lance les bonnes commandes.

**Règle d'or** : lance `sync` **avant** de commencer à travailler (pour partir
à jour) et **après** avoir fini (pour publier).

---

## Dépannage

**Le push échoue / demande un mot de passe (erreur 403)**
→ L'authentification n'est pas faite sur cette machine. Refais l'étape 3
(`gh auth login`). Le mot de passe GitHub classique ne fonctionne plus pour
git depuis 2021 — il faut `gh auth login` ou un *Personal Access Token*.

**« CONFLIT pendant la fusion »**
→ Le même fichier a été modifié sur deux machines en même temps. Demande à
Claude de résoudre le conflit, ou annule avec `git rebase --abort` puis
recommence.

**Config et données ne sont pas sur GitHub — c'est normal**
→ `derush_config.json`, le dossier `projects/`, `derush_sync.php`, `index.db`
sont **volontairement exclus** (ils contiennent ta config locale, tes données
projet et des clés secrètes). Sur une nouvelle machine, tu refais la
configuration via le wizard de l'application au premier lancement.

**Ne pas confondre les deux synchros**
- `sync.ps1` / `sync.sh` → synchronise le **code de l'application** (via GitHub).
- La synchro **cloud dans l'app** (bouton ☁️) → synchronise les **données
  projet** (annotations, marqueurs) entre collaborateurs. C'est indépendant.
