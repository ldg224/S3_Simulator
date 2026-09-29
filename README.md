# HCL Season 3 Simulator

Match engine for the Heineken C League. It reads the league spreadsheet and simulates
full 11-a-side, 90-minute matches as a physical, second-by-second world, producing a
file with every player's and the ball's position five times a second, every event
(passes, shots, saves, tackles, fouls, cards, set pieces...) and full statistics:
everything a FotMob-style 2D match view needs.

The key property: **the replay is always physically and logically consistent.** The
ball is a real object with physics; possession only changes when a player actually gets
to it. A pass from A to B can't be followed by C suddenly having it on the other side of
the pitch. Every match file is checked for this automatically. See [docs/DESIGN.md](docs/DESIGN.md).

## Requirements

Python 3.10 or newer. No other packages.

## The simulator page

**Online:** https://ldg224.github.io/S3_Simulator/ runs the whole simulator in your
browser (the Python engine via Pyodide), so there's nothing to install. A match takes about
1-2 minutes there, and matches are saved in that browser.

**On your computer (faster, about 30 s a match, files saved to `matches/`):**

```
python -m hcl_sim app
```

That opens **http://localhost:8000**. Both use the same page (`index.html`). From there:

* **Simulate a match:** pick home and away (and optionally a seed), click Simulate. About 30 seconds.
* **Simulate a week:** pick a week from the Schedule tab; all its fixtures run in parallel,
  and a results CSV in the sheet's Schedule & Results format appears for download.
* **Match library:** every generated match, with **Watch** (a 2D replay with events, stats
  and player ratings), **JSON** and **.json.gz** downloads.
* **Refresh sheet** re-reads the Google Sheet after you change it.

Files are saved in the `matches/` folder. Leave the terminal window open while you use the
page; press Ctrl+C in it to stop.

## Command line

```
python -m hcl_sim teams                     # teams and squads from the sheet
python -m hcl_sim simulate TUR SKS          # simulate one match
python -m hcl_sim simulate TUR SKS --seed 42 --out matches/test.json.gz
python -m hcl_sim week 1                    # every week-1 fixture on the Schedule tab
python -m hcl_sim validate matches/*.json.gz
python -m hcl_sim calibrate --matches 44    # realism check against real football stats
python -m hcl_sim ratings-template          # export full player attributes to a CSV
```

Add `--offline` (before the command) to use the last downloaded copy of the sheet.

`simulate` prints the score, scorers and match stats, writes the match file, and
validates it. The same teams and seed always give the identical match.

`week N` writes one match file per fixture plus `weekN_results.csv` with the scores and
goal columns in the **Schedule & Results** format (`GOAL 1 MIN`, `GOAL 1 ID`, ...),
ready to paste into the sheet.

## The league sheet

`league.json` points at the published Google Sheet and its tab ids (the same links the
website uses). For Season 3, publish the new sheet and replace the `sheet` link and tab
`gid`s. A tab can also point at a local CSV file, e.g. `"attributes": "data/attributes.csv"`.

Tabs read:

| Tab | Used for |
|---|---|
| Teams | team names, codes, colours |
| Roster | players, positions, offense/defense ratings |
| Schedule & Results | fixtures for `week` |
| **Attributes** (optional) | detailed player ratings, overriding the derived ones |
| **Tactics** (optional) | per team: TEAM CODE, FORMATION (4-3-3, 4-4-2, 4-2-3-1, 3-5-2), PRESSING, LINE HEIGHT, TEMPO, WIDTH, DIRECTNESS (0-100) |

### Advanced ratings

Every player has 25 attributes (1-100), derived from the sheet's offense/defense ratings
and position. To revise them:

1. `python -m hcl_sim ratings-template` writes `attributes.csv` with every player's current profile.
2. Import it into the sheet as a new **Attributes** tab and edit any values.
3. Publish the tab and set its `gid` under `"attributes"` in `league.json`.

Blank cells fall back to the derived value, so you only need to fill in what you change.

## Output

Match files are gzipped JSON. Full format: [docs/OUTPUT_FORMAT.md](docs/OUTPUT_FORMAT.md).
`samples/` has an example match. `tools/debug-viewer.html` is a bare-bones viewer for
checking output: serve the folder (`python -m http.server`) and open
`http://localhost:8000/tools/debug-viewer.html?file=../samples/sample_TUR_v_SKS.json.gz`.

## Realism

`calibrate` compares batch statistics with real football; 13 of 16 are in range. The latest
results and known gaps are in [docs/CALIBRATION.md](docs/CALIBRATION.md). Tuning values
live in `hcl_sim/config.py`.

## Tests

```
python -m unittest discover -s tests -v
```

## Layout

```
hcl_sim/
  engine.py     the match loop: physics, contacts, duels, set pieces, movement
  decisions.py  on-ball decision making and the pitch value / xG models
  tactics.py    formations, team shape, set-piece positions
  physics.py    ball physics and kick planning
  ratings.py    player attribute model
  sheet.py      reads the league sheet
  teams.py      builds teams and line-ups
  output.py     statistics, player ratings and the match file
  validate.py   consistency checks
  calibrate.py  realism report
  run.py        simulate / week helpers
docs/           design, output format, calibration
tools/          debug viewer
samples/        example match file
```

## Roadmap

* The 2D match display (FotMob-style), reading these files.
* Optional "scripted result" mode: generate a match that reproduces a given score and
  scorers.
* Substitutes and injuries, if the league adds benches.
* Further tuning of offsides, corners, and spreading shots across the team.
