# aero_auto 1.1 - User Manual (dark edition)

Multi-element wing design, simulation and reporting toolchain built on the
JavaFoil panel solver. This manual covers the GUI (run_ui.sh / aero_ui.exe),
every tab, and exactly where the airfoil files and the results land.
For the "why" behind the code, open `docs/TECHNICAL_GUIDE.pdf`.

## 1. Overview

| Module | Purpose |
|--------|---------|
| aero_auto.py | core engine - regulatory rules, geometry, JavaFoil runner, campaign planner |
| aero_targets.py | CL*A / CD*A target report |
| aero_report.py | ranked tables, Excel workbook, graphs, --resim |
| flowfield.py | schematic potential-flow model for the velocity field images |
| aero_ui.py | the GUI shell (six tabs + menus + status bar) |
| render_field.py | headless velocity-field PNG renderer |
| launcher.py | one entry point for every tool (ui/campaign/report/targets/field) |

## 2. Requirements

- Python 3.9+ with Tkinter (the python.org installer bundles Tk on Windows).
- Java 8+ and `javafoil.jar` + `mhclasses.jar` (the engine's solver).
- Python packages in `requirements.txt`: numpy, pandas, matplotlib, openpyxl, Pillow.
- `faketime` on Linux (auto-skipped on Windows).
- Your airfoil `.dat` library - see chapter 6.
- The standalone `aero_ui` needs none of the above - it bundles Python, the
  solver dependencies and the docs inside its folder.

## 3. Install

```
python3 -m pip install -r requirements.txt

# optional standalone (no Python on the target machine):
python3 create_standalone.sh     # linux/macos -> dist/aero_ui/
create_standalone.bat            # windows     -> dist\aero_ui\aero_ui.exe
```

Rebuild the distribution zips with `python3 build_dist.py` (see chapter 11).

## 4. Run

GUI:

```
./run_ui.sh            # linux/macos
run_ui.bat             # windows
# or double-click aero_ui.exe (standalone build)
# or
python3 launcher.py ui
```

Headless tools:

```
python3 launcher.py campaign --role fw --flow ground --height 300 --hours 0.5
python3 launcher.py report   --results ~/aero_campaign/results.csv --top 3
python3 launcher.py report   --results .../ground/h300pct/results.csv --resim
python3 launcher.py targets  --results ~/aero_campaign/results.csv --role fw
python3 launcher.py field    --main s1223 --flap e423,30,-6,100,5 --out f.png
                              --ground-height 300
```

## 5. The GUI, tab by tab (run_ui.sh / aero_ui.exe)

The window has a menu bar (File / View / Appearance / Help), seven tabs -
**Configure, Airfoils, Campaigns, Results, Graphs, Optimizer, Themes & Settings** -
and a status bar at the bottom. The same engine runs behind the window, so a config you
have just sanity-checked can be simulated, campaigned or optimized without
leaving the app. Every JavaFoil operation runs in a worker thread - the window
never freezes.

Every control has a **hover description**: hold the mouse over a button, entry or
checkbox for a moment to see what it does. Descriptions wait for a short delay,
use high-contrast colours, and disappear the instant you click, press Esc, move
away or switch tabs - so nothing stays floating over the window. You can turn
them off or tune them in the **Themes & Settings** tab.

### 5.0 Menus and status bar

| Item | What it does |
|------|--------------|
| File &gt; Open output folder | opens the campaign output folder (default `~/aero_campaign`) |
| File &gt; Open current results file | opens the currently loaded results.csv in the default editor |
| File &gt; Write report (Ctrl+R) | builds the full report folder for the current results file |
| File &gt; Reload airfoils | re-scans the airfoil store and `AIRFOIL_DIR` |
| File &gt; Quit (Ctrl+Q) | closes the app (saves your settings first) |
| View &gt; Refresh results & graphs (F5) | redraws the Results table and Graphs list |
| View &gt; Reset results filter/sort | restores the default table view |
| View &gt; Clear campaign log | empties the campaign log |
| View &gt; Jump to ... tab (Alt+1 … Alt+7) | switches tab from the keyboard |
| Appearance &gt; Dark / Light / High contrast | switches the colour theme instantly |
| Appearance &gt; Open Themes & Settings tab | opens the settings tab |
| Help &gt; About / Open airfoil store / Open JavaFoil folder / Open project folder | links to the folders you care about |
| status bar | live readout: airfoil count, `OUT_DIR`, JavaFoil jar health, last reported results file |
| header band | title bar with the library root and airfoil count |

Navigation shortcuts: **Alt+1 … Alt+7** jump straight to a tab, **Ctrl+Tab /
Ctrl+Shift+Tab** cycle through them, **Esc** dismisses a hover description,
**Ctrl+R** writes a report and **F5** refreshes.

Your window layout and all settings are remembered between sessions - they are
saved on close to `~/.aero_auto/ui_state.json` (Linux) /
`%USERPROFILE%\.aero_auto\ui_state.json` (Windows) and restored on start.

### 5.0 Run library

Every run/campaign is written to its own dated folder inside a single app-managed
library: `<OUT_DIR>/library/<YYYYMMDD-HHMMSS>_<kind>[_label]/`. Each folder holds a
`results.csv`, an optional `graphs/` and `Best/` report, and a `meta.json`
manifest (kind, date, main airfoil, run count, best score). The library root
follows the Campaigns **Out folder** (`~/aero_campaign` by default).

On the very first start after upgrading, the app **copies** (never moves) any
existing `<OUT_DIR>/results.csv` and `<OUT_DIR>/ground/*/results.csv` into the
library as dated `import` runs, so your history shows up in the Results tab. A
`legacy_imported` flag in `ui_state.json` makes this a one-off.


### 5.1 Configure tab

| Control | What it does |
|---------|--------------|
| Main element | the airfoil that defines the wing; the combo lists every profile found in your store and `.dat` folder |
| Role: front / rear / custom | sets the span used by CL*A and the force model (fw 1400 / rw 950 / custom, editable span) and the FSUK/FSG rule set checked |
| Main chord (mm) | physical chord in millimetres; enables the all-mm geometry columns and the force conversion |
| Speed (m/s) | freestream speed for `q = 0.5 rho V^2` in the force model |
| Reynolds number | run Reynolds number sent to JavaFoil (default 570 000) |
| Alpha start / end / step (deg) | polar sweep angles; default -20..+5 step 1 covers the stall search |
| Flap rows F1..F3 | per slot: airfoil combo + S% scale of main chord, A deg mount angle, X% position, Y% position; tick the checkbutton to enable the row |
| derived values readout | live label of the running config: Reynolds, dynamic pressure q, and the CL*A / CD*A targets for the selected role |
| enforce FSUK/FSG size limits | master switch for the regulatory checks |
| Ground effect / Ground height (% chord) | wing height above the ground for ground-effect runs; off or empty = unbounded flow. Must be a positive number when ground effect is on |
| Sanity check geometry | instant PASS/FAIL vs the size limits - prints the exact mm value vs limit and per-pair gap/overlap in %, redraws the preview (green PASS / red FAIL, ground line drawn when a ground height is set) |
| Simulate this wing now (JavaFoil) | runs the real JavaFoil analysis in a worker thread, writes the row to a new dated run folder in the library and logs Run_ID, Status, Cl@0, Cd@0, max L/D, stall angle, Downforce_N |
| Run in Terminal (konsole) | runs the same simulation in a separate terminal |
| Batch: Multiple Main/Flaps | sweeps several main/flap combos in one go |
| status log + geometry preview | right-hand pane: live log and an embedded matplotlib drawing of the stack in mm |

### 5.2 Airfoils tab

The Airfoils tab is your private airfoil library. Profiles you import are copied
into an internal store (`~/.aero_auto/airfoils` on Linux,
`%USERPROFILE%\.aero_auto\airfoils` on Windows) under the name you give them -
you never need to remember where a `.dat` lives.

| Control | What it does |
|---------|--------------|
| store location label | shows the internal store folder, auto-created on first use |
| Filter store | live filter box - type to narrow the list; the count label shows `matched / total` |
| Import .dat... | copies any `.dat` file into the store under your chosen name; the profile then appears in every airfoil combo |
| Remove selected | deletes the selected profile from the store (never touches your original files) |
| Open store folder | opens the store in the file manager |
| Refresh | re-scans the store and `AIRFOIL_DIR` in case files changed on disk |
| store list | every stored profile with its full path; select one to remove it |

The app also reads the shared `AIRFOIL_DIR` folder (top-level `.dat` files
only), so both sources feed the same combos. Importing, removing or reloading a
profile refreshes **every** airfoil picker at once - the Configure main/flap
combos, the Campaigns main/flap pools (your current selections are preserved)
and the Optimizer main/flap combos - and updates the airfoil count in the status
bar.

### 5.3 Campaigns tab

The left pane is the setup, the right pane is a live monitor - you can watch a
campaign progress, skip a stuck scenario or stop everything, all while the
rows stream into the output file.

| Control | What it does |
|---------|--------------|
| Hours | campaign time budget for the planner (0.1 works for a smoke test) |
| Workers | number of parallel JavaFoil worker directories |
| Out folder + Browse/Open | where the campaign writes (default `~/aero_campaign`) - ground-effect runs get their own `ground/<height>pct/` subfolders here |
| Flow: Unbounded / Ground effect | unbounded free stream, or ground effect at one or more heights (comma list, e.g. `50,100,300` % chord, or a length such as `200mm` converted with the Configure chord). Each height must be positive and becomes its own scenario + `ground/<height>pct/` folder |
| Role: Rear / Front / Custom | which regulatory rule set and CL*A span to use |
| Main elements / Flap pool | multi-select lists of the airfoils the planner may explore, with All/None/Inv helpers |
| Resume previous results.csv | on - the planner detects the output folder's existing rows, keeps consistent row counts and continues `RUN_COUNTER` instead of overwriting history; off - starts fresh |
| Enforce FSUK/FSG size limits | regulatory gate on every generated candidate |
| Self-check before each scenario | runs a quick JavaFoil+faketime validation before each scenario; failures mark the scenario skipped instead of poisoning the campaign |
| Build report folder when finished / Open results folder when finished | post-campaign actions; the report option auto-builds the full report (Best/ + graphs) into every scenario folder |
| Start campaign / Stop all / Skip scenario | run control |
| Self-check only | validates JavaFoil, faketime and each scenario without simulating |
| Write report now / Open results folder / Copy plan | helpers; Copy plan puts the full plan (per-scenario budgets, mains, flap pool) on the clipboard |
| live stats label | elapsed time, simulations finished, current runs/second |
| Scenarios tree | one row per scenario with live Status and Runs count; double-click a row to open that scenario's folder |
| Current best (live) | the best config found so far, updated as runs finish |
| Campaign log | streamed log (Clear / Save... / Copy, auto-scroll toggle); capped so long campaigns stay responsive |

Each campaign becomes one dated run folder in the library (e.g.
`~/aero_campaign/library/20261011-153000_campaign_fw_both/`). Inside it the main
file is `results.csv` and each ground scenario has its own
`ground/<height>pct/results.csv`; if **Build report folder when finished** is on,
each of those folders gets a `Best/` sheet and a `graphs/` folder too.

### 5.4 Results tab

| Control | What it does |
|---------|--------------|
| Run Library tree | one row per run/campaign in the library: date, kind (single/batch/campaign/optimizer/import), main airfoil, best score and run count. Click a row to load it |
| Refresh | re-scans the library for new runs |
| Import existing results... | copy any existing `results.csv` (plus its `graphs/` and `Best/`) into the library as a dated run |
| Export run... | zip the selected run folder for archiving or sharing |
| Open best sheet | opens the selected run's `Best/` report folder (falls back to the run folder) |
| results.csv path entry + Load | which result file to inspect (default the newest library run) |
| Browse... | pick any results.csv on disk (e.g. a legacy ground folder) |
| Show targets | runs the CL*A / CD*A target report for the selected role and prints the ranked top-10 |
| live filter | type to keep only rows matching in any column (case-insensitive, instant);    empty = show all |
| stats footer | shows everything the current view matches: total simulations, summed sim time, first → last date |
| sortable headers | click any column header to sort; click again to reverse (numeric columns sort numerically) |
| results tree | one row per config: Run_ID, Date, Elements, Main, Cl_a0, Cd_a0, Max_LD, Downforce_N, Duration_s, Tier, Score, Status - so you can see how many simulations exist, when each ran and how long it took; renders up to 1000 rows |
| Export view to CSV | saves the currently filtered and sorted rows (all columns, whole rows) to a CSV file you choose |
| Graphs for selected run | renders polar / geometry / field PNGs for the highlighted row into `<results-dir>/graphs` and opens the Graphs tab. Clicking a row does this automatically (images are only rebuilt when missing) |
| detail pane | click a row to see everything: date, duration, alpha interval + RE, flap stack, flow type, polar metrics, force model output and the mm geometry. The summary line counts simulations and total sim time |
| CSV Data Viewer | raw CSV text of the loaded file with Refresh / Save for manual inspection and small edits |

### 5.5 Graphs tab

The Graphs tab is the image side of the app: every generated image for a results
file, previewed right in the window. Its picker lists every results file the app
knows about - the dated library runs and any legacy `<OUT_DIR>` / `ground/`
folders - with an image count per row.

| Control | What it does |
|---------|--------------|
| results file tree | one row per results file (library run or legacy folder) with its modified date and PNG count; click to load it |
| Refresh | re-scans for results files and their `graphs/` PNGs |
| Write report | builds the full report folder for the selected results file |
| Open in viewer | opens the current image in your system image viewer |
| image list | every `<results-dir>/graphs/*.png` found for the chosen results file |
| preview | click an image name to see it scaled inside the app (needs Pillow; without it the list still works) |

### 5.6 Optimizer tab

A hill-climbing optimizer over flap geometry (and main choice), repeatedly
simulating candidates and keeping the best. The scored best config lands in the
Configure tab via **Apply Best** and its final run is appended to the results
file.

| Control | What it does |
|---------|--------------|
| Base Wing Configuration | manual entry, same fields as Configure: main element, results file, flap rows F1..F3 (S/A/X/Y + enable), chord/speed/Re/alpha, ground effect + height |
| Optimization Objectives | weighted objectives to optimize: Lift (Cl), Efficiency (Cl/Cd), Stability (min Cl variation), Stack Height, Stack Length, Target Gap, Downforce, Efficiency @ target Cl |
| Target Values | target Cl, target gap %, max height (mm), max length (mm) used by the corresponding objectives |
| Optimization Parameters | iterations, step size, perturb scale, enforce-regulations switch (height/length/gap constraints) |
| Progress bar + status | current iteration out of total; status text updates live |
| Start Optimization / Stop / Apply Best | run control; Apply Best pushes the winning configuration back into Configure |

The optimizer runs in a worker thread too - the window stays responsive; stop
takes effect between iterations. See the technical guide section 7 for the
scoring function.

### 5.7 Themes & Settings tab

The last tab controls the look of the app and the hover descriptions. Every
change is saved to `ui_state.json` immediately, so it survives a restart.

| Control | What it does |
|---------|--------------|
| Theme: Dark (default) / Light / High contrast | three full palettes; the radio swatches preview each one. Picking a theme re-themes the whole window instantly (a running campaign or optimizer keeps going in the background) |
| Apply theme | same as picking a radio, kept for convenience |
| Show hover descriptions | turn the hover help on or off |
| Delay before showing (ms) | how long the mouse must rest before a description appears (0 = instant) |
| Wrap width (px) | line length of long descriptions |
| Preview description | pops a sample description built with your current settings |
| Navigation | shortcut cheat-sheet (Alt+1 … Alt+7, Ctrl+Tab, Ctrl+R, F5, Esc, Ctrl+Q) |

**Where the colours come from.** The three palettes live in `aero_ui.py`
(`THEMES`); the dark one is the same palette used by the generated PDFs
(`docs/theme.py`). Descriptions always use a high-contrast pair (light card with
dark text on the dark themes, and vice-versa), so they stay readable whatever
theme you pick.

## 6. File locations at a glance

| Artifact | Location |
|----------|----------|
| airfoil `.dat` files | default `AIRFOIL_DIR` = `/mnt/data/FSEA/AIRFOILS JAVAFOIL/AIRFOILS` - put one `.dat` per profile here (top-level files only, no sub-folders). The GUI combos are built from these filenames. Set `AERO_AIRFOILS` to point elsewhere |
| internal airfoil store | `~/.aero_auto/airfoils` (Windows: `%USERPROFILE%\.aero_auto\airfoils`) - profiles imported inside the app; auto-created |
| GUI settings | `~/.aero_auto/ui_state.json` (Windows: `%USERPROFILE%\.aero_auto\ui_state.json`) - window layout + every tab's settings, saved on close |
| run library root | `<OUT_DIR>/library/` (default `~/aero_campaign/library/`) - one dated folder per run |
| single simulations | `<run-dir>/results.csv` in a fresh `library/<stamp>_single_<main>/` folder |
| GUI + CLI campaigns | `<run-dir>/results.csv` in `library/<stamp>_campaign_<role>_<flow>/`; the raw engine `aero_auto.py` you launch yourself still writes `<OUT_DIR>/results.csv` |
| ground-effect campaigns | `<run-dir>/ground/<height>pct/results.csv` - one file per ride height, inside the campaign run folder |
| run manifest | `<run-dir>/meta.json` - date, kind, main, run count, best score; drives the Run Library tree |
| ranked tables | `<results-dir>/Best/configs.csv`, `Best/overview.txt`, `Best/overview.xlsx` - next to whichever results.csv you reported |
| readable CSV + legend | `<results-dir>/results_human.csv` and `<results-dir>/columns_legend.csv` |
| polar and geometry graphs | `<results-dir>/graphs/polar_<Run>.png` and `geometry_<Run>.png` |
| velocity maps (field sims) | `<results-dir>/graphs/field_<Run>.png` - schematic potential-flow velocity field for that config; `render_field.py` produces a single picture from any configuration |
| exported run archive | wherever you choose, a `.zip` of the whole run folder (Export run...) |
| target report | `targets_report.csv` next to the results file you pointed the tool at |

> Note: the polar graphs are the authoritative data. `field_*.png` images are
> a schematic potential-flow visualisation whose circulation comes from each
> config's own JavaFoil Cl - not a second force solver.

## 7. Environment overrides

| Variable | Effect |
|----------|--------|
| AERO_JAVA_DIR | folder that contains javafoil.jar |
| AERO_AIRFOILS | folder with the .dat profiles |
| AERO_OUT | campaign output folder (default ~/aero_campaign) |
| AERO_ICON | explicit GUI icon path |

## 8. What a campaign writes

Rows carry the configuration, the polar metrics, per-pair geometry, forces and
quality: `Run_ID Phase Main F1_* F2_* F3_* Cl_peak Cd_peak Stall_Angle Max_LD
Cl_a0 Cd_a0 Cm_a0 Cl_am2 Cl_ap2 Downforce_N Drag_N Tier Score Status` plus
per-pair gap/overlap/step and the all-mm geometry. A backup of the previous
file is written before a resumed campaign migrates an old-format file.

## 9. The report folder

| File | Content |
|------|---------|
| Best/configs.csv | the top-N, round-robin across stack sizes |
| Best/overview.txt | human summary incl. spans, q and force model |
| Best/overview.xlsx | Top configs / All rows / Legend sheets |
| results_human.csv | every valid row, readable column names |
| columns_legend.csv | column - unit - description for everything |
| graphs/*.png | polar, geometry and field (velocity) images per config |

## 10. Regulatory reference (FSUK 2026 / FSG v1.1)

| Rule | Limit |
|------|-------|
| Min ground clearance | 35 mm |
| Front wing max stack height | 250 mm |
| Front wing max stack length | 600 mm |
| Rear wing max total height | 1100 mm |
| Rear wing max stack length | 250 mm |
| Front wing span | 1400 mm |
| Rear wing span | 950 mm |
| Targets CL*A / CD*A roof | fw 1.75 / 0.45 - rw/beam 1.85 / 0.95 (tol ±0.4) |

## 11. Packaging and platform notes

| Artifact | Run with | Notes |
|----------|----------|-------|
| aero_auto_linux_1.1.tar.gz | ./run_ui.sh | python 3.9+ + requirements.txt |
| aero_auto_windows_1.1.zip | run_ui.bat | needs installed Python |
| aero_auto_windows_app_1.1.zip | aero_ui\aero_ui.exe | standalone, no Python |
| desktop app | ~/Applications/aero_auto/ | .desktop entry registered |
| aero_ui.exe | standalone | PyInstaller (built under wine) |

`python3 build_dist.py` builds the versioned linux tar.gz and windows zip
(pure source + launch scripts), and `create_standalone.sh` /
`create_standalone.bat` build the self-contained PyInstaller folder. The
report/manual PDFs (`docs/TECHNICAL_GUIDE.pdf`, `docs/USER_MANUAL.pdf`, dark
themed) are regenerated with `python3 docs/build_docs.py` and are embedded
inside the standalone folder, so the shipped app carries its own
documentation.

## 12. Changelog highlights

1.0
- regulatory engine + GUI verdict, geometry_ok gate before JavaFoil
- ground-effect campaigns and per-height result files
- force model (Downforce_N / Drag_N) and all-mm geometry columns
- target report against CL*A / CD*A roofs
- calibrated potential-flow model (replaces the abandoned linear solver)
- full report pipeline: workbook, legend, duplicate-safe headers, --resim
- threaded Tk GUI with a queue-based thread bridge and icon support
- cross-platform packaging: launcher, field CLI, desktop app, wine-built exe

1.1 (this build)
- Campaigns tab redesigned into setup + live monitor: per-scenario tree with
  live status/runs, live best config, stats (elapsed / finished / runs-per-s),
  Skip scenario / Stop all, Self-check only, Copy plan to clipboard,
  resume-prevents-overwrite
- shared `run_plan` engine for CLI and GUI campaigns: per-scenario time
  budgets, strict deadline, scenario progress events
- Optimizer tab: objectives, target values, constraints, live progress, Apply
  Best
- Results tab: sortable columns, live filter, stats footer, detail pane,
  CSV data viewer, results-folder browser
- menu bar (File / View / Help with Ctrl+R, F5, Ctrl+Q), status bar,
  settings persistence to `~/.aero_auto/ui_state.json`
- legacy results.csv auto-upgrade with backup (recover old 31/47-column rows)
- docs regenerated for 1.1 (dark edition)

1.1 (UI refresh)
- dark theme across the whole app (matches the docs palette), header band and
  themed ttk widgets; dark geometry preview
- **app-managed run library**: every single/batch/campaign/optimizer run becomes
  a dated folder under `<OUT_DIR>/library/` with a `meta.json` manifest; existing
  data is auto-imported on first run
- Run Library tree on the Results tab with Import existing / Export run (zip) /
  Open best sheet
- click a results row to auto-generate its graphs (only when missing) and jump to
  the Graphs tab; Graphs tab gains Write report + Open in viewer
- campaigns auto-build the full report (Best/ + graphs) into each scenario folder
  when finished
- central ground-height guard: heights must be positive (used by every entry
  point, including `aero_targets --height`)

1.1 (themes + descriptions)
- **Themes & Settings tab**: Dark / Light / High contrast palettes with live
  switching (the window rebuilds under the new colours), plus hover-description
  and navigation settings - all persisted
- hover descriptions rebuilt as one shared, delayed, high-contrast popup that is
  dismissed on click / Esc / leave / tab change, so no description keeps floating
  over the window
- Appearance menu and Alt+1 … Alt+7 / Ctrl+Tab tab navigation