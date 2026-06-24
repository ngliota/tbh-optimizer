# TBH Optimizer

A localhost dashboard that **passively** reads my own *Taskbar Hero* data (read-only) to show
live progression, run empirical drop tests, model the interval-based drop system, and recommend
what to farm/upgrade.

> **Safety:** This project never interacts with the game. No memory reads, no injection, no
> automation, no editing the save. It only reads a **copy** of the save file and public web data.
> The anti-cheat watches the running game process, not a script reading a copied `.es3` file.

## What it does (tabs)
- **LIVE** — gold, hero levels/EXP, chests, stage from the live save; rolling gold/hr, EXP/hr,
  item/hr from snapshot diffs; live charts.
- **DROP TEST** — change events derived by diffing snapshots (~5s): chest/item/gold gains with
  timestamps. (Used to measure the real `drop_interval` and the shared-vs-independent cooldown.)
- **SIMULATOR** — Monte-Carlo of the interval/window/rate mechanic → "Average Drops vs Clear Time"
  chart + table. Tunable; plug in your measured interval/window.
- **OPTIMIZER** — ranks clearable stages by gold/hr, EXP/hr, or chest-value/hr under the
  interval-gated model, with rotation advice.
- **BUILD ADVISOR** — reads equipped gear grades from the save (by hero **name**), shows "my build"
  (grade mix per hero), and compares to an editable target loadout (`data/build_targets.json`).
  Buttons: *Fetch current build*, *Set targets = my current build* (lock in a baseline), *Reset targets*.
- **MY STATS** — manual entry of the in-game **Stat List** numbers (boss gold/EXP, chest drop-chance
  multipliers, auto-open times, capacities, offline %). These are a runtime-computed aggregate the game
  does **not** store in the save and the wiki does not expose, so they can't be auto-read — but they are
  exactly the Optimizer/Simulator inputs, so typing them in makes those tabs reflect *your* character.
  Saved to `data/my_stats.json`; the Optimizer adds boss-gold/EXP bonuses per clear when present.

Stages are named with their difficulty tier to disambiguate the repeated act maps, e.g.
**Torment · Act 3-9 · Core of the Abyss** (key scheme: `difficulty×1000 + act×100 + no`, where
1=Normal, 2=Nightmare, 3=Hell, 4=Torment; `no==10` is the act boss).

## Requirements
- **Windows** (native — not WSL). The game, save, and screen are all on Windows.
- **Python 3.11** — download from [python.org](https://www.python.org/downloads/). Check "Add Python to PATH" during install.

## Install
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run
```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
Open **http://localhost:8000**. The save poller starts automatically (~5s interval) and resolves
the decryption password on first poll.

## Auto-start / one-click
- **Desktop shortcut "TBH Optimizer"** → runs `start.bat`: starts the server if it isn't already up,
  waits for it, then opens http://localhost:8000. If it's already running, it just opens the browser.
- **On login (background):** a shortcut in the Startup folder runs `start-silent.vbs`, which launches the
  server hidden (no console window, no browser). Open the dashboard yourself or via the desktop shortcut.
- Both are CRLF batch/VBS scripts in the project root. To remove auto-start, delete
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TBH Optimizer.lnk`.

## Refresh reference data (cached, refresh-only)
- Wiki catalog (items, stages, grades, loot tables):
  `curl -X POST http://localhost:8000/api/refresh/wiki`
- Steam Market prices (appid 3678970):
  `curl -X POST http://localhost:8000/api/refresh/steam`
- Catalog freshness: `GET http://localhost:8000/api/catalog/status`

## How the save is read (provenance)
The save is **Easy Save 3 AES-encrypted** (AES-128-CBC; first 16 bytes = IV = PBKDF2-SHA1 salt,
100 iterations). The decryption **password is sourced from the public client-side JavaScript of the
community tool `taskbarhero.wiki/my-save`** (which decrypts in-browser, no upload). This touches no
game process and reads only a copy. The password can change after a game update — `password_resolver.py`
falls back to re-scraping the current password from that tool's JS automatically.

## Data provenance labels (shown in the UI)
`save (live)` · `save-diff (observed)` · `wiki (scraped, vX)` · `Steam price` · `my assumption`.
Measured values (interval, drop rates from the Drop Test) override scraped/assumed defaults.

## Project layout
```
backend/
  main.py              # FastAPI app + routes
  save/                # es3 decrypt, password resolver, parser, snapshot poller+differ
  sources/             # wiki.py (catalog JSON), steam.py (prices)
  model/               # simulator.py, optimizer.py, advisor.py
frontend/index.html    # single-page dashboard (Chart.js)
data/                  # snapshots, catalog cache, prices.json, build_targets.json, caches
```

## Notes / current limitations
- The Records log is **not** written to disk and **not** in the save — drop events are reconstructed
  by diffing snapshots. Exact per-round *clear times* would need optional OCR (not built; clear time
  barely matters under the interval model).
- `drop_interval`/`drop_window` are not in the wiki JSON → measure them in the Drop Test (source of
  truth); the simulator/optimizer use tunable defaults until then.
- The per-stage loot-table join (which `DropKey` belongs to each stage) isn't wired yet; the optimizer
  uses stage tier as a value-per-chest proxy (labeled as an assumption).
- `build_targets.json` ships empty — fill it from a community tier list to activate gap analysis.
