"""Strategy test: three rule sets run side by side on the same coins, each on its own
virtual account, so they can be compared fairly from the same start.

  1  Bredt vindue      the current rules, but a wider window: $100k-$20M, 10 min-7 days
  2  Nuværende regler  the rules the real paper desk runs with
  3  Gamle regler      the rules from before 15 Nov: score >= 70, 8% per trade, no impact
                       cap, no position cap, LP >= 90%, trailing stop from +12%
  4  Længere trailing  strategy 2, but the trailing stop arms at +15% and trails 10% under the high
  5  Dybe pools        strategy 2, but only pools with $100k+ liquidity and at most 0.5% price impact
  6  Kræsen            score >= 76, $100k+ liquidity, at most 0.5% impact, trailing from +15% / 10%
  7  Profil B          the user's own profile: 1-24 h, $300k-$10M, stricter filters, score >= 78,
                       6 h cooldown, 2% entry drift cap, >= 1.25% cost per side, 12 h pause after 3 losses
  8  Aggressiv         aims at 1% a day: wide window, score >= 65, 10% stake, 6 open, 30 min cooldown,
                       stop -8%, trailing from +20% / 12%
  9  Hurtig gevinst    strategy 2 plus a +12% take-profit and a 2-hour time stop
  10 Kræsen+           strategy 6 sharpened: $150k+ liquidity, 0.3% impact, at most +40% in 1h,
                       top 10 <= 20%, bundles <= 5%, 3% stake
  11 Kræsen+ stor      strategy 10 with a 6% stake and a 24 h pause after 2 losses in a row
  12 Kræsen+ max       strategy 10 with an 8% stake (the desk's hard maximum) and a 48 h pause after 2 losses
  13 Kræsen+ 15 %      strategy 12 with a 15% stake: virtual only (the paper account's cap stays 8%)
  14 Max kræsen        every picky setting at its tightest realistic value (score >= 82, $250k liquidity,
                       0.2% impact, LP 100%, top 10 <= 15%, dev <= 1%, bundles <= 3%) and a 15% stake
  15 Bred max kræsen   strategy 14's rules in strategy 1's wide window ($100k-$20M, 10 min-7 days)
  16 Bred Kræsen+ 15 % strategy 13's rules in strategy 1's wide window
  17 Mange små         many small trades: wide window, score >= 55, 0.5% stake, 10 open, 15 min cooldown,
                       stop -4%, take-profit +5%, trailing +3%/2%, 30 min time stop

All three are measured the same way: a real Jupiter quote of the book's own order size on
entry (so an 8% order pays its real price impact), the real stop and trailing rules on every
mark, and an estimated sale (the mark minus the price impact the buy paid, minus fees). The
real paper account (strategy 2's rules with real sell quotes) keeps running untouched.

The books get their coins from the desk's normal pipeline: every scorecard the Analyst makes
for the real window, and every scorecard from the shadow's wide window. Filter rules shared by
all three are applied once; the one difference (LP 90% for strategy 3) is checked per book.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field

from .messages import Candidate, new_id
from .store import Store

START_EQUITY = 10_000.0


@dataclass(frozen=True)
class StrategyRules:
    key: str
    name: str
    min_age_minutes: float
    max_age_hours: float
    min_mcap: float
    max_mcap: float
    min_lp_pct: float
    min_score: float
    stake_pct: float
    impact_cap_pct: float        # 0 = no cap
    max_open: int                # 0 = no cap (cash is the only limit)
    cooldown_minutes: float
    stop_pct: float
    trail_trigger_pct: float
    trail_distance_pct: float
    rules: tuple[tuple[str, tuple[str, ...]], ...] = field(default=())
    min_liq_usd: float = 40_000.0    # the Filter already requires $40k; a book can ask for more
    # Stricter filters a book can add on top of the shared Filter (None = use the shared rule).
    # A missing measurement fails the check (fail closed, like the Filter).
    min_vol_1h_usd: float | None = None
    max_change_1h_pct: float | None = None
    max_top10_pct: float | None = None
    max_dev_pct: float | None = None
    max_bundle_pct: float | None = None
    max_entry_drift_pct: float | None = None   # skip if the quote's price moved more than this since the scan
    min_cost_per_side_pct: float = 0.0        # costs per side are at least this (floor on the real impact)
    pause_after_losses: int = 0               # after this many losses in a row ...
    pause_hours: float = 0.0                  # ... buy nothing for this long (0 = never pause)
    take_profit_pct: float | None = None      # sell when the mark is this far above the entry
    max_hold_minutes: float | None = None     # sell after this long, whatever the price


def _rules(r: dict) -> tuple:
    return tuple((k, tuple(v)) for k, v in r.items())


STRATEGIES = (
    StrategyRules(
        "s1", "Bredt vindue", 10, 168, 100_000, 20_000_000, 95, 73, 1.0, 1.0, 3, 120, 6, 8, 6,
        _rules({
            "Scout": ["Alder 10 min.–7 dage", "Markedsværdi $100k–$20 mio."],
            "Filter": ["Som strategi 2 (LP mindst 95 %)"],
            "Analyst": ["Køber ved score 73 eller mere"],
            "Executor": ["1 % af kontoen pr. handel", "Prisvirkning højst 1,0 %", "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Stop −6 %", "Trailing fra +8 %, 6 % under toppen"],
        })),
    StrategyRules(
        "s2", "Nuværende regler", 30, 72, 300_000, 20_000_000, 95, 73, 1.0, 1.0, 3, 120, 6, 8, 6,
        _rules({
            "Scout": ["Alder 30 min.–72 t.", "Markedsværdi $300k–$20 mio."],
            "Filter": ["Likviditet ≥ $40k, 1-times volumen ≥ $50k, ikke +80 % på 1 t.",
                       "Mint/freeze tilbagekaldt, LP mindst 95 % brændt/låst",
                       "Top 10 ≤ 25 %, udvikler ≤ 3 %, bundtede ≤ 10 %"],
            "Analyst": ["Køber ved score 73 eller mere"],
            "Executor": ["1 % af kontoen pr. handel", "Prisvirkning højst 1,0 %", "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Stop −6 %", "Trailing fra +8 %, 6 % under toppen"],
        })),
    StrategyRules(
        "s3", "Gamle regler", 30, 72, 300_000, 20_000_000, 90, 70, 8.0, 0.0, 0, 120, 6, 12, 6,
        _rules({
            "Scout": ["Alder 30 min.–72 t.", "Markedsværdi $300k–$20 mio."],
            "Filter": ["Som strategi 2, men LP mindst 90 % brændt/låst"],
            "Analyst": ["Køber ved score 70 eller mere"],
            "Executor": ["8 % af kontoen pr. handel", "Intet loft på prisvirkning", "Intet loft på antal åbne",
                         "Karantæne 2 t."],
            "Risk": ["Stop −6 %", "Trailing fra +12 %, 6 % under toppen"],
        })),
    StrategyRules(
        "s4", "Længere trailing", 30, 72, 300_000, 20_000_000, 95, 73, 1.0, 1.0, 3, 120, 6, 15, 10,
        _rules({
            "Alt andet": ["Præcis som strategi 2 (vindue, filtre, score 73, 1 %, højst 3 åbne)"],
            "Risk": ["Stop −6 %", "Trailing fra +15 %, 10 % under toppen", "Giver vinderne mere plads"],
        })),
    StrategyRules(
        "s5", "Dybe pools", 30, 72, 300_000, 20_000_000, 95, 73, 1.0, 0.5, 3, 120, 6, 8, 6,
        _rules({
            "Alt andet": ["Præcis som strategi 2 (vindue, filtre, score 73, 1 %, højst 3 åbne, trailing +8 %/6 %)"],
            "Filter": ["Likviditet mindst $100k (i stedet for $40k)"],
            "Executor": ["Prisvirkning højst 0,5 % (i stedet for 1,0 %)", "Billigere handler, færre coins"],
        }), min_liq_usd=100_000),
    StrategyRules(
        "s6", "Kræsen", 30, 72, 300_000, 20_000_000, 95, 76, 1.0, 0.5, 3, 120, 6, 15, 10,
        _rules({
            "Idé": ["Kun de stærkeste coins, billigt købt, og vinderne får plads"],
            "Scout": ["Alder 30 min.–72 t.", "Markedsværdi $300k–$20 mio."],
            "Filter": ["Som strategi 2, men likviditet mindst $100k"],
            "Analyst": ["Køber ved score 76 eller mere"],
            "Executor": ["1 % af kontoen pr. handel", "Prisvirkning højst 0,5 %", "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Stop −6 %", "Trailing fra +15 %, 10 % under toppen"],
        }), min_liq_usd=100_000),
    StrategyRules(
        "s7", "Profil B", 60, 24, 300_000, 10_000_000, 100, 78, 1.0, 1.0, 3, 360, 6, 8, 6,
        _rules({
            "Scout": ["Alder 1–24 t.", "Markedsværdi $300k–$10 mio."],
            "Filter": ["Likviditet ≥ $60k, 1-times volumen ≥ $100k, højst +50 % på 1 t.",
                       "Mint/freeze tilbagekaldt, LP 100 % brændt/låst",
                       "Top 10 ≤ 20 %, udvikler ≤ 2 %, bundtede ≤ 5 %"],
            "Analyst": ["Køber ved score 78 eller mere", "Samme vægte som de andre"],
            "Executor": ["1 % af kontoen pr. handel", "Prisvirkning højst 1,0 %", "Højst 3 åbne",
                         "Karantæne 6 t.", "Køber ikke, hvis kursen har flyttet sig over 2 % siden scanningen",
                         "Regner med mindst 1,25 % i omkostning pr. side"],
            "Risk": ["Stop −6 %", "Trailing fra +8 %, 6 % under toppen", "Pause i 12 t. efter 3 tab i træk"],
        }), min_liq_usd=60_000, min_vol_1h_usd=100_000, max_change_1h_pct=50, max_top10_pct=20,
        max_dev_pct=2, max_bundle_pct=5, max_entry_drift_pct=2.0, min_cost_per_side_pct=1.25,
        pause_after_losses=3, pause_hours=12),
    StrategyRules(
        "s8", "Aggressiv", 10, 168, 100_000, 20_000_000, 90, 65, 10.0, 2.0, 6, 30, 8, 20, 12,
        _rules({
            "Mål": ["1 % afkast om dagen: mange handler, stor indsats, vinderne løber langt"],
            "Scout": ["Alder 10 min.–7 dage", "Markedsværdi $100k–$20 mio. (bredt vindue)"],
            "Filter": ["Som strategi 2, men LP mindst 90 %"],
            "Analyst": ["Køber ved score 65 eller mere"],
            "Executor": ["10 % af kontoen pr. handel", "Prisvirkning højst 2,0 %", "Højst 6 åbne", "Karantæne 30 min."],
            "Risk": ["Stop −8 %", "Trailing fra +20 %, 12 % under toppen"],
        })),
    StrategyRules(
        "s9", "Hurtig gevinst", 30, 72, 300_000, 20_000_000, 95, 73, 1.0, 1.0, 3, 120, 6, 8, 6,
        _rules({
            "Alt andet": ["Præcis som strategi 2 (vindue, filtre, score 73, 1 %, højst 3 åbne)"],
            "Risk": ["Stop −6 %, trailing fra +8 %, 6 % under toppen",
                     "Sælger ved +12 % (gevinstmål)", "Sælger efter 2 timer, hvis intet andet er sket"],
        }), take_profit_pct=12.0, max_hold_minutes=120),
    StrategyRules(
        "s10", "Kræsen+", 30, 72, 300_000, 20_000_000, 95, 76, 3.0, 0.3, 3, 120, 6, 15, 10,
        _rules({
            "Idé": ["Strategi 6 skærpet: endnu billigere handler, ikke for sent ind, og 3 % indsats"],
            "Scout": ["Alder 30 min.–72 t.", "Markedsværdi $300k–$20 mio."],
            "Filter": ["Likviditet mindst $150k", "Højst +40 % på 1 time (ikke for sent ind)",
                       "Top 10 ≤ 20 %, bundtede ≤ 5 %"],
            "Analyst": ["Køber ved score 76 eller mere"],
            "Executor": ["3 % af kontoen pr. handel", "Prisvirkning højst 0,3 %", "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Stop −6 %", "Trailing fra +15 %, 10 % under toppen"],
        }), min_liq_usd=150_000, max_change_1h_pct=40, max_top10_pct=20, max_bundle_pct=5),
    StrategyRules(
        "s11", "Kræsen+ stor", 30, 72, 300_000, 20_000_000, 95, 76, 6.0, 0.3, 3, 120, 6, 15, 10,
        _rules({
            "Idé": ["Strategi 10 med dobbelt indsats, og en pause når det går dårligt"],
            "Alt andet": ["Som strategi 10: likviditet ≥ $150k, prisvirkning ≤ 0,3 %, højst +40 % på 1 t.,",
                          "top 10 ≤ 20 %, bundtede ≤ 5 %, score ≥ 76, trailing +15 %/10 %, stop −6 %"],
            "Executor": ["6 % af kontoen pr. handel", "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Pause i 24 t. efter 2 tab i træk"],
        }), min_liq_usd=150_000, max_change_1h_pct=40, max_top10_pct=20, max_bundle_pct=5,
        pause_after_losses=2, pause_hours=24),
    StrategyRules(
        "s12", "Kræsen+ max", 30, 72, 300_000, 20_000_000, 95, 76, 8.0, 0.3, 3, 120, 6, 15, 10,
        _rules({
            "Idé": ["Strategi 11 med den højeste indsats, desken tillader (8 %), og en længere pause"],
            "Alt andet": ["Som strategi 10: likviditet ≥ $150k, prisvirkning ≤ 0,3 %, højst +40 % på 1 t.,",
                          "top 10 ≤ 20 %, bundtede ≤ 5 %, score ≥ 76, trailing +15 %/10 %, stop −6 %"],
            "Executor": ["8 % af kontoen pr. handel", "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Pause i 48 t. efter 2 tab i træk"],
        }), min_liq_usd=150_000, max_change_1h_pct=40, max_top10_pct=20, max_bundle_pct=5,
        pause_after_losses=2, pause_hours=48),
    StrategyRules(
        "s13", "Kræsen+ 15 %", 30, 72, 300_000, 20_000_000, 95, 76, 15.0, 0.3, 3, 120, 6, 15, 10,
        _rules({
            "Idé": ["Præcis som strategi 12, men 15 % indsats. Kun en større indsats, ikke bedre regler"],
            "Alt andet": ["Som strategi 10: likviditet ≥ $150k, prisvirkning ≤ 0,3 %, højst +40 % på 1 t.,",
                          "top 10 ≤ 20 %, bundtede ≤ 5 %, score ≥ 76, trailing +15 %/10 %, stop −6 %"],
            "Executor": ["15 % af kontoen pr. handel (over den rigtige kontos grænse på 8 %)", "Højst 3 åbne",
                         "Karantæne 2 t."],
            "Risk": ["Pause i 48 t. efter 2 tab i træk", "Ét stop-tab koster ca. 1,4 % af kontoen"],
        }), min_liq_usd=150_000, max_change_1h_pct=40, max_top10_pct=20, max_bundle_pct=5,
        pause_after_losses=2, pause_hours=48),
    StrategyRules(
        "s14", "Max kræsen", 30, 72, 300_000, 20_000_000, 100, 82, 15.0, 0.2, 3, 120, 6, 15, 10,
        _rules({
            "Idé": ["Alle kræsne krav skruet helt op, og 15 % indsats som strategi 13",
                    "Score 82 er det højeste, der er set mere end én gang på 2,6 dage"],
            "Filter": ["Likviditet ≥ $250k, 1-times volumen ≥ $150k, højst +25 % på 1 t.",
                       "LP 100 % brændt/låst, top 10 ≤ 15 %, udvikler ≤ 1 %, bundtede ≤ 3 %"],
            "Analyst": ["Køber ved score 82 eller mere"],
            "Executor": ["15 % af kontoen pr. handel", "Prisvirkning højst 0,2 %", "Køber ikke, hvis kursen har flyttet sig over 1 %",
                         "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Stop −6 %", "Trailing fra +15 %, 10 % under toppen", "Pause i 48 t. efter 2 tab i træk"],
        }), min_liq_usd=250_000, min_vol_1h_usd=150_000, max_change_1h_pct=25, max_top10_pct=15,
        max_dev_pct=1, max_bundle_pct=3, max_entry_drift_pct=1.0, pause_after_losses=2, pause_hours=48),
    StrategyRules(
        "s15", "Bred max kræsen", 10, 168, 100_000, 20_000_000, 100, 82, 15.0, 0.2, 3, 120, 6, 15, 10,
        _rules({
            "Idé": ["Strategi 1's brede vindue med alle strategi 14's stramme krav"],
            "Scout": ["Alder 10 min.–7 dage", "Markedsværdi $100k–$20 mio."],
            "Filter": ["Likviditet ≥ $250k, 1-times volumen ≥ $150k, højst +25 % på 1 t.",
                       "LP 100 % brændt/låst, top 10 ≤ 15 %, udvikler ≤ 1 %, bundtede ≤ 3 %"],
            "Analyst": ["Køber ved score 82 eller mere"],
            "Executor": ["15 % af kontoen pr. handel", "Prisvirkning højst 0,2 %",
                         "Køber ikke, hvis kursen har flyttet sig over 1 %", "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Stop −6 %", "Trailing fra +15 %, 10 % under toppen", "Pause i 48 t. efter 2 tab i træk"],
        }), min_liq_usd=250_000, min_vol_1h_usd=150_000, max_change_1h_pct=25, max_top10_pct=15,
        max_dev_pct=1, max_bundle_pct=3, max_entry_drift_pct=1.0, pause_after_losses=2, pause_hours=48),
    StrategyRules(
        "s16", "Bred Kræsen+ 15 %", 10, 168, 100_000, 20_000_000, 95, 76, 15.0, 0.3, 3, 120, 6, 15, 10,
        _rules({
            "Idé": ["Strategi 1's brede vindue med alle strategi 13's regler"],
            "Scout": ["Alder 10 min.–7 dage", "Markedsværdi $100k–$20 mio."],
            "Filter": ["Likviditet ≥ $150k, højst +40 % på 1 t.", "LP mindst 95 %, top 10 ≤ 20 %, bundtede ≤ 5 %"],
            "Analyst": ["Køber ved score 76 eller mere"],
            "Executor": ["15 % af kontoen pr. handel", "Prisvirkning højst 0,3 %", "Højst 3 åbne", "Karantæne 2 t."],
            "Risk": ["Stop −6 %", "Trailing fra +15 %, 10 % under toppen", "Pause i 48 t. efter 2 tab i træk"],
        }), min_liq_usd=150_000, max_change_1h_pct=40, max_top10_pct=20, max_bundle_pct=5,
        pause_after_losses=2, pause_hours=48),
    StrategyRules(
        "s17", "Mange små", 10, 168, 100_000, 20_000_000, 90, 55, 0.5, 1.0, 10, 15, 4, 3, 2,
        _rules({
            "Idé": ["Rigtig mange små handler: lave krav, lille indsats, hurtigt ude igen"],
            "Scout": ["Alder 10 min.–7 dage", "Markedsværdi $100k–$20 mio. (bredt vindue)"],
            "Filter": ["Som strategi 2, men LP mindst 90 %"],
            "Analyst": ["Køber ved score 55 eller mere"],
            "Executor": ["0,5 % af kontoen pr. handel", "Prisvirkning højst 1,0 %", "Højst 10 åbne", "Karantæne 15 min."],
            "Risk": ["Stop −4 %", "Sælger ved +5 % (gevinstmål)", "Trailing fra +3 %, 2 % under toppen",
                     "Sælger efter 30 min., hvis intet andet er sket"],
        }), take_profit_pct=5.0, max_hold_minutes=30),
)
MIN_LP = min(s.min_lp_pct for s in STRATEGIES)


@dataclass
class BookPosition:
    id: str
    strategy: str
    mint: str
    symbol: str
    pair_address: str
    score: float
    opened_ts: float
    qty: float
    cost_usd: float
    entry_price: float
    entry_impact_pct: float
    stop_price: float
    high_price: float
    trail_active: bool
    trail_trigger_price: float
    trail_distance_pct: float
    last_price: float
    last_price_ts: float
    status: str = "open"
    closed_ts: float | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    proceeds_usd: float | None = None
    pnl_usd: float | None = None


COLS = list(BookPosition.__dataclass_fields__)


class StrategyBook:
    def __init__(self, rules: StrategyRules, store: Store, fit, tx_cost_usd: float, min_order_usd: float,
                 start_ts: float | None = None):
        self.r = rules
        self.store = store
        self.fit = fit                  # (mint, usd, cap) -> (quote, usd, impact_pct, tried)
        self.tx = tx_cost_usd
        self.min_order = min_order_usd
        self.lock = threading.RLock()
        row = store.query("SELECT * FROM strategy_account WHERE strategy=?", (rules.key,))
        if row:
            self.start_ts, self.start_equity, self.cash = row[0]["start_ts"], row[0]["start_equity"], row[0]["cash"]
        else:
            self.start_ts, self.start_equity, self.cash = start_ts or time.time(), START_EQUITY, START_EQUITY
            self._save_account()
        self.open: dict[str, BookPosition] = {}
        for r in store.query("SELECT * FROM strategy_positions WHERE strategy=? AND status='open'", (rules.key,)):
            d = dict(r)
            d["trail_active"] = bool(d["trail_active"])
            self.open[d["id"]] = BookPosition(**d)

    def _save_account(self) -> None:
        self.store.execute("INSERT INTO strategy_account(strategy, start_ts, start_equity, cash) VALUES(?,?,?,?) "
                           "ON CONFLICT(strategy) DO UPDATE SET cash=excluded.cash",
                           (self.r.key, self.start_ts, self.start_equity, self.cash))

    def _save(self, p: BookPosition) -> None:
        d = asdict(p)
        d["trail_active"] = int(d["trail_active"])
        self.store.execute(f"INSERT OR REPLACE INTO strategy_positions({','.join(COLS)}) "
                           f"VALUES({','.join('?' * len(COLS))})", [d[c] for c in COLS])

    def equity(self) -> float:
        with self.lock:
            return self.cash + sum(p.qty * p.last_price for p in self.open.values())

    # ---- entries -------------------------------------------------------------
    def in_window(self, c: Candidate) -> bool:
        return (self.r.min_age_minutes / 60 <= c.pair_age_hours <= self.r.max_age_hours
                and self.r.min_mcap <= c.mcap_usd <= self.r.max_mcap)

    def wants(self, c: Candidate, now: float | None = None) -> bool:
        if not self.in_window(c):
            return False
        now = now or time.time()
        with self.lock:
            if any(p.mint == c.mint for p in self.open.values()):
                return False
            if 0 < self.r.max_open <= len(self.open):
                return False
        last = self.store.query("SELECT MAX(closed_ts) AS t FROM strategy_positions WHERE strategy=? AND mint=?",
                                (self.r.key, c.mint))[0]["t"]
        return not (last and now - last < self.r.cooldown_minutes * 60)

    def qualifies(self, c: Candidate, score: float, checks) -> bool:
        ch = checks if isinstance(checks, dict) else {"lp_locked_pct": checks}
        r = self.r

        def at_most(value, limit):
            return limit is None or (value is not None and value <= limit)
        lp = ch.get("lp_locked_pct")
        return (score >= r.min_score and (lp is None or lp >= r.min_lp_pct)
                and c.liquidity_usd >= r.min_liq_usd
                and (r.min_vol_1h_usd is None or c.volume.get("h1", 0.0) >= r.min_vol_1h_usd)
                and at_most(c.price_change.get("h1"), r.max_change_1h_pct)
                and at_most(ch.get("top10_pct"), r.max_top10_pct)
                and at_most(ch.get("dev_pct"), r.max_dev_pct)
                and at_most(ch.get("bundle_pct"), r.max_bundle_pct))

    def paused(self, now: float) -> bool:
        """After N losses in a row, buy nothing for pause_hours from the last of them."""
        n = self.r.pause_after_losses
        if n <= 0:
            return False
        last = self.store.query("SELECT pnl_usd, closed_ts FROM strategy_positions WHERE strategy=? AND status='closed' "
                                "ORDER BY closed_ts DESC LIMIT ?", (self.r.key, n))
        return (len(last) == n and all((r["pnl_usd"] or 0) < 0 for r in last)
                and now - last[0]["closed_ts"] < self.r.pause_hours * 3600)

    def consider(self, c: Candidate, score: float, checks, decimals: int | None) -> BookPosition | None:
        if not self.qualifies(c, score, checks) or decimals is None:
            return None
        if not self.wants(c) or self.paused(time.time()):
            return None
        with self.lock:
            size = min(self.equity() * self.r.stake_pct / 100, self.cash - self.tx)
        if size < self.min_order:
            return None
        quote, size, impact, _ = self.fit(c.mint, size, self.r.impact_cap_pct)
        if quote is None:
            return None
        spent = int(quote["inAmount"]) / 1e6
        qty = int(quote["outAmount"]) / 10 ** int(decimals)
        if qty <= 0 or spent <= 0:
            return None
        impact = impact or 0.0
        mid = spent / qty / (1 + impact / 100)
        if self.r.max_entry_drift_pct is not None and c.price_usd > 0 \
                and abs(mid / c.price_usd - 1) * 100 > self.r.max_entry_drift_pct:
            return None
        if impact < self.r.min_cost_per_side_pct:    # charge at least the floor: fewer tokens for the same money
            impact = self.r.min_cost_per_side_pct
            qty = spent / (mid * (1 + impact / 100))
        entry = spent / qty
        now = time.time()
        p = BookPosition(
            id=new_id("st"), strategy=self.r.key, mint=c.mint, symbol=c.symbol, pair_address=c.pair_address,
            score=score, opened_ts=now, qty=qty, cost_usd=spent + self.tx, entry_price=entry,
            entry_impact_pct=impact, stop_price=entry * (1 - self.r.stop_pct / 100), high_price=entry,
            trail_active=False, trail_trigger_price=entry * (1 + self.r.trail_trigger_pct / 100),
            trail_distance_pct=self.r.trail_distance_pct, last_price=entry / (1 + impact / 100), last_price_ts=now)
        with self.lock:
            if p.cost_usd > self.cash + 1e-9:
                return None
            self.cash -= p.cost_usd
            self.open[p.id] = p
            self._save(p)
            self._save_account()
        return p

    # ---- marks and exits -----------------------------------------------------------
    def tick(self, marks: dict[str, float], risk, stale_s: float, now: float | None = None) -> list[BookPosition]:
        now = now or time.time()
        closed = []
        with self.lock:
            positions = list(self.open.values())
        for p in positions:
            mark = marks.get(p.mint)
            if mark is None:
                if now - p.last_price_ts > stale_s:
                    closed.append(self._close(p, p.last_price, "stale_price", now))
                continue
            d = risk.evaluate(p, mark, now)
            p.high_price = max(p.high_price, d.high_price)
            p.stop_price = max(p.stop_price, d.stop_price)
            p.trail_active = p.trail_active or d.trail_active
            p.last_price, p.last_price_ts = mark, now
            if d.exit:
                closed.append(self._close(p, mark, d.exit.reason, now))
            elif self.r.take_profit_pct is not None and mark >= p.entry_price * (1 + self.r.take_profit_pct / 100):
                closed.append(self._close(p, mark, "take_profit", now))
            elif self.r.max_hold_minutes is not None and now - p.opened_ts >= self.r.max_hold_minutes * 60:
                closed.append(self._close(p, mark, "time_stop", now))
            else:
                with self.lock:
                    self._save(p)
        return closed

    def _close(self, p: BookPosition, mark: float, reason: str, now: float) -> BookPosition:
        exit_price = mark * (1 - p.entry_impact_pct / 100)       # estimated: the buy's impact again
        proceeds = p.qty * exit_price - self.tx
        p.status, p.closed_ts, p.exit_price, p.exit_reason = "closed", now, exit_price, reason
        p.proceeds_usd, p.pnl_usd = proceeds, proceeds - p.cost_usd
        p.last_price = mark
        with self.lock:
            self.open.pop(p.id, None)
            self.cash += proceeds
            self._save(p)
            self._save_account()
        return p


def reset_if_new_epoch(store: Store, epoch: str | None) -> bool:
    """Start every book over (once) when the configured epoch changes. Only the strategy test's
    own tables and journal lines are removed; the paper account and the shadow book stay."""
    if not epoch or store.get_account("strategy_epoch") == epoch:
        return False
    with store.lock:
        for table in ("strategy_account", "strategy_positions", "strategy_equity"):
            store.conn.execute(f"DELETE FROM {table}")
        store.conn.execute("DELETE FROM events WHERE agent='strategy'")
        store.conn.execute("DELETE FROM account WHERE key='strategy_mark_every_s'")
        store.conn.commit()
    store.set_account("strategy_epoch", epoch)
    return True


class StrategyLab:
    """The strategy books, fed from the desk's pipeline and marked from the shadow thread."""
    EQUITY_EVERY_S = 60.0

    def __init__(self, store: Store, fit, tx_cost_usd: float, min_order_usd: float, risk, stale_s: float,
                 strategies=STRATEGIES, epoch: str | None = None):
        self.reset = reset_if_new_epoch(store, epoch)
        self.store = store
        self.risk = risk
        self.stale_s = stale_s
        start = time.time()                    # books created together share one start
        self.books = [StrategyBook(s, store, fit, tx_cost_usd, min_order_usd, start) for s in strategies]
        self._equity_at = 0.0

    def wants(self, c: Candidate) -> bool:
        return any(b.wants(c) for b in self.books)

    # ---- speed: what each book sees per scan round, and how often it is marked ----------
    def new_round(self, real_window: list[Candidate], wide: list[Candidate]) -> None:
        self.round = {b.r.key: {"window": sum(1 for c in [*real_window, *wide] if b.in_window(c)),
                                "scored": [], "qualified": [], "bought": 0} for b in self.books}

    def note(self, c: Candidate, score: float, lp, bought: list[str]) -> None:
        rnd = getattr(self, "round", None)
        if rnd is None:
            return
        for b in self.books:
            if not b.in_window(c):
                continue
            r = rnd[b.r.key]
            r["scored"].append(c.mint)
            if b.qualifies(c, score, lp):
                r["qualified"].append(c.mint)
            r["bought"] += b.r.key in bought

    def end_round(self) -> dict:
        rnd, self.round = getattr(self, "round", None) or {}, None
        return rnd

    def consider(self, c: Candidate, score: float, checks, decimals: int | None) -> list[BookPosition]:
        out = []
        for b in self.books:
            p = b.consider(c, score, checks, decimals)
            if p:
                out.append(p)
        return out

    def open_positions(self) -> list[BookPosition]:
        return [p for b in self.books for p in list(b.open.values())]

    def tick(self, marks: dict[str, float], now: float | None = None) -> list[BookPosition]:
        now = now or time.time()
        self._ticks = getattr(self, "_ticks", [])
        self._ticks.append(now)
        self._ticks = [t for t in self._ticks if now - t <= 300]
        if len(self._ticks) > 1 and now - getattr(self, "_speed_at", 0) >= 60:
            self._speed_at = now
            gaps = len(self._ticks) - 1
            self.store.set_account("strategy_mark_every_s", (self._ticks[-1] - self._ticks[0]) / gaps)
        closed = [p for b in self.books for p in b.tick(marks, self.risk, self.stale_s, now)]
        if closed or now - self._equity_at >= self.EQUITY_EVERY_S:
            self._equity_at = now
            self.store.executemany("INSERT INTO strategy_equity(ts, strategy, equity) VALUES(?,?,?)",
                                   [(now, b.r.key, b.equity()) for b in self.books])
        return closed
