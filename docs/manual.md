# aero_auto 1.0 - User Manual (dark edition)

Multi-element wing design, simulation and reporting toolchain built on the
JavaFoil panel solver. This manual covers the GUI (run_ui.sh / aero_ui.exe),
every functionality, and exactly where the airfoil files and the results land.
For the "why" behind the code, open `docs/TECHNICAL_GUIDE.pdf`.

## 1. Overview

| Module | Purpose |
|--------|---------|
| aero_auto.py | core engine - regulatory rules, geometry, JavaFoil runner, campaign planner |
| aero_targets.py | CL*A / CD*A target report |
| aero_report.py | ranked tables, Excel workbook, graphs, --resim |
| flowfield.py | schematic potential-flow model for the velocity field images |
| aero_ui.py | the GUI shell (Configure / Campaigns / Results) |
| render_field.py | headless velocity-field PNG renderer |
| launcher.py | one entry point for every tool (ui/campaign/report/targets/field) |

## 2. Requirements

- Python 3.9+ with Tkinter (the python.org installer bundles Tk on Windows).
- Java 8+ and `javafoil.jar` + `mhclasses.jar` (the engine's solver).
- Python packages in `requirements.txt`: numpy, pandas, matplotlib, openpyxl, Pillow.
- `faketime` on Linux (auto-skipped on Windows).
- Your airfoil `.dat` library - see chapter 6.
- The standalone `aero_ui.exe` needs none of the above - it bundles Python, the
  solver dependencies and the docs inside the zip.

## 3. Install

```
python3 -m pip install -r requirements.txt

# optional standalone (no Python on the target machine):
python3 create_standalone.sh     # linux/macos -> dist/aero_ui/
create_standalone.bat            # windows     -> dist\aero_ui\aero_ui.exe
```

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

The same engine runs behind the window, so a config you have just
sanity-checked can be simulated or campaigned without leaving the app. Every
JavaFoil operation runs in a worker thread - the window never freezes.

### 5.1 Configure tab

| Control | What it does |
|---------|--------------|
| Main element | the airfoil that defines the wing; the combo lists every profile found in your `.dat` folder |
| Role: front / rear / custom | sets the span used by CL*A and the force model (fw 1400 / rw 950 / custom 1000 mm) and the FSUK/FSG rule set checked |
| Main chord (mm) | physical chord in millimetres; enables the all-mm geometry columns and the force conversion |
| Speed (m/s) | freestream speed for `q = 0.5 rho V^2` in the force model |
| Reynolds number | run Reynolds number sent to JavaFoil (default 570 000) |
| Alpha start / end / step (deg) | polar sweep angles; default -20..+5 step 1 covers the stall search |
| Flap rows F1..F3 | per slot: airfoil combo + S% scale of main chord, A deg mount angle, X% position, Y% position; tick the checkbutton to enable the row |
| enforce FSUK/FSG size limits | master switch for the regulatory checks |
| Ground height (% chord) | wing height above the ground for ground-effect runs; empty or `none` = unbounded flow |
| Sanity check geometry | instant PASS/FAIL vs the size limits - prints the exact mm value vs limit and per-pair gap/overlap in %, redraws the preview (green PASS / red FAIL, ground line drawn when a ground height is set) |
| Simulate this wing now (JavaFoil) | runs the real JavaFoil analysis in a worker thread, appends the row to `~/aero_campaign/results.csv` and logs Run_ID, Status, Cl@0, Cd@0, max L/D, stall angle, Downforce_N |
| Simulate in Terminal | launches the simulation in an external terminal window (konsole, alacritty, gnome-terminal, xterm) for real-time stdout monitoring |
| Batch Simulate | runs multiple configurations or angle sweeps sequentially in worker threads |
| Extract JavaFoil Graphs (Native) | runs JavaFoil in the background and extracts all 6 native JavaFoil plots (drag polar, lift curve, moment curve, surface velocity/Cp distribution, skin friction, and boundary layer thickness) straight to the Graphs tab |
| status log + geometry preview | right-hand pane: live log and an embedded interactive matplotlib drawing of the stack in mm with hovering coordinate inspection and ground line |

### 5.2 Airfoils tab

The Airfoils tab is your private airfoil library. Profiles you import are copied
into an internal store (`~/.aero_auto/airfoils` on Linux, `%USERPROFILE%\.aero_auto\airfoils` on
Windows) under the name you give them - you never need to remember where a `.dat` lives.

| Control | What it does |
|---------|--------------|
| Store location label | Shows the internal store folder (`~/.aero_auto/airfoils`), auto-created on first use |
| Import airfoil (.dat)... | Batch import one or multiple `.dat` files into the store; profiles appear in every combo immediately |
| Import folder... | Recursively scans a selected folder and batch imports all `.dat` files found into the store |
| Remove selected | Deletes the selected profile from the store (never touches your original files) |
| Open store folder | Opens the store in the OS file manager |
| Refresh | Re-scans the store and `AIRFOIL_DIR` in case files changed on disk |
| Filter store | Live filter box to quickly find any airfoil by name or filename |
| Store list | Lists every stored profile with its full path and count badge |

The app also ships with the shared `AIRFOIL_DIR` folder (top-level `.dat` files
only), so both sources feed the same combos.

### 5.3 Campaigns tab

The Campaigns tab is the automated aerodynamic optimization hub. It features the authentic 7-section configuration layout, live progress monitors, scenario tree, and integrated logging:

| Section | Control / Feature | What it does |
|---------|-------------------|--------------|
| **1. Time Budget** | Hours entry + Quick Buttons | Total wall-clock time limit for the campaign. Quick-select buttons: `30m` (0.5h), `1h`, `4h`, `12h`, `24h` for instant setup. Budgets are split across selected scenarios. |
| **2. Parallelism** | Workers & CPU display | Number of parallel JavaFoil worker processes (defaults to CPU count up to 4). Each worker runs in an isolated directory (`<out>/work/w0..wN`). Includes "Browse..." and "Open folder" buttons. |
| **3. Flow Scenarios** | Unbounded vs Ground effect | Select unbounded flow, ground effect, or both. For ground effect, specify comma-separated heights as % of chord (e.g. `300, 150, 50`). |
| **4. Wing Role** | Radios (Rear / Front / Custom) | Selects aerodynamic role rules (Rear Wing, Front Wing, or Custom span) to constrain bounding dimensions and downforce span calculations. |
| **5. Airfoil Pools** | Dual Listboxes + Quick Buttons | Dedicated selection listboxes for Main element and Flap elements. Use `All`, `None`, and `Inv` (Invert) buttons to quickly select candidate airfoils, or "Prefill pool" from the active Configure tab. |
| **6. Options** | Checkboxes | `Resume`: continue from existing `results.csv`; `Enforce regulations`: filter geometries vs FSUK/FSG rules; `Self-check first`: validate pool before running; `Build report`: automatically generate `Best/` and graphs on completion; `Open results`: open output folder upon completion. |
| **7. Actions** | Control Buttons | `Start campaign`: launch multi-scenario run in worker thread; `Stop`: request clean shutdown; `Skip`: advance to next scenario; `Self-check only`: test pool without solver; `Write report now`: generate report immediately; `Copy plan`: copy full plan specification to clipboard. |

#### Campaign Live Monitoring
- **Live Progress Monitor**: Displays overall progress bar, elapsed time, estimated time of arrival (ETA), current phase (1: Coarse exploration, 2: Fine refinement, 3: Polish), and active runs/sec.
- **Live Best Table**: Real-time leaderboard table showing top performing configuration discovered so far per element count (1-elem, 2-elem, 3-elem, 4-elem) with Main airfoil, Cl@0, Cd@0, L/D, Downforce, and Score.
- **Scenarios Tree**: Lists each scenario with its execution status (`pending`, `running`, `done`) and run count. Double-click any scenario to immediately open its directory.
- **Campaign Log**: Real-time streaming log of all worker activities, simulation status verdicts, and errors. Includes `Clear`, `Save...`, `Copy`, and `Auto-scroll` controls.

### 5.4 Results tab & Run Library

The Results tab manages all simulation runs with hierarchical folder-inside-folder organization, real-time executive KPI metrics, rich right-click operations, CAD export, and click-to-graph auto-navigation:

#### 5.4.1 Run Library (Top Panel)
- **Hierarchical Folder-Inside-Folder Treeview**: Displays simulations grouped into collapsible and expandable nodes:
  - `📁 Active Campaign`: Lists unbounded flow results (`results.csv`) and sub-folder `📁 Ground Effect Scenarios` (each ground height `h31pct`, `h100pct`, `h300pct`).
  - `📁 Archived Run Library`: Lists all historical dated campaign runs and library imports with date, wing kind, main airfoil, best score, and simulation count.
  - Clicking any row or sub-item immediately loads its `results.csv`, calculates executive KPIs, and refreshes the Graphs gallery.
- **Import Existing Results…**: Imports any external `results.csv` (and its `graphs/` folder) into the library as a dated archive.
- **Export Run…**: Compresses the selected run folder into a self-contained `.zip` archive for sharing.
- **Open Best Sheet**: Opens the `Best/` report folder (Excel sheet + summary report + graphs) for the selected run in your file manager.

#### 5.4.2 Executive KPI Summary Banner
Situated directly above the Results Table, this real-time executive card banner provides instantaneous Formula Student aerodynamic metrics for the loaded dataset (or filtered view):
- **Runs**: Total simulation count in view.
- **Max Downforce**: Peak downforce in Newtons ($N$) calculated using freestream velocity and aerodynamic span.
- **Max L/D**: Peak aerodynamic efficiency ratio ($C_l / C_d$).
- **Best Score**: Top overall optimization score achieved.
- **Valid Ratio**: Percentage and count of geometrically rule-compliant runs.
- **Sim Time**: Total cumulative solver wall-clock time.

#### 5.4.3 Results Table, Headline Ranking & Horizontal Scrolling (Center Panel)
- **Comprehensive 50+ Column Display**: Displays every available simulation variable and metric from the dataset:
  - *Evaluation*: `Run_ID`, `Rank`, `Score`, `Tier`, `Status`
  - *Aerodynamics*: `Cl_a0`, `Cd_a0`, `Cm_a0`, `Max_LD`, `Downforce_N`, `Drag_N`, `Cl_peak`, `Cd_peak`, `Stall_Angle`, `Cl_am2`, `Cl_ap2`
  - *Wing Setup*: `Elements`, `Main`, `Flow`, `Height_pct`
  - *Flap 1..3 Geometry*: Airfoil, Scale %, Angle deg, X %, Y %, Gaps %, Overlaps %, Steps %
  - *Stack Dimensions*: `Stack_Length_mm`, `Stack_Height_mm`, `Min_Clearance_mm`, `Stack_Length_pct`, `Stack_Height_pct`
  - *Execution Telemetry*: `Speed_ms`, `Duration_s`, `Date`, `Alpha_Interval`, `Phase`
- **Headline Click-to-Rank**: Clicking ANY column header immediately ranks the entire dataset based on that column:
  - First click on performance metrics (`Score`, `Downforce_N`, `Max_LD`, `Cl_a0`, etc.) ranks descending (`▼`) so top performers appear at the top.
  - Clicking again toggles ascending rank (`▲`).
  - Active sorted column displays a visual arrow indicator (`▲` or `▼`) in its header, and live stats reflect the ranking criterion.
- **Left and Right Horizontal Scrolling**:
  - Embedded horizontal scrollbar directly beneath the table grid.
  - Quick toolbar navigation buttons: `◀ Left` and `Right ▶`.
  - Shift + Mouse Wheel (`Shift + Scroll`) and trackpad horizontal scrolling.
  - Keyboard `<Left>` and `<Right>` arrow key panning when table is focused.
- **Precision Numerical Alignment**: Every float is formatted to standard engineering precision (e.g. 4 decimals for aerodynamic coefficients, 2 decimals for efficiency and scores, 1 decimal for forces and mm dimensions), with right-aligned numbers (`anchor='e'`) to ensure vertical decimal point alignment across all rows.
- **Column View Presets**: Quick dropdown selector to switch between:
  - `All Columns (50+)`: Complete dataset view with horizontal scroll.
  - `Aerodynamics & Performance`: Focused view on lift, drag, moment, downforce, and efficiency.
  - `Wing Geometry & Flaps`: Detailed element scales, angles, gaps, and dimensions.
  - `Core Telemetry`: Essential multi-element metrics in a compact view.
- **Dual Graph Generation (Code + JavaFoil) into Dedicated Run Folder**:
  Clicking any row in the table automatically generates BOTH coded Matplotlib graphs (`polar`, `geometry`, `field`) AND JavaFoil authentic native aerodynamic plots (`javafoil_polar_cl_cd`, `javafoil_polar_cl_alfa`, `javafoil_polar_cm_alfa`, `javafoil_velocity_cp`, `javafoil_bl_cf`, `javafoil_bl_delta`) into a dedicated folder `<results_dir>/graphs/run_<Run_ID>/`, also copies them to `<results_dir>/graphs/`, and immediately switches to the Graphs tab focused on that run.
- **Right-Click Context Menu**: Right-clicking (`Button-3` / `Button-2`) on any run row brings up a full engineering workflow menu:
  - 🚀 **Send to Optimizer (Set as Base Design)**: Automatically parses the wing and flap elements, sets them as the baseline design in the Optimizer tab, and switches directly to the Optimizer.
  - 📐 **Export 2D CAD Model (AutoCAD DXF)**: Exports the multi-element wing to an AutoCAD-compatible DXF file in millimeter units with distinct layers (`MAIN_ELEMENT`, `FLAP_1..3`, `GROUND_PLANE`, `BOUNDING_BOX`).
  - 🎨 **Export Vector Geometry (SVG)**: Exports clean vector graphic representation for design reports and presentations.
  - ⚙️ **Load to Configure Tab**: Loads the wing into Configure and triggers an immediate sanity-check and outline redraw.
  - 📊 **Generate All Graphs (Code + JavaFoil) & View**: Generates all plots and switches to the Graphs tab.
  - 📁 **Open Run Graphs Folder in File Manager**: Opens `<results_dir>/graphs/run_<Run_ID>/` in the OS file explorer.
  - 📋 **Copy Run Telemetry / Summary to Clipboard**: Copies all telemetry figures to the clipboard.
  - 🗜️ **Export Run Archive (.zip)**: Bundles data row, telemetry text, CAD files, and graphs into a standalone zip file.

#### 5.4.4 Enhanced CSV Data Viewer & External Spreadsheet Integration (Bottom Panel)
- **Monospaced Data Viewer**: Monospaced font display (`DejaVu Sans Mono`, 9pt) with distinct golden/cyan table header highlighting.
- **Header Info Badge**: Shows active file name, file size in KB/MB, and line count.
- **In-Text Search Filter**: Type any query into the search entry to find and highlight matches in real time.
- **Open in External Calc / Spreadsheet ↗**: 1-click button to launch your system's default spreadsheet application (LibreOffice Calc, Excel, etc.) directly on the loaded CSV file.
- **Safe Backup Saving**: Edit raw values directly and save with an automatic timestamped backup (`_backup_YYYYMMDD_HHMMSS.csv`).

### 5.5 Graphs tab

The Graphs tab provides immediate visual inspection of generated aerodynamic plots:
- **Runs with Graphs**: Treeview listing every results file with its last modified timestamp and image count.
- **Image Listbox**: Lists all PNG graphs in the `<results-dir>/graphs/` folder (`polar_<Run>.png`, `geometry_<Run>.png`, `field_<Run>.png`, and native `javafoil_*` plots).
- **Embedded Preview**: High-contrast thumbnail rendering inside the window with auto-scaling to fit the display.
- **Open in Viewer**: Opens full-resolution image in your system default image viewer.
- **Write Report**: Generates `Best/` folder and all graphs for the selected run.

### 5.6 Optimizer tab

The Optimizer tab provides multi-objective wing optimization via stochastic perturbation sweeps:
- **Base Wing Configuration**: Load baseline stack from the Configure tab or browse and load the highest-scoring run from any `results.csv`.
- **Multi-Objective Targets**: Configure weighted optimization objectives:
  - Maximize Lift ($C_l$)
  - Maximize Efficiency ($C_l / C_d$)
  - Minimize $C_l$ variation over angle range (aerodynamic stability)
  - Minimize Stack Height (mm)
  - Minimize Stack Length (mm)
  - Target specific gap size (% chord)
  - Maximize Downforce (N)
  - Maximize efficiency at a specified target $C_l$
- **Target Boundaries**: Set target $C_l$, target gap %, max allowed height (mm), and max allowed length (mm).
- **Sweep Parameters**: Set iteration count, step size, and perturbation scale.
- **Optimizer Worker**: Background solver evaluates candidates against regulatory geometry constraints and JavaFoil, streaming log updates and tracking best score.
- **Apply Best**: Automatically pushes the winning airfoil and flap parameters to the Configure tab and triggers a redraw.

### 5.7 Themes & Settings tab

The Settings tab personalizes appearance, ergonomics, and navigation:
- **Color Themes**: Instant re-theming with multiple color palettes (Dark, Light, Contrast).
- **Hover Descriptions**: Toggle hover tooltips on/off, adjust display delay (0–2000 ms), and adjust popup text wrap width (160–900 px).
- **Keyboard Shortcuts Reference**:
  - `Alt + 1 … 7`: Jump directly to any tab
  - `Ctrl + Tab` / `Ctrl + Shift + Tab`: Cycle through tabs
  - `Ctrl + R`: Write report for current results file
  - `F5`: Refresh results, runs, and graphs
  - `Esc`: Dismiss active hover tooltip
  - `Ctrl + Q`: Quit application


The Graphs tab is the image side of the app: every generated image for a results
file, previewed right in the window.

| Control | What it does |
|---------|--------------|
| results file combo | lists `~/aero_campaign/results.csv`, each ground folder's `results.csv` and the file you last loaded |
| Write report | builds the full report folder for the selected results file |
| Refresh | re-scans the selected results folder for `polar`, `geometry`, `field`, and native `javafoil_*` PNGs |
| Open in viewer | opens the current image in your system image viewer |
| image list | every `<results-dir>/graphs/*.png` found for the chosen results file (including custom plots and native JavaFoil polars, velocity/Cp, and boundary layer charts) |
| preview | click an image name to see it scaled inside the app (needs Pillow; without it the list still works) |

## 6. File locations at a glance

| Artifact | Location |
|----------|----------|
| airfoil `.dat` files | default `AIRFOIL_DIR` = `/mnt/data/FSEA/AIRFOILS JAVAFOIL/AIRFOILS` - put one `.dat` per profile here (top-level files only, no sub-folders). The GUI combos are built from these filenames. Set `AERO_AIRFOILS` to point elsewhere |
| internal airfoil store | `~/.aero_auto/airfoils` (Windows: `%USERPROFILE%\.aero_auto\airfoils`) - profiles imported inside the app; auto-created |
| single simulations / GUI + CLI campaigns | `~/aero_campaign/results.csv`, appended after every run |
| ground-effect campaigns (CLI) | `~/aero_campaign/ground/<height>pct/results.csv` - one file per ride height |
| ranked tables | `<results-dir>/Best/configs.csv`, `Best/overview.txt`, `Best/overview.xlsx` - next to whichever results.csv you reported |
| readable CSV + legend | `<results-dir>/results_human.csv` and `<results-dir>/columns_legend.csv` |
| polar and geometry graphs | `<results-dir>/graphs/polar_<Run>.png` and `geometry_<Run>.png` |
| native JavaFoil graphs | `<results-dir>/graphs/javafoil_polar_cl_cd_<Run>.png`, `javafoil_polar_cl_alfa_<Run>.png`, `javafoil_polar_cm_alfa_<Run>.png`, `javafoil_velocity_cp_<Run>.png`, `javafoil_bl_cf_<Run>.png`, `javafoil_bl_delta_<Run>.png` - native headless vector captures from JavaFoil's internal Polar, Velocity, and BoundaryLayer cards |
| velocity maps (field sims) | `<results-dir>/graphs/field_<Run>.png` - schematic potential-flow velocity field for that config; `render_field.py` produces a single picture from any configuration |
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
per-pair gap/overlap/step and the all-mm geometry.

## 9. The report folder

| File | Content |
|------|---------|
| Best/configs.csv | the top-N, round-robin across stack sizes |
| Best/overview.txt | human summary incl. spans, q and force model |
| Best/overview.xlsx | Top configs / All rows / Legend sheets |
| results_human.csv | every valid row, readable column names |
| columns_legend.csv | column - unit - description for everything |
| graphs/*.png | polar, geometry, field (velocity), and native JavaFoil engine graphs (polar Cl-Cd, Cl-alpha, Cm-alpha, velocity Cp, BL Cf/delta) per config |

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
| aero_auto_linux.tar.gz | ./run_ui.sh | python 3.9+ + requirements.txt |
| aero_auto_windows.zip | run_ui.bat | needs installed Python |
| aero_auto_windows_app.zip | aero_ui\aero_ui.exe | standalone, no Python |
| desktop app | ~/Applications/aero_auto/ | .desktop entry registered |
| aero_ui.exe | standalone | PyInstaller (built under wine) |

The GUI and the report/manual PDFs (`docs/TECHNICAL_GUIDE.pdf`,
`docs/USER_MANUAL.pdf`, dark themed, regenerated with `docs/build_docs.py`)
are embedded inside the `.exe` via `--add-data`, so the shipped app carries its
own documentation. Rebuild with `create_standalone.bat` on Windows or the wine
command in the technical guide's packaging chapter.

## 12. Changelog highlights

- regulatory engine + GUI verdict, geometry_ok gate before JavaFoil
- ground-effect campaigns and per-height result files
- force model (Downforce_N / Drag_N) and all-mm geometry columns
- target report against CL*A / CD*A roofs
- calibrated potential-flow model (replaces the abandoned linear solver)
- full report pipeline: workbook, legend, duplicate-safe headers, --resim
- threaded Tk GUI with a queue-based thread bridge and icon support
- cross-platform packaging: launcher, field CLI, desktop app, wine-built exe
- Results tab CSV Dataset Navigator: recursive multi-folder scanner across campaign, ground sweeps, and root workspace
- Universal dynamic table: automatic schema detection for arbitrary CSVs (iteration sheets, sweep logs)
- Interactive numeric-aware column sorting and real-time multi-column filter
- Dynamic aerodynamic KPI summary banner (Rows, Max Downforce, Max L/D, Best Score, Valid %)
- Dual-view Run Inspector (telemetry summary card + complete key-value property grid)
- 1-click engineering workflows: "Load to Configure", "Send to Optimizer", and "Graphs for Selected Run"
- Raw CSV data viewer and editor with live line/char stats and in-place saving
- Aeronautical dark UI polish: slate palette, alternating row striping, status badges, and multi-terminal launcher support
- Native JavaFoil graph extraction engine: headless vector extraction of JavaFoil's internal Polar, Velocity/Cp, and Boundary Layer graphs alongside custom matplotlib plots
- "Extract JavaFoil Graphs (Native)" instant button in Configure tab and automated multi-artifact generation in Results tab and aero_report