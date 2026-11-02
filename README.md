# ENPRT 2D JavaFoil Automation & Multi-Element Aerodynamic Suite (`aero_auto`)

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Java Requirement](https://img.shields.io/badge/java-JRE%208%2B-orange)](https://adoptium.net/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-lightgrey)](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION)
[![Ruleset](https://img.shields.io/badge/regulations-FSUK%202026%20%2F%20FSG%20v1.1-green)](https://www.imeche.org/)

An automated multi-element aerodynamic optimization and campaign toolchain built on JavaFoil. Engineered for high-downforce motorsports and Formula Student (FSAE / FSG / FSUK) aerodynamics teams.

---

## Windows Executable Packages (Ready to Run - No Python Required)

For Windows users who want to run Aero Auto immediately without installing Python or setting up an environment:

- [**Download AeroAuto_GUI_Windows_v1.2.zip (v1.2 - Recommended)**](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/download/v1.2/AeroAuto_GUI_Windows_v1.2.zip)
  *Complete pre-packaged Windows distribution archive (~132 MB). Extract and double-click `AeroAuto_GUI.exe` to launch immediately.*
- [**Download AeroAuto_GUI_Standalone.exe (v1.2)**](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/download/v1.2/AeroAuto_GUI_Standalone.exe)
  *Single-file portable executable (~128 MB). No installation needed.*
- [**View Full v1.2 Release Notes**](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/tag/v1.2)
  *Release highlights: 3D race car wings engine, authentic ISO 10303-21 `.step` solid CAD models with 1-click SolidWorks launcher, universal multi-version ANSYS Fluent detection (2020 through 2026+) with pre-calculated CFD solution loading (mesh, converged data, pressure contours & force monitors ready), OpenFOAM/SU2 CFD cases, and verified empirical benchmarks.*

*(Legacy v1.1 releases remain archived at [Releases / v1.1](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/tag/v1.1))*

*(Requirement: Java JRE/JDK 8+ installed on your system for JavaFoil simulation. Free installer: [Adoptium Temurin](https://adoptium.net))*

---

## Key Capabilities

- **Multi-Element Geometry Engine (1 to 4 Elements)**:
  Parameterizes main planes and trailing-edge flaps (scale, incidence angle, $x/y$ slots, and overlaps) with collision detection, sanity clipping, and ground-effect modeling.
  
- **7-Tab Interactive Graphical Interface**:
  1. **Configure**: Interactive wing visualizer with real-time camber/incidence controls and instant JavaFoil single simulation.
  2. **Airfoils**: Profile library manager with direct Selig coordinate validation, visual previews, and format import.
  3. **Campaigns**: Batch and multi-hour design space exploration with real-time progress monitoring and worker allocation.
  4. **Results**: 56-column physical and aerodynamic inspector with click-to-rank sorting, search filters, and horizontal scrolling.
  5. **Graphs**: High-resolution aerodynamic chart visualizer (Polars, Pressure distributions, Boundary layer graphs).
  6. **Optimizer**: Multi-objective genetic optimization and parametric refinement targeting maximum downforce and $L/D$.
  7. **Themes & Settings**: Dark aeronautical theme, typography controls, and path configuration.

- **Authentic Publication-Grade Aerodynamic Plots**:
  Generates 16:9 high-resolution dark aeronautical graphs extracted directly from authentic JavaFoil boundary layer and potential flow tables:
  - **Drag Polar**: $C_l$ vs $C_d$
  - **Lift Curve**: $C_l$ vs $\alpha$ with peak and stall detection
  - **Pitching Moment**: $C_m$ vs $\alpha$
  - **Surface Pressure Distribution**: $C_p$ vs $x/c$
  - **Boundary Layer Friction**: $C_f$ vs $x/c$
  - **Boundary Layer Thickness**: $\delta$ vs $x/c$

- **Authentic 3D STEP Solid CAD Models & 1-Click SolidWorks Launcher**:
  Direct generation of watertight 3D solid BREP models (`.step` / `.stp`) with curved 3D endplates and footplates conforming to ISO 10303-21 standards. Includes automatic detection of SolidWorks (2020 through 2026+) and instant 1-click launch from the GUI.

- **Pre-Calculated ANSYS Fluent Interactive Integration**:
  Direct 1-click launch into ANSYS Fluent GUI loading full converged solution data (`/file/read-case-data`). Mesh, converged velocity/pressure flowfields, wall shear stress, surface pressure contours, and aerodynamic force reports ($C_l, C_d, C_m$) are rendered on screen and ready for instant interactive exploration without waiting for re-computation.

- **Universal Multi-Version ANSYS Compatibility (2020 to 2026+)**:
  Automatic dynamic detection across all standard installation paths (`C:\Program Files\ANSYS Inc\v***\fluent\ntbin\win64\fluent.exe`), dynamic desktop discovery, and GUI settings configurator for custom CFD executable paths.

- **CAD Model Export (2D)**:
  Direct 2D CAD export of multi-element configurations into **DXF (AutoCAD)** and **SVG** vector formats for import into CAD software (Fusion 360, SolidWorks, CATIA, Onshape).

- **Formula Student Regulatory Compliance**:
  Built-in physical envelope verification against FSUK 2026 / FSG rules:
  - Minimum ground clearance ($T2.3.2 \ge 35\text{ mm}$)
  - Front wing maximum stack height and length ($T8.2.1b \le 250\text{ mm}$, $T8.2.3b \le 600\text{ mm}$)
  - Rear wing maximum stack length and total height ($T8.2.3a \le 250\text{ mm}$, $T8.2.1c \le 1100\text{ mm}$)

---

## Project Structure

The repository is organized into modular packages separating the core solver engines, user interfaces, benchmarks, test suites, and automation tools:

```text
├── START_AERO_AUTO.bat         # 1-Click Windows launcher (launches GUI app)
├── START_3D_WING_OPTIMIZER.bat # 1-Click 3D multi-element wing suite & optimizer
├── aero_ui.py                  # 7-tab Tkinter/ttk desktop GUI with live 3D CFD monitors
├── aero_auto.py                # Core aerodynamic simulation engine & JavaFoil bridge
├── ansys_engine.py             # ANSYS Fluent 2024 automated case solver & monitor
├── aero_3d_engine.py           # Finite wing 3D ground effect & downforce engine
├── aero_auto_wings_suite.py    # Multi-element front/rear wing suite generator
├── aero_report.py              # HTML & PDF aerodynamic report compiler
├── aero_targets.py             # Performance targets and downforce vs drag trade-offs
├── flowfield.py                # Streamline and velocity vector potential flow solver
├── launcher.py                 # Cross-platform CLI unified command entrypoint
├── openfoam_engine.py          # OpenFOAM-13 RANS k-omega SST solver interface
├── su2_engine.py               # SU2 incompressible RANS solver interface
├── _sim_worker.py              # Background multi-process worker runner
├── audit_system.py             # Automated adversarial integrity audit suite
├── requirements.txt            # Python dependencies manifest
├── pyproject.toml              # PEP 518/621 project configuration
│
├── assets/                     # Core assets and databases
│   ├── airfoils/               # Selig airfoil coordinate library (.dat)
│   ├── JavaFoil/               # JavaFoil simulation engine jars
│   └── icon.ico, icon.png      # High-DPI branding and UI icons
│
├── benchmarks/                 # Verification & validation datasets
│   ├── step4_mesh_independence_results.csv # Grid convergence & GCI study
│   ├── step4_nasa_30p30n_results.csv       # NASA 30P-30N experimental validation
│   ├── step4_single_element_results.csv    # Single-element XFOIL/SU2 baseline
│   └── step5_retest_values_results.csv     # RANS vs panel comparison data
│
├── configs/                    # Preset wing configuration profiles
│   ├── FWA_hero.json           # Maximum downforce front wing
│   ├── FWA_stable.json         # Pitch-stable front wing
│   ├── FWB_hero.json           # Separation-resistant front wing
│   ├── RW_hero.json            # 4-Element rear wing baseline
│   └── RW_incidence3.json      # Elevated incidence rear wing
│
├── docs/                       # Technical manuals & reports
│   ├── USER_MANUAL.pdf         # Complete GUI walkthrough and tutorial
│   ├── TECHNICAL_GUIDE.pdf     # Mathematical formulations & rules guide
│   ├── FSAE_OPTIMIZATION_GUIDE.pdf # Theoretical manual & operational guide
│   ├── validation_report.md    # Comprehensive CFD validation report
│   └── README_WINDOWS.txt      # Quick-start guide for Windows users
│
├── launchers/                  # Alternative platform launchers & shortcuts
│   ├── run_ui.bat              # Windows batch launch script
│   ├── run_ui.sh               # Linux shell launch script
│   ├── run_ui_debug.bat        # Diagnostic verbose launcher
│   ├── open_in_aero_auto.py    # Standalone interactive preset launcher
│   └── *.desktop               # Linux desktop application shortcuts
│
├── packaging/                  # PyInstaller build recipes & scripts
│   ├── AeroAuto_GUI.spec       # Directory-mode PyInstaller specification
│   ├── AeroAuto_GUI_Standalone.spec # One-file PyInstaller specification
│   ├── create_standalone.bat   # Windows build script for portable exe
│   └── create_standalone.sh    # Linux build script
│
├── scripts/                    # Auxiliary CAD generators, solvers & tools
│   ├── benchmark_and_optimize_all_wings_3d.py # 3D wing suite optimizer
│   ├── build_and_solve_evo1_fluent.py         # ANSYS Fluent automated solver
│   ├── freecad_bodywork_orchestrator.py       # Full-vehicle bodywork generator
│   ├── render_visualizations.py               # Technical graphics renderer
│   └── run_pipeline_and_report.py             # End-to-end benchmark pipeline
│
└── tests/                      # Automated test suite
    ├── test_engine.py          # Core math and CSV regression tests
    ├── test_report.py          # Report compiler tests
    ├── test_cad_integrity.py   # STL / STEP geometry verification
    └── test_all_46_zero_clash.py # Chassis standoff interference checks
```

---

## Quick Start

### 1. Requirements

- **Python**: Version 3.10 or higher.
- **Java**: JRE or JDK 8+ is required to execute JavaFoil.
  - Linux: `sudo apt install default-jre` (or your distribution's JRE package)
  - Windows: Download the free installer from [Adoptium Temurin](https://adoptium.net).

### 2. Installation

Clone this repository and install Python dependencies:

```bash
git clone https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION.git
cd ENPRT_2D_JAVAFOIL_AUTOMATION
pip install -r requirements.txt
```

### 3. Launching the GUI

- **Windows**:
  - Double-click **`START_AERO_AUTO.bat`** in the repository root to launch the main application.
  - Or double-click **`START_3D_WING_OPTIMIZER.bat`** to run the 3D finite wing optimizer.
  - Command line alternative:
    ```cmd
    python launcher.py ui
    ```

- **Linux**:
  ```bash
  ./launchers/run_ui.sh
  ```
  *(or `python launcher.py ui`)*

---

## Headless & Command-Line Interface

`launcher.py` provides cross-platform command line access for headless servers and HPC clusters:

```bash
# Launch interactive graphical interface
python launcher.py ui

# Launch 3D multi-element wing suite & optimizer
python launcher.py wings-suite

# Launch unattended exploration campaign
python launcher.py campaign --flow both --height 100,300 --hours 12 --yes

# Generate HTML analysis report from a completed campaign
python launcher.py report ~/aero_campaign/

# Compute downforce and drag trade-off targets
python launcher.py targets ~/aero_campaign/results.csv

# Render potential flowfield contours
python launcher.py field --main s1223 --flaps e423
```

---

## Building Standalone Executables

To package standalone executables without requiring a Python runtime on target machines:

```bash
# On Windows (builds portable single-file executable using packaging recipe):
packaging\create_standalone.bat

# On Linux:
./packaging/create_standalone.sh
```

This creates:
- `dist/aero_ui_standalone.exe` (portable single-file Windows executable)
- `dist/aero_auto_windows_standalone_1.1.zip` (portable Windows standalone package)
- `dist/aero_auto_windows_app_1.1.zip` (standalone Windows directory package)
- `dist/aero_auto_linux_app_1.1.tar.gz` (standalone Linux app bundle)
- `dist/aero_auto_windows_1.1.zip` (release package with bundled standalone exe & scripts)

---

## Documentation

Full documentation is included in the [`docs/`](docs/) directory and accessible from the GUI Help menu:
- [**User Manual (PDF)**](docs/USER_MANUAL.pdf): Step-by-step tutorial, tab-by-tab walkthrough, and workflows.
- [**Technical Guide (PDF)**](docs/TECHNICAL_GUIDE.pdf): Mathematical background, coordinate transformations, regulatory checks, and scoring formulas.
- [**FSAE Optimization Guide (PDF)**](docs/FSAE_OPTIMIZATION_GUIDE.pdf): Formula Student wing optimization framework, A.M.O. Smith theory, 2D to 3D CAD/CFD workflows, and design playbook. Also available as [fsea.pdf](docs/fsea.pdf).

---

## Authors & Acknowledgments

- **ENPRT Motorsports / Formula Student Team**
- Aerodynamic Solver: **JavaFoil** by Martin Hepperle
