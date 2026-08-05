# Schéma canonique minimal des données de marché (socle Data Center, Phase 1)

Status: Proposé

Nous démarrons le futur "Data Center" (voir la demande utilisateur du 2026-08-05 décrivant la
cible multi-fournisseurs EODHD/Dukascopy/FirstRate/IG/Binance/Alpaca) par un socle local minimal,
sans aucun appel réseau. Nous introduisons un schéma canonique réduit — uniquement les colonnes
déjà produites aujourd'hui par `data_validator.py` (`time`, `open`, `high`, `low`, `close`,
`volume`) — plutôt que le schéma complet à 20+ colonnes (bid/ask, dividendes, options, Greeks...)
décrit dans la demande initiale.

Le schéma complet sera introduit par des ADR successifs, un lot de colonnes à la fois, au fur et
à mesure des fournisseurs réellement branchés (voir Phase 2 EODHD, Phase 3 Dukascopy/FirstRate,
Phase 4 IG). Étendre le schéma canonique plus tard ne doit jamais retirer ni renommer une colonne
existante de cette version — uniquement en ajouter, pour rester compatible avec les adaptateurs
déjà écrits.

Nous introduisons également un port `MarketDataSource` (interface, au sens architecture
hexagonale) et son premier adaptateur `LocalCsvMarketDataSource`, qui réutilise `path_resolver.py`
et `data_validator.py` sans dupliquer leur logique. Ce port n'est pour l'instant branché nulle
part dans `app.py` ni `engine.py` — ceux-ci continuent de fonctionner exactement comme avant.
Le brancher sera une étape ultérieure distincte, validée séparément.

## Considered Options

- **Reproduire immédiatement le schéma complet (20+ colonnes : bid/ask, dividendes, splits,
  options, Greeks...) décrit dans la demande initiale.** Rejeté pour cette étape : aucun
  fournisseur ne produit encore ces champs dans ce dépôt, et un schéma trop large sans donnée
  réelle pour le remplir est plus difficile à valider et à tester correctement dès le départ.
- **Ne pas introduire de port `MarketDataSource` et continuer à coupler `engine.load_data()`
  directement à un chemin CSV.** Rejeté : c'est précisément le couplage identifié comme
  bloquant dans l'audit d'architecture (2026-08-05) pour accueillir plusieurs fournisseurs.

## Consequences

- Toute future colonne ajoutée au schéma canonique (bid/ask, dividend_gross, adjusted_status...)
  doit faire l'objet d'un nouvel ADR ou d'une mise à jour explicite de celui-ci, pas d'un ajout
  silencieux dans le code.
- `market_data.adapters.local_csv.LocalCsvMarketDataSource` doit rester un simple habillage de
  `path_resolver.py` : toute divergence de comportement avec l'import CSV existant est un bug.
- `engine.py` et `app.py` ne sont pas modifiés par cette étape ; les brancher sur le port
  `MarketDataSource` nécessitera une validation utilisateur séparée (risque de régression sur le
  moteur de backtest).
