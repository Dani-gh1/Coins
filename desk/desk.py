"""The desk: wires the six agents together with hard handoffs and runs two loops.

scan loop (every scan_interval_seconds)
    Scout -> Candidate -> Filter -> FilterPass | Kill
                       -> Analyst -> ScoreCard (>=70) | Kill | Deferral
                       -> Risk.plan -> RiskPlan -> Executor.enter -> Fill + Position | Kill
    then the smart-wallet learner sweeps a couple of trending pools.
risk loop (every risk.poll_seconds)
    Executor.open_positions -> marks -> Risk.evaluate -> Executor.apply / ExitSignal -> Executor.exit
Everything is written by the Logger.
"""
from __future__ import annotations

import signal
import threading
import time
import traceback
from pathlib import Path

from .agents.analyst import Analyst
from .agents.executor import Executor
from .agents.filter import Filter
from .agents.logger import Logger
from .agents.risk import Risk
from .agents.scout import Scout
from .config import DeskConfig
from .messages import Deferral, Kill, ScoreCard
from .smart_wallets import SmartWalletBook
from .sources import Sources
from .store import Store


class Desk:
    def __init__(self, cfg: DeskConfig, run_id: str, echo: bool = True, sources: Sources | None = None):
        self.cfg = cfg
        self.run_id = run_id
        data_dir = Path(cfg.data_dir)
        self.run_dir = data_dir / run_id
        self.store = Store(data_dir / "desk.db")
        self.log = Logger(self.store, self.run_dir / "events.jsonl", run_id, echo=echo)
        self.src = sources or Sources()
        self.book = SmartWalletBook(self.store, cfg.smart_wallet_seed_file)
        self.scout = Scout(cfg.scout, self.src)
        self.filter = Filter(cfg.filter, self.src)
        self.analyst = Analyst(cfg.analyst, self.src, self.book)
        self.risk = Risk(cfg.risk, cfg.analyst)
        self.executor = Executor(cfg.executor, self.src, self.store, self.risk)
        self.stop_event = threading.Event()
        now = time.time()
        self.recheck_at: dict[str, float] = {
            r["mint"]: r["t"] for r in self.store.query(
                "SELECT mint, MAX(recheck_at) AS t FROM kills GROUP BY mint HAVING t > ?", (now,))}
        self.learner_swept: dict[str, float] = {}
        self.cycle = 0

    # ---- scan loop -------------------------------------------------------------
    def scan_cycle(self) -> dict:
        self.cycle += 1
        t0 = time.time()
        rep = self.scout.scan()
        now = time.time()
        fresh, held, suppressed = [], 0, 0
        for c in rep.candidates:
            if self.executor.holds(c.mint):
                held += 1
                continue
            if self.recheck_at.get(c.mint, 0) > now:
                suppressed += 1
                continue
            self.log.candidate(c)
            fresh.append(c)
        self.log.event("scout", "scan", {
            "cycle": self.cycle, "mints_seen": rep.mints_seen, "pairs_seen": rep.pairs_seen,
            "in_window": len(rep.candidates), "new_to_evaluate": len(fresh), "held": held,
            "waiting_recheck": suppressed, "feeds": rep.feed_counts},
            line=f"cycle {self.cycle}: {rep.mints_seen} mints -> {len(rep.candidates)} in window "
                 f"(30m-72h, $300k-$20M) -> {len(fresh)} to filter ({suppressed} cooling down, {held} held)")

        stats = {"killed_filter": 0, "passed_filter": 0, "scored": 0, "passed_analyst": 0,
                 "deferred": 0, "entered": 0}
        for result in self.filter.evaluate(fresh):
            if isinstance(result, Kill):
                self._kill(result)
                stats["killed_filter"] += 1
                continue
            stats["passed_filter"] += 1
            self.log.filter_pass(result)
            card = self.analyst.evaluate(result)
            if isinstance(card, Deferral):
                self.log.deferral(card)
                stats["deferred"] += 1
                continue
            stats["scored"] += 1
            self.log.scorecard(card)
            if not card.passed:
                self._kill(self._analyst_kill(card))
                continue
            stats["passed_analyst"] += 1
            plan = self.risk.plan(card)
            self.log.risk_plan(plan)
            if not plan.approved:
                continue
            outcome = self.executor.enter(plan)
            if isinstance(outcome, Kill):
                self._kill(outcome)
            else:
                self.log.fill(*outcome)
                stats["entered"] += 1

        self._learn()
        stats.update(cycle=self.cycle, seconds=round(time.time() - t0, 1),
                     equity=round(self.executor.equity(), 2), cash=round(self.executor.cash, 2),
                     open_positions=len(self.executor.positions), smart_wallets=self.book.size())
        self.log.event("desk", "cycle", stats,
                       line=f"cycle {self.cycle} done in {stats['seconds']}s | equity ${stats['equity']:,.2f} "
                            f"| open {stats['open_positions']} | smart book {stats['smart_wallets']}")
        return stats

    def _analyst_kill(self, card: ScoreCard) -> Kill:
        c = card.candidate
        weak = sorted(((k, v) for k, v in card.components.items() if v is not None), key=lambda kv: kv[1])[:3]
        reason = (f"score {card.score:.1f} < {self.cfg.analyst.min_score:.0f} "
                  f"(weakest: {', '.join(f'{k}={v:.0f}' for k, v in weak)})")
        return Kill(stage="analyst", mint=c.mint, symbol=c.symbol, reasons=(reason,),
                    metrics={"score": card.score, "components": card.components},
                    recheck_after_s=self.cfg.analyst.rescore_after_minutes * 60, candidate_id=c.id)

    def _kill(self, k: Kill) -> None:
        self.log.kill(k)
        self.recheck_at[k.mint] = k.ts + k.recheck_after_s

    def _learn(self) -> None:
        if self.cfg.learner_pools_per_cycle <= 0:
            return
        now = time.time()
        pools = [p for p in self.scout.last_trending if now - self.learner_swept.get(p, 0) > 600]
        for pool in pools[: self.cfg.learner_pools_per_cycle]:
            self.learner_swept[pool] = now
            trades = self.src.gecko.trades(pool)
            if not trades:
                continue
            mint = self.scout.pool_mint.get(pool)
            if not mint:
                continue
            promoted = self.book.ingest(mint, trades)
            if promoted:
                self.log.event("analyst", "smart_wallets_learned",
                               {"pool": pool, "mint": mint, "wallets": promoted, "book_size": self.book.size()},
                               line=f"smart-wallet book +{len(promoted)} -> {self.book.size()}")

    # ---- risk loop -------------------------------------------------------------
    def risk_tick(self) -> None:
        positions = self.executor.open_positions()
        if not positions:
            return
        marks = self.src.jup.prices([p.mint for p in positions])
        missing = [p.mint for p in positions if p.mint not in marks]
        if missing:
            for pair in self.src.dex.pairs_for_tokens(missing):
                mint = (pair.get("baseToken") or {}).get("address")
                if mint in missing and pair.get("priceUsd") and mint not in marks:
                    marks[mint] = float(pair["priceUsd"])
        now = time.time()
        for pos in positions:
            mark = marks.get(pos.mint)
            if mark is None:
                if now - pos.last_price_ts > self.cfg.risk.stale_price_seconds:
                    self.log.event("risk", "stale_price", {"position_id": pos.id,
                                                           "age_s": round(now - pos.last_price_ts)},
                                   mint=pos.mint, symbol=pos.symbol)
                continue
            decision = self.risk.evaluate(pos, mark, now)
            if decision.trail_active and not pos.trail_active:
                self.log.event("risk", "trail_armed", {"position_id": pos.id, "high": decision.high_price,
                                                       "stop": decision.stop_price},
                               mint=pos.mint, symbol=pos.symbol,
                               line=f"TRAIL {pos.symbol:<10} armed at {mark:.8g} (+"
                                    f"{(mark / pos.entry_price - 1) * 100:.1f}%), stop -> {decision.stop_price:.8g}")
            self.executor.apply(decision, now)
            if decision.exit:
                self.log.exit_signal(decision.exit)
                result = self.executor.exit(decision.exit)
                if result:
                    self.log.fill(*result)
                else:
                    self.log.event("executor", "exit_retry", {"position_id": pos.id},
                                   mint=pos.mint, symbol=pos.symbol, line=f"exit for {pos.symbol} pending (no route)")

    def _risk_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.risk_tick()
            except Exception as e:  # keep risk alive no matter what
                self.log.event("risk", "error", {"error": repr(e), "trace": traceback.format_exc()},
                               line=f"risk error: {e!r}")
            self.stop_event.wait(self.cfg.risk.poll_seconds)

    # ---- lifecycle --------------------------------------------------------------
    def run(self, hours: float | None = None) -> None:
        deadline = time.time() + hours * 3600 if hours else None

        def _stop(signum, _frame):
            self.log.say("desk", f"signal {signum}: shutting down")
            self.stop_event.set()
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        self.log.event("desk", "start", {"hours": hours, "equity": self.executor.equity(),
                                         "open_positions": len(self.executor.positions),
                                         "smart_wallets": self.book.size()},
                       line=f"run {self.run_id} starting (paper) equity ${self.executor.equity():,.2f}")
        risk_thread = threading.Thread(target=self._risk_loop, name="risk", daemon=True)
        risk_thread.start()
        try:
            while not self.stop_event.is_set():
                started = time.time()
                try:
                    self.scan_cycle()
                except Exception as e:
                    self.log.event("desk", "error", {"error": repr(e), "trace": traceback.format_exc()},
                                   line=f"scan error: {e!r}")
                if self.cycle % 30 == 0:
                    self.book.prune()
                if deadline and time.time() >= deadline:
                    break
                wait = self.cfg.scan_interval_seconds - (time.time() - started)
                if deadline:
                    wait = min(wait, deadline - time.time())
                if wait > 0:
                    self.stop_event.wait(wait)
        finally:
            self.stop_event.set()
            risk_thread.join(timeout=30)
            self.log.event("desk", "stop", {"equity": self.executor.equity(),
                                            "open_positions": len(self.executor.positions),
                                            "http": dict(self.src.http.stats)},
                           line=f"run {self.run_id} stopped, equity ${self.executor.equity():,.2f}")
            self.log.close()
