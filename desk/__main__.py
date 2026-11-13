"""CLI.

  python -m desk run [--hours 10] [--run-id NAME] [--config my.toml]   start the desk (paper)
  python -m desk once [--run-id NAME]                                   one scan cycle, then exit
  python -m desk report [--run-id NAME]                                 print / write the report
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import load_config
from .report import build_report, write_report
from .store import Store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="desk", description="Solana memecoin paper desk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "once", "report"):
        p = sub.add_parser(name)
        p.add_argument("--config", help="TOML overrides (see config.example.toml)")
        p.add_argument("--run-id", default=None, help="name for this run (logs go to runs/<run-id>/)")
        if name == "run":
            p.add_argument("--hours", type=float, default=None, help="stop after this many hours")
            p.add_argument("--quiet", action="store_true", help="no console lines (journal only)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)

    if args.cmd == "report":
        store = Store(Path(cfg.data_dir) / "desk.db")
        print(build_report(store, args.run_id))
        if args.run_id:
            write_report(store, Path(cfg.data_dir) / args.run_id, args.run_id)
        return 0

    from .desk import Desk  # imported late so `report` works without network

    run_id = args.run_id or time.strftime("run-%Y%m%d-%H%M", time.gmtime())
    desk = Desk(cfg, run_id, echo=not getattr(args, "quiet", False))
    if args.cmd == "once":
        try:
            desk.risk_tick()
            desk.scan_cycle()
        finally:
            desk.log.close()
    else:
        desk.run(hours=args.hours)
    path = write_report(desk.store, desk.run_dir, run_id)
    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
