# ENPRT 2D JavaFoil Automation & Multi-Element Aerodynamic Suite (`aero_auto`)

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Java Requirement](https://img.shields.io/badge/java-JRE%208%2B-orange)](https://adoptium.net/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-lightgrey)](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION)
[![Ruleset](https://img.shields.io/badge/regulations-FSUK%202026%20%2F%20FSG%20v1.1-green)](https://www.imeche.org/)

An automated multi-element aerodynamic optimization and campaign toolchain built on JavaFoil. Engineered for high-downforce motorsports and Formula Student (FSAE / FSG / FSUK) aerodynamics teams.

---

## Windows Standalone Executable (Ready to Run - No Python Required)

For Windows users who want to run Aero Auto immediately without installing Python or setting up an environment:

- [**Download aero_ui_standalone.exe (v1.1)**](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/download/v1.1/aero_ui_standalone.exe)
  *Single-file portable executable (~85 MB). Download and double-click to launch.*
- [**Download aero_auto_windows_standalone_1.1.zip**](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/download/v1.1/aero_auto_windows_standalone_1.1.zip)
  *Portable zip archive containing the standalone executable, official manuals, airfoils library, and batch launchers.*
- [**Download aero_auto_windows_app_1.1.zip**](https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/download/v1.1/aero_auto_windows_app_1.1.zip)
  *Full pre-extracted application folder bundle with START_AERO_AUTO.bat.*

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

- **CAD Model Export**:
  Direct 2D CAD export of multi-element configurations into **DXF (AutoCAD)** and **SVG** vector formats for import into CAD software (Fusion 360, SolidWorks, CATIA, Onshape).

- **Formula Student Regulatory Compliance**:
  Built-in physical envelope verification against FSUK 2026 / FSG rules:
  - Minimum ground clearance ($T2.3.2 \ge 35\text{ mm}$)
  - Front wing maximum stack height and length ($T8.2.1b \le 250\text{ mm}$, $T8.2.3b \le 600\text{ mm}$)
  - Rear wing maximum stack length and total height ($T8.2.3a \le 250\text{ mm}$, $T8.2.1c \le 1100\text{ mm}$)

---

## Project Structure

```text
├── aero_auto.py            # Core simulation engine, JavaFoil bridge & campaign planner
├── aero_ui.py              # 7-tab Tkinter/ttk desktop GUI application
├── aero_targets.py         # Downforce/Drag target analysis and downforce vs drag trade-offs
├── aero_report.py          # HTML and PDF report generator
├── flowfield.py            # Streamline and velocity vector potential flow solver
├── render_field.py         # Flowfield rendering and contour map visualization
├── launcher.py             # Cross-platform CLI unified entrypoint
├── _sim_worker.py          # Multi-process simulation worker execution helper
├── run_sim_terminal.py     # Terminal-mode standalone simulation runner
├── make_icon.py            # Application icon generator
├── build_dist.py           # Packaging script for distributable kits and standalone bundles
├── START_AERO_AUTO.bat     # Windows 1-click launcher (runs standalone exe or python)
├── run_ui.sh               # Linux launch script
├── run_ui.bat              # Windows launch script
├── requirements.txt        # Python dependency manifest
├── pyproject.toml          # PEP 518/621 project configuration
├── README_WINDOWS.txt      # Quick-start instructions for Windows users
├── assets/
│   ├── airfoils/           # Bundled baseline airfoil profiles (.dat)
│   ├── JavaFoil/           # JavaFoil simulation engine jars (javafoil.jar, mhclasses.jar)
│   └── icon.ico, icon.png  # Branding and interface icons
└── docs/
    ├── USER_MANUAL.pdf              # Complete end-user guide and workflow documentation
    ├── TECHNICAL_GUIDE.pdf          # Mathematical models, algorithms, and regulatory rules guide
    ├── FSAE_OPTIMIZATION_GUIDE.pdf  # FSAE multi-element wing theoretical manual & operational guide (fsea.pdf)
    ├── manual.md                    # Source documentation text
    └── make_pdf.py                  # ReportLab PDF documentation builder
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

- **Linux**:
  ```bash
  ./run_ui.sh
  ```
  *(or `python launcher.py ui`)*

- **Windows**:
  Double-click **`START_AERO_AUTO.bat`** (or `run_ui.bat`):
  ```cmd
  python launcher.py ui
  ```

---

## Headless & Command-Line Interface

`launcher.py` provides cross-platform command line access for headless servers and HPC clusters:

```bash
# Launch interactive graphical interface
python launcher.py ui

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

To build standalone Windows or Linux applications using PyInstaller:

```bash
# Assemble standalone binaries and distribution archives:
python build_dist.py
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
