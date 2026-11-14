"""Read-only web dashboard over the desk's SQLite journal.

  python -m desk dashboard [--port 8787] [--host 127.0.0.1]
  python -m desk run --dashboard 8787          # desk + dashboard in one process

GET /            the page (desk/dashboard.html, no external assets)
GET /api/state   one JSON snapshot: account, positions, trades, equity curve, funnel, kills

The server never writes to the database and exposes no actions - it only shows what the
desk has done. It binds to localhost unless you pass --host.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).with_name("dashboard.html")
RUNNING_WITHIN_S = 180.0      # the desk logs a scan every cycle; quieter than this = stopped
ACTIVITY_KINDS = ("fill_buy", "fill_sell", "exit_signal", "trail_armed", "start", "stop",
                  "error", "smart_wallets_learned")


def rule_code(stage: str, reason: str) -> str:
    """Stable code for a kill reason, so the page can label and group it."""
    if stage == "analyst":
        return "score_below_min"
    if stage == "executor":
        if reason.startswith("price impact"):
            return "price_impact"
        if reason.startswith("re-entry cooldown"):
            return "reentry_cooldown"
        if reason.startswith("max open positions"):
            return "max_positions"
        if reason.startswith("already holding"):
            return "already_holding"
        if "Jupiter route" in reason:
            return "no_route"
        if reason.startswith(("order $", "insufficient cash")):
            return "no_cash"
        return "executor_other"
    return reason.split(":", 1)[0]


def _reason(stage: str, text: str) -> dict:
    """A kill reason as {code, detail}; filter reasons are logged as "code: measured value"."""
    detail = text.split(":", 1)[1].strip() if stage == "filter" and ":" in text else text
    return {"code": rule_code(stage, text), "detail": detail}


def _drop_restarts(items: list[dict], within_s: float = 120.0) -> list[dict]:
    """Hide stop->start pairs a couple of minutes apart: that is the desk being restarted,
    not something the reader needs to see. `items` is newest first."""
    out: list[dict] = []
    i = 0
    while i < len(items):
        cur, older = items[i], items[i + 1] if i + 1 < len(items) else None
        if (cur["kind"] == "start" and older is not None and older["kind"] == "stop"
                and cur["ts"] - older["ts"] <= within_s):
            i += 2
            continue
        out.append(cur)
        i += 1
    return out


def _equity_points(rows: list, start_ts: float | None, start_equity: float, max_points: int = 600) -> list:
    """Compress the per-cycle equity series: keep the points around every change."""
    pts: list[list[float]] = []
    prev = None
    if start_ts is not None:
        pts.append([start_ts, start_equity])
        prev = (start_ts, start_equity)
    for ts, eq in rows:
        if eq is None:
            continue
        if prev is not None and eq != prev[1] and pts[-1][0] != prev[0]:
            pts.append(list(prev))            # the last point before the change (keeps steps square)
        if prev is None or eq != prev[1]:
            pts.append([ts, eq])
        prev = (ts, eq)
    if prev is not None and pts[-1][0] != prev[0]:
        pts.append(list(prev))
    if len(pts) > max_points:                 # many mark-to-market wiggles: thin evenly, keep the ends
        stride = len(pts) / max_points
        pts = [pts[int(i * stride)] for i in range(max_points - 1)] + [pts[-1]]
    return [[round(t, 1), round(e, 2)] for t, e in pts]


def snapshot(db_path: str | Path, min_score: float = 70.0, now: float | None = None) -> dict:
    now = now or time.time()
    base = {"generated_ts": now, "mode": "paper", "min_score": min_score}
    if not Path(db_path).exists():
        return {**base, "empty": True}
    conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        return {**base, "empty": False, **_read(conn, min_score, now)}
    finally:
        conn.close()


def _read(conn: sqlite3.Connection, min_score: float, now: float) -> dict:
    def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return conn.execute(sql, params).fetchall()

    def account(key: str, default: float) -> float:
        rows = q("SELECT value FROM account WHERE key=?", (key,))
        return float(json.loads(rows[0]["value"])) if rows else default

    start_equity = account("starting_equity", 0.0)
    cash = account("cash", start_equity)

    open_pos, closed = [], []
    for r in q("SELECT * FROM positions ORDER BY opened_ts"):
        p = dict(r)
        entry = p["entry_price"] or 0.0
        if p["status"] == "open":
            value = p["qty"] * p["last_price"]
            open_pos.append({
                "symbol": p["symbol"], "mint": p["mint"], "score": p["score"], "opened_ts": p["opened_ts"],
                "cost_usd": p["cost_usd"], "entry_price": entry, "last_price": p["last_price"],
                "last_price_ts": p["last_price_ts"], "stop_price": p["stop_price"],
                "stop_pct": (p["stop_price"] / entry - 1) * 100 if entry else 0.0,
                "trail_active": bool(p["trail_active"]), "value_usd": value,
                "unrealized_usd": value - p["cost_usd"],
                "unrealized_pct": (value / p["cost_usd"] - 1) * 100 if p["cost_usd"] else 0.0,
            })
        else:
            closed.append({
                "symbol": p["symbol"], "mint": p["mint"], "score": p["score"],
                "opened_ts": p["opened_ts"], "closed_ts": p["closed_ts"],
                "duration_s": (p["closed_ts"] or 0) - (p["opened_ts"] or 0),
                "cost_usd": p["cost_usd"], "proceeds_usd": p["proceeds_usd"], "pnl_usd": p["pnl_usd"],
                "pnl_pct": (p["pnl_usd"] / p["cost_usd"] * 100) if p["cost_usd"] else 0.0,
                "entry_price": entry, "exit_price": p["exit_price"],
                "max_gain_pct": (p["high_price"] / entry - 1) * 100 if entry else 0.0,
                "exit_reason": p["exit_reason"],
            })
    closed.sort(key=lambda t: t["closed_ts"] or 0, reverse=True)

    open_value = sum(p["value_usd"] for p in open_pos)
    unrealized = sum(p["unrealized_usd"] for p in open_pos)
    realized = sum(t["pnl_usd"] or 0.0 for t in closed)
    wins = sum(1 for t in closed if (t["pnl_usd"] or 0) > 0)
    equity = cash + open_value

    span = q("SELECT MIN(ts) AS a, MAX(ts) AS b FROM events")[0]
    last = q("SELECT run_id FROM events ORDER BY id DESC LIMIT 1")
    cycles = q("SELECT COUNT(*) AS n FROM events WHERE kind='cycle'")[0]["n"]
    curve = _equity_points(
        [(r["ts"], r["eq"]) for r in q(
            "SELECT ts, json_extract(payload, '$.equity') AS eq FROM events WHERE kind='cycle' ORDER BY ts")],
        span["a"], start_equity)
    if curve and span["b"] and (span["b"] - curve[-1][0] > 1 or abs(curve[-1][1] - equity) >= 0.005):
        curve.append([round(max(span["b"], curve[-1][0]), 1), round(equity, 2)])   # bring the line up to now

    # ---- funnel (distinct coins) and why coins were killed -------------------
    funnel = {
        "in_window": q("SELECT COUNT(DISTINCT mint) AS n FROM events WHERE kind='candidate'")[0]["n"],
        "passed_filter": q("SELECT COUNT(DISTINCT mint) AS n FROM events WHERE kind='pass'")[0]["n"],
        "scored_pass": q("SELECT COUNT(DISTINCT mint) AS n FROM scores WHERE passed=1")[0]["n"],
        "bought": q("SELECT COUNT(DISTINCT mint) AS n FROM positions")[0]["n"],
    }
    by_rule: dict[tuple[str, str], dict] = {}
    for k in q("SELECT stage, mint, reasons FROM kills"):
        for reason in json.loads(k["reasons"]):
            slot = by_rule.setdefault((k["stage"], rule_code(k["stage"], reason)), {"coins": set(), "hits": 0})
            slot["coins"].add(k["mint"])
            slot["hits"] += 1
    kills = sorted(({"stage": stage, "rule": rule, "coins": len(v["coins"]), "hits": v["hits"]}
                    for (stage, rule), v in by_rule.items()), key=lambda r: (-r["coins"], -r["hits"]))
    recent_kills = [{"ts": r["ts"], "stage": r["stage"], "symbol": r["symbol"], "mint": r["mint"],
                     "reasons": [_reason(r["stage"], text) for text in json.loads(r["reasons"])]}
                    for r in q("SELECT ts, stage, symbol, mint, reasons FROM kills ORDER BY id DESC LIMIT 12")]

    # ---- best score per coin ---------------------------------------------------
    traded = {p["mint"] for p in open_pos} | {t["mint"] for t in closed}
    top_scores = [{"symbol": r["symbol"], "mint": r["mint"], "score": r["score"], "ts": r["ts"],
                   "scorecards": r["n"], "components": json.loads(r["components"]),
                   "traded": r["mint"] in traded}
                  for r in q("SELECT mint, symbol, MAX(score) AS score, components, ts, COUNT(*) AS n "
                             "FROM scores GROUP BY mint ORDER BY score DESC LIMIT 8")]

    # ---- notable events ---------------------------------------------------------
    marks = ",".join("?" * len(ACTIVITY_KINDS))
    activity = []
    for r in q(f"SELECT ts, kind, symbol, payload FROM events WHERE kind IN ({marks}) "
               "ORDER BY id DESC LIMIT 60", ACTIVITY_KINDS):
        p = json.loads(r["payload"] or "{}")
        pos = p.get("position") or {}
        item = {"ts": r["ts"], "kind": r["kind"], "symbol": r["symbol"]}
        if r["kind"] == "fill_buy":
            item.update(usd=p.get("usd"), score=pos.get("score"), impact_pct=p.get("impact_pct"))
        elif r["kind"] == "fill_sell":
            cost = pos.get("cost_usd") or 0.0
            pnl = pos.get("pnl_usd") or 0.0
            item.update(pnl_usd=pnl, pnl_pct=(pnl / cost * 100) if cost else 0.0,
                        reason=pos.get("exit_reason"))
        elif r["kind"] == "exit_signal":
            item.update(reason=p.get("reason"))
        elif r["kind"] in ("start", "stop"):
            item.update(equity=p.get("equity"))
        elif r["kind"] == "error":
            item.update(error=str(p.get("error"))[:200])
        elif r["kind"] == "smart_wallets_learned":
            item.update(book_size=p.get("book_size"))
        activity.append(item)
    activity = _drop_restarts(activity)

    scan = q("SELECT ts, payload FROM events WHERE kind='scan' ORDER BY id DESC LIMIT 1")
    last_scan = None
    if scan:
        sp = json.loads(scan[0]["payload"] or "{}")
        last_scan = {"ts": scan[0]["ts"], "mints_seen": sp.get("mints_seen"), "in_window": sp.get("in_window")}

    return {
        "status": {
            "running": bool(span["b"]) and now - span["b"] < RUNNING_WITHIN_S,
            "last_event_ts": span["b"], "first_event_ts": span["a"],
            "run_id": last[0]["run_id"] if last else None, "cycles": cycles, "last_scan": last_scan,
        },
        "account": {
            "starting_equity": start_equity, "cash": cash, "open_value": open_value, "equity": equity,
            "return_pct": (equity / start_equity - 1) * 100 if start_equity else 0.0,
            "pnl_usd": equity - start_equity, "realized_usd": realized, "unrealized_usd": unrealized,
            "closed_trades": len(closed), "wins": wins, "losses": len(closed) - wins,
            "win_rate": (wins / len(closed) * 100) if closed else None,
            "smart_wallets": q("SELECT COUNT(*) AS n FROM smart_wallets")[0]["n"],
        },
        "equity_curve": curve,
        "open_positions": open_pos,
        "closed_trades": closed,
        "funnel": funnel,
        "kills": kills,
        "kill_decisions": q("SELECT COUNT(*) AS n FROM kills")[0]["n"],
        "recent_kills": recent_kills,
        "top_scores": top_scores,
        "activity": activity,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "desk-dashboard"

    def _send(self, status: int, ctype: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
            elif path == "/api/state":
                body = json.dumps(self.server.state()).encode()          # type: ignore[attr-defined]
                self._send(200, "application/json", body)
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # a bad read must not kill the server
            self._send(500, "application/json", json.dumps({"error": repr(e)}).encode())

    def log_message(self, *_args) -> None:   # keep the desk's console clean
        pass


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, db_path: str | Path, host: str = "127.0.0.1", port: int = 8787,
                 min_score: float = 70.0, cache_seconds: float = 2.0):
        super().__init__((host, port), _Handler)
        self.db_path = Path(db_path)
        self.min_score = min_score
        self.cache_seconds = cache_seconds
        self._cache: tuple[float, dict] | None = None
        self._lock = threading.Lock()

    def state(self) -> dict:
        with self._lock:
            if self._cache and time.time() - self._cache[0] < self.cache_seconds:
                return self._cache[1]
            snap = snapshot(self.db_path, self.min_score)
            self._cache = (time.time(), snap)
            return snap

    def start_in_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, name="dashboard", daemon=True)
        t.start()
        return t
