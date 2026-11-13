"""Scout: find Solana pairs 30m-72h old with market cap $300k-$20M.

Mint addresses come from several public feeds (DexScreener profiles/boosts/takeovers,
Jupiter trending/traded/organic/recent, GeckoTerminal trending/new pools). DexScreener is
the single source of truth for each pair's age, market cap and market data.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..config import ScoutConfig
from ..messages import Candidate
from ..sources import Sources


@dataclass
class ScoutReport:
    candidates: list[Candidate]
    trending_pools: list[str]
    feed_counts: dict[str, int]
    mints_seen: int
    pairs_seen: int


def best_pair(pairs: list[dict], mint: str, accepted_quotes: tuple[str, ...]) -> dict | None:
    """The deepest pair where `mint` is the base token and the quote is SOL/USDC/USDT."""
    best = None
    best_liq = -1.0
    for p in pairs:
        if (p.get("baseToken") or {}).get("address") != mint:
            continue
        if (p.get("quoteToken") or {}).get("address") not in accepted_quotes:
            continue
        liq = float((p.get("liquidity") or {}).get("usd") or 0.0)
        if liq > best_liq:
            best, best_liq = p, liq
    return best


def in_window(pair: dict, cfg: ScoutConfig, now: float) -> tuple[bool, float, float]:
    created_ms = pair.get("pairCreatedAt") or 0
    age_h = (now - created_ms / 1000.0) / 3600.0 if created_ms else -1.0
    mcap = float(pair.get("marketCap") or pair.get("fdv") or 0.0)
    ok = (cfg.min_pair_age_minutes / 60.0 <= age_h <= cfg.max_pair_age_hours
          and cfg.min_mcap_usd <= mcap <= cfg.max_mcap_usd)
    return ok, age_h, mcap


def to_candidate(pair: dict, age_h: float, mcap: float, via: tuple[str, ...]) -> Candidate:
    base = pair["baseToken"]
    return Candidate(
        mint=base["address"],
        symbol=(base.get("symbol") or "?")[:16],
        name=(base.get("name") or "")[:64],
        pair_address=pair["pairAddress"],
        dex_id=pair.get("dexId") or "?",
        quote_mint=pair["quoteToken"]["address"],
        pair_age_hours=age_h,
        mcap_usd=mcap,
        liquidity_usd=float((pair.get("liquidity") or {}).get("usd") or 0.0),
        price_usd=float(pair.get("priceUsd") or 0.0),
        volume={k: float(v or 0) for k, v in (pair.get("volume") or {}).items()},
        price_change={k: float(v or 0) for k, v in (pair.get("priceChange") or {}).items()},
        txns=pair.get("txns") or {},
        discovered_via=via,
    )


class Scout:
    name = "scout"

    def __init__(self, cfg: ScoutConfig, sources: Sources):
        self.cfg = cfg
        self.src = sources
        # Trending pools (pool -> mint) from the last scan, used by the smart-wallet learner.
        self.pool_mint: dict[str, str] = {}
        self.last_trending: list[str] = []

    def scan(self) -> ScoutReport:
        feeds: dict[str, set[str]] = {}

        def add(mapping: dict[str, str]) -> None:
            for mint, feed in mapping.items():
                feeds.setdefault(mint, set()).add(feed)

        add(self.src.dex.discovery_mints())
        if self.cfg.use_jupiter_feeds:
            add(self.src.jup.discovery_mints())
        trending: dict[str, str] = {}
        if self.cfg.use_geckoterminal_feeds:
            gt_mints, trending = self.src.gecko.discovery()
            add(gt_mints)
            self.pool_mint.update(trending)
            self.last_trending = list(trending)

        for quote in self.cfg.accepted_quote_mints:
            feeds.pop(quote, None)

        feed_counts: dict[str, int] = {}
        for fs in feeds.values():
            for f in fs:
                feed_counts[f] = feed_counts.get(f, 0) + 1

        pairs = self.src.dex.pairs_for_tokens(list(feeds))
        by_mint: dict[str, list[dict]] = {}
        for p in pairs:
            by_mint.setdefault((p.get("baseToken") or {}).get("address"), []).append(p)

        now = time.time()
        out: list[Candidate] = []
        for mint, ps in by_mint.items():
            if mint not in feeds:
                continue
            pair = best_pair(ps, mint, self.cfg.accepted_quote_mints)
            if not pair:
                continue
            ok, age_h, mcap = in_window(pair, self.cfg, now)
            if ok:
                out.append(to_candidate(pair, age_h, mcap, tuple(sorted(feeds[mint]))))
        out.sort(key=lambda c: c.volume.get("h1", 0.0), reverse=True)
        return ScoutReport(out, list(trending), feed_counts, len(feeds), len(pairs))
