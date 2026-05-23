# Backtest Pro — Module Optimisateur : Document de Spec

**Version :** 1.0  
**Date :** 2026-05-19  
**Statut :** En attente de validation utilisateur avant implémentation  
**Projet :** Backtest Nasdaq revolution 3Mn  

---

## 1. Objectif

Transformer Backtest Pro en un outil professionnel d'optimisation de stratégies de trading. L'optimisateur doit pouvoir tester automatiquement des centaines à dizaines de milliers de combinaisons de paramètres, les classer selon un score global personnalisable favorisant la robustesse plutôt que le gain brut, et produire un rapport exploitable pour aider à choisir les meilleurs réglages.

**Ce que l'optimisateur N'est PAS :**
- Il ne remplace pas le jugement du trader
- Il ne garantit pas que les résultats se reproduiront en réel
- Il n'est pas un black box : chaque résultat est traçable et explicable

---

## 2. Fichiers à créer / modifier

### Nouveaux fichiers

```
📁 Backtest Nasdaq revolution 3Mn/
│
├── scoring.py                  Calcul du score global (fonctions pures, pas d'I/O)
├── optimizer.py                Moteur d'optimisation (sans Streamlit, testable standalone)
├── optimizer_process.py        Point d'entrée subprocess (lance optimizer.py, écrit les fichiers de suivi)
├── optimization_store.py       Persistance des runs d'optimisation
├── report_generator.py         Génération du rapport automatique orienté décision
│
├── optimization_history/       Répertoire de stockage des runs (créé automatiquement)
│   ├── {run_id}.meta.json      Métadonnées + top 100 résultats
│   ├── {run_id}.results.csv    Tous les résultats (exportable)
│   └── {run_id}.config.json    Config complète (permet de relancer à l'identique)
│
└── tests/
    ├── test_scoring.py         Tests unitaires du scoring et des pénalités
    └── test_optimizer.py       Tests unitaires du moteur (génération de combos, benchmark)
```

### Fichiers existants modifiés

```
app.py          Ajout d'un 4ème onglet "🔬 Optimisation" (~400 lignes)
                Les 3 onglets existants ne sont pas touchés.

engine.py       Modification 1 : Ajout de 2 paramètres optionnels start_date/end_date à run_backtest()
                → Changement minimal (~5 lignes), rétro-compatible à 100%.
                Modification 2 : Ajout de equity_r_squared dans _compute_stats()
                → Importe compute_equity_r_squared depuis scoring.py, l'ajoute à stats_dict.
                → Rétro-compatible (clé supplémentaire dans le dict existant).
```

**Principe directeur :** Chaque fichier a une responsabilité unique. L'optimisateur fonctionne sans Streamlit (testable en ligne de commande). L'interface Streamlit ne fait que piloter et afficher.

---

## 3. Architecture multiprocessing — Pattern subprocess (Windows-safe)

### Problème

Sur Windows, Streamlit + `ProcessPoolExecutor` directement dans `app.py` provoque des boucles infinies : Windows re-importe `app.py` dans chaque worker, ce qui relance Streamlit.

### Solution : subprocess.Popen + fichier de progression atomique

```
app.py (Streamlit, processus principal)
    │
    │  subprocess.Popen(["python", "optimizer_process.py", run_id, config_file])
    │  → Processus Python SÉPARÉ, totalement indépendant de Streamlit
    │
    ↓
optimizer_process.py (processus indépendant)
    │
    │  ProcessPoolExecutor(max_workers=n_workers)
    │
    ├── Worker 1 : run_backtest(params_batch_1)
    ├── Worker 2 : run_backtest(params_batch_2)
    ├── Worker 3 : run_backtest(params_batch_3)
    └── Worker N : run_backtest(params_batch_N)
    │
    │  Toutes les 500ms, écriture atomique de :
    │  → optimization_history/{run_id}_progress.json   (état temps réel)
    │
    │  Après chaque batch (N_WORKERS résultats) :
    │  → optimization_history/{run_id}.results.csv     (append ligne par ligne)
    │
    ↓
app.py (Streamlit)
    │
    │  Rerun toutes les 2 secondes
    │  → Lit {run_id}_progress.json
    │  → Affiche barre de progression, meilleur résultat actuel, ETA
```

### Mécanisme d'arrêt propre

1. Utilisateur clique "Arrêter" → `app.py` écrit `optimization_history/{run_id}_stop.flag`
2. `optimizer_process.py` vérifie ce fichier après chaque batch de résultats
3. Si le flag existe : arrêt propre, statut = "stopped", résultats partiels conservés
4. Le flag est supprimé après prise en compte

### Écriture atomique (Ajustement 3)

Toutes les écritures de fichiers critiques utilisent ce pattern (identique à `history_store.py`) :

```python
import tempfile, os

def atomic_write_json(path: str, data: dict):
    dir_path = os.path.dirname(path)
    with tempfile.NamedTemporaryFile(mode='w', dir=dir_path, delete=False, suffix='.tmp') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path = f.name
    os.replace(tmp_path, path)  # Atomique sur Windows et Linux
```

Garanti : Streamlit ne lira jamais un fichier à moitié écrit.

---

## 4. Structures de données

### 4.1 ParamRange — Plage d'optimisation d'un paramètre

```python
@dataclass
class ParamRange:
    name: str           # ex: "stop_loss_pct"
    param_type: str     # "number" | "bool" | "select"
    label: str          # ex: "Stop Loss (%)"
    # Pour type "number" :
    min_val: float = None
    max_val: float = None
    step: float = None
    # Pour type "bool" : options = [True, False]
    # Pour type "select" : options = ["low", "medium", "high"]
    options: list = None
    enabled: bool = True   # L'utilisateur peut désactiver une variable

    def generate_values(self) -> list:
        """Génère toutes les valeurs à tester pour ce paramètre."""
        if self.param_type == "number":
            values = []
            v = self.min_val
            while v <= self.max_val + self.step * 0.001:
                values.append(round(v, 10))
                v += self.step
            return values
        elif self.param_type in ("bool", "select"):
            return self.options
        return []
```

### 4.2 ScoreWeights — Pondération du score global

```python
@dataclass
class ScoreWeights:
    profit_factor:          float = 3.0   # Très important
    max_drawdown:           float = 3.0   # Très important
    total_trades:           float = 2.0   # Important (anti-PF artificiel)
    max_consecutive_losses: float = 2.0   # Important
    pct_gain:               float = 2.0   # Important
    win_rate:               float = 1.0   # Secondaire
    avg_win_loss_ratio:     float = 1.5   # Intermédiaire
    equity_regularity:      float = 1.5   # Intermédiaire (R² de l'equity curve)
    recovery_factor:        float = 1.0   # Secondaire
```

### 4.3 FilterConfig — Filtres éliminatoires (avant calcul du score)

```python
@dataclass
class FilterConfig:
    min_trades:              int   = 30     # Nombre minimum de trades valides
    max_drawdown_pct:        float = 25.0   # Drawdown maximum toléré (%)
    min_profit_factor:       float = 1.1    # PF minimum
    max_consecutive_losses:  int   = 12     # Pertes consécutives max
    min_win_rate:            float = 35.0   # Winrate minimum (%)
```

### 4.4 TrainTestConfig — Configuration split train/test (Ajustement 7)

```python
@dataclass
class TrainTestConfig:
    enabled: bool = False
    split_method: str = "ratio"    # "ratio" | "date"
    train_ratio: float = 0.70      # 70% train, 30% test (si split_method="ratio")
    split_date: str = None         # "YYYY-MM-DD" (si split_method="date")
    alert_degradation_pct: float = 30.0  # Alerte si score test < score train * (1 - 0.30)
```

### 4.5 OptimizationConfig — Configuration complète d'un run

```python
@dataclass
class OptimizationConfig:
    run_id: str                     # ex: "opt_20260519_143022_a3f7"
    strategy_module: str            # ex: "strategies.perfect_revolution_v1"
    strategy_name: str              # ex: "Perfect Revolution V1.1"
    data_file: str                  # Chemin absolu vers le fichier CSV de données
    base_params: dict               # Tous les paramètres de la stratégie (valeurs actuelles)
    param_ranges: list[ParamRange]  # Uniquement les paramètres à optimiser
    mode: str                       # "single_var" | "cross_zone" | "grid" | "general"
    score_weights: ScoreWeights
    filters: FilterConfig
    train_test: TrainTestConfig
    global_params: dict             # initial_capital, spread, slip_in, slip_out
    n_workers: int                  # Nombre de workers CPU
    max_combinations_warning: int = 100_000  # Seuil de confirmation obligatoire
    top_k_save: int = 100           # Sauvegarde top 100
    top_k_display: int = 10         # Affiche top 10
    resume_run_id: str = None       # Si reprise d'un run interrompu (Ajustement 2)
```

### 4.6 ProgressState — État temps réel (fichier {run_id}_progress.json)

```json
{
    "run_id": "opt_20260519_143022_a3f7",
    "status": "running",
    "total_combinations": 4860,
    "completed": 1234,
    "failed": 3,
    "progress_pct": 25.4,
    "best_score": 78.3,
    "best_params": {"stop_loss_pct": 1.2, "take_profit_pct": 5.5},
    "best_stats": {
        "profit_factor": 2.1, "total_trades": 87,
        "win_rate": 58.2, "max_dd_pct": 12.3, "pct_gain": 145.0
    },
    "elapsed_seconds": 87.2,
    "eta_seconds": 258.0,
    "workers_used": 8,
    "benchmark_ms_per_backtest": 423.0,
    "already_tested_count": 0,
    "error_message": null
}
```

Statuts possibles : `"running"` | `"stopped"` | `"completed"` | `"error"`

---

## 5. Algorithme de scoring (scoring.py)

### 5.1 Principe général

```
Score final = 100 × [Σ(métrique_normalisée × poids) / Σ(poids)] × (1 - pénalité_overfitting)
```

Un résultat est d'abord soumis aux **filtres éliminatoires** (score = 0 si non passé), puis les métriques sont normalisées sur [0, 1], pondérées, et une pénalité anti-overfitting est appliquée.

### 5.2 Normalisation des métriques

| Métrique | Formule | Logique |
|---|---|---|
| **Profit Factor** | `log(PF) / log(4.0)` clampé [0, 1] | PF=1→0, PF=2→0.50, PF=4+→1. Log car PF=3 n'est pas 3× meilleur que PF=2. PF=∞ → 0.95 (trop parfait = suspect) |
| **Max Drawdown** | `1 - (DD / 25%)` clampé [0, 1] | 0%DD→1, 25%DD→0. Inversé. |
| **Total Trades** | `log(N) / log(150)` clampé [0, 1] | 0→0, 30→0.64, 100→0.87, 150+→1. Log pénalise fortement les petits N |
| **Pertes consécutives max** | `1 - (N / 12)` clampé [0, 1] | 0→1, 6→0.5, 12+→0. Inversé. |
| **% de gain** | `gain_pct / 200.0` clampé [0, 1] | 0%→0, 100%→0.5, 200%+→1 |
| **Winrate** | `(WR - 35%) / 30%` clampé [0, 1] | 35%→0, 50%→0.5, 65%+→1 |
| **Ratio gain moyen / perte** | `ratio / 3.0` clampé [0, 1] | ratio=1→0.33, ratio=3+→1 |
| **Régularité equity** | R² de régression linéaire sur equity curve | 0→0, 0.5→0.5, 1→1 |
| **Recovery Factor** | `RF / 5.0` clampé [0, 1] | RF=2.5→0.5, RF=5+→1 |

### 5.3 Calcul du R² de l'equity curve

```python
def compute_equity_r_squared(equity_values: list[float]) -> float:
    """
    Mesure si l'equity curve ressemble à une droite montante.
    R²=1 : croissance parfaitement régulière
    R²=0 : aucune tendance linéaire détectable
    """
    if len(equity_values) < 10:
        return 0.5  # Insuffisant pour calculer, valeur neutre
    x = np.arange(len(equity_values))
    y = np.array(equity_values)
    # Régression linéaire manuelle (numpy pour performance)
    x_m, y_m = x.mean(), y.mean()
    ss_tot = ((y - y_m) ** 2).sum()
    if ss_tot == 0:
        return 0.5  # Ligne plate = pas de gain = neutre
    slope = ((x - x_m) * (y - y_m)).sum() / ((x - x_m) ** 2).sum()
    y_pred = slope * x + (y_m - slope * x_m)
    r_squared = 1 - ((y - y_pred) ** 2).sum() / ss_tot
    return float(np.clip(r_squared, 0.0, 1.0))
```

### 5.4 Filtres éliminatoires (FilterConfig)

Appliqués AVANT le calcul du score. Si un filtre échoue, score = 0.0.

```python
def is_filtered_out(stats: dict, filters: FilterConfig) -> tuple[bool, str]:
    """Retourne (est_éliminé, raison_lisible)"""
    checks = [
        (stats['total_trades'] < filters.min_trades,
         f"Trop peu de trades ({stats['total_trades']} < {filters.min_trades})"),
        (stats['max_dd_pct'] > filters.max_drawdown_pct,
         f"Drawdown trop élevé ({stats['max_dd_pct']:.1f}% > {filters.max_drawdown_pct}%)"),
        (stats['profit_factor'] < filters.min_profit_factor,
         f"Profit Factor insuffisant ({stats['profit_factor']:.2f})"),
        (stats['max_consecutive_losses'] > filters.max_consecutive_losses,
         f"Pertes consécutives excessives ({stats['max_consecutive_losses']})"),
        (stats['win_rate'] < filters.min_win_rate,
         f"Winrate insuffisant ({stats['win_rate']:.1f}%)"),
    ]
    for condition, reason in checks:
        if condition:
            return True, reason
    return False, ""
```

### 5.5 Pénalités anti-overfitting (Ajustement 6)

Les pénalités RÉDUISENT le score mais n'éliminent pas le résultat (contrairement aux filtres).  
Chaque pénalité est justifiée dans la liste des avertissements.

| Pénalité | Condition | Réduction | Message |
|---|---|---|---|
| **PF élevé / peu de trades** | PF > 3.5 ET trades < 30 | 5% à 25% proportionnel | "PF élevé basé sur peu de trades → peu fiable" |
| **Paramètres aux extrêmes** | ≥2 params sur min ou max du range | 5% par param extrême | "X paramètres sur valeur extrême → risque d'overfitting" |
| **Ratio gain/DD irréaliste** | gain_pct/DD > 25 | 15% | "Ratio gain/drawdown suspect" |
| **Equity irrégulière** | R² < 0.5 | 0% à 20% proportionnel | "Equity curve irrégulière → performance peu constante" |

Pénalité maximum cumulée : **60%** (plancher de protection).

---

## 6. Modes d'optimisation (optimizer.py)

### Mode 1 — Optimisation variable par variable

**Principe :** Optimiser une variable à la fois. Garder le meilleur réglage. Passer à la suivante.

**Algorithme :**
```
best_params = base_params.copy()
pour chaque param_range dans param_ranges (dans l'ordre) :
    résultats = []
    pour chaque valeur dans param_range.generate_values() :
        params_test = best_params.copy()
        params_test[param_range.name] = valeur
        stats = run_backtest(params_test)
        score = compute_score(stats)
        résultats.append((score, valeur, stats))
    meilleur = max(résultats, key=lambda x: x[0])
    si meilleur.score > 0 :
        best_params[param_range.name] = meilleur.valeur
```

**Nombre de backtests :** Σ(nb_valeurs_par_variable)  
**Exemple (5 variables × 16 valeurs) :** ~80 backtests

**Avantage :** Rapide, lisible. **Limite :** Ne capture pas les interactions entre variables.

### Mode 2 — Optimisation croisée autour des meilleures zones

**Prérequis :** Résultats d'un Mode 1 ou résultats existants.

**Algorithme :**
```
pour chaque param_range dans param_ranges :
    scores_par_valeur = agréger les scores de tous les résultats par valeur de ce param
    top_30pct = valeurs avec score >= percentile_70(scores)
    zone_prometteuse[param_range.name] = top_30pct

combinations = cartesian_product(zones_prometteuses)
tester toutes les combinations
```

**Nombre de backtests :** `(nb_valeurs × 0.30)^N_vars` — beaucoup moins qu'une grille complète  
**Exemple :** 5 variables × 5 valeurs dans la zone = 5^5 = 3125 backtests

### Mode 3 — Grille complète

**Principe :** `itertools.product` de tous les ranges. Teste TOUT.

**Limite de sécurité (Ajustement 8) :**
- Si N_combinations > `max_combinations_warning` (défaut: 100 000) : **validation obligatoire dans l'interface**
- Si N_combinations > 500 000 : l'interface propose automatiquement le Mode 4

### Mode 4 — Optimisation générale intelligente

Sélection automatique de la méthode selon N_combinations :

| Plage | Méthode | Détail |
|---|---|---|
| N ≤ 50 000 | **Grille complète** | Tout tester |
| 50 000 < N ≤ 500 000 | **Échantillonnage stratifié** | 50 000 tirages aléatoires, répartis uniformément sur chaque variable |
| N > 500 000 | **Grille progressive (3 passes)** | Voir ci-dessous |

**Grille progressive (N > 500 000) :**
```
PASS 1 : Grille grossière (step × 4 pour chaque variable)
         → Identifier le top 20% des combinaisons testées

PASS 2 : Grille fine autour du top 20% (step × 1)
         → Identifier le top 5% des combinaisons testées

PASS 3 (optionnel, si demandé) : Ultra-fine autour du top 5% (step × 0.5)
```

**Avantage :** Explore efficacement sans tester de millions de combinaisons inutiles.

### Mode 5 — Walk-forward (V2, placeholder uniquement)

Prévu pour une version future. Placeholder dans l'interface avec message "Disponible en V2".  
Logique estimée : split en N fenêtres temporelles glissantes, train sur N-1, test sur la dernière.

---

## 7. Split train/test simple (Ajustement 7)

### Objectif

Limiter l'overfitting en vérifiant que les meilleurs paramètres trouvés en optimisation restent bons sur une période que l'optimisateur n'a pas vue.

### Implémentation

**Modification de `engine.py` (3 lignes, rétro-compatible) :**

```python
def run_backtest(params, data_file, initial_capital, spread, slip_in, slip_out,
                 start_date=None, end_date=None):   # ← 2 nouveaux paramètres optionnels
    df = load_and_prepare_data(data_file)
    # ← 3 nouvelles lignes :
    if start_date:
        df = df[df.index >= pd.Timestamp(start_date, tz='Europe/Paris')]
    if end_date:
        df = df[df.index <= pd.Timestamp(end_date, tz='Europe/Paris')]
    # ... reste inchangé
```

**Dans `optimizer.py` :**

```
Si train_test.enabled = True :

1. PHASE OPTIMISATION (avec date_range=train_period) :
   → Trouver les top_k_save meilleurs paramètres sur la période d'entraînement

2. PHASE VALIDATION (avec date_range=test_period) :
   → Pour chaque résultat du top 100 train :
       relancer run_backtest() sur la période de test
       calculer le score_test

3. Stocker dans chaque résultat :
   - score_train
   - score_test
   - degradation_pct = (score_train - score_test) / score_train * 100

4. Alerte si degradation_pct > train_test.alert_degradation_pct (défaut: 30%)
```

**Affichage dans le rapport :**

| Réglage | Score Train | Score Test | Dégradation | Alerte |
|---|---|---|---|---|
| Params #1 | 82.4 | 71.3 | -13.4% | ✅ OK |
| Params #2 | 79.1 | 41.2 | -47.9% | ⚠️ OVERFITTING |

---

## 8. Benchmark de vitesse (Ajustement 1)

**Déclenchement :** Automatiquement avant toute optimisation (sauf reprise de run).

**Processus :**
```python
def benchmark_speed(config: OptimizationConfig, n_sample: int = 20) -> float:
    """
    Lance n_sample backtests avec les paramètres actuels.
    Retourne le temps moyen en millisecondes par backtest.
    """
    times = []
    for _ in range(n_sample):
        start = time.perf_counter()
        run_backtest(config.base_params, ...)
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)  # médiane (robuste aux outliers)
```

**Estimation de durée affichée avant lancement :**
```
Benchmark : 423 ms/backtest (médiane sur 20 tests)
Total combinations : 4 860
Workers disponibles : 8
───────────────────────────────────────────
Durée estimée : ~4 minutes (en parallèle)
```

**Note :** L'ETA en temps réel est recalculée dynamiquement avec la vitesse réelle observée, pas seulement le benchmark initial.

---

## 9. Système de reprise après interruption (Ajustement 2)

### Identification des combinaisons testées

Chaque combinaison testée est identifiée par un **hash de ses paramètres** :

```python
def params_hash(params: dict) -> str:
    """Hash stable d'un dict de paramètres."""
    import hashlib, json
    serialized = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(serialized.encode()).hexdigest()[:12]
```

Les hashs des combinaisons testées sont stockés dans `{run_id}.tested.json` (set de hashs).

### Reprise d'un run interrompu

Si `resume_run_id` est fourni dans `OptimizationConfig` :

```
1. Charger {resume_run_id}.tested.json → set des combos déjà testées
2. Charger {resume_run_id}.results.csv → résultats déjà collectés
3. Filtrer le plan d'optimisation : exclure les combos déjà testées
4. Continuer l'optimisation avec les combos restantes
5. Fusionner les nouveaux résultats avec les anciens en fin de run
```

### Sauvegarde progressive (Ajustement 4)

Le fichier `.results.csv` est écrit **en mode append** après chaque batch de résultats (N_WORKERS résultats). Il n'est PAS maintenu entièrement en mémoire.

En mémoire, on conserve seulement :
- **Top 100** (trié par score)
- **Statistiques de progression** (completed, failed, best_score, elapsed)
- **Set des hashs testés** (compact, ~12 octets par combo)

---

## 10. Gestion mémoire (Ajustement 4)

**Pour 100 000 combinaisons :**

| Donnée | Taille estimée | Stockage |
|---|---|---|
| Top 100 résultats | ~200 KB | RAM |
| Set de hashs testés | ~1.2 MB (100K × 12B) | RAM |
| Stats de progression | < 1 KB | RAM |
| Tous les résultats | ~50 MB | CSV sur disque, écrit progressivement |

**Conclusion :** La RAM utilisée est bornée, quelle que soit la taille de l'optimisation.

---

## 11. Sauvegarde (optimization_store.py)

### Structure par run dans `optimization_history/`

```
optimization_history/
├── {run_id}.meta.json       Métadonnées + top 100 + rapport
├── {run_id}.results.csv     Tous les résultats (colonnes : score, params..., stats...)
├── {run_id}.config.json     Config complète (pour relance identique)
└── {run_id}.tested.json     Set des hashs testés (pour reprise)

Fichiers temporaires (supprimés à la fin) :
└── {run_id}_progress.json   État temps réel (gardé 24h puis nettoyé)
└── {run_id}_stop.flag       Signal d'arrêt (supprimé après lecture)
```

### Schéma du fichier {run_id}.meta.json (Ajustement 5)

```json
{
    "run_id": "opt_20260519_143022_a3f7",
    "date": "2026-05-19T14:30:22",
    "strategy_name": "Perfect Revolution V1.1",
    "mode": "general",
    "status": "completed",
    "variables_tested": ["stop_loss_pct", "take_profit_pct", "ema_trend_period"],
    "total_combinations": 4860,
    "combinations_tested": 4860,
    "combinations_filtered_out": 1203,
    "duration_seconds": 342,
    "workers_used": 8,
    "benchmark_ms_per_backtest": 423.0,
    "score_weights": { "profit_factor": 3.0, "max_drawdown": 3.0, ... },
    "filters": { "min_trades": 30, "max_drawdown_pct": 25.0, ... },
    "train_test": { "enabled": true, "train_ratio": 0.70, ... },
    "top_100": [
        {
            "rank": 1,
            "score": 82.4,
            "score_train": 82.4,
            "score_test": 71.3,
            "degradation_pct": 13.4,
            "params": {"stop_loss_pct": 1.2, "take_profit_pct": 5.5, ...},
            "stats": {
                "profit_factor": 2.3,
                "total_trades": 87,
                "win_rate": 58.2,
                "max_dd_pct": 11.4,
                "pct_gain": 145.2,
                "max_consecutive_losses": 4,
                "avg_win_loss_ratio": 1.8,
                "equity_r_squared": 0.91,
                "recovery_factor": 3.2,
                "net_profit": 14520.0
            },
            "warnings": []
        }
    ],
    "sensitivity": {
        "stop_loss_pct": 0.82,
        "take_profit_pct": 0.67,
        "ema_trend_period": 0.31
    },
    "report": { ... }
}
```

### API de optimization_store.py

```python
def save_run(result: OptimizationResult) -> str:   # → run_id
def list_runs() -> list[dict]:                      # → liste métadonnées (lecture JSON seul)
def load_run(run_id: str) -> OptimizationResult:   # → run complet
def load_results_csv(run_id: str) -> pd.DataFrame:  # → tous les résultats
def delete_run(run_id: str) -> None
def get_run_status(run_id: str) -> str:             # → statut depuis progress.json
def cleanup_old_progress_files(max_age_hours=24):   # → supprime fichiers temporaires anciens
```

---

## 12. Analyse de sensibilité (rapport automatique)

### Calcul de la sensibilité d'un paramètre

**Deux méthodes selon le mode d'optimisation :**

**Méthode A — Modes 1, 2, 3 (grilles complètes ou séquentielles) :**
Filtrer les résultats où tous les autres paramètres sont fixés aux valeurs du meilleur résultat,
puis calculer l'écart-type des scores sur les différentes valeurs de `param_name`.

```python
def compute_sensitivity_filtered(results, param_name, best_params) -> float:
    filtered = [
        r for r in results
        if all(r['params'].get(k) == best_params.get(k)
               for k in best_params if k != param_name)
    ]
    if len(filtered) < 3:
        return 0.0
    return round(float(np.std([r['score'] for r in filtered])), 3)
```

**Méthode B — Mode 4 (échantillonnage aléatoire ou grille progressive) :**
Il n'y a pas assez de résultats avec les autres params identiques. Utiliser la corrélation
rang de Spearman entre la valeur du paramètre et le score.

```python
from scipy.stats import spearmanr

def compute_sensitivity_correlation(results, param_name) -> float:
    values = [r['params'].get(param_name) for r in results]
    scores = [r['score'] for r in results]
    # Filtrer les None et les résultats filtrés (score=0)
    pairs = [(v, s) for v, s in zip(values, scores) if v is not None and s > 0]
    if len(pairs) < 10:
        return 0.0
    corr, _ = spearmanr([p[0] for p in pairs], [p[1] for p in pairs])
    return round(abs(float(corr)), 3)  # |corrélation| = sensibilité
```

**Sélection automatique** : `optimizer.py` choisit la méthode selon le mode.

---

## 13. Rapport automatique orienté décision (report_generator.py, Ajustement 9)

### Catégorisation du meilleur résultat

```python
def categorize_result(top1: dict, train_test_enabled: bool) -> str:
    """Retourne l'une des 4 catégories."""
    score = top1['score']
    dd = top1['stats']['max_dd_pct']
    pf = top1['stats']['profit_factor']
    degradation = top1.get('degradation_pct', 0)
    
    if score < 40 or (train_test_enabled and degradation > 50):
        return "Réglage à éviter"
    elif dd > 20 or pf > 3.0:
        return "Réglage agressif"
    elif dd < 10 and pf < 1.5:
        return "Réglage défensif"
    else:
        return "Réglage recommandé"
```

### Structure du rapport final

```json
{
    "categorie": "Réglage recommandé",
    "resume": "Le meilleur réglage offre un bon équilibre entre gain (145%) et risque (DD 11.4%), avec 87 trades sur la période et un PF de 2.3.",
    "points_forts": [
        "Profit Factor solide à 2.3",
        "Drawdown maîtrisé à 11.4%",
        "Equity curve régulière (R²=0.91)",
        "87 trades : résultat statistiquement significatif"
    ],
    "points_faibles": [
        "Stop Loss à la valeur maximum du range testé → tester au-delà",
        "Résultat à vérifier sur d'autres périodes de marché"
    ],
    "risque_overfitting": "Modéré",
    "raison_overfitting": "1 paramètre sur valeur extrême du range. Tester une plage élargie recommandé.",
    "variables_sensibles": ["stop_loss_pct (0.82)", "take_profit_pct (0.67)"],
    "variables_peu_sensibles": ["ema_trend_period (0.31)"],
    "convient_paper_trading": true,
    "raison_paper_trading": "Drawdown <15% et winrate >50%. Score de robustesse satisfaisant.",
    "retester_autre_periode": true,
    "raison_retester": "Score train/test avec 13.4% de dégradation : acceptable mais à surveiller.",
    "recommandation_finale": "Ce réglage est utilisable pour du paper trading avec les paramètres trouvés. Avant le live, valider sur au moins 3 mois supplémentaires non vus par l'optimisateur."
}
```

---

## 14. Interface Streamlit — Onglet "🔬 Optimisation" (app.py)

### Disposition générale (3 sous-sections)

**Sous-section A : Configuration**
- Sélecteur de stratégie (même liste que l'onglet Backtest)
- Sélecteur de mode d'optimisation (radio buttons)
- Tableau des variables : cocher/décocher, modifier min/max/step
- Compteur de combinaisons mis à jour en temps réel avec le choix des variables
- Estimation de durée (basée sur benchmark)
- Avertissement + confirmation si N > seuil
- Configuration du scoring (sliders de pondération)
- Configuration des filtres
- Configuration train/test (optionnel, toggle)
- Sélecteur du nombre de workers (slider 1 → CPU_COUNT)
- Bouton **"Lancer l'optimisation"** (désactivé pendant un run en cours)

**Sous-section B : Progression (pendant un run)**
- Barre de progression `st.progress()`
- Métriques temps réel : terminés / total, workers actifs, vitesse réelle
- ETA recalculé dynamiquement
- Résumé du meilleur résultat actuel
- Bouton **"Arrêter proprement"** (visible uniquement pendant un run)
- Auto-refresh toutes les 2 secondes (`st_autorefresh` ou `st.rerun()` avec timer)

**Sous-section C : Résultats**
- Onglets internes : "Top 10", "Tous les résultats", "Rapport", "Historique"
- **Top 10** : tableau avec rang, score, métriques clés, paramètres, boutons "Relancer ce backtest" et "Exporter"
- **Tous les résultats** : tableau filtrable et triable (depuis CSV)
- **Rapport** : rendu du rapport automatique avec mise en forme
- **Historique** : liste des runs précédents avec chargement, comparaison, suppression

### Sécurité (Ajustement 8)

Avant de lancer, si N_combinations > `max_combinations_warning` :
```
⚠️ ATTENTION : 247,680 combinaisons détectées
Durée estimée : ~35 minutes avec 8 workers

[  Lancer quand même  ]   [  Passer en mode intelligent (50,000 max)  ]
```

---

## 15. Ordre d'implémentation validé

| Étape | Fichier(s) | Dépendances |
|---|---|---|
| 1 | `scoring.py` | Aucune |
| 2 | `tests/test_scoring.py` | scoring.py |
| 3 | `engine.py` (+start_date/end_date) | Aucune (modif mineure) |
| 4 | `optimizer.py` | engine.py, scoring.py |
| 5 | `optimization_store.py` | Aucune |
| 6 | `optimizer_process.py` | optimizer.py, optimization_store.py |
| 7 | `tests/test_optimizer.py` | optimizer.py |
| 8 | `report_generator.py` | scoring.py |
| 9 | `app.py` — onglet Optimisation | optimization_store.py, optimizer_process.py, report_generator.py |
| 10 | Export CSV/JSON (dans app.py) | optimization_store.py |

---

## 16. Points techniques critiques à retenir pour l'implémentation

0. **Dépendance scipy** : Ajouter `scipy` dans `requirements.txt` pour la corrélation de Spearman (analyse de sensibilité Mode 4). Vérifier si déjà présente (`pip show scipy`). Si non, `pip install scipy`.

1. **Pickling des workers** : Les fonctions passées à `ProcessPoolExecutor` doivent être importables au top-level de leur module. La stratégie (`Strategy` class) doit être picklable. Chaque worker charge lui-même le module stratégie via `importlib`.

2. **Windows spawn context** : L'`optimizer_process.py` utilise `if __name__ == '__main__':` + `multiprocessing.freeze_support()` pour être compatible Windows.

3. **pandas-ta dans les workers** : Chaque worker importe pandas-ta indépendamment. Pas de state partagé.

4. **Gestion des exceptions par worker** : Si un `run_backtest()` lève une exception (données insuffisantes, etc.), le résultat est marqué "failed" et le worker continue.

5. **Infinite Profit Factor** : Quand il n'y a aucun trade perdant, PF = ∞. À traiter explicitement : `if math.isinf(pf): normalized_pf = 0.95`.

6. **Métriques manquantes dans stats_dict** : `engine.py` peut ne pas retourner toutes les métriques (ex: `equity_r_squared` n'existe pas encore). Le scoring doit être défensif : `stats.get('metric', default_value)`.

7. **Metric `pct_gain`** : Calculée comme `net_profit / initial_capital * 100`. À vérifier si `_compute_stats()` la retourne déjà sous ce nom ou si elle doit être calculée dans le scorer.

8. **`equity_r_squared`** : À calculer dans `_compute_stats()` d'`engine.py` (pas dans scoring.py en dehors du moteur). Raison : passer `equity_df` entier depuis chaque worker ProcessPoolExecutor est coûteux en sérialisation. Calculer R² directement dans `engine.py` puis l'inclure dans `stats_dict` est plus efficace. `scoring.py` lit simplement `stats.get('equity_r_squared', 0.5)`. Modification d'`engine.py` : ajouter `equity_r_squared` à `_compute_stats()` en important la fonction utilitaire `compute_equity_r_squared` depuis `scoring.py`.

---

## 17. Ce qui n'est PAS dans la V1 (reporté en V2)

- Walk-forward complet (Mode 5) : placeholder uniquement
- Monte Carlo simulation
- Optimisation bayésienne (gaussian process)
- Interface de comparaison côte-à-côte de 2 runs complets
- Alertes email quand l'optimisation est terminée
- Déduplication automatique des résultats très similaires ("clustering")

---

*Fin du document de spec — Version 1.0*  
*Ce document doit être approuvé par l'utilisateur avant le début de l'implémentation.*
