import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from desk.config import DeskConfig
from desk.dashboard import DashboardServer, _drop_restarts, _equity_points, rule_code, snapshot
from desk.desk import Desk

from tests.test_executor_desk import sources


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "desk.db"
        self.src = sources()
        self.desk = Desk(DeskConfig(data_dir=self.tmp.name, smart_wallet_seed_file="/nonexistent"),
                         "test", echo=False, sources=self.src)

    def tearDown(self):
        self.desk.log.close()
        self.desk.store.close()
        self.tmp.cleanup()

    def test_missing_database_is_an_empty_state(self):
        self.assertTrue(snapshot(Path(self.tmp.name) / "nope.db")["empty"])

    def test_open_position_then_closed_trade(self):
        self.desk.scan_cycle()
        snap = snapshot(self.db)
        acct = snap["account"]
        self.assertTrue(snap["status"]["running"])
        self.assertEqual(len(snap["open_positions"]), 1)
        pos = snap["open_positions"][0]
        self.assertAlmostEqual(pos["stop_pct"], -6.0, places=6)
        self.assertAlmostEqual(acct["equity"], acct["cash"] + pos["value_usd"])
        # a fresh position is marked at the mid the quote implies: down by its impact, no more
        self.assertAlmostEqual(pos["unrealized_pct"], -0.5, delta=0.1)
        self.assertEqual(snap["funnel"], {"in_window": 3, "passed_filter": 1, "scored_pass": 1, "bought": 1})
        rules = {(k["stage"], k["rule"]): k["coins"] for k in snap["kills"]}
        self.assertEqual(rules[("filter", "low_liquidity")], 1)
        self.assertEqual(rules[("filter", "bundled")], 1)
        self.assertEqual(snap["kill_decisions"], 2)
        self.assertTrue(snap["top_scores"][0]["traded"])

        self.src.jup.price["GOOD"] = 0.0005          # collapse -> stop loss
        self.desk.risk_tick()
        snap = snapshot(self.db)
        self.assertEqual(snap["open_positions"], [])
        trade = snap["closed_trades"][0]
        self.assertEqual(trade["exit_reason"], "stop_loss")
        self.assertLess(trade["pnl_pct"], -40)
        self.assertAlmostEqual(trade["pnl_pct"], trade["pnl_usd"] / trade["cost_usd"] * 100)
        acct = snap["account"]
        self.assertAlmostEqual(acct["equity"], acct["starting_equity"] + trade["pnl_usd"], places=6)
        self.assertEqual((acct["wins"], acct["losses"], acct["win_rate"]), (0, 1, 0.0))
        kinds = [a["kind"] for a in snap["activity"]]
        self.assertEqual(kinds[:3], ["fill_sell", "exit_signal", "fill_buy"])

    def test_http_serves_page_and_state(self):
        self.desk.scan_cycle()
        server = DashboardServer(self.db, "127.0.0.1", 0)
        server.start_in_thread()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(base + "/") as r:
                self.assertEqual(r.status, 200)
                self.assertIn(b"Memecoin-desk", r.read())
            with opener.open(base + "/api/state") as r:
                self.assertEqual(json.load(r)["account"]["closed_trades"], 0)
            with self.assertRaises(urllib.error.HTTPError) as err:
                opener.open(base + "/desk.db")
            self.assertEqual(err.exception.code, 404)
            err.exception.close()
        finally:
            server.shutdown()
            server.server_close()


class HelperTests(unittest.TestCase):
    def test_rule_codes(self):
        self.assertEqual(rule_code("filter", "low_liquidity: $1 < $40,000"), "low_liquidity")
        self.assertEqual(rule_code("analyst", "score 41.0 < 70 (weakest: ...)"), "score_below_min")
        self.assertEqual(rule_code("executor", "price impact 2.2% > 2.0% even at $70"), "price_impact")
        self.assertEqual(rule_code("executor", "re-entry cooldown"), "reentry_cooldown")

    def test_equity_curve_keeps_only_the_steps(self):
        rows = [(t, 100.0) for t in range(10, 60, 10)] + [(60, 110.0), (70, 110.0), (80, 110.0)]
        self.assertEqual(_equity_points(rows, 0, 100.0),
                         [[0, 100.0], [50, 100.0], [60, 110.0], [80, 110.0]])

    def test_restarts_are_hidden_but_real_stops_stay(self):
        feed = [{"kind": "stop", "ts": 1000}, {"kind": "start", "ts": 500}, {"kind": "stop", "ts": 495},
                {"kind": "fill_buy", "ts": 300}, {"kind": "start", "ts": 100}]
        self.assertEqual([(a["kind"], a["ts"]) for a in _drop_restarts(feed)],
                         [("stop", 1000), ("fill_buy", 300), ("start", 100)])


if __name__ == "__main__":
    unittest.main()
