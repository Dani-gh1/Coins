# Memecoin-desk: kontekst til nye Claude-sessioner

Denne fil indlæses automatisk af Claude Code. Den samler det vigtigste fra den første
session, så en ny session kan fortsætte uden at starte forfra.

## Hvad projektet er
En Solana-memecoin-desk, **kun papirhandel**. Seks agenter med hårde overdragelser:
Scout → Filter → Analyst → Risk → Executor, og Logger skriver alt.
Det er ren Python-stdlib (3.11+), uden afhængigheder. Se `README.md` for kommandoerne.

- Scout: par mellem 30 min og 72 t gamle, mcap $300k–$20M (DexScreener, GeckoTerminal, Jupiter).
- Filter dræber, hvis: mint/freeze ikke er revoked, LP ikke er brændt/låst (90 %), liq < $40k,
  1h-vol < $50k, top10 > 25 %, dev > 3 % eller tidligere rugs, bundle > 10 %, eller +80 % på 1 time.
- Analyst scorer 0–100 (momentum, unikke købere, køb/salg, holdervækst, liq/mcap, smart wallets).
  Tærsklen er **73**. Brugeren valgte den efter en backtest, hvor alt under 73 tabte.
- Executor: maks. 8 % pr. handel, ingen grænse for prisvirkning, ingen grænse for antal åbne
  positioner, og 120 min karantæne efter salg.
- Risk: stop −6 % under indgang, trailing stop slås til ved +12 % og ligger 6 % under toppen.
  Kursen tjekkes hvert 3. sekund.
- Alle tærskler står i `desk/config.py`.

## Sådan køres den
- `python3 -m desk run --dashboard 8787` (brug `python3`, ikke `python`, på brugerens Mac).
- Dashboardet ligger på `http://127.0.0.1:8787` (dansk UI, 4 faner).
- Papirbogen gemmes portabelt i `runs/state.json` og gendannes, når databasen er tom.
- Testene køres med `python3 -m unittest discover -s tests` (46 tests).
- I cloud-sessioner køres desken i blokke på 2 timer (`--hours 1.95`). Efter hver blok committes
  `runs/state.json` og dagens rapport. Der arbejdes på branchen `claude/gallant-planck-vsfkxd`.

## Brugerens ønsker (vigtigt)
- Brugeren skriver dansk, så svar på dansk og kort.
- Papirpenge vises **altid i procent**, aldrig i dollars. Markedstal (liq, vol, mcap) må stå i $.
- Rigtige penge og indbetalinger er udskudt ("det venter vi med"). Byg det ikke uopfordret.
- Brugeren har også en desk kørende på sin egen Mac med sin egen papirkonto. Den er adskilt fra
  cloud-sessionens konto, så tallene kan være forskellige.

## Status pr. 2026-11-15
- 3 lukkede handler: CSI (+), WOHAIHAO (+) og bill (−11,1 %). Kontoen står på ca. −0,33 %.
- Datagrundlaget for tærsklen er meget tyndt (én handel over 73 i backtesten), så analysen bør
  køres igen, når der er mere data.
- Flere datakilder gav ikke flere coins. Markedet er flaskehalsen, og der kommer flest coins
  omkring kl. 03–07 dansk tid.
