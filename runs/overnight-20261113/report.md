# Memecoin desk report - run overnight-20261113

Generated 2026-11-14 02:56 UTC. **Paper trading only.**

Window: 11-13 19:07 -> 11-14 02:56 UTC (7.8 h, 470 scan cycles)

## Account

| starting equity | cash | open MTM | equity | return | realised P&L | closed trades | win rate |
|---|---|---|---|---|---|---|---|
| $10,000.00 | $10,052.01 | $0.00 | $10,052.01 | +0.52% | $52.01 | 1 | 100% |

## Closed trades

| symbol | opened | closed | score | cost | proceeds | P&L | % | exit |
|---|---|---|---|---|---|---|---|---|
| CSI | 11-14 00:16 | 11-14 00:18 | 84.2 | $290.58 | $342.58 | $52.01 | +17.9% | trailing_stop |

## Kills

621 kill decisions across 27 distinct coins (filter 344, analyst 274, executor 3). A coin can fail several rules at once.

| stage | rule | times hit |
|---|---|---|
| filter | low_volume_1h | 298 |
| analyst | score_below_70 | 274 |
| filter | low_liquidity | 215 |
| filter | already_pumped | 42 |
| filter | mint_authority | 2 |
| filter | lp_unlocked | 2 |
| filter | top10_concentration | 2 |
| filter | bundled | 2 |
| executor | price impact 2.38% > 2.0% | 1 |
| executor | price impact 2.21% > 2.0% | 1 |
| executor | re-entry cooldown | 1 |

## Analyst scores

278 scorecards, 4 at 70+.

| symbol | when | score | momentum | unique buyers | buy/sell | holder growth | liq/mcap | smart wallets |
|---|---|---|---|---|---|---|---|---|
| CSI | 11-14 00:16 | **84.2** | 87 | 100 | 100 | 89 | 39 | - |
| SPEED | 11-13 22:29 | **63.6** | 70 | 42 | 81 | 60 | 70 | - |
| WANTED | 11-13 21:03 | **56.6** | 74 | 74 | 42 | 25 | 57 | - |
| inuhao | 11-14 02:47 | **54.1** | 99 | 77 | 4 | 9 | 59 | - |
| FOOD | 11-13 19:32 | **45.2** | 48 | 77 | 45 | 5 | 39 | - |
| Max | 11-14 01:41 | **43.8** | 60 | 16 | 100 | 0 | 47 | - |
| AMC | 11-13 21:29 | **39.2** | 53 | 37 | 100 | 2 | 0 | - |
| JENSEN | 11-14 02:47 | **27.3** | 56 | 11 | 16 | 28 | 23 | - |

## Every coin the desk evaluated

| coin | mint | first seen | last seen | checks | best score | trades | what stopped it (times) |
|---|---|---|---|---|---|---|---|
| inuhao | `FyHakv…` | 11-13 19:08 | 11-14 02:52 | 75 | 54.1 | - | score < 70 (75) |
| FOOD | `FTu55M…` | 11-13 19:08 | 11-13 21:24 | 24 | 45.2 | - | score < 70 (23), bundled (1) |
| Max | `5qaP7o…` | 11-13 19:08 | 11-14 02:53 | 70 | 43.8 | - | score < 70 (56), low_volume_1h (14) |
| WANTED | `BeLVQE…` | 11-13 19:08 | 11-13 23:48 | 47 | 56.6 | - | score < 70 (46), already_pumped (1) |
| SHARKBUX | `ttwocS…` | 11-13 19:08 | 11-14 02:46 | 45 | - | - | low_volume_1h (45) |
| QQQ | `QQQvDY…` | 11-13 19:08 | 11-13 19:38 | 4 | - | - | low_volume_1h (4) |
| LAB | `BQ1onb…` | 11-13 19:08 | 11-14 02:46 | 45 | - | - | low_liquidity (45), low_volume_1h (45) |
| PREDICT | `7GM6DT…` | 11-13 19:08 | 11-13 22:56 | 23 | - | - | low_liquidity (23), low_volume_1h (23) |
| PICO | `6rWAho…` | 11-13 19:08 | 11-14 02:46 | 45 | - | - | low_liquidity (45), low_volume_1h (45) |
| PICO | `6YMLWr…` | 11-13 19:08 | 11-14 02:46 | 45 | - | - | low_liquidity (45), low_volume_1h (45) |
| UODF | `GdauN3…` | 11-13 19:08 | 11-13 21:54 | 17 | - | - | low_liquidity (17), low_volume_1h (17) |
| GTA 6 Coin | `D2pZMT…` | 11-13 19:08 | 11-13 20:36 | 8 | - | - | low_liquidity (8), low_volume_1h (8) |
| AMC | `HWya5C…` | 11-13 19:34 | 11-14 02:52 | 67 | 39.2 | - | score < 70 (56), already_pumped (11) |
| AKT | `5d3fjP…` | 11-13 19:40 | 11-13 22:55 | 6 | - | - | low_volume_1h (6) |
| MORI | `MoR1wh…` | 11-13 19:50 | 11-14 01:50 | 2 | - | - | mint_authority (2), lp_unlocked (2), top10_concentration (2) |
| Shitcoin | `8p7GCo…` | 11-13 19:58 | 11-14 02:47 | 19 | - | - | low_volume_1h (19) |
| Ballfin | `9jh6f2…` | 11-13 20:35 | 11-13 20:35 | 1 | - | - | already_pumped (1) |
| Speed | `4cPQ6s…` | 11-13 21:05 | 11-13 21:33 | 2 | - | - | low_volume_1h (1), bundled (1) |
| punchhao | `C5jaQ3…` | 11-13 21:11 | 11-13 21:11 | 1 | - | - | already_pumped (1) |
| SPEED | `7csfMg…` | 11-13 21:51 | 11-13 23:04 | 11 | 63.6 | - | score < 70 (7), already_pumped (4) |
| AI | `A8oP4D…` | 11-13 21:59 | 11-13 23:03 | 7 | - | - | low_liquidity (7), low_volume_1h (7) |
| CSI | `CRwB4G…` | 11-13 23:07 | 11-14 02:55 | 23 | 84.2 | 1 ($52.01) | score < 70 (10), already_pumped (9), executor: price impact (2) |
| FOOD | `9YuoQD…` | 11-14 00:54 | 11-14 01:24 | 4 | - | - | low_liquidity (4), low_volume_1h (4) |
| PREDICT | `6dWweg…` | 11-14 00:59 | 11-14 02:56 | 12 | - | - | low_liquidity (12), low_volume_1h (12) |
| JENSEN | `B2YpP2…` | 11-14 01:23 | 11-14 02:52 | 10 | 27.3 | - | already_pumped (9), score < 70 (1) |
| GCAT | `7U2kPF…` | 11-14 01:49 | 11-14 02:51 | 7 | - | - | low_liquidity (7), already_pumped (6), low_volume_1h (1) |
| ANTH | `2bvKtU…` | 11-14 02:36 | 11-14 02:46 | 2 | - | - | low_liquidity (2), low_volume_1h (2) |

## Smart-wallet book

empty
