"""Strategy test: three rule sets run side by side on the same coins, each on its own
virtual account, so they can be compared fairly from the same start.

  1  Bredt vindue      the current rules, but a wider window: $100k-$20M, 10 min-7 days
  2  Nuværende regler  the rules the real paper desk runs with
  3  Gamle regler      the rules from before 15 Nov: score >= 70, 8% per trade, no impact
                       cap, no position cap, LP >= 90%, trailing stop from +12%

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
    def __init__(self, rules: StrategyRules, store: Store, fit, tx_cost_usd: float, min_order_usd: float):
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
            self.start_ts, self.start_equity, self.cash = time.time(), START_EQUITY, START_EQUITY
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

    def consider(self, c: Candidate, score: float, lp_pct: float | None, decimals: int | None) -> BookPosition | None:
        if score < self.r.min_score or (lp_pct is not None and lp_pct < self.r.min_lp_pct) or decimals is None:
            return None
        if not self.wants(c):
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


class StrategyLab:
    """The three books, fed from the desk's pipeline and marked from the shadow thread."""
    EQUITY_EVERY_S = 60.0

    def __init__(self, store: Store, fit, tx_cost_usd: float, min_order_usd: float, risk, stale_s: float,
                 strategies=STRATEGIES):
        self.store = store
        self.risk = risk
        self.stale_s = stale_s
        self.books = [StrategyBook(s, store, fit, tx_cost_usd, min_order_usd) for s in strategies]
        self._equity_at = 0.0

    def wants(self, c: Candidate) -> bool:
        return any(b.wants(c) for b in self.books)

    def consider(self, c: Candidate, score: float, lp_pct: float | None, decimals: int | None) -> list[BookPosition]:
        out = []
        for b in self.books:
            p = b.consider(c, score, lp_pct, decimals)
            if p:
                out.append(p)
        return out

    def open_positions(self) -> list[BookPosition]:
        return [p for b in self.books for p in list(b.open.values())]

    def tick(self, marks: dict[str, float], now: float | None = None) -> list[BookPosition]:
        now = now or time.time()
        closed = [p for b in self.books for p in b.tick(marks, self.risk, self.stale_s, now)]
        if closed or now - self._equity_at >= self.EQUITY_EVERY_S:
            self._equity_at = now
            self.store.executemany("INSERT INTO strategy_equity(ts, strategy, equity) VALUES(?,?,?)",
                                   [(now, b.r.key, b.equity()) for b in self.books])
        return closed
