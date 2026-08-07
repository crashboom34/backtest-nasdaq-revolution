# Rapport de portabilité Linux — PH0-OCI-01

> Voir `docs/INDEX.md` pour la navigation. Référence Git de départ : `62e9282363631a95dfbdf6df6a64b6ffafacec7b`
> (`master` = `origin/master`, working tree propre au démarrage et à la fin de cette session).
> Décision associée : [ADR 0015](../adr/0015-oracle-cloud-infrastructure-payg.md) (Oracle Cloud
> Infrastructure PAYG). Ticket : `docs/roadmap/EPICS_AND_TICKETS.md` → `PH0-OCI-01`.

Libellés utilisés : **Compatible** (aucune action requise) / **Compatible sous condition**
(fonctionne, avec une réserve documentée) / **Correction requise** (action concrète à faire,
listée en section 8) / **Bloquant** (empêcherait un déploiement Linux) / **Hors périmètre**.

## 1. Environnement testé

**Constat initial important** : ni Docker ni WSL2 ne sont réellement disponibles sur ce poste
(vérifié, pas supposé) :
- `docker --version` → `docker: command not found`.
- `wsl --status` / `wsl -l -v` → erreur "le chemin d'accès spécifié est introuvable" (le
  sous-système WSL n'est pas activé ; l'activer nécessite des privilèges administrateur non
  disponibles dans cette session).
- Aucun workflow GitHub Actions (`.github/workflows/` absent).

**Conséquence** : le **Palier A** (exécution dynamique réelle sous Linux) n'a **pas** pu être
exécuté cette session. Ce qui suit est :
1. Un **audit statique exhaustif** du code (32 catégories couvertes, regroupant les points
   demandés en section 4 de la mission), qui ne dépend d'aucun environnement Linux réel.
2. Une **vérification de résolution de dépendances Linux réelle** via `pip download
   --platform` (simule la résolution PyPI pour Linux/glibc/Python 3.13 sans nécessiter de
   machine Linux — méthode fiable pour ce point précis, détaillée en section 6).
3. Des **tests dynamiques légers exécutés sous Windows** (section 7), qui valident la logique
   applicative mais **ne remplacent pas** une exécution Linux réelle pour les aspects propres à
   l'OS (limites du filesystem, comportement runtime des extensions C, etc.).

| Élément | Valeur |
|---|---|
| Système d'exécution des tests de cette session | Windows 10, poste de développement |
| Version Python locale | 3.13.7 (`.venv\Scripts\python.exe`) |
| Système Linux testé dynamiquement | **Aucun** — indisponible cette session (voir ci-dessus) |
| Système Linux ciblé pour la vérification statique des wheels | `manylinux2014`/`manylinux_2_17`/`manylinux_2_28`/`manylinux_2_34`, `x86_64`, `cp313` (couvre la plage de distributions Linux courantes, d'Oracle Linux 7 à 9 / Ubuntu 18.04 à 24.04) |

## 2. Dépendances système

Aucune dépendance système Linux (paquet `apt`/`dnf`) n'a pu être testée réellement (pas de
machine Linux disponible). D'après l'audit statique (section 4) : aucune bibliothèque graphique
système (X11, GTK) n'est requise (`matplotlib` n'est utilisé nulle part dans le code applicatif
actuel — dépendance déclarée mais inerte) ; Pillow/Plotly embarquent leurs bibliothèques C
(libjpeg/libpng) dans leurs wheels manylinux. **Aucune dépendance système Linux identifiée comme
requise** pour ce dépôt en l'état — à confirmer lors du premier déploiement réel (Palier B).

## 3. Commandes utilisées

```bash
# Vérification Docker/WSL2/CI (négatif, voir section 1)
docker --version
wsl --status ; wsl -l -v
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux   # nécessite admin, non exécutable

# Suite de tests hors ligne existante (baseline, Windows)
.venv\Scripts\python.exe -m pytest tests/ -q --basetemp=C:/pytmp

# Vérification de résolution des wheels Linux (sans machine Linux, via pip download --platform)
.venv\Scripts\pip.exe download -r requirements-server.txt --no-deps --dest <tmp> \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_34_x86_64 \
  --python-version 313 --implementation cp --abi cp313 --only-binary=:all:

# Tests légers dynamiques (script dédié, données synthétiques, BACKTEST_BASE_DIR isolé)
.venv\Scripts\python.exe ph0_oci_01_smoke_tests.py

# Test de reprise de job (resume_run_id), script dédié
.venv\Scripts\python.exe ph0_oci_01_resume_test.py
```

## 4. Audit statique de portabilité — 32 catégories

Réalisé par 4 audits parallèles ciblés (`Agent`), classification par catégorie :

| Catégorie | Verdict | Détail |
|---|---|---|
| Chemins Windows codés en dur | **Compatible** | Seules occurrences : docstrings d'exemple de `path_resolver.py` et assertions de test qui vérifient leur absence |
| Séparateurs `\` pour construire des chemins | **Compatible** | Aucune concaténation trouvée ; toutes les occurrences de `\\` sont des `\n` |
| Différences de casse dans les chemins/fichiers | **Compatible** | Aucun fichier dupliqué à la casse près (non trouvé après recherche) |
| Encodages non-UTF-8 | **Compatible sous condition** | Un seul `open()` sans `encoding=` explicite en mode texte (`optimization_store.py:238`, écrit `"stop"` ASCII — inoffensif mais correction recommandée par prudence) |
| Fins de ligne | **Compatible sous condition** | Tout le contenu indexé Git est `LF` (vérifié `git ls-files --eol`) ; recommandé d'ajouter un `.gitattributes` pour l'imposer plutôt que de dépendre de la config Git de chaque contributeur |
| Permissions d'exécution | **Correction requise (documentaire)** | Aucun script `.sh` équivalent à `lancer_app.bat` — absence à documenter/combler avant Phase 1 |
| Fichiers temporaires | **Compatible** | `demo_data.py`/`optimization_store.py` utilisent `tempfile.gettempdir()`/`tempfile.NamedTemporaryFile` (portable) ; aucun `%TEMP%` en dur trouvé |
| `path_resolver.py` (BACKTEST_BASE_DIR, chemins POSIX) | **Compatible** | Lu intégralement ; consommé correctement par tous les points d'écriture JSON audités |
| Garde `if __name__ == "__main__":`| **Compatible** | Présent dans `run_job.py` et `optimizer_process.py` (seuls scripts exécutés en subprocess séparé) |
| `ProcessPoolExecutor` (spawn/fork) | **Compatible sous condition** | Pas de `mp_context` explicite ; le code transmet l'état via `initializer`/`initargs` (pattern déjà compatible spawn ET fork, déjà validé en production sous spawn/Windows) ; delta de performance possible (pas de correction) entre fork (Linux) et spawn |
| `subprocess.Popen` (flags Windows) | **Compatible** | Aucun `creationflags`/`shell=True` ; commande construite en liste d'arguments |
| Gestion des signaux | **Compatible** | Aucun usage de `signal` dans le code ; arrêt piloté entièrement par `stop.flag` (fichier, polling) |
| Verrouillage de fichiers | **Compatible** | Aucun lock système (`fcntl`/`msvcrt`) ; uniquement retry sur `os.replace()` |
| Écriture atomique JSON / `os.replace()` | **Compatible** | `atomic_write_json()` retry sur `PermissionError` générique (portable) ; branche `winerror` inerte et sûre sous Linux ; tous les fichiers temporaires créés dans le même dossier que la cible (condition d'atomicité respectée) |
| Verrou "un seul job actif" | **Compatible** | Basé uniquement sur l'état disque (statuts JSON + `stop.flag` + mtime), aucun PID/mutex système |
| Dépendances Python (wheels Linux) | **Compatible, vérifié réellement** | Voir section 6 — un problème réel trouvé et documenté (`contourpy`) |
| Streamlit headless | **Correction requise** | `.streamlit/config.toml:5` → `headless = false`, à passer à `true` pour un déploiement serveur sans affichage |
| Ouverture automatique du navigateur (code applicatif) | **Compatible** | Aucun `webbrowser.open()` dans le code ; le comportement observé vient uniquement de Streamlit lui-même |
| Port | **Compatible** | `8501`, cohérent entre `.streamlit/config.toml`, `README.md`, `AI_HANDOFF.md` |
| Génération HTML (`report.html`, exports Champion) | **Compatible** | Template Python pur (f-strings + `html.escape()`), aucun moteur externe (pas de wkhtmltopdf/Selenium/LibreOffice) |
| Bibliothèques graphiques | **Compatible** | `matplotlib` déclaré mais non utilisé dans le code applicatif ; Pillow/Plotly portables (wheels manylinux) |
| openpyxl / Excel | **Compatible sous condition** | Déclaré dans les deux `requirements*.txt` mais **non utilisé** dans le code (`to_excel`/`read_excel`/`ExcelWriter` : 0 occurrence) — candidat à un nettoyage futur, sans impact sur la portabilité |
| MetaTrader 5 | **Compatible** | Isolé à `get_data.py`/`check_mt5.py`, jamais importé par le pipeline applicatif ; absent de `requirements-server.txt` |
| ProRealTime | **Compatible** | Présent uniquement en commentaires descriptifs ("traduction fidèle du code ProRealTime"), aucune dépendance technique |
| Excel / LibreOffice (dépendance système) | **Compatible** | Aucune dépendance à un logiciel externe installé sur la machine |
| Secrets dans les logs | **Compatible** | Reconfirmé par lecture directe : `provider_config.py`/`ig/config.py`/`eodhd/config.py`/scripts de test rédigent systématiquement les secrets ; `logs.txt` d'un job de backtest ne peut aujourd'hui contenir aucune exception EODHD/IG (le pipeline de job n'importe pas ces modules) |
| Variables d'environnement | **Compatible** | `BACKTEST_BASE_DIR`, `BACKTEST_DATA_DIR`, `BACKTEST_JOB_DIR`, `BACKTEST_EODHD_API_KEY`, `BACKTEST_IG_*`, `BACKTEST_RUN_LIVE_PROVIDER_TESTS` — toutes lues via `os.environ`/`os.getenv`, aucune dépendance registre Windows |
| Stockage des données | **Compatible** | `BACKTEST_DATA_DIR` sans défaut implicite (fail-fast explicite si absent, conçu dès l'origine pour un déploiement Linux — docstring `path_resolver.py` documente `export BACKTEST_BASE_DIR=/app`) |
| SQLite | **Compatible** | Confirmé absent (aucun `sqlite3`/`.db`/ORM dans le code) |
| Scripts `.bat`/`.ps1` sans alternative Linux | **Correction requise (documentaire)** | `lancer_app.bat` est un simple raccourci (`cd` + commande `streamlit run` + `pause`) ; aucune logique indispensable, remplacé nativement par la commande directe ou un futur `docker-compose`/service systemd |
| `.gitignore` | **Compatible** | Règles déjà multi-OS (`.DS_Store` macOS + `Thumbs.db`/`desktop.ini` Windows), aucune règle Linux manquante |
| Collecte pytest à la racine (hygiène, pas portabilité pure) | **Correction requise** | `pytest` lancé sans argument depuis la racine tente de collecter les scripts procéduraux `test_e2e_parallel.py`/`test_e2e_subprocess.py`/`test_path_resolver.py` (non conçus comme tests pytest) — provoque une `INTERNALERROR` sur `test_path_resolver.py` (son `sys.exit()` de niveau module lève pendant la collection). Reproductible sous Linux également (indépendant de l'OS) — un `pytest.ini`/`pyproject.toml` avec `testpaths = tests` corrigerait ce point une fois pour toutes |

## 5. Différences Windows/Linux résumées

| Aspect | Windows (actuel) | Linux (cible) |
|---|---|---|
| Lancement de l'interface | `lancer_app.bat` (double-clic) | Commande directe `streamlit run app.py` ou service Docker/systemd (à créer, Phase 1) |
| `headless` Streamlit | `false` (ouvre un navigateur local) | Doit passer à `true` (pas d'affichage sur un serveur) |
| Multiprocessing | `spawn` (forcé par l'OS) | `fork` par défaut (Python < 3.14) ou `spawn` (Python ≥ 3.14) — le code est déjà compatible avec les deux |
| `PermissionError`/`WinError 5` sur écriture atomique | Cas réel rencontré (antivirus/lecteur Streamlit) | Cas rare (`EACCES` seulement si permissions insuffisantes) — la branche `winerror` reste inerte, sans danger |
| Wheels de dépendances lourdes (`contourpy`, `pandas`, `scipy`) | N/A (roues Windows) | Nécessitent glibc ≥ 2.28 (voir section 6) — satisfait par les images Oracle Linux 8/9 et Ubuntu 20.04+/22.04+/24.04 standard |

## 6. Dépendances Python — vérification réelle de résolution Linux

**Méthode** : `pip download -r requirements-server.txt --platform <tags> --python-version 313
--implementation cp --abi cp313 --only-binary=:all:` — force pip à résoudre chaque paquet comme
s'il tournait sur une vraie machine Linux/glibc/CPython 3.13, sans nécessiter cette machine. Fiable
pour vérifier la disponibilité réelle des wheels (contrairement à une simple lecture de
`requirements.txt`).

**Résultat** : avec les 4 tags manylinux combinés (`manylinux2014`, `manylinux_2_17`,
`manylinux_2_28`, `manylinux_2_34`, tous `x86_64`), **les 24 paquets de `requirements-server.txt`
se résolvent tous avec succès** (`Successfully downloaded ...`), y compris les 2 paquets
initialement signalés comme prioritaires à vérifier par l'audit statique :
- `pandas-ta==0.4.71b0` — package réel et maintenu (`pandas-ta.dev`, successeur du projet
  `twopirllc/pandas-ta` abandonné à `0.3.14b0` — confirmé par `pip show`, pas un fork non
  officiel). Wheel `py3-none-any` (pure Python) — **Compatible**.
- `numba==0.61.2` / `llvmlite==0.44.0` — wheels manylinux réelles pour `cp313`/`x86_64` — **Compatible**.

**Point réel trouvé** (nuance à respecter, pas un blocage pratique) : `contourpy==1.3.3` (dépendance
transitive de `matplotlib`, lui-même non utilisé dans le code applicatif — voir section 4) et
`pandas==3.0.3`/`scipy` ne fournissent de wheel binaire **que** pour `manylinux_2_28` (glibc
≥ 2.28), pas pour l'ancien tag `manylinux2014`/`manylinux_2_17` (glibc 2.17). **Conséquence
concrète** : la base OCI choisie en Phase 1 doit avoir glibc ≥ 2.28 — c'est le cas des images
standard Oracle Linux 8/9 et Ubuntu 20.04+ (largement le choix par défaut pour une nouvelle
instance OCI), donc **non bloquant en pratique**, mais à vérifier explicitement si une image plus
ancienne était envisagée (sinon `pip` devrait compiler `contourpy` depuis les sources, nécessitant
un compilateur C++ et rallongeant l'installation).

## 7. Tests exécutés et résultats

### Suite de tests hors ligne existante (baseline)

```
.venv\Scripts\python.exe -m pytest tests/ -q --basetemp=C:/pytmp
535 passed in 228.17s
```
Aucune régression détectée (dépôt inchangé côté code depuis le dernier passage à 535/535).

### Tests légers dédiés PH0-OCI-01 (section 7 de la mission, script dédié, données synthétiques,
`BACKTEST_BASE_DIR` isolé dans un répertoire temporaire — jamais le vrai `results/`, jamais
`nasdaq_3m.csv`)

11 catégories de tests demandées par la mission, couvertes par 14 vérifications élémentaires
(certaines catégories comportent plusieurs vérifications, ex. #4/#4b pour la progression, #7/#7b/#7c
pour la finalisation du job) :

| # | Test | Résultat |
|---|---|---|
| 1 | Import smoke test (`engine`, `optimizer`, `job_launcher`, `market_data.*`) | **OK** |
| 2 | Construction de chemins avec `pathlib`/`path_resolver` (POSIX) | **OK** |
| — | Génération des données synthétiques (pas `nasdaq_3m.csv`) | **OK** — 4 800 lignes |
| 3 | Job directory créé dans un répertoire temporaire isolé | **OK** |
| 4 | `progress.json` mis à jour | **OK** |
| 4b | `progress.json` — statut terminal (`completed`) | **OK** |
| 5 | Sérialisation JSON (`config_used.json`/`meta.json` round-trip) | **OK** |
| 6 | Petit backtest hors ligne (`engine.run_backtest` sur données synthétiques) | **OK** (0 trade — données aléatoires, comportement attendu, pas un échec) |
| 7 | Petit job d'optimisation (2 combinaisons, 1 worker) se termine (`returncode=0`) | **OK** |
| 7b | `results.csv` généré | **OK** |
| 7c | `metrics.json` généré (finalisation) | **OK** |
| 9 | Aucun secret dans `logs.txt` | **OK** |
| 10 | Aucun chemin absolu utilisateur (`C:\Users...`) dans les artefacts | **OK** |
| 8 | Lancement Streamlit headless, banner détecté sous 25 s | **OK** |

**14/14 vérifications réussies** dans ce premier script. Répertoire temporaire nettoyé après
exécution ; `git status --short` vérifié vide avant et après (aucune pollution du dépôt).

**Test de reprise d'un job (catégorie #5 de la mission)** — la fonctionnalité existe réellement
(`resume_run_id` + `tested.json`, voir `COMPUTE_AND_JOBS.md` §4), donc un test réel a été exécuté
dans un second script dédié : job A (3 combinaisons) mené à terme dans un `job_dir` temporaire,
`tested.json` confirmé avec 3 hashes réels ; job B lancé avec `resume_run_id="resume_src"`
pointant vers le job A, mêmes combinaisons. **Résultat : `logs.txt` du job B affiche "Reprise : 0
combinaisons déjà testées"**, alors que 3 étaient réellement disponibles — voir "Tests échoués"
ci-dessous, ce test a mis en évidence un défaut réel, documenté en section 8 (problème #7), pas
appliqué de correctif (hors périmètre de cette session sans autorisation).

**Limite explicite** : l'ensemble de ces tests (14 + le test de reprise) a été exécuté **sous
Windows**, faute d'environnement Linux disponible (section 1). Ils valident la logique
applicative (contrat de fichiers, absence de chemins Windows en dur dans les artefacts, absence de
secrets) mais **ne prouvent pas** le bon fonctionnement réel sous Linux — seule une exécution
Palier A (Docker/WSL2/instance OCI) le prouverait. Voir section 11 pour la procédure future.

### Tests échoués

- **Test de reprise d'un job** (ci-dessus) : le mécanisme `resume_run_id` ne retrouve **pas** les
  combinaisons déjà testées lorsqu'un job tourne dans le pipeline `results/job_xxx/` actuel (voir
  cause exacte en section 8, problème #7). Test exécuté avec succès (aucune erreur d'exécution),
  mais son **résultat révèle un défaut fonctionnel réel** — à distinguer d'un échec du test
  lui-même.
- Un incident de tooling (pas un test à proprement parler) : la collecte `pytest` à la racine du
  dépôt sans argument casse sur les scripts procéduraux (voir section 4, dernière ligne),
  contourné en ciblant explicitement `tests/` — comportement indépendant de Linux/Windows.

## 8. Problèmes trouvés et corrections proposées (état au moment de l'audit — voir section 14 pour les corrections réellement appliquées depuis)

| # | Problème | Gravité | Fichier(s) concerné(s) | Correction proposée (la plus petite possible) |
|---|---|---|---|---|
| 1 | `.streamlit/config.toml` a `headless = false` | Correction requise | `.streamlit/config.toml` | Passer à `headless = true` (a minima pour l'environnement serveur — via un fichier de config séparé ou une variable d'environnement Streamlit, pas nécessairement en cassant l'usage local) |
| 2 | `optimization_store.py:238` — `open(path, "w")` sans `encoding="utf-8"` explicite | Correction requise (mineure) | `optimization_store.py` | Ajouter `encoding="utf-8"` par prudence (contenu actuel ASCII, sans impact fonctionnel connu, mais bonne pratique de portabilité) |
| 3 | Aucun script de lancement Linux (`.sh`) équivalent à `lancer_app.bat` | Correction requise (documentaire) | Nouveau fichier à créer (hors périmètre code de cette session) | Créer un `lancer_app.sh` minimal ou documenter la commande directe dans le futur `docker-compose.yml` (Phase 1) |
| 4 | Absence de `.gitattributes` — la garantie LF dépend de la config Git de chaque contributeur | Non bloquant (recommandation) | Nouveau fichier `.gitattributes` (hors périmètre code de cette session) | `* text=auto eol=lf` |
| 5 | Collecte pytest à la racine casse sur les scripts procéduraux (`test_path_resolver.py`) | Correction requise (config, pas code) | Nouveau `pytest.ini`/section `[tool.pytest.ini_options]` | `testpaths = tests` |
| 6 | `openpyxl`/`matplotlib` déclarés mais non utilisés dans le code applicatif | Non bloquant, nettoyage optionnel | `requirements.txt`, `requirements-server.txt` | Retrait possible en Phase 2+ après confirmation qu'aucun usage futur n'est prévu — **pas proposé maintenant**, aucune urgence |
| 7 | **`resume_run_id` ne retrouve jamais les combinaisons déjà testées dans le pipeline `results/job_xxx/` actuel** — trouvé par le test de reprise (section 7). `optimizer_process.py:280` appelle `load_tested_hashes(config.resume_run_id)` **sans** `job_dir=`, donc `_path()` (`optimization_store.py:106-116`) résout vers l'ancien chemin `optimization_history/{run_id}.tested.json` au lieu de `results/job_xxx/tested.json` — confirmé par test réel : job A termine avec 3 hashes dans `tested.json`, job B avec `resume_run_id` pointant vers A rapporte "0 combinaisons déjà testées". **Pas une régression de cette session** — cohérent avec le constat déjà documenté (`COMPUTE_AND_JOBS.md` §4 : "aucune UI ni CLI ne l'expose"), mais c'est la première fois que le mécanisme est testé en conditions réelles du pipeline job-directory et confirmé silencieusement cassé (aucune erreur levée, juste une reprise vide). | **Correction requise** (bug fonctionnel confirmé, pas seulement une lacune de portabilité) | `optimizer_process.py:280` | Passer `job_dir=job_dir` (la variable module déjà utilisée par tous les autres appels de ce fichier, ex. lignes 194, 269, 339, 423) à l'appel `load_tested_hashes()` ligne 280 — le plus petit changement possible ; nécessite un test dédié avant correction (`/tdd`), hors périmètre de cette session sans autorisation |

**Aucune de ces corrections n'était appliquée au moment de l'audit** — conformément à la mission,
elles attendaient l'autorisation explicite d'utiliser `/implement`. **Cette autorisation a été
donnée dans une session ultérieure** : les problèmes 1, 2, 3, 4, 5 et 7 sont désormais corrigés
— voir section 14. Seul le problème 6 (nettoyage `openpyxl`/`matplotlib`) reste volontairement
non traité (explicitement hors périmètre de la session corrective).

## 9. Éléments bloquants

**Aucun élément réellement bloquant identifié** pour un déploiement Linux du pipeline applicatif
lui-même. Le seul point nécessitant une vigilance concrète (pas un blocage) est le choix d'une
image OCI avec glibc ≥ 2.28 (section 6) — trivialement satisfait par les images standard
actuelles.

**Limite de cette session** (pas un problème de code, une limite d'environnement) : aucune
exécution réelle sous Linux n'a pu être réalisée (Docker/WSL2/CI tous indisponibles) — voir
section 11 pour la procédure qui permettra de lever cette limite.

## 10. Procédure reproductible

```bash
# 1. Vérifier l'environnement Linux disponible avant de commencer
docker --version || echo "Docker absent"
wsl --status || echo "WSL absent/non activé"

# 2. Baseline hors ligne
python -m pytest tests/ -q

# 3. Vérification des wheels Linux (ne nécessite pas de machine Linux)
pip download -r requirements-server.txt --no-deps --dest /tmp/wheel_check \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_34_x86_64 \
  --python-version 313 --implementation cp --abi cp313 --only-binary=:all:
rm -rf /tmp/wheel_check

# 4. Tests légers dynamiques (script dédié, données synthétiques)
python ph0_oci_01_smoke_tests.py
```

## 11. Procédure future pour OCI (Palier B — non exécutée cette session)

1. Provisionner une instance OCI minimale (palier Always Free, Ampere A1 ou petite forme AMD
   E-Flex — voir `BENCHMARK_PLAN.md`), image Oracle Linux 9 ou Ubuntu 22.04/24.04 (glibc ≥ 2.28).
2. Cloner le dépôt, `pip install -r requirements-server.txt` — **exécution réelle** (pas une
   simulation) pour confirmer la résolution de dépendances de la section 6 en conditions réelles.
3. Exécuter la même suite `pytest tests/ -q` réellement sous Linux.
4. Exécuter le même script `ph0_oci_01_smoke_tests.py` (à copier depuis le scratchpad de cette
   session ou régénérer) réellement sous Linux, avec `BACKTEST_BASE_DIR` pointé vers le volume
   persistant OCI (Block Volume).
5. Lancer `streamlit run app.py --server.headless true` réellement, vérifier l'accès HTTP depuis
   l'extérieur (avant tout reverse proxy — juste le port direct pour ce test).
6. Comparer les résultats du petit backtest/optimisation à ceux obtenus sous Windows (section 7)
   — les métriques doivent être strictement identiques (calcul déterministe, mêmes données).
7. Documenter les écarts réels constatés (s'il y en a) dans une mise à jour de ce rapport, pas
   dans un nouveau document.

**Aucune ressource OCI n'a été créée pendant cette session** — cette procédure reste à exécuter
dans une session ultérieure, avec autorisation explicite.

## 12. Critères d'acceptation PH0-OCI-01 — état actuel

| Critère (mission, section 10) | État |
|---|---|
| L'environnement Linux peut installer les dépendances | **Vérifié par simulation de résolution** (section 6, réussi) ; **non vérifié par installation réelle** (pas de machine Linux) |
| Les modules principaux sont importables | **Vérifié sous Windows** (test 1) ; à revérifier sous Linux réel |
| Les tests hors ligne passent ou les exceptions sont documentées | **535/535 passent sous Windows** ; aucune exception à documenter |
| Un petit backtest fonctionne | **Vérifié sous Windows** (test 6) |
| Un petit job d'optimisation fonctionne | **Vérifié sous Windows** (test 7) |
| Le job directory est créé correctement | **Vérifié sous Windows** (test 3) |
| Les fichiers de progression sont mis à jour | **Vérifié sous Windows** (test 4) |
| Streamlit démarre en mode headless | **Vérifié sous Windows** (test 8) — mais `headless=false` doit être corrigé pour un vrai serveur (voir section 8, point 1) |
| Aucune dépendance Windows bloquante ne subsiste | **Confirmé** (MT5 isolé, absent de `requirements-server.txt`) |
| Aucun secret n'est exposé | **Confirmé** (test 9 + relecture des modules provider) |
| Les différences restantes sont documentées | **Oui** (section 5, section 8) |
| La procédure peut être reproduite plus tard sur OCI | **Oui** (section 10-11) |
| *(hors liste initiale, trouvé pendant l'audit)* Reprise de job (`resume_run_id`) fonctionnelle | **Oui, corrigée depuis** (section 14) — bug confirmé au moment de l'audit (section 8, problème #7), corrigé avec test de régression dans la session suivante |

## 13. Décision Go/No-Go

**Go conditionnel** — rien dans cette analyse statique et dans les tests dynamiques sous Windows
n'indique un blocage réel pour un déploiement Linux/OCI. La procédure peut avancer vers un
**premier test réel sur une instance OCI** (Palier B, section 11), qui reste la seule étape
capable de transformer ce "Go conditionnel" en confirmation définitive — aucune exécution Linux
réelle n'a eu lieu cette session.

**Conditions à satisfaire avant de considérer PH0-OCI-01 pleinement clos** (pas des bloquants pour
avancer, mais à faire avant la Phase 1 complète) :
1. Exécuter réellement la procédure de la section 11 sur une instance OCI (même le palier
   gratuit suffit) — **seule condition encore ouverte**, aucune ressource OCI créée à ce jour.
2. ~~Appliquer les corrections listées en section 8~~ — **fait** (session du 2026-08-07, voir
   section 14), sauf le nettoyage optionnel `openpyxl`/`matplotlib` (volontairement non traité).
3. Confirmer que `contourpy`/`pandas`/`scipy` s'installent réellement sur l'image OCI retenue
   (glibc ≥ 2.28 attendu, déjà vérifié par résolution réelle des wheels — section 6 — mais
   l'installation réelle sur l'image retenue reste à confirmer une fois, pas à chaque
   déploiement).

**Statut du ticket `PH0-OCI-01`** : **Implémentation corrective terminée — validation Linux
réelle OCI restante.** Voir section 14 pour le détail des corrections, et
`docs/roadmap/EPICS_AND_TICKETS.md` pour l'état synchronisé du ticket.

## 14. Corrections appliquées (session du 2026-08-07, autorisation explicite)

> Cette section distingue, pour chaque problème de la section 8 : le problème identifié, la
> correction réellement appliquée, le test associé, le résultat obtenu, et ce qui reste à
> vérifier uniquement sous Linux réel (Palier B).

### Bug de reprise de job (`resume_run_id`) — priorité de la session

**Investigation avant correction** (`/tdd`, `/debug`) : l'explication du rapport d'audit
("passer `job_dir=job_dir` à `load_tested_hashes()`") s'est révélée **incomplète à l'examen**.
`job_dir` est le dossier du job **courant** ; le job **source** d'une reprise (désigné par
`resume_run_id`) vit dans un dossier différent. Comme `run_id == job_id` (invariant V1), le job
source vit dans un dossier **frère** de `job_dir`, sous le même `results/` — jamais dans
`job_dir` lui-même. Passer `job_dir=job_dir` aurait fait chercher `tested.json` dans le dossier
du job en cours (toujours vide au démarrage), pas dans celui du job source — un correctif qui
aurait semblé fonctionner sur un cas trivial mais serait resté cassé en pratique.

**Cause exacte confirmée** : `optimizer_process.py` (ligne du bloc "REPRISE DE RUN INTERROMPU")
appelait `load_tested_hashes(config.resume_run_id)` sans aucun `job_dir`, donc `_path()`
(`optimization_store.py`) résolvait systématiquement vers l'ancien chemin classique
`optimization_history/{run_id}.tested.json`, jamais vers `results/{resume_run_id}/tested.json`.

**Test écrit AVANT correction** (`tests/test_job_resume.py::TestJobResumeEndToEnd::
test_resume_finds_combinations_already_tested_by_a_prior_job`) — reproduction fidèle via le vrai
`optimizer_process.py` (subprocess), données synthétiques minimales, `BACKTEST_BASE_DIR` isolé :
job A (2 combinaisons) mené à terme, `tested.json` confirmé avec 2 hashs réels ; job B lancé avec
`resume_run_id` pointant vers A. **Rouge avant correction** : `logs.txt` du job B affichait
`"Reprise : 0 combinaisons déjà testées"`.

**Correction appliquée** (la plus petite possible, deux fichiers) :
- `optimization_store.py` : nouvelle fonction pure `resolve_sibling_job_dir(job_dir, run_id)` —
  retourne le dossier frère `os.path.dirname(job_dir)/{run_id}` en mode job, `None` en mode
  classique (comportement historique préservé). Ne crée aucun répertoire.
- `optimizer_process.py` : `load_tested_hashes(config.resume_run_id, job_dir=resolve_sibling_job_dir(job_dir, config.resume_run_id))`
  au lieu de l'appel sans `job_dir`.

**Résultat après correction** : **vert**. `logs.txt` du job B affiche
`"Reprise : 2 combinaisons déjà testées"` ; `meta.json` du job B confirme
`combinations_tested: 0` (les 2 combinaisons ne sont pas recalculées, conformément au critère de
succès de la mission).

**Tests ajoutés** (`tests/test_job_resume.py`, 11 tests, tous verts) :
- `test_resume_finds_combinations_already_tested_by_a_prior_job` — reproduction du bug, bout en
  bout (subprocess réel).
- `test_normal_run_without_resume_is_unaffected` — le fonctionnement actuel hors reprise est
  inchangé (aucune ligne "Reprise :" dans les logs sans `resume_run_id`, combinaisons toutes
  recalculées normalement).
- `test_resolve_sibling_job_dir_none_in_classic_mode` / `..._points_to_sibling_in_job_mode` /
  `..._does_not_create_directory` — comportement de la nouvelle fonction pure.
- `test_load_tested_hashes_via_resolved_sibling_dir_finds_real_hashes` — cas nominal.
- `test_resume_run_id_nonexistent_returns_empty_set` — **test négatif** : `resume_run_id` inexistant.
- `test_job_without_previous_results_returns_empty_set` — **test négatif** : job source sans
  aucun résultat précédent (jamais de `tested.json` écrit).
- `test_partial_results_returns_only_what_was_saved` — **test négatif** : résultats partiels
  (job source interrompu après 1 combinaison sur N).
- `test_no_collision_between_two_job_directories` — **test négatif** : deux job directories
  indépendants ne se contaminent jamais l'un l'autre.
- `test_classic_mode_resume_still_works_unchanged` — non-régression du mode classique
  (`optimization_history/`).

**Contraintes respectées** : aucune donnée historique modifiée (tests isolés via `tmp_path`/
`BACKTEST_BASE_DIR`, jamais le vrai `results/`) ; aucun autre job pris pour source que celui
explicitement désigné ; format des job directories inchangé (mêmes noms de fichiers, même
contenu) ; chemins toujours relatifs/portables dans les JSON persistés (`resolve_sibling_job_dir`
ne construit un chemin absolu qu'en mémoire, jamais écrit tel quel dans un artefact).

### Corrections de portabilité (A à D — E n'est pas un correctif de code)

| # | Problème (section 8) | Correction appliquée | Test associé | Résultat | Reste à vérifier uniquement sous Linux réel |
|---|---|---|---|---|---|
| A | `.streamlit/config.toml` : `headless = false` | Passé à `headless = true` (défaut portable, sans affichage) ; `lancer_app.bat` reçoit désormais explicitement `--server.headless false` en argument de ligne de commande pour **préserver l'ouverture automatique du navigateur en usage local Windows** (les arguments CLI de Streamlit prennent le pas sur `config.toml`) | Test 8 des vérifications légères (Streamlit démarre en mode headless, banner détecté) — ré-exécuté après correction, toujours vert | **Vert** — le comportement par défaut (serveur) est maintenant headless-safe, l'usage local via `lancer_app.bat` n'est pas dégradé | Confirmer que `lancer_app.bat` n'est simplement pas utilisé sur OCI (attendu : un futur service Docker/systemd appellera `streamlit run` directement, sans ce script) |
| B | `optimization_store.py` — `open(path, "w")` sans encodage explicite (écriture de `stop.flag`) | `encoding="utf-8"` ajouté, uniquement à cette écriture précise (aucune modification massive) | Suite complète `pytest tests/` (couvre `write_stop_flag`/`stop_flag_exists` dans `test_optimization_store.py`) | **Vert** — 546/546 | Aucun — changement purement défensif, sans dépendance à l'OS |
| C | Collecte `pytest` à la racine casse sur les scripts procéduraux | Nouveau `pytest.ini` (`testpaths = tests`) — un seul réglage, aucun test masqué | `pytest -q` et `pytest tests/ -q` exécutés séparément après correction | **Vert** — les deux commandes collectent exactement les mêmes 546 tests, comportement désormais cohérent | Aucun — comportement indépendant de l'OS (déjà noté en section 4) |
| D | Aucun lanceur Linux équivalent à `lancer_app.bat` | Nouveau `lancer_app.sh` — résout son propre répertoire (`BASH_SOURCE`), lance `streamlit run app.py` via `.venv/bin/python`, aucun chemin absolu, aucun secret ; ne force pas `--server.headless false` (pas de navigateur à ouvrir sur un serveur) | Revue manuelle du script (syntaxe `bash -n` non disponible dans cet environnement Windows — voir limite ci-dessous) | **Non exécuté réellement** | **À vérifier sous Linux réel** : exécution effective de `lancer_app.sh` (droit d'exécution à positionner explicitement au moment du commit — Windows ne peut pas écrire le bit exécutable Unix — via `git update-index --chmod=+x lancer_app.sh` ou `chmod +x` sur un checkout Linux) |
| E | Absence de `.gitattributes` | Nouveau `.gitattributes` minimal : `* text=auto eol=lf` (normalise tous les fichiers texte en LF, indépendamment de la config Git locale de chaque contributeur) ; `*.sh text eol=lf` (un CRLF casserait l'exécution du script sous Linux via le shebang) ; `*.bat text eol=crlf` (convention native `cmd.exe`, script jamais exécuté sous Linux) | Sans objet (fichier de configuration Git, pas de comportement applicatif à tester) | — | Confirmer qu'un futur `git add`/checkout applique bien ces règles (effet visible seulement au prochain commit) |

**Limite explicite sur D** : `bash -n lancer_app.sh` (vérification de syntaxe shell) n'a pas pu
être exécuté dans cet environnement Windows (pas de `bash` réel autre que Git Bash, dont le
comportement pour `-n` sur un script avec `set -euo pipefail` n'a pas été vérifié comme fiable
équivalent à un vrai Bash Linux) — le script a été relu manuellement (syntaxe standard, pattern
`BASH_SOURCE`/`cd`/`pwd` largement éprouvé) mais son exécution réelle reste à confirmer sous
Linux (Palier B).

### Ce qui reste à vérifier uniquement sous Linux réel (résumé, sans duplication du détail ci-dessus)

- Exécution réelle de `lancer_app.sh`.
- Application effective des règles `.gitattributes` au prochain commit/checkout.
- Comportement réel de `headless = true` sur un serveur sans aucun affichage (testé ici avec
  l'argument `--server.headless true` sous Windows, pas la valeur par défaut de `config.toml`
  sur une machine réellement sans affichage).
- Tout ce qui était déjà listé en section 1/7/9/11 avant cette session corrective (installation
  réelle des dépendances, `pytest` réel sous Linux, petit backtest/petite optimisation réels sur
  OCI).
