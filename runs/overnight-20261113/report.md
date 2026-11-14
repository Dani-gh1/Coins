# Memecoin desk report - run overnight-20261113

Generated 2026-11-14 01:35 UTC. **Paper trading only.**

Window: 11-13 19:07 -> 11-14 01:34 UTC (6.4 h, 388 scan cycles)

## Account

| starting equity | cash | open MTM | equity | return | realised P&L | closed trades | win rate |
|---|---|---|---|---|---|---|---|
| $10,000.00 | $10,052.01 | $0.00 | $10,052.01 | +0.52% | $52.01 | 1 | 100% |

## Closed trades

| symbol | opened | closed | score | cost | proceeds | P&L | % | exit |
|---|---|---|---|---|---|---|---|---|
| CSI | 11-14 00:16 | 11-14 00:18 | 84.2 | $290.58 | $342.58 | $52.01 | +17.9% | trailing_stop |

## Kills

517 kill decisions across 25 distinct coins (filter 289, analyst 225, executor 3). A coin can fail several rules at once.

| stage | rule | times hit |
|---|---|---|
| filter | low_volume_1h | 257 |
| analyst | score_below_70 | 225 |
| filter | low_liquidity | 177 |
| filter | already_pumped | 29 |
| filter | bundled | 2 |
| filter | mint_authority | 1 |
| filter | lp_unlocked | 1 |
| filter | top10_concentration | 1 |
| executor | price impact 2.38% > 2.0% | 1 |
| executor | price impact 2.21% > 2.0% | 1 |
| executor | re-entry cooldown | 1 |

## Analyst scores

229 scorecards, 4 at 70+.

| symbol | when | score | momentum | unique buyers | buy/sell | holder growth | liq/mcap | smart wallets |
|---|---|---|---|---|---|---|---|---|
| CSI | 11-14 00:16 | **84.2** | 87 | 100 | 100 | 89 | 39 | - |
| SPEED | 11-13 22:29 | **63.6** | 70 | 42 | 81 | 60 | 70 | - |
| WANTED | 11-13 21:03 | **56.6** | 74 | 74 | 42 | 25 | 57 | - |
| inuhao | 11-13 21:01 | **52.9** | 86 | 75 | 0 | 9 | 75 | - |
| FOOD | 11-13 19:32 | **45.2** | 48 | 77 | 45 | 5 | 39 | - |
| Max | 11-13 19:08 | **43.4** | 53 | 53 | 50 | 16 | 39 | - |
| AMC | 11-13 21:29 | **39.2** | 53 | 37 | 100 | 2 | 0 | - |

## Every coin the desk evaluated

| coin | mint | first seen | last seen | checks | best score | trades | what stopped it (times) |
|---|---|---|---|---|---|---|---|
| inuhao | `FyHakv…` | 11-13 19:08 | 11-14 01:29 | 61 | 52.9 | - | score < 70 (61) |
| FOOD | `FTu55M…` | 11-13 19:08 | 11-13 21:24 | 24 | 45.2 | - | score < 70 (23), bundled (1) |
| Max | `5qaP7o…` | 11-13 19:08 | 11-14 01:30 | 56 | 43.4 | - | score < 70 (43), low_volume_1h (13) |
| WANTED | `BeLVQE…` | 11-13 19:08 | 11-13 23:48 | 47 | 56.6 | - | score < 70 (46), already_pumped (1) |
| SHARKBUX | `ttwocS…` | 11-13 19:08 | 11-14 01:33 | 38 | - | - | low_volume_1h (38) |
| QQQ | `QQQvDY…` | 11-13 19:08 | 11-13 19:38 | 4 | - | - | low_volume_1h (4) |
| LAB | `BQ1onb…` | 11-13 19:08 | 11-14 01:34 | 38 | - | - | low_liquidity (38), low_volume_1h (38) |
| PREDICT | `7GM6DT…` | 11-13 19:08 | 11-13 22:56 | 23 | - | - | low_liquidity (23), low_volume_1h (23) |
| PICO | `6rWAho…` | 11-13 19:08 | 11-14 01:34 | 38 | - | - | low_liquidity (38), low_volume_1h (38) |
| PICO | `6YMLWr…` | 11-13 19:08 | 11-14 01:34 | 38 | - | - | low_liquidity (38), low_volume_1h (38) |
| UODF | `GdauN3…` | 11-13 19:08 | 11-13 21:54 | 17 | - | - | low_liquidity (17), low_volume_1h (17) |
| GTA 6 Coin | `D2pZMT…` | 11-13 19:08 | 11-13 20:36 | 8 | - | - | low_liquidity (8), low_volume_1h (8) |
| AMC | `HWya5C…` | 11-13 19:34 | 11-14 01:29 | 53 | 39.2 | - | score < 70 (42), already_pumped (11) |
| AKT | `5d3fjP…` | 11-13 19:40 | 11-13 22:55 | 6 | - | - | low_volume_1h (6) |
| MORI | `MoR1wh…` | 11-13 19:50 | 11-13 19:50 | 1 | - | - | mint_authority (1), lp_unlocked (1), top10_concentration (1) |
| Shitcoin | `8p7GCo…` | 11-13 19:58 | 11-14 01:33 | 18 | - | - | low_volume_1h (18) |
| Ballfin | `9jh6f2…` | 11-13 20:35 | 11-13 20:35 | 1 | - | - | already_pumped (1) |
| Speed | `4cPQ6s…` | 11-13 21:05 | 11-13 21:33 | 2 | - | - | low_volume_1h (1), bundled (1) |
| punchhao | `C5jaQ3…` | 11-13 21:11 | 11-13 21:11 | 1 | - | - | already_pumped (1) |
| SPEED | `7csfMg…` | 11-13 21:51 | 11-13 23:04 | 11 | 63.6 | - | score < 70 (7), already_pumped (4) |
| AI | `A8oP4D…` | 11-13 21:59 | 11-13 23:03 | 7 | - | - | low_liquidity (7), low_volume_1h (7) |
| CSI | `CRwB4G…` | 11-13 23:07 | 11-14 01:12 | 16 | 84.2 | 1 ($52.01) | already_pumped (9), score < 70 (3), executor: price impact (2) |
| FOOD | `9YuoQD…` | 11-14 00:54 | 11-14 01:24 | 4 | - | - | low_liquidity (4), low_volume_1h (4) |
| PREDICT | `6dWweg…` | 11-14 00:59 | 11-14 01:32 | 4 | - | - | low_liquidity (4), low_volume_1h (4) |
| JENSEN | `B2YpP2…` | 11-14 01:23 | 11-14 01:34 | 2 | - | - | already_pumped (2) |

## Smart-wallet book

empty
