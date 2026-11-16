# Memecoin-desk: kontekst til nye Claude-sessioner

Denne fil indlæses automatisk af Claude Code. Den samler det vigtigste fra den første
session, så en ny session kan fortsætte uden at starte forfra.

## Hvad projektet er
En Solana-memecoin-desk, **kun papirhandel**. Seks agenter med hårde overdragelser:
Scout → Filter → Analyst → Risk → Executor, og Logger skriver alt.
Det er ren Python-stdlib (3.11+), uden afhængigheder. Se `README.md` for kommandoerne.

- Scout: par mellem 30 min og 72 t gamle, mcap $300k–$20M (DexScreener, GeckoTerminal, Jupiter).
- Filter dræber, hvis: mint/freeze ikke er revoked, LP ikke er brændt/låst (95 %), liq < $40k,
  1h-vol < $50k, top10 > 25 %, dev > 3 % eller tidligere rugs, bundle > 10 %, eller +80 % på 1 time.
- Analyst scorer 0–100 (momentum, unikke købere, køb/salg, holdervækst, liq/mcap, smart wallets).
  Tærsklen er **73**. Brugeren valgte den efter en backtest, hvor alt under 73 tabte.
- Executor: fast 1 % af kontoen pr. handel, maks. 1 % prisvirkning, maks. 3 åbne positioner,
  og 120 min karantæne efter salg. Scanning hvert 20. sekund.
- Risk: stop −6 % under indgang, trailing stop slås til ved +8 % og ligger 6 % under toppen.
  Kursen tjekkes hvert sekund.
- Alle tærskler står i `desk/config.py`.

## Sådan køres den
- `python3 -m desk run --dashboard 8787` (brug `python3`, ikke `python`, på brugerens Mac).
- Dashboardet ligger på `http://127.0.0.1:8787` (dansk UI, 4 faner).
- Papirbogen gemmes portabelt i `runs/state.json` og gendannes, når databasen er tom.
- Testene køres med `python3 -m unittest discover -s tests` (47 tests).
- **Desken kører kun på brugerens Mac** (i `~/Coins`), startet med
  `nohup caffeinate -i python3 -m desk run --dashboard 8787 --host 0.0.0.0 > desk.log 2>&1 &`.
  Brugeren ser dashboardet på telefonen via Tailscale (`http://100.73.239.46:8787`).
- **Start ikke desken i cloud-sessioner.** Brugeren vil kun have én papirkonto. Cloud-desken blev
  stoppet 2026-11-16, fordi containeren lukker ned og to desks giver to konti.
- Der arbejdes på branchen `claude/gallant-planck-vsfkxd`.

## Brugerens ønsker (vigtigt)
- Brugeren skriver dansk, så svar på dansk og kort.
- Papirpenge vises **altid i procent**, aldrig i dollars. Markedstal (liq, vol, mcap) må stå i $.
- Rigtige penge og indbetalinger er udskudt ("det venter vi med"). Byg det ikke uopfordret.

## Status pr. 2026-11-16
- 4 lukkede handler: CSI (+), WOHAIHAO (+), bill (−11,1 %) og Socks (ca. −9 %, stop med slippage).
  Kontoen står på ca. −1,05 %. Macen kører videre fra denne bog (`runs/state.json` på GitHub er
  cloud-bogen fra 2026-11-16; Macens nye handler ligger kun lokalt på Macen).
- Datagrundlaget for tærsklen er meget tyndt (én handel over 73 i backtesten), så analysen bør
  køres igen, når der er mere data.
- Flere datakilder gav ikke flere coins. Markedet er flaskehalsen, og der kommer flest coins
  omkring kl. 03–07 dansk tid.
