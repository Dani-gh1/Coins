"""Strategy test: three rule sets on virtual accounts, fed from the desk's pipeline."""
import tempfile
import time
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
        self.assertEqual([p.strategy for p in lab.consider(c, 71.0, 100.0, 6)], ["s3", "s8", "s17"])         # 70 <= score < 73
        c2 = candidate(mint="LP92", symbol="LP92")
        desk.src.jup.tokens_["LP92"], desk.src.jup.price["LP92"] = jup_token("LP92"), 0.001
        self.assertEqual([p.strategy for p in lab.consider(c2, 80.0, 92.0, 6)], ["s3", "s8", "s17"])       # LP 90-95 %
        young = candidate(mint="YNG", symbol="YNG", age_h=0.25)
        desk.src.jup.tokens_["YNG"], desk.src.jup.price["YNG"] = jup_token("YNG"), 0.001
        self.assertEqual([p.strategy for p in lab.consider(young, 80.0, 100.0, 6)], ["s1", "s8", "s17"])   # wide window only
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
        closed = desk.store.query("SELECT strategy, exit_reason, pnl_usd FROM strategy_positions WHERE status='closed' AND strategy != 's17'")
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
        self.assertEqual([b["key"] for b in st["books"]], ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11", "s12", "s13", "s14", "s15", "s16", "s17"])
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


class Strategy5Tests(unittest.TestCase):
    def test_deep_pools_only_and_a_tighter_impact_cap(self):
        thin = pair(mint="THIN", symbol="THIN", liq=60_000, mcap=600_000)   # passes the $40k filter, not $100k
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False,
                        sources=market([thin]))
            desk.scan_cycle()
            held = {b.r.key: {p.mint for p in b.open.values()} for b in desk.lab.books}
            self.assertEqual(held["s5"], {"GOOD"})
            self.assertEqual(held["s2"], {"GOOD", "THIN"})
            # an order whose impact is above 0.5% is shrunk until it fits (or skipped)
            s5 = next(b for b in desk.lab.books if b.r.key == "s5")
            p = next(iter(s5.open.values()))
            self.assertLessEqual(p.entry_impact_pct, 0.5)
            desk.log.close()
            desk.store.close()


class Strategy6Tests(unittest.TestCase):
    def test_picky_needs_score_76_and_a_deep_pool(self):
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=market())
            src = desk.src
            for m in ("A", "B", "C"):
                src.jup.tokens_[m], src.jup.price[m] = jup_token(m), 0.001
            buyers = lambda c, score: {p.strategy for p in desk.lab.consider(c, score, 100.0, 6)}   # noqa: E731
            self.assertNotIn("s6", buyers(candidate(mint="A", symbol="A"), 75.0))
            self.assertIn("s6", buyers(candidate(mint="B", symbol="B"), 76.0))
            self.assertNotIn("s6", buyers(candidate(mint="C", symbol="C", liq=80_000, mcap=800_000), 90.0))
            s6 = next(b for b in desk.lab.books if b.r.key == "s6")
            self.assertEqual((s6.r.trail_trigger_pct, s6.r.trail_distance_pct, s6.r.impact_cap_pct), (15, 10, 0.5))
            desk.log.close()
            desk.store.close()


class Strategy7Tests(unittest.TestCase):
    def lab(self, d):
        desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=market())
        return desk, next(b for b in desk.lab.books if b.r.key == "s7")

    def coin(self, desk, mint, **kw):
        desk.src.jup.tokens_[mint], desk.src.jup.price[mint] = jup_token(mint), kw.pop("px", 0.001)
        return candidate(mint=mint, symbol=mint, **kw)

    def test_profile_b_rules(self):
        ok = {"lp_locked_pct": 100.0, "top10_pct": 15.0, "dev_pct": 1.0, "bundle_pct": 2.0}
        with tempfile.TemporaryDirectory() as d:
            desk, b = self.lab(d)
            self.assertIsNone(b.consider(self.coin(desk, "A"), 77.0, ok, 6))                      # score < 78
            self.assertIsNone(b.consider(self.coin(desk, "B"), 80.0, {**ok, "lp_locked_pct": 99.0}, 6))
            self.assertIsNone(b.consider(self.coin(desk, "C"), 80.0, {**ok, "top10_pct": 21.0}, 6))
            self.assertIsNone(b.consider(self.coin(desk, "D"), 80.0, {**ok, "bundle_pct": None}, 6))  # fail closed
            self.assertIsNone(b.consider(self.coin(desk, "E", age_h=30.0), 80.0, ok, 6))           # older than 24 h
            self.assertIsNone(b.consider(self.coin(desk, "F", pc_h1=60.0), 80.0, ok, 6))           # +60% in 1 h
            self.assertIsNone(b.consider(self.coin(desk, "G", px=0.00103), 80.0, ok, 6))           # quote 3% above scan
            p = b.consider(self.coin(desk, "H"), 80.0, ok, 6)
            self.assertIsNotNone(p)
            self.assertEqual(p.entry_impact_pct, 1.25)                                           # the cost floor
            desk.log.close()
            desk.store.close()

    def test_pause_after_three_losses_and_six_hour_cooldown(self):
        ok = {"lp_locked_pct": 100.0, "top10_pct": 15.0, "dev_pct": 1.0, "bundle_pct": 2.0}
        with tempfile.TemporaryDirectory() as d:
            desk, b = self.lab(d)
            for m in ("L1", "L2", "L3"):
                p = b.consider(self.coin(desk, m), 80.0, ok, 6)
                b._close(p, p.entry_price * 0.9, "stop_loss", time.time())
            self.assertTrue(b.paused(time.time()))
            self.assertIsNone(b.consider(self.coin(desk, "NEW"), 90.0, ok, 6))
            self.assertFalse(b.paused(time.time() + 12 * 3600 + 1))
            self.assertEqual(b.r.cooldown_minutes, 360)
            desk.log.close()
            desk.store.close()


class Strategy8And9Tests(unittest.TestCase):
    def test_aggressive_stake_and_quick_profit_exits(self):
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=market())
            desk.scan_cycle()
            b = {x.r.key: x for x in desk.lab.books}
            s8 = next(iter(b["s8"].open.values()))
            self.assertAlmostEqual(s8.cost_usd / 10_000 * 100, 10.0, delta=0.05)
            desk.src.jup.price["GOOD"] = 0.00114          # +14%: s9 takes its profit, s2 keeps trailing
            desk.shadow_tick()
            r = desk.store.query("SELECT exit_reason, pnl_usd FROM strategy_positions WHERE strategy='s9'")[0]
            self.assertEqual(r["exit_reason"], "take_profit")
            self.assertGreater(r["pnl_usd"], 0)
            self.assertEqual(len(b["s2"].open), 1)
            desk.log.close()
            desk.store.close()

    def test_time_stop_after_two_hours(self):
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=market())
            desk.scan_cycle()
            s9 = next(x for x in desk.lab.books if x.r.key == "s9")
            next(iter(s9.open.values())).opened_ts -= 2 * 3600 + 1
            desk.shadow_tick()
            r = desk.store.query("SELECT exit_reason FROM strategy_positions WHERE strategy='s9'")[0]
            self.assertEqual(r["exit_reason"], "time_stop")
            desk.log.close()
            desk.store.close()


class Strategy10Tests(unittest.TestCase):
    def test_sharper_picky_rules_and_three_percent_stake(self):
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=market())
            src = desk.src
            src.jup.impact_fn = lambda usd: usd / 1000          # $300 -> 0.3% impact, bigger orders cost more
            s10 = next(b for b in desk.lab.books if b.r.key == "s10")
            ok = {"lp_locked_pct": 100.0, "top10_pct": 15.0, "dev_pct": 1.0, "bundle_pct": 2.0}

            def coin(m, **kw):
                src.jup.tokens_[m], src.jup.price[m] = jup_token(m), 0.001
                return candidate(mint=m, symbol=m, **kw)
            self.assertIsNone(s10.consider(coin("THIN", liq=120_000, mcap=1_200_000), 80.0, ok, 6))
            self.assertIsNone(s10.consider(coin("LATE", liq=200_000, mcap=2_000_000, pc_h1=45.0), 80.0, ok, 6))
            p = s10.consider(coin("DEEP", liq=200_000, mcap=2_000_000), 80.0, ok, 6)
            self.assertIsNotNone(p)
            self.assertLessEqual(p.entry_impact_pct, 0.3)
            self.assertAlmostEqual(p.cost_usd / 10_000 * 100, 3.0, delta=0.01)   # 3% plus the $0.05 fee
            desk.log.close()
            desk.store.close()


class Strategy11Tests(unittest.TestCase):
    def test_double_stake_and_pause_after_two_losses(self):
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=market())
            src = desk.src
            src.jup.impact_fn = lambda usd: usd / 3000           # $600 -> 0.2% impact
            s11 = next(b for b in desk.lab.books if b.r.key == "s11")
            ok = {"lp_locked_pct": 100.0, "top10_pct": 15.0, "dev_pct": 1.0, "bundle_pct": 2.0}

            def coin(m):
                src.jup.tokens_[m], src.jup.price[m] = jup_token(m), 0.001
                return candidate(mint=m, symbol=m, liq=200_000, mcap=2_000_000)
            for m in ("L1", "L2"):
                p = s11.consider(coin(m), 80.0, ok, 6)
                self.assertAlmostEqual(p.cost_usd / s11.equity() * 100, 6.0, delta=0.6)
                s11._close(p, p.entry_price * 0.9, "stop_loss", time.time())
            self.assertIsNone(s11.consider(coin("NEXT"), 90.0, ok, 6))     # paused for 24 h
            desk.log.close()
            desk.store.close()


class Strategy12Tests(unittest.TestCase):
    def test_max_stake_and_long_pause(self):
        from desk.strategies import STRATEGIES
        s12 = next(s for s in STRATEGIES if s.key == "s12")
        self.assertEqual((s12.stake_pct, s12.pause_after_losses, s12.pause_hours, s12.min_score), (8.0, 2, 48, 76))


class Strategy13Tests(unittest.TestCase):
    def test_only_the_stake_differs_from_strategy_12(self):
        from dataclasses import asdict
        from desk.strategies import STRATEGIES
        s12, s13 = (next(s for s in STRATEGIES if s.key == k) for k in ("s12", "s13"))
        diff = {k for k, v in asdict(s13).items() if asdict(s12)[k] != v} - {"key", "name", "rules"}
        self.assertEqual(diff, {"stake_pct"})
        self.assertEqual(s13.stake_pct, 15.0)


class Strategy14Tests(unittest.TestCase):
    def test_max_picky_is_at_least_as_strict_as_every_other_picky_strategy(self):
        from desk.strategies import STRATEGIES
        by = {s.key: s for s in STRATEGIES}
        s14 = by["s14"]
        for k in ("s6", "s10", "s11", "s12", "s13"):
            o = by[k]
            self.assertGreaterEqual(s14.min_score, o.min_score)
            self.assertGreaterEqual(s14.min_liq_usd, o.min_liq_usd)
            self.assertLessEqual(s14.impact_cap_pct, o.impact_cap_pct)
            self.assertGreaterEqual(s14.min_lp_pct, o.min_lp_pct)
        self.assertEqual((s14.min_score, s14.stake_pct, s14.max_bundle_pct), (82, 15.0, 3))


class Strategy15And16Tests(unittest.TestCase):
    def test_wide_window_with_strategy_14_and_13_rules(self):
        from dataclasses import asdict
        from desk.strategies import STRATEGIES
        by = {s.key: asdict(s) for s in STRATEGIES}
        window = ("min_age_minutes", "max_age_hours", "min_mcap", "max_mcap")
        for mix, rules in (("s15", "s14"), ("s16", "s13")):
            for k, v in by[mix].items():
                if k in ("key", "name", "rules"):
                    continue
                self.assertEqual(v, by["s1" if k in window else rules][k], (mix, k))


class Strategy17Tests(unittest.TestCase):
    def test_many_small_trades(self):
        with tempfile.TemporaryDirectory() as d:
            desk = Desk(DeskConfig(data_dir=d, smart_wallet_seed_file="/nonexistent"), "t", echo=False, sources=market())
            src = desk.src
            s17 = next(b for b in desk.lab.books if b.r.key == "s17")
            for i in range(12):
                m = f"M{i}"
                src.jup.tokens_[m], src.jup.price[m] = jup_token(m), 0.001
                s17.consider(candidate(mint=m, symbol=m), 56.0, 92.0, 6)
            self.assertEqual(len(s17.open), 10)                              # at most 10 open
            p = next(iter(s17.open.values()))
            self.assertAlmostEqual(p.cost_usd / 10_000 * 100, 0.5, delta=0.01)
            desk.lab.tick({p.mint: 0.00106})                                # +6%: take profit at +5%
            r = desk.store.query("SELECT exit_reason FROM strategy_positions WHERE strategy='s17' AND id=?", (p.id,))[0]
            self.assertIn(r["exit_reason"], ("take_profit", "trailing_stop"))
            desk.log.close()
            desk.store.close()
