# Backtest — NASDAQ Perfect Revolution V1.1

## Parametres
- Symbole : US100
- Timeframe : M3
- Capital initial : $10,000.00
- Spread stress-test : 1.0 pt
- Slippage entree / sortie : 0.5 / 0.5 pt
- Shorts autorises : False
- Compounding : False

## Resultats globaux
| Metrique | Valeur |
|---|---|
| Capital initial | $10,000.00 |
| Capital final | $9,892.42 |
| Rendement net | -1.08% / $-107.58 |
| Nombre de trades | 114 |
| Trades gagnants | 58 (50.9%) |
| Trades perdants | 56 |
| Gain moyen | $+106.66 |
| Perte moyenne | $-112.39 |
| Payoff ratio | 0.95 |
| Profit Factor | 0.98 |
| Max Drawdown | 13.69% / $1,559.89 |
| Max Daily Drawdown | 3.57% |
| Plus gros gain | $+414.87 |
| Plus grosse perte | $-297.55 |
| Pertes consecutives max | 5 |

## Rendement par annee
| Annee | Rendement ($) | Nb trades |
|---|---|---|
| 2020 | $-5.09 | 13 |
| 2021 | $-121.74 | 6 |
| 2022 | $-844.08 | 25 |
| 2023 | $+398.53 | 7 |
| 2024 | $+509.20 | 9 |
| 2025 | $+898.70 | 28 |
| 2026 | $-943.09 | 26 |

## Hypotheses de traduction
- Timestamps CSV : UTC -> converti en Europe/Paris pour les comparaisons horaires
- Signaux evalues sur bougie fermee i, execution a l'open de la bougie i+1
- Entree LONG : open[i+1] + spread(1pt) + slippage_entree(0.5pt)
- Sortie : prix_sortie - slippage_sortie(0.5pt) pour les longs
- Stop et target calcules depuis le prix d'entree reel (apres couts)
- TrailPts = 650 = 650 unites de prix (confirme par commentaire '2.25% ~ 650 pts')
- Trailing activee sur close[i], appliquee a partir de [i+1]
- Time stop et flat-time : sortie au open[i+1] (comportement ProOrder standard)
- AllowShort = False : longs uniquement
- UseCompounding = False : 1 contrat fixe
- Stop vs target meme bougie : pessimiste, stop l'emporte
- StrategyProfit = P&L realise uniquement (pas de P&L latent dans le seuil journalier)