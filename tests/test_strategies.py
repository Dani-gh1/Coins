"""Strategy test: three rule sets on virtual accounts, fed from the desk's pipeline."""
import tempfile
import unittest
import urllib.request

from desk.config import DeskConfig
from desk.dashboard import DashboardServer, snapshot
from desk.desk import Desk

from tests.fakes import FakeSources, candidate, jup_token, pair, rug_report, trades


def market(extra_pairs=(), extra_rugs=None):
    mints = ["GOOD"] + [p["baseToken"]["address"] for p in extra_pairs]
    rugs = {"GOOD": rug_report("GOOD")}
    rugs.update(extra_rugs or {m: rug_report(m) for m in mints if m != "GOOD"})
    return FakeSources(
        pairs=[pair(mint="GOOD", symbol="GOOD"), *extra_pairs], rugs=rugs,
        jup_tokens={m: jup_token(m) for m in mints}, prices={m: 0.001 for m in mints},
        trades_by_pool={f"PAIR_{m}": trades(n_real=150, n_sells=40, prefix=m) for m in mints})


class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def desk(self, src):
        self.d = Desk(DeskConfig(data_dir=self.tmp.name, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=src)
        return self.d

    def close(self):
        self.d.log.close()
        self.d.store.close()

    def books(self):
        return {b.r.key: b for b in self.d.lab.books}

    def test_a_good_coin_is_bought_by_every_book_at_its_own_size(self):
        desk = self.desk(market())
        desk.scan_cycle()
        b = self.books()
        stakes = {k: [p.cost_usd / 10_000 * 100 for p in v.open.values()] for k, v in b.items()}
        self.assertAlmostEqual(stakes["s1"][0], 1.0, delta=0.05)
        self.assertAlmostEqual(stakes["s2"][0], 1.0, delta=0.05)
        self.assertAlmostEqual(stakes["s3"][0], 8.0, delta=0.05)
        self.close()

    def test_score_lp_and_window_rules_per_book(self):
        desk = self.desk(market())
        lab = desk.lab
        c = candidate(mint="M71", symbol="M71")
        desk.src.jup.tokens_["M71"], desk.src.jup.price["M71"] = jup_token("M71"), 0.001
        self.assertEqual([p.strategy for p in lab.consider(c, 71.0, 100.0, 6)], ["s3"])         # 70 <= score < 73
        c2 = candidate(mint="LP92", symbol="LP92")
        desk.src.jup.tokens_["LP92"], desk.src.jup.price["LP92"] = jup_token("LP92"), 0.001
        self.assertEqual([p.strategy for p in lab.consider(c2, 80.0, 92.0, 6)], ["s3"])       # LP 90-95 %
        young = candidate(mint="YNG", symbol="YNG", age_h=0.25)
        desk.src.jup.tokens_["YNG"], desk.src.jup.price["YNG"] = jup_token("YNG"), 0.001
        self.assertEqual([p.strategy for p in lab.consider(young, 80.0, 100.0, 6)], ["s1"])   # wide window only
        self.close()

    def test_lp_90_to_95_coin_killed_by_the_real_filter_reaches_strategy_3(self):
        lp = pair(mint="LP92", symbol="LP92")
        desk = self.desk(market([lp], {"LP92": rug_report("LP92", lp_locked=92.0)}))
        stats = desk.scan_cycle()
        self.assertEqual(stats["entered"], 1)                                   # the real desk: GOOD only
        held = {k: {p.mint for p in v.open.values()} for k, v in self.books().items()}
        self.assertEqual(held["s3"], {"GOOD", "LP92"})
        self.assertEqual(held["s2"], {"GOOD"})
        self.close()

    def test_trailing_rules_differ_and_caps_hold(self):
        desk = self.desk(market())
        desk.scan_cycle()
        src = desk.src
        src.jup.price["GOOD"] = 0.0011          # +10%: trail arms for s1/s2 (+8%), not for s3 (+12%)
        desk.shadow_tick()
        src.jup.price["GOOD"] = 0.00102         # back down: s1/s2 hit their trailing stop, s3 holds
        desk.shadow_tick()
        b = self.books()
        self.assertEqual((len(b["s1"].open), len(b["s2"].open), len(b["s3"].open)), (0, 0, 1))
        closed = desk.store.query("SELECT strategy, exit_reason, pnl_usd FROM strategy_positions WHERE status='closed'")
        self.assertEqual({r["exit_reason"] for r in closed}, {"trailing_stop"})
        self.assertTrue(all(r["pnl_usd"] > 0 for r in closed))
        # s2 holds at most 3, s3 has no cap
        for i in range(5):
            m = f"X{i}"
            src.jup.tokens_[m], src.jup.price[m] = jup_token(m), 0.001
            desk.lab.consider(candidate(mint=m, symbol=m), 80.0, 100.0, 6)
        self.assertEqual((len(b["s2"].open), len(b["s3"].open)), (3, 6))
        self.close()

    def test_dashboard_page_switch_and_numbers(self):
        desk = self.desk(market())
        desk.scan_cycle()
        desk.src.jup.price["GOOD"] = 0.0009
        desk.shadow_tick()
        st = snapshot(desk.store.path)["strategies"]
        self.assertEqual([b["key"] for b in st["books"]], ["s1", "s2", "s3", "s4"])
        s3 = st["books"][2]
        self.assertEqual(s3["closed"], 1)
        self.assertLess(s3["return_pct"], -0.4)                 # an 8% stake stopped out costs the account ~0.5-0.9%
        self.assertLess(st["books"][1]["return_pct"], 0)
        self.assertGreater(st["books"][1]["return_pct"], s3["return_pct"])
        # the server serves the strategy page while dashboard_view = "strategies", the full one at /full
        for view, marker in (("strategies", b"Strategitest"), ("full", b"Memecoin-desk</title>")):
            srv = DashboardServer(desk.store.path, port=0, rules={"dashboard_view": view})
            srv.start_in_thread()
            page = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/").read()
            full = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/full").read()
            srv.shutdown()
            srv.server_close()
            self.assertIn(marker, page)
            self.assertIn(b"Memecoin-desk</title>", full)
        self.close()


if __name__ == "__main__":
    unittest.main()


class SpeedTests(unittest.TestCase):
    def test_each_strategy_counts_its_own_window_scores_and_buys(self):
        young = pair(mint="YNG", symbol="YNG", age_h=0.3)
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False,
                        sources=market([young]))
            desk.scan_cycle()
            sp = snapshot(desk.store.path)["strategies"]["speed"]["hour"]
            self.assertEqual(sp["rounds"], 1)
            b = sp["books"]
            self.assertEqual((b["s1"]["window_avg"], b["s2"]["window_avg"], b["s3"]["window_avg"]), (2, 1, 1))
            self.assertEqual((b["s1"]["scored"], b["s2"]["scored"]), (2, 1))
            self.assertEqual((b["s1"]["bought"], b["s2"]["bought"], b["s3"]["bought"]), (2, 1, 1))
            desk.log.close()
            desk.store.close()


class Strategy4Tests(unittest.TestCase):
    def test_longer_trailing_gives_winners_more_room(self):
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=market())
            desk.scan_cycle()
            b = {x.r.key: x for x in desk.lab.books}
            px = desk.src.jup.price
            px["GOOD"] = 0.00118            # +18%: s2 trails 6% under, s4 10% under
            desk.shadow_tick()
            px["GOOD"] = 0.00109            # -7.6% from the high: s2 is out, s4 still holds
            desk.shadow_tick()
            self.assertEqual((len(b["s2"].open), len(b["s4"].open)), (0, 1))
            px["GOOD"] = 0.00104            # -11.9% from the high: now s4 sells too, still in profit
            desk.shadow_tick()
            r = desk.store.query("SELECT exit_reason, pnl_usd FROM strategy_positions WHERE strategy='s4'")[0]
            self.assertEqual(r["exit_reason"], "trailing_stop")
            self.assertGreater(r["pnl_usd"], 0)
            desk.log.close()
            desk.store.close()


class ResetTests(unittest.TestCase):
    def test_a_new_epoch_starts_every_book_over_once_and_leaves_the_paper_account(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent", strategy_epoch="a")
            first = Desk(cfg, "t", echo=False, sources=market())
            first.scan_cycle()
            cash, shadows = first.executor.cash, len(first.store.query("SELECT * FROM shadow_positions"))
            self.assertGreater(len(first.store.query("SELECT * FROM strategy_positions")), 0)
            first.log.close()
            first.store.close()
            # same epoch: nothing is wiped
            again = Desk(cfg, "t", echo=False, sources=market())
            self.assertFalse(again.lab.reset)
            self.assertGreater(len(again.store.query("SELECT * FROM strategy_positions")), 0)
            again.log.close()
            again.store.close()
            # new epoch: all books start over together; the paper account and the shadow book stay
            cfg.strategy_epoch = "b"
            fresh = Desk(cfg, "t", echo=False, sources=market())
            self.assertTrue(fresh.lab.reset)
            self.assertEqual(fresh.store.query("SELECT * FROM strategy_positions"), [])
            starts = {r["start_ts"] for r in fresh.store.query("SELECT start_ts FROM strategy_account")}
            self.assertEqual(len(starts), 1)
            self.assertTrue(all(b.cash == 10_000 for b in fresh.lab.books))
            self.assertAlmostEqual(fresh.executor.cash, cash)
            self.assertEqual(len(fresh.store.query("SELECT * FROM shadow_positions")), shadows)
            fresh.log.close()
            fresh.store.close()
