# Solana memecoin desk (paper)

Six agents with hard handoffs that look for the strongest fresh Solana memecoins using
on-chain data. It paper-trades them with real Jupiter quotes and logs every decision,
including every coin it kills.

```
Scout ──Candidate──▶ Filter ──FilterPass──▶ Analyst ──ScoreCard(≥73)──▶ Risk ──RiskPlan──▶ Executor
                       │                       │                                           │
                      Kill                  Kill/Defer                       Fill + Position (stop set at fill)
                                                                                           │
                           Risk ◀── marks every 3s ─── open positions ◀────────────────────┘
                             └──ExitSignal──▶ Executor ──Fill──▶ closed
Logger: every message above goes to SQLite + JSONL
```

Agents only talk through the immutable messages in `desk/messages.py`. The Executor raises
`HandoffError` on any order that lacks an approved `RiskPlan`, a passing `ScoreCard` or a stop.

## The rules

| Agent | Rule | Data |
|---|---|---|
| **Scout** | pair age 30 min – 72 h, market cap $300k – $20M, quoted in SOL/USDC/USDT | DexScreener (source of truth). Mints are fed in from DexScreener profiles/boosts/takeovers, Jupiter trending/traded/organic/recent and GeckoTerminal trending/new/top-volume pools |
| **Filter** | kill: mint authority not revoked | Solana RPC `getAccountInfo` (falls back to RugCheck, then Jupiter) |
| | kill: freeze authority not revoked | same |
| | kill: LP < 95% burned/locked on the traded pair | RugCheck `markets[].lp.lpLockedPct` |
| | kill: liquidity < $40k | DexScreener |
| | kill: 1h volume < $50k | DexScreener |
| | kill: top 10 holders > 25% (AMM pools and lockers excluded) | RugCheck `topHolders` |
| | kill: dev holds > 3% | RugCheck creator balance / creator wallets in top holders |
| | kill: dev past rugs | RugCheck "creator history of rugged tokens", `rugged` flag, or ≥ 3 dead prior launches |
| | kill: bundled launch > 10% of supply | RugCheck insider networks (linked-wallet clusters) + insider-flagged holders |
| | kill: already +80% in 1h | DexScreener |
| **Analyst** | score 0–100, only 73+ passes (`analyst.min_score`) | see below |
| **Executor** | fixed 1% of equity per trade, max 3 open positions; `executor.max_price_impact_pct` (1%) shrinks an order until its quote fits | Jupiter quote API |
| **Risk** | stop −6% from the fill, set in the same step as the fill; trailing stop arms at +8% and trails 6% under the high | Jupiter price API (DexScreener fallback) |
| **Logger** | every candidate, kill (with every failed rule and its measured value), score, plan, fill, exit | `runs/desk.db`, `runs/<run>/events.jsonl` |

The Filter fails closed. If RugCheck or the authority check can't be read, the coin is killed
as `data_unavailable` and re-checked later. Kills on market data are re-checked after 10 min.
Kills on contract safety stick for 6 h. Analyst kills are re-scored after 5 min.

### Analyst score

| Component | Weight | Input | 0 → 100 |
|---|---|---|---|
| momentum | 20% | 1h and 5m price change, 5m volume pace vs 1h | 0→+40% 1h, −2→+6% 5m, 0.5→1.5× pace |
| unique buyers | 20% | distinct wallets that bought ≥ $25 in the last hour (GeckoTerminal swaps, capped by Jupiter's 1h unique traders) | 50 → 800 per hour (log) |
| buy/sell ratio | 15% | 70% 1h buy/sell volume (Jupiter) + 30% count of ≥ $25 buys vs sells | 0.9× → 1.8× |
| holder growth | 15% | Jupiter 1h and 5m holder change, discounted by the share of new buyers that are sub-$5 dust | 0 → 20%/h, 0 → 2%/5m |
| liq/mcap | 15% | liquidity ÷ market cap | 4% → 16% |
| smart wallets | 15% | smart-book wallets net-buying in the last hour | 0, 1 = 50, 2 = 80, 3+ = 100 |

Most fresh pump.fun coins are flooded with sub-$5 buys from bot-farmed wallets. These inflate
"holders" and "buys". Counting them would reward the manipulation, so buyers and holder growth
are measured at wallet level with the dust removed.

There's no free, trustworthy smart-money list for Solana, so the desk **learns its own**. A
wallet is promoted once it has made at least two profitable round trips on different coins:
each one ≥ +30% and ≥ +$50, held ≥ 60 s, ≤ 40 swaps, win rate ≥ 60%. The evidence comes from
the swaps the desk observes. Until the book holds 10 wallets, the smart-wallet component is
marked unavailable on the scorecard and its weight is spread over the other five. You can
seed wallets you trust in `data/smart_wallets.txt`.

## Run it

Python ≥ 3.11, standard library only. No API keys needed. On macOS and most Linux systems the
command is `python3` (there is no `python`); check the version with `python3 --version`.

```bash
python3 -m desk run --hours 10                 # paper desk overnight
python3 -m desk run --hours 10 --run-id night1 --config my.toml
python3 -m desk once                           # a single scan cycle
python3 -m desk report --run-id night1         # P&L, trades, kill table, top scores
python3 -m desk dashboard                      # web dashboard on http://127.0.0.1:8787
python3 -m desk run --hours 10 --dashboard 8787   # desk and dashboard in one process
python3 -m unittest discover -s tests -t .     # 46 offline tests
```

### Dashboard

`python3 -m desk dashboard` serves a read-only page over `runs/desk.db` that refreshes every
5 seconds. It shows the paper book in percent and has four tabs:

- **Overblik**: return since start, today and the last 24 hours / 7 days / 30 days, win rate,
  average result per trade, the largest drawdown, the return curve, open positions and a
  day-by-day table.
- **Handler**: key figures for the closed trades, and every trade with its result, stake, hold
  time and exit. A row expands to show entry and exit prices, the price impact paid on each side
  and the six score components behind the buy.
- **Marked**: the coins inside the Scout's window right now with their market data and the
  desk's latest verdict on each, how many coins reached each stage, which rules killed them and
  the coins closest to a buy.
- **Desk**: the desk's health, the rules it is running with (read from the configuration) and
  the event log.

It works on a phone, has light and dark themes, uses no external assets, and binds to localhost
unless you pass `--host`. The page text is Danish. It shows what the desk did. It cannot place
orders or move money.

### Running it around the clock

`python3 -m desk run --dashboard 8787` with no `--hours` runs until you stop it, so 24/7 is a
matter of keeping that one command alive on a machine that stays on. With systemd:

```ini
# /etc/systemd/system/memecoin-desk.service
[Service]
WorkingDirectory=/path/to/Coins
ExecStart=/usr/bin/python3 -m desk run --dashboard 8787
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
```

Every scan cycle the desk also writes `runs/state.json`: cash, every position with its stop,
learned wallets and the equity curve. A desk started with an empty database restores from that
file, so the paper book survives a lost machine as long as the file was kept (it is small
enough to commit).

## Know before trusting the numbers

- **Paper only.** `executor.mode` must be `paper`. There is no live broker and no key handling.
- Orders are not shrunk to fit the pool. An 8% order on a $40–60k pool pays roughly 3–4.5%
  in price impact going in and again coming out, and the −6% stop is measured from that fill,
  so it sits only about 2% under the market price at entry.
- By default there is no cap on open positions: cash is the only limit (about twelve 8%
  positions). `executor.max_open_positions` brings a cap back. After a sale the same coin is
  not bought again for two hours (`executor.reentry_cooldown_minutes`).
- Fills use real Jupiter quotes for the exact size, so price impact and pool fees are real.
  Latency, MEV, failed transactions and priority-fee spikes are not modelled. Each swap is
  charged a flat $0.05.
- Stops are checked every 3 s against the mark price. On a fast dump the exit fills at the
  next quote, so a "−6% stop" can realise a bigger loss. The journal records the actual fill.
- "Bundled launch" relies on RugCheck's linked-wallet insider networks. That is a strong proxy,
  not a slot-by-slot reconstruction of the launch block.
- The smart-wallet component is absent for the first hours of a fresh desk while the book fills.
- Discovery is limited to what the public feeds surface. Usually 6–15 coins are inside the
  age/mcap window at any moment.
