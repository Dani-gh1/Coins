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
- Skyggehandel (`desk/shadow.py`, fra 2026-11-16): følger hver scoret coin (også under 73) og
  coins afvist kun for +80 % med de rigtige regler, uden at røre papirkontoen. Bruges til at vælge
  tærskel og filtre med mere data. Vises under fanen Handler.
- Skyggen har også et bredt vindue ($100k–$20M, 10 min–7 dage): coins uden for det rigtige vindue
  skyggehandles kun, så vi kan se, om et bredere rigtigt vindue ville betale sig.

## Sådan køres den
- `python3 -m desk run --dashboard 8787` (brug `python3`, ikke `python`, på brugerens Mac).
- Dashboardet ligger på `http://127.0.0.1:8787` (dansk UI, 4 faner).
- Papirbogen gemmes portabelt i `runs/state.json` og gendannes, når databasen er tom.
- Testene køres med `python3 -m unittest discover -s tests` (87 tests).
- **Desken kører 24/7 på brugerens Oracle Cloud-server** (Ubuntu 24.04, offentlig IP 89.168.96.169,
  bruger `ubuntu`, mappe `~/Coins`) som systemd-servicen `desk` (`Restart=always`). Brugeren logger
  ind fra Macen med `ssh -i ~/.ssh/oracle ubuntu@89.168.96.169`. Opdatering på serveren:
  `git checkout -- runs/state.json && git pull --ff-only origin claude/gallant-planck-vsfkxd &&
  sudo systemctl restart desk`. Log: `sudo journalctl -u desk -n 20`.
- Dashboardet hedder **Nova AI** (hed før Moonshot) og ligger som app på brugerens iPhone-hjemmeskærm. Telefonen
  når serveren via Tailscale (serverens `100.x`-IP, port 8787). Oracle-firewallen åbner kun for
  `tailscale0`.
- **Start ikke desken i cloud-sessioner eller på Macen.** Brugeren vil kun have én papirkonto, og
  den ligger på serveren. Serverens nye handler ligger i dens database, ikke på GitHub.
- Notifikationer til telefonen via ntfy-appen (`desk/notify.py`): miljøvariablen `NTFY_TOPIC` sættes
  med `sudo systemctl edit desk` ligesom `JUPITER_API_KEY`. Sendes kun ved køb, salg, stop og nedbrud (brugerens ønske),
  og ved køb og salg i hver af strategierne (S1–S7).
- **Strategitest (midlertidig, fra 2026-11-16):** `desk/strategies.py` kører tre regelsæt på virtuelle
  konti side om side (1 bredt vindue, 2 nuværende regler, 3 gamle regler: score ≥ 70, 8 %, LP 90 %,
  trail +12 %, intet loft på prisvirkning/positioner, 4 som 2 men trailing fra +15 % og 10 % under toppen, 5 som 2 men likviditet ≥ $100k
  og prisvirkning ≤ 0,5 %, 6 "Kræsen": score ≥ 76, likviditet ≥ $100k, prisvirkning ≤ 0,5 %, trailing
  +15 %/10 %, 7 "Profil B": brugerens egen profil, se `desk/strategies.py`). Dashboardet viser KUN strategitesten, fordi
  `dashboard_view = "strategies"` i `desk/config.py`. Når brugeren siger til, skiftes det tilbage
  ved at sætte `dashboard_view = "full"` (det normale dashboard er urørt i `dashboard.html` og kan
  altid ses på `/full`). Spørg, om strategitesten (`strategy_test`) også skal slås fra.
  Alle strategier nulstilles samtidig ved at ændre `strategy_epoch` i config (sidst: 2026-11-16, 7 strategier).
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
