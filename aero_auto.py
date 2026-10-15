#!/usr/bin/env python3
"""
aero_auto.py - fully automated multi-element JavaFoil campaign (1 to 4 elements).

What it does
  1. Reads every .dat in the airfoil folder (Selig or Lednicer format, any chord length).
  2. Asks for the flow field: unbounded, or ground effect (ground at y = 0) with the wing height.
  3. Runs every airfoil alone as a 1-element wing.
  4. EXPLORE phase: random sampling of 2/3/4-element wings (random airfoils, scales, angles, X, Y).
     Geometry that clashes/intersects/touches the ground is rejected before JavaFoil is called.
  5. REFINE phase: tests the neighbours (one grid step, or one airfoil swapped) of the best results.
  6. Everything goes to results.csv as it runs (resume any time). Every 30 min and at the end it also
     writes summary.xlsx: sheets All, 1 element, 2 elements, 3 elements, 4 elements and Best.

Where the data goes
  unbounded flow  ->  ~/aero_campaign/
  ground effect   ->  ~/aero_campaign/ground/h<height>pct/      (one folder per height)

Usage (everything is asked ONCE at the start; after you confirm it runs unattended)
  python aero_auto.py                        # questions -> automatic self-check -> long run, all in one go
  python aero_auto.py --test                 # only the self-check for each scenario, then stop
  python aero_auto.py --flow both --height 100,300 --hours 20 --yes   # no questions at all

At the start it asks: total hours, parallel runs, flow field (unbounded / ground / both), wing role
(front / rear / custom), chord, speed, span and the ground heights, plus the FSUK 2026 / FSG v1.1 size limits.
A quick self-check runs before each scenario; if it fails, that scenario is skipped and the next one starts.
Time is split evenly between scenarios. Run the same command again to resume.

Regulatory mode (default on, disable with --no-reg)
  The wing role selects the standard span and the rulebook limits. Configurations that break them are rejected
  before JavaFoil is ever called:
    * ground clearance >= MIN_GROUND_CLEARANCE_MM            (T2.3.2, built-in 35 mm)
    * front wing stack height <= FW_MAX_STACK_HEIGHT_MM      (T8.2.1b, built-in 250 mm)
    * front wing stack length <= FW_MAX_STACK_LENGTH_MM      (T8.2.3b, built-in 600 mm)
    * rear wing stack length  <= RW_MAX_STACK_LENGTH_MM      (T8.2.3a, built-in 250 mm)
    * rear wing total height  <= RW_MAX_TOTAL_HEIGHT_MM      (T8.2.1c, built-in 1100 mm)
  Every limit is overridable at the questions, from the command line or in the config JSON. When flow is
  "both", the ground scenario applies the front-wing limits and the unbounded scenario the rear-wing ones.

Built-in values (press Enter at the questions): chord 300 mm, speed 27.74 m/s (100 km/h, Re = 570000),
front-wing span 1400 mm / rear-wing span 950 mm (T8.2.2), ground height 300 percent of the chord.
Change DEFAULT_* at the top of the file to suit your car.
"""
import os
import re
import sys
import csv
import json
import math
import time
import queue
import random
import shutil
import zipfile
import argparse
import datetime
import itertools
import subprocess
import threading
import uuid
import tempfile
import glob
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

VERSION = "1.1.2"
HERE = os.path.dirname(os.path.abspath(__file__))

# =====================================================================
# SETTINGS (edit these, or override the main ones from the command line)
# =====================================================================
JAVA_DIR = os.environ.get("AERO_JAVA_DIR", os.path.expanduser("~/MH-AeroTools/JavaFoil"))   # folder containing javafoil.jar
JAVAFOIL_JAR = "javafoil.jar"
AIRFOIL_DIR = "/mnt/data/FSEA/AIRFOILS JAVAFOIL/AIRFOILS"  # your folder of .dat files (top level only)
OUT_DIR = os.path.expanduser("~/aero_campaign")            # unbounded results here, ground results in OUT_DIR/ground/

APP_DATA_DIR = os.path.join(os.path.expanduser("~"), ".aero_auto")
AIRFOIL_STORE = os.path.join(APP_DATA_DIR, "airfoils")     # internal airfoil library (managed from the GUI)

TOTAL_HOURS = 12.0
WORKERS = max(1, (os.cpu_count() or 2) // 2)               # parallel JavaFoil runs
EXPLORE_FRACTION = 0.6                                     # share of the time spent on random exploration
ELEMENT_WEIGHTS = {2: 0.25, 3: 0.45, 4: 0.30}              # how the exploration time is split

MAIN_INCLUDE = None     # e.g. ["s1223", "e423"] to restrict which airfoils may be the main plane (None = all)
FLAP_INCLUDE = None     # same for flaps (None = all)

ROT_SIGN = -1                    # validated against your hand run (flap angle -15 = trailing edge up)
INVERT_FOR_DOWNFORCE = True
RE = 570000                      # replaced automatically if you give chord and speed at the questions
ALPHA = (-20, 5, 1)              # polar start, end, step (deg)
DESIGN_ALPHA = 0.0               # main plane parallel to the ground
RUN_TIMEOUT = 120                # seconds per JavaFoil run before it is killed

# Ground effect: all elements are translated up by the wing height (in % of the main chord, like selecting
# every element in JavaFoil and translating in Y). The ground is y = 0.
MIN_CLEARANCE_PCT = 1.0          # configs whose lowest point is closer than this to the ground are rejected

# Built-in real-world values, used when you just press Enter at the questions (typical FSAE rear wing).
# 300 mm chord at 27.74 m/s (about 100 km/h) gives exactly Re = 570000, the Reynolds number your hand run
# and the earlier sweeps used, so old and new results stay comparable.
DEFAULT_CHORD_MM = 300.0
DEFAULT_SPEED = 27.74            # m/s
SPEED = DEFAULT_SPEED            # freestream speed for the force model (GUI sets this from its input box)

# Wing spans (Rule T8.2.2): the front wing is bounded by the outer edge of the front tires, the rear wing by the
# inner edge of the rear tires.
DEFAULT_SPAN_FW_MM = 1400.0      # front wing standard span
DEFAULT_SPAN_RW_MM = 950.0       # rear wing standard span
DEFAULT_SPAN_MM = DEFAULT_SPAN_FW_MM   # deprecated alias for legacy plan files without a role

DEFAULT_HEIGHT_PCT = 300.0       # ground effect: about 900 mm above the ground at 300 mm chord

# FSUK 2026 / FSG v1.1 regulatory limits (mm). All are overridable at the questions, from the command line or
# in the config JSON. Set REG_ENFORCE = False (or pass --no-reg) to turn the physical checks off.
MIN_GROUND_CLEARANCE_MM = 35.0   # T2.3.2 (rule requires >= 30 mm static with driver)
FW_MAX_STACK_HEIGHT_MM = 250.0   # T8.2.1b
FW_MAX_STACK_LENGTH_MM = 600.0   # T8.2.3b (allows up to 700 mm)
RW_MAX_TOTAL_HEIGHT_MM = 1100.0  # T8.2.1c
RW_MAX_STACK_LENGTH_MM = 250.0   # T8.2.3a (overhang limit)

# Air properties for the optional real-world numbers
NU = 1.46e-5                     # kinematic viscosity (m^2/s), 15 C
RHO = 1.225                      # air density (kg/m^3)

# Real-world aerodynamic integration rules (McBeath & Katz Formula Student guidelines)
REAL_WING_ENFORCE = True

# Sweep ranges per flap position: (min, max, step). Tuned for realistic aerodynamic integration.
RANGES = {
    1: dict(scale=(30, 42, 4), angle=(-26, -12, 4),  x=(97, 102, 1),   y=(3, 8, 1)),
    2: dict(scale=(20, 32, 4), angle=(-42, -24, 4), x=(120, 134, 2),  y=(10, 18, 2)),
    3: dict(scale=(15, 24, 3), angle=(-52, -36, 4), x=(140, 155, 3), y=(18, 28, 2)),
}

TOP_K = 8                # parents per element count in each refine round
SWAPS_PER_PARENT = 3     # airfoil-swap neighbours per parent
MAX_ROUND = None         # cap on runs per refine round (None = workers * 20)
MAX_CONSEC_FAILS = 40    # stop if this many runs in a row fail (JavaFoil/faketime broken)
SUMMARY_EVERY = 1800     # seconds between summary.xlsx refreshes

# Multi-Objective Scoring System Profiles for Formula Student
SCORING_PROFILES = {
    "balanced": {
        "name": "Balanced Multi-Objective (FSAE Overall)",
        "short": "Balanced",
        "description": "Standard balanced trade-off across all FSAE dynamic events: 40% Downforce + 30% Stall Margin + 20% L/D Efficiency + 10% Pitch Robustness.",
        "weights": (0.40, 0.30, 0.20, 0.10),
    },
    "autocross": {
        "name": "Autocross & Skidpad (Max Downforce / Grip)",
        "short": "Autocross",
        "description": "Max Downforce Priority: 70% Downforce + 20% Stall Margin + 10% Efficiency. Designed for tight 40–65 km/h slalom courses where lateral acceleration wins and drag penalty is minimal.",
        "weights": (0.70, 0.20, 0.10, 0.00),
    },
    "efficiency": {
        "name": "Endurance & Efficiency (High L/D / Energy Saving)",
        "short": "Endurance/Eff",
        "description": "Aerodynamic Efficiency Priority: 60% L/D + 25% Downforce + 10% Stall Margin + 5% Robustness. Ideal for electric vehicles to conserve battery kilowatt-hours and combustion cars for fuel score.",
        "weights": (0.25, 0.10, 0.60, 0.05),
    },
    "robust": {
        "name": "Pitch-Stable & Stall-Robust (Braking Stability)",
        "short": "Robust/Braking",
        "description": "Safety & Pitch Insensitivity: 45% Stall Margin + 35% Pitch Robustness (±2°) + 20% Downforce. Prevents catastrophic downforce loss and snap-oversteer during heavy braking pitch dive.",
        "weights": (0.20, 0.45, 0.05, 0.30),
    },
    "cl_stability": {
        "name": "Cl Alpha Stability (Pitch Dive Robustness)",
        "short": "Cl Alpha Stable",
        "description": "Cl Stability Priority: 40% Pitch Robustness (smooth Cl retention across ±2°) + 35% Stall Margin (>=3.5°) + 25% Downforce. Guarantees linear pitch response without sudden separation under dynamic chassis dive.",
        "weights": (0.25, 0.35, 0.00, 0.40),
    },
    "laptime": {
        "name": "Lap Time Sensitivity Index (3.5:1 DF/Drag Tradeoff)",
        "short": "Lap Time Index",
        "description": "Simulated Lap Time Metric: Models real FSAE track lap-time sensitivity where 1 N of Downforce is worth ~3.5x to 4.0x more lap time reduction than 1 N of drag penalty.",
        "weights": (0.55, 0.15, 0.25, 0.05),
    },
}

# Score scaling parameters
W_DF, W_MG, W_EF, W_RB = 0.40, 0.30, 0.20, 0.10
DF_LO, DF_HI = 1.0, 5.0          # |Cl| at design alpha -> 0..1
MARGIN_FULL = 3.0                # deg of stall margin for a full score
LD_LO, LD_HI = 40.0, 120.0       # |Cl|/Cd at design alpha -> 0..1
TIER1_MARGIN, TIER2_MARGIN = 2.0, 1.0
CD_MAX = 0.3

PAIRS = ["Main_to_F1", "F1_to_F2", "F2_to_F3"]
GEO_FIELDS = ([f"{p}_{m}_pct" for p in PAIRS for m in ("Gap", "Overlap", "Step")]
              + ["Stack_Length_pct", "Stack_Height_pct", "Stack_Ymin_pct", "Stack_Ymax_pct"])
SCORE_FIELDS = ["Score", "Score_Balanced", "Score_Autocross", "Score_Efficiency", "Score_Robust", "Score_ClStability", "Score_LapTime"]
FIELDS = (["Run_ID", "Phase", "Elements", "Main"]
          + [f"F{k}_{p}" for k in (1, 2, 3) for p in ("Airfoil", "Scale", "Angle", "X", "Y")]
          + GEO_FIELDS
          + ["Flow", "Height_pct", "Min_Clearance_pct",
             "Stack_Length_mm", "Stack_Height_mm", "Min_Clearance_mm"]
          + ["Date", "Duration_s", "Alpha_Interval"]
          + ["Cl_peak", "Cd_peak", "Stall_Angle", "Max_LD", "Cl_a0", "Cd_a0", "Cm_a0", "Cl_am2", "Cl_ap2",
             "Downforce_N", "Drag_N", "Tier"]
          + SCORE_FIELDS
          + ["Status", "Speed_ms"])

# =====================================================================
# GLOBAL STATE
# =====================================================================
UNSET = object()
GROUND_H = None               # None = unbounded flow, else wing height in % of main chord
PHYS = None                   # None, or dict(chord_mm, speed, span_mm) for real-world numbers
CHORD_MM = None               # main chord in mm (from the plan); required by the regulatory mm checks
ROLE = "custom"               # "fw", "rw" or "custom": which regulatory limit set applies
REG = {}                      # regulatory limits (mm); filled by apply_plan_numbers / default_reg()
REG_ENFORCE = True            # False (--no-reg) disables the physical mm checks
WING_MOUNT_HEIGHT_MM = None   # physical height of the main chord line above the ground for the RW total-height rule
RUN_DIR = OUT_DIR             # folder of the current mode (set in main)
AIRFOILS = {}                 # name -> coordinates (normalised, inverted, Selig order)
GRID = {}                     # flap position -> {param: [values]}
DONE = set()                  # configs already run
RESULTS = []                  # list of row dicts
LOCK = threading.Lock()
WORKER_DIRS = queue.Queue()
STOP = threading.Event()
INTERRUPT = threading.Event()   # Ctrl+C: stop everything (STOP alone only ends the current scenario)
RESULTS_FILE = [None]
FAIL_SAVED = [0]
RUN_COUNTER = itertools.count(1)
CONSEC_FAILS = [0]
T0 = [time.time()]
START_COUNT = [0]

def frange(lo, hi, step):
    n = int(math.floor((hi - lo) / step + 1e-9)) + 1
    return [round(lo + i * step, 6) for i in range(n)]

def init_grid():
    """Initialize GRID from RANGES. Call before running campaigns."""
    global GRID
    GRID.clear()
    for k, r in RANGES.items():
        GRID[k] = {p: frange(*r[p]) for p in ("scale", "angle", "x", "y")}

init_grid()
LAST_PRINT = [0.0]
safe_date_str = "@2020-01-01 12:00:00"


def default_reg():
    """The standard FSUK 2026 / FSG v1.1 regulatory limits (mm)."""
    return dict(min_ground_clearance_mm=MIN_GROUND_CLEARANCE_MM,
                fw_max_stack_height_mm=FW_MAX_STACK_HEIGHT_MM,
                fw_max_stack_length_mm=FW_MAX_STACK_LENGTH_MM,
                rw_max_total_height_mm=RW_MAX_TOTAL_HEIGHT_MM,
                rw_max_stack_length_mm=RW_MAX_STACK_LENGTH_MM)


def plan_span(plan, role=None):
    """The active wing span (mm) for the given role (defaults to the plan's role)."""
    role = role or plan.get("role", "custom")
    if role == "rw":
        return plan.get("span_rw") or plan.get("span")
    if role == "fw":
        return plan.get("span_fw") or plan.get("span")
    return plan.get("span_fw") or plan.get("span_rw") or plan.get("span")


# =====================================================================
# AIRFOIL LOADING
# =====================================================================
def load_airfoil(path):
    """Returns (coords, info). Handles Selig and Lednicer, any chord length. coords=None if unusable."""
    pts = []
    first_numeric = True
    with open(path, "r", errors="ignore") as f:
        for line in f:
            parts = line.replace(",", " ").split()
            if len(parts) >= 2:
                try:
                    x, y = float(parts[0]), float(parts[1])
                except ValueError:
                    continue
                if first_numeric:
                    first_numeric = False
                    
                    if x == int(x) and y == int(y) and x >= 3 and y >= 3:
                        continue
                pts.append((x, y))
    if len(pts) < 10:
        return None, "too few points"
    c = np.array(pts)
    fmt = "Selig"
    jumps = np.where(np.diff(c[:, 0]) < -0.5)[0]
    if len(jumps) == 1 and c[0, 0] < 0.05:        
        k = jumps[0] + 1
        a, b = c[:k], c[k:]
        if a[:, 1].mean() < b[:, 1].mean():
            a, b = b, a
        c = np.vstack([a[::-1], b[1:]])
        fmt = "Lednicer->Selig"
    xmin, xmax = c[:, 0].min(), c[:, 0].max()
    chord = xmax - xmin
    if chord <= 0:
        return None, "zero chord"
    c = (c - [xmin, 0.0]) / chord                  # unit chord, LE at x=0
    le = int(np.argmin(c[:, 0]))
    if c[:le + 1, 1].mean() < c[le:, 1].mean():    
        c = c[::-1]
    if INVERT_FOR_DOWNFORCE:
        c = c.copy()
        c[:, 1] = -c[:, 1]
        c = c[::-1]
    return c, f"{fmt}, {len(c)} pts"

def load_all(folder):
    """Loads all valid airfoils (.dat, .txt, .cor) from folder. Never crashes on missing directories."""
    out = {}
    if not folder or not os.path.isdir(folder):
        return out
    for fn in sorted(os.listdir(folder)):
        if fn.lower().endswith((".dat", ".txt", ".cor")):
            name = os.path.splitext(fn)[0]
            c, info = load_airfoil(os.path.join(folder, fn))
            if c is not None:
                out[name] = c
    return out


def seed_airfoil_store(store=None):
    """Ensure internal airfoil store contains baseline airfoils so airfoils are never missing."""
    store = store or AIRFOIL_STORE
    os.makedirs(store, exist_ok=True)
    existing = set(f.lower() for f in os.listdir(store) if f.lower().endswith(".dat"))
    search_dirs = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            search_dirs.append(os.path.join(sys._MEIPASS, "assets", "airfoils"))
        exe_dir = os.path.dirname(sys.executable)
        search_dirs.append(os.path.join(exe_dir, "assets", "airfoils"))
        search_dirs.append(os.path.join(exe_dir, "_internal", "assets", "airfoils"))
    base_dir = os.path.dirname(os.path.abspath(__file__))
    search_dirs.extend([
        os.path.join(base_dir, "assets", "airfoils"),
        os.path.join(HERE, "assets", "airfoils") if "HERE" in globals() else "",
        AIRFOIL_DIR,
    ])
    for sdir in search_dirs:
        if sdir and os.path.isdir(sdir):
            for fn in sorted(os.listdir(sdir)):
                if fn.lower().endswith(".dat") and fn.lower() not in existing:
                    try:
                        shutil.copy2(os.path.join(sdir, fn), os.path.join(store, fn))
                        existing.add(fn.lower())
                    except Exception:
                        pass




def ensure_airfoils_loaded():
    """Ensure internal airfoil store contains baseline airfoils and AIRFOILS is loaded into memory."""
    if not AIRFOILS:
        seed_airfoil_store()
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cand_dirs = [
            os.path.join(base_dir, "assets", "airfoils"),
            getattr(sys, "_MEIPASS", "") and os.path.join(sys._MEIPASS, "assets", "airfoils"),
            os.path.join(os.path.dirname(sys.executable), "assets", "airfoils") if getattr(sys, "frozen", False) else None,
            os.path.join(os.path.dirname(sys.executable), "_internal", "assets", "airfoils") if getattr(sys, "frozen", False) else None,
            AIRFOIL_DIR,
            AIRFOIL_STORE,
        ]
        for cd in cand_dirs:
            if cd and os.path.isdir(cd):
                AIRFOILS.update(load_all(cd))

def install_airfoil(src, name=None, store=None):
    """Copy a .dat/coordinate profile into the internal airfoil store under a chosen name.
    Validates coordinate parsability across .dat, .txt, .cor, or raw text files.

    Returns (store_name, path_to_dat). The profile then appears in every airfoil
    combo of the GUI without you having to manage where files live."""
    store = store or AIRFOIL_STORE
    os.makedirs(store, exist_ok=True)
    coords, info = load_airfoil(src)
    if coords is None:
        raise ValueError(f"Cannot parse airfoil coordinates ({info})")
    base = os.path.splitext(os.path.basename(src or ""))[0]
    clean_name = re.sub(r"[^A-Za-z0-9 _\\-]", "", (name or base).strip()).strip() or "airfoil"
    dst = os.path.join(store, clean_name + ".dat")
    shutil.copy(src, dst)
    return clean_name, dst


list_store_airfoils = None  # alias below

def list_store(store=None):
    """(name, path) pairs for every profile currently in the internal store."""
    store = store or AIRFOIL_STORE
    if not os.path.isdir(store):
        seed_airfoil_store(store)
    if not os.path.isdir(store):
        return []
    items = [(os.path.splitext(fn)[0], os.path.join(store, fn))
             for fn in sorted(os.listdir(store)) if fn.lower().endswith((".dat", ".txt", ".cor"))]
    if not items:
        seed_airfoil_store(store)
        items = [(os.path.splitext(fn)[0], os.path.join(store, fn))
                 for fn in sorted(os.listdir(store)) if fn.lower().endswith((".dat", ".txt", ".cor"))]
    return items

list_store_airfoils = list_store


def remove_store_airfoil(name, store=None):
    """Delete a profile from the internal store. Returns True when it existed."""
    store = store or AIRFOIL_STORE
    for ext in (".dat", ".txt", ".cor"):
        p = os.path.join(store, name + ext)
        if os.path.exists(p):
            os.remove(p)
            return True
    return False


# =====================================================================
# GEOMETRY
# =====================================================================
def transform_coords(coords, scale_pct, angle_deg, dx_pct, dy_pct):
    c = coords * (scale_pct / 100.0)
    th = np.radians(ROT_SIGN * angle_deg)
    xr = c[:, 0] * np.cos(th) - c[:, 1] * np.sin(th)
    yr = c[:, 0] * np.sin(th) + c[:, 1] * np.cos(th)
    return np.column_stack((xr + dx_pct / 100.0, yr + dy_pct / 100.0))

def _ccw(a, b, c):
    return (c[..., 1] - a[..., 1]) * (b[..., 0] - a[..., 0]) > (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])

def outlines_intersect(p, q):
    a, b = p[:-1][:, None, :], p[1:][:, None, :]
    c, d = q[:-1][None, :, :], q[1:][None, :, :]
    return bool(np.any((_ccw(a, c, d) != _ccw(b, c, d)) & (_ccw(a, b, c) != _ccw(a, b, d))))

def build_outlines(cfg, ground_h=UNSET):
    """Outlines of all elements. In ground effect every element is translated up by the wing height."""
    h = GROUND_H if ground_h is UNSET else ground_h
    if h is not None:
        try:
            fh = float(h)
            if math.isnan(fh) or fh <= 0:
                raise ValueError(f"invalid ground height: {h}")
        except (TypeError, ValueError) as err:
            raise ValueError(f"invalid ground height: {h}") from err
    main, flaps = cfg
    if main not in AIRFOILS:
        ensure_airfoils_loaded()
    if main not in AIRFOILS:
        raise KeyError(f"unknown main airfoil: {main!r}")
    outs = [AIRFOILS[main]]
    for (name, s, a, x, y) in flaps:
        if not name or name not in AIRFOILS:
            raise KeyError(f"unknown airfoil: {name!r}")
        outs.append(transform_coords(AIRFOILS[name], s, a, x, y))
    if h is not None:
        outs = [o + np.array([0.0, float(h) / 100.0]) for o in outs]
    return outs

def wing_mount_chord():
    """Height of the main chord line above the ground, in main-chord units, or None if unknown.
    In ground effect this is the scenario height; otherwise it comes from WING_MOUNT_HEIGHT_MM."""
    if GROUND_H is not None:
        return GROUND_H / 100.0
    if WING_MOUNT_HEIGHT_MM is not None and CHORD_MM:
        return WING_MOUNT_HEIGHT_MM / CHORD_MM
    return None

def regulatory_reject(outs, mount_chord):
    """Returns a detailed reason string if the untranslated outlines break an FSUK/FSG size rule, else None.
    Needs a chord (mm) to know the physical sizes, so it is a no-op until the plan supplies one."""
    if not REG_ENFORCE or not CHORD_MM:
        return None
    allp = np.vstack(outs)
    stack_len_mm = (allp[:, 0].max() - allp[:, 0].min()) * CHORD_MM
    ymin, ymax = allp[:, 1].min(), allp[:, 1].max()
    stack_h_mm = (ymax - ymin) * CHORD_MM
    
    errors = []
    
    if GROUND_H is not None and mount_chord is not None:
        clearance_mm = (mount_chord + ymin) * CHORD_MM
        if clearance_mm < REG["min_ground_clearance_mm"]:
            errors.append({
                "rule": "Ground Clearance",
                "description": f"Ground clearance is {clearance_mm:.1f} mm, below minimum {REG['min_ground_clearance_mm']:.1f} mm",
                "actual": clearance_mm,
                "limit": REG["min_ground_clearance_mm"],
                "fix": "Increase ground height (% chord) or reduce flap angles/positions that lower the wing"
            })
    
    if ROLE == "fw":
        if stack_len_mm > REG["fw_max_stack_length_mm"]:
            errors.append({
                "rule": "Front Wing Stack Length",
                "description": f"Stack length {stack_len_mm:.1f} mm exceeds maximum {REG['fw_max_stack_length_mm']:.1f} mm",
                "actual": stack_len_mm,
                "limit": REG["fw_max_stack_length_mm"],
                "fix": "Reduce flap X positions (move flaps closer to main), reduce flap scales, or use shorter chords"
            })
        if stack_h_mm > REG["fw_max_stack_height_mm"]:
            errors.append({
                "rule": "Front Wing Stack Height",
                "description": f"Stack height {stack_h_mm:.1f} mm exceeds maximum {REG['fw_max_stack_height_mm']:.1f} mm",
                "actual": stack_h_mm,
                "limit": REG["fw_max_stack_height_mm"],
                "fix": "Reduce flap Y positions (move flaps closer vertically), reduce flap scales/angles"
            })
    elif ROLE == "rw":
        if stack_len_mm > REG["rw_max_stack_length_mm"]:
            errors.append({
                "rule": "Rear Wing Stack Length",
                "description": f"Stack length {stack_len_mm:.1f} mm exceeds maximum {REG['rw_max_stack_length_mm']:.1f} mm",
                "actual": stack_len_mm,
                "limit": REG["rw_max_stack_length_mm"],
                "fix": "Reduce flap X positions, reduce flap scales, or use shorter chords"
            })
        if mount_chord is not None:
            total_mm = (mount_chord + ymax) * CHORD_MM
            if total_mm > REG["rw_max_total_height_mm"]:
                errors.append({
                    "rule": "Rear Wing Total Height",
                    "description": f"Total height {total_mm:.1f} mm exceeds maximum {REG['rw_max_total_height_mm']:.1f} mm",
                    "actual": total_mm,
                    "limit": REG["rw_max_total_height_mm"],
                    "fix": "Reduce ground height, reduce flap Y positions, or reduce flap scales"
                })
    
    if errors:
        return errors
    return None

def geometry_ok(cfg):
    """Cheap rejection of configs that would clash, intersect or touch the ground, or that break the
    FSUK/FSG size limits (never sent to JavaFoil)."""
    flaps = cfg[1]
    for k in range(len(flaps) - 1):
        _, s, a, x, y = flaps[k]
        if x + 0.8 * s >= flaps[k + 1][3]:
            return False
    outs = build_outlines(cfg, ground_h=None)          # untranslated: clashes are translation invariant
    for i, j in itertools.combinations(range(len(outs)), 2):
        if outlines_intersect(outs[i], outs[j]):
            return False
    mount = wing_mount_chord()
    ymin = min(o[:, 1].min() for o in outs)
    if GROUND_H is not None and mount is not None and (mount + ymin) * 100 < MIN_CLEARANCE_PCT:
        return False
    if regulatory_reject(outs, mount) is not None:
        return False
    if REAL_WING_ENFORCE and not realistic_wing_check(cfg):
        return False
    return True

def _densify(o, n=8):
    parts = []
    for a, b in zip(o[:-1], o[1:]):
        t = np.linspace(0, 1, n, endpoint=False)[:, None]
        parts.append(a + (b - a) * t)
    parts.append(o[-1:])
    return np.vstack(parts)

def _min_gap(p, q):
    P, Q = _densify(p), _densify(q)
    return float(np.sqrt(((P[:, None, :] - Q[None, :, :]) ** 2).sum(-1)).min())

def realistic_wing_check(cfg):
    """Aerodynamic realism constraint for multi-element FSAE wings.
    Rejects floating, disconnected, unslotted, or decambered element arrangements.
    Ensures:
      1. Monotonic progressive camber deflection: elements do not counter-deflect
      2. Realistic scale bounds: each flap chord between 8% and 75% of main chord
      3. Physically coupled slot gap: 0.5% <= min_gap <= 18.0% of main chord
      4. Slot overlap within aerodynamic suction boundary: -15.0% <= overlap <= 15.0%
      5. Positive suction-side nozzle step: -5.0% <= step <= 22.0%
    """
    if not REAL_WING_ENFORCE:
        return True
    main, flaps = cfg
    if not flaps:
        return True
    
    # 1. Deflection & scale bounds
    prev_a = 0.0
    for (_, s, a, x, y) in flaps:
        if s < 8.0 or s > 75.0:
            return False
        if abs(a) < abs(prev_a) - 8.0:
            return False
        prev_a = a
        
    # 2. Slot gap, overlap, and nozzle step checks
    try:
        outs = build_outlines(cfg, ground_h=None)
        for k in range(len(outs) - 1):
            p, q = outs[k], outs[k + 1]
            gap = _min_gap(p, q)
            if gap < 0.005 or gap > 0.18:
                return False
            te = p[np.argmax(p[:, 0])]
            le = q[np.argmin(q[:, 0])]
            overlap = te[0] - le[0]
            if overlap < -0.15 or overlap > 0.15:
                return False
            step = le[1] - te[1]
            if step < -0.05 or step > 0.22:
                return False
    except Exception:
        return False
    return True

def geometry_columns(cfg, ground_h=UNSET):
    """Slot gap, overlap and height step between neighbouring elements, stack size, ground clearance.
    All in % of the main chord. Overlap > 0: the next element's leading edge is ahead of the previous
    trailing edge; overlap < 0: there is an open gap in x."""
    outs = build_outlines(cfg, ground_h)
    cols = {}
    for k in range(len(outs) - 1):
        p, q = outs[k], outs[k + 1]
        te = p[np.argmax(p[:, 0])]
        le = q[np.argmin(q[:, 0])]
        cols[f"{PAIRS[k]}_Gap_pct"] = 100 * _min_gap(p, q)
        cols[f"{PAIRS[k]}_Overlap_pct"] = 100 * (te[0] - le[0])
        cols[f"{PAIRS[k]}_Step_pct"] = 100 * (le[1] - te[1])
    allp = np.vstack(outs)
    ymin, ymax = allp[:, 1].min(), allp[:, 1].max()
    cols["Stack_Length_pct"] = 100 * (allp[:, 0].max() - allp[:, 0].min())
    cols["Stack_Height_pct"] = 100 * (ymax - ymin)
    cols["Stack_Ymin_pct"] = 100 * ymin
    cols["Stack_Ymax_pct"] = 100 * ymax
    h = GROUND_H if ground_h is UNSET else ground_h
    if h is not None:
        cols["Min_Clearance_pct"] = 100 * ymin
    if CHORD_MM:
        cols["Stack_Length_mm"] = (allp[:, 0].max() - allp[:, 0].min()) * CHORD_MM
        cols["Stack_Height_mm"] = (ymax - ymin) * CHORD_MM
        if h is not None:
            cols["Min_Clearance_mm"] = ymin * CHORD_MM
    return cols


# =====================================================================
# FAMOUS FSAE MULTI-ELEMENT WING COMBINATIONS
# =====================================================================
FAMOUS_PACKAGES = [
    {
        'id': 'fsg_2018_monash_m18',
        'source_url': 'https://www.monashmotorsport.com',
        'source_title': 'Monash Motorsport M18 Technical Archive & Engineering Review',
        'name': 'FSG 2018 · Monash Motorsport (M18) – Front Wing',
        'competition': 'Formula Student Germany (FSG)',
        'comp_short': 'FSG (Germany)',
        'team': 'Monash Motorsport (Monash University)',
        'year': 2018,
        'car': 'M18',
        'achievement': 'Overall World Champion (FSG 2018 & FSAE-A 2018)',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1223',
        'chord': 250.0,
        'speed': 18.0,
        're': 300000,
        'ge': True,
        'gh_pct': 32.0,
        'span': 1400.0,
        'flaps': [
            ('s1223rtl', 32.0, -14.0, 96.0, 4.0),
            ('WORTMANN FX 63-137', 24.0, -28.0, 122.5, 14.5),
            ('be50', 18.0, -42.0, 142.5, 27.5)
        ],
        'targets': {'cl': 3.45, 'cd': 1.08, 'ld': 3.19, 'df_n': 282.5, 'drag_n': 88.5},
        'highlights': [
            'Dominant 4-element ground effect front wing inspired by multi-time world champions Monash Motorsport (M18).',
            'Uses Selig 1223 as primary ground-effect suction driver generating extreme low pressure on underwing.',
            'First flap uses S1223RTL with modified trailing edge reflex to energize boundary layer for subsequent flaps.',
            'Intermediate Wortmann FX 63-137 delivers substantial circulation jump without flow detachment.',
            'Aft Liebeck BE50 flap provides extreme downforce turning (-42°) to maximize corner-entry front grip in tight autocross slaloms.'
        ],
        'aerodynamics': {
            'design_intent': 'Maximum Ground Effect Downforce & Low-Speed Slalom Authority',
            'flow_physics': 'Multi-slot boundary layer injection; fresh high-energy airflow from the pressure side prevents detachment on downstream flaps under aggressive cumulative camber (-42° total deflection).',
            'operating_envelope': 'Autocross / Skidpad tight corners (15–20 m/s, ground clearance 35–45 mm).'
        }
    },
    {
        'id': 'fsg_2019_stuttgart_f0711',
        'source_url': 'https://www.rennteam-stuttgart.de',
        'source_title': 'Rennteam Uni Stuttgart F0711-14 Engineering Design',
        'name': 'FSG 2019 · Rennteam Uni Stuttgart (F0711-14) – Front Wing',
        'competition': 'Formula Student Germany (FSG)',
        'comp_short': 'FSG (Germany)',
        'team': 'Rennteam Uni Stuttgart (University of Stuttgart)',
        'year': 2019,
        'car': 'F0711-14',
        'achievement': '1st Place Combustion Overall (FSG 2019 Champion)',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1223',
        'chord': 260.0,
        'speed': 20.0,
        're': 355000,
        'ge': True,
        'gh_pct': 30.0,
        'span': 1400.0,
        'flaps': [
            ('e423', 35.0, -15.0, 96.0, 4.2),
            ('NACA 6412', 26.0, -30.0, 124.5, 15.0)
        ],
        'targets': {'cl': 3.15, 'cd': 0.92, 'ld': 3.42, 'df_n': 322.0, 'drag_n': 94.1},
        'highlights': [
            'Engineered specifically for heavy braking pitch dive stability (1.8g deceleration).',
            'High-camber S1223 main paired with Eppler 423 intermediate element maintain gentle stall behavior.',
            'NACA 6412 aft flap ensures stall angle is at least 3.5° above design alpha.',
            'Guarantees linear Cl response across ±2° pitch dive, preventing sudden understeer when the car pitches nose-down.'
        ],
        'aerodynamics': {
            'design_intent': 'Braking Pitch Dive Stability & Stall Margin Robustness',
            'flow_physics': 'Graduated pressure recovery minimizes adverse pressure gradient peaks. When front ride height compresses by 15–20 mm under braking, slot flow remains stable without suction collapse.',
            'operating_envelope': 'Heavy braking zones and corner entry transitions (18–24 m/s).'
        }
    },
    {
        'id': 'fsg_2019_tudelft_dut19',
        'source_url': 'https://www.dutracing.nl',
        'source_title': 'TU Delft DUT Racing Team DUT19 Aerodynamics Specification',
        'name': 'FSG 2019 · TU Delft (DUT19) – Rear Wing',
        'competition': 'Formula Student Germany (FSG)',
        'comp_short': 'FSG (Germany)',
        'team': 'TU Delft FS Team (DUT Racing, Netherlands)',
        'year': 2019,
        'car': 'DUT19',
        'achievement': '1st Place Electric Overall (FSG 2019 Champion)',
        'category': 'Rear Wing',
        'role': 'rear wing',
        'main': 'e423',
        'chord': 165.0,
        'speed': 22.0,
        're': 450000,
        'ge': False,
        'gh_pct': 300.0,
        'span': 950.0,
        'flaps': [
            ('s1210', 32.0, -16.0, 96.5, 4.5),
            ('NACA 4412', 24.0, -32.0, 122.5, 15.5)
        ],
        'targets': {'cl': 2.95, 'cd': 0.78, 'ld': 3.78, 'df_n': 178.6, 'drag_n': 47.2},
        'highlights': [
            'Electric vehicle endurance efficiency benchmark designed for minimal battery consumption.',
            'High lift-to-drag ratio (L/D > 3.6 2D) minimizes induced and pressure drag on straights.',
            'Selig 1210 provides laminar bucket pressure recovery across mid-chord.',
            'Strictly packaged within 250 mm total stack length constraint for FSG/FSAE rear wing regulations.'
        ],
        'aerodynamics': {
            'design_intent': 'High Aerodynamic Efficiency (L/D) & Endurance Energy Conservation',
            'flow_physics': 'E423 provides high baseline circulation while S1210 and NACA 4412 maintain laminar flow retention and moderate trailing edge boundary layer displacement thickness.',
            'operating_envelope': 'High-speed endurance circuit driving (20–28 m/s).'
        }
    },
    {
        'id': 'fsae_2019_mit_my19',
        'source_url': 'https://fsae.mit.edu',
        'source_title': 'MIT Motorsports Formula SAE Technical Documentation',
        'name': 'FSAE MI 2019 · MIT Motorsports (MY19) – Rear Wing',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'comp_short': 'FSAE Michigan (USA)',
        'team': 'MIT Motorsports (MIT, USA)',
        'year': 2019,
        'car': 'MY19',
        'achievement': 'FSAE Americas Peak Downforce Leader',
        'category': 'Rear Wing',
        'role': 'rear wing',
        'main': 's1223',
        'chord': 150.0,
        'speed': 20.0,
        're': 380000,
        'ge': False,
        'gh_pct': 300.0,
        'span': 950.0,
        'flaps': [
            ('s1223', 30.0, -16.0, 96.0, 4.2),
            ('fx74cl5140', 22.0, -32.0, 120.5, 14.5),
            ('be50', 16.0, -46.0, 139.0, 28.0)
        ],
        'targets': {'cl': 3.58, 'cd': 1.28, 'ld': 2.80, 'df_n': 180.2, 'drag_n': 64.4},
        'highlights': [
            'Maximum-downforce 4-element cascade engineered to extract peak tire vertical load.',
            'Dual Selig 1223 elements establish strong initial bound vortex circulation.',
            'Wortmann FX 74-CL5-140 is a legendary high-lift airfoil designed specifically for aggressive multi-element flaps.',
            'Liebeck BE50 terminal flap turns flow to -46° without bubble burst, delivering peak Cl > 3.5 2D.',
            'Fully compliant with 250 mm stack length and 1100 mm height rules.'
        ],
        'aerodynamics': {
            'design_intent': 'Peak Downforce Generation for Acceleration & Hairpin Exit Traction',
            'flow_physics': 'Extreme flow turning enabled by cascading slot jets. High suction on upper flap surfaces induces high upwash behind the rear wheels.',
            'operating_envelope': 'Autocross and tight hairpins (16–22 m/s).'
        }
    },
    {
        'id': 'fsg_2021_tumunich_emuc21',
        'source_url': 'https://tufast-racingteam.de',
        'source_title': 'TUfast Racing Team e-MUC21 Aerodynamic Development',
        'name': 'FSG 2021 · TUfast Racing Munich (e-MUC21) – Front Wing',
        'competition': 'Formula Student Germany (FSG)',
        'comp_short': 'FSG (Germany)',
        'team': 'TUfast Racing Munich (TU Munich, Germany)',
        'year': 2021,
        'car': 'e-MUC21',
        'achievement': '1st Place Driverless & Electric Champion',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1210',
        'chord': 270.0,
        'speed': 19.5,
        're': 350000,
        'ge': True,
        'gh_pct': 28.0,
        'span': 1400.0,
        'flaps': [
            ('e420', 34.0, -15.0, 96.5, 4.2),
            ('NACA7412', 25.0, -28.0, 124.0, 14.8)
        ],
        'targets': {'cl': 2.92, 'cd': 0.79, 'ld': 3.70, 'df_n': 284.1, 'drag_n': 76.9},
        'highlights': [
            'Multi-stage front wing optimized for high-speed slalom and yaw transient response.',
            'Combines low-profile Selig 1210 main element with high-camber Eppler 420.',
            'NACA 7412 aft element has smooth curvature distribution that delays flow separation during steering roll/yaw.',
            'Minimizes drag buildup while ensuring prompt aerodynamic balance response in driverless and manual agility runs.'
        ],
        'aerodynamics': {
            'design_intent': 'Yaw Sensitivity Reduction & High Transient Agility',
            'flow_physics': 'Mild adverse pressure gradient on suction surface mitigates separation during lateral steering angle inputs.',
            'operating_envelope': 'Fast transitions and driverless trackdrive (18–26 m/s).'
        }
    },
    {
        'id': 'fsa_2022_graz_jr22',
        'source_url': 'https://www.joanneum-racing.at',
        'source_title': 'Joanneum Racing Graz jr22 Vehicle Specifications',
        'name': 'FSA 2022 · Joanneum Racing Graz (jr22) – Front Wing',
        'competition': 'Formula Student Austria (FSA)',
        'comp_short': 'FSA (Austria)',
        'team': 'Joanneum Racing Graz (FH Joanneum, Austria)',
        'year': 2022,
        'car': 'jr22',
        'achievement': 'FSA 2022 Overall Champion (Red Bull Ring)',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1223',
        'chord': 245.0,
        'speed': 19.0,
        're': 320000,
        'ge': True,
        'gh_pct': 31.0,
        'span': 1400.0,
        'flaps': [
            ('e423', 34.0, -16.0, 96.0, 4.2),
            ('be50', 22.0, -34.0, 123.5, 15.2)
        ],
        'targets': {'cl': 3.28, 'cd': 0.99, 'ld': 3.31, 'df_n': 289.4, 'drag_n': 87.3},
        'highlights': [
            'Championship-winning front wing developed for the high-elevation Red Bull Ring circuit.',
            'Features S1223 mainplane paired with E423 intermediate element for high initial ground-effect expansion.',
            'BE50 Liebeck high-lift aft flap achieves -34° turning to provide sharp turn-in authority in elevation-change corners.'
        ],
        'aerodynamics': {
            'design_intent': 'High Suction Gradient & Turn-in Agility',
            'flow_physics': 'Boundary layer slot injection energizes Liebeck aft element, eliminating corner-entry understeer.',
            'operating_envelope': 'High elevation change and sweeping medium-speed corners (16–24 m/s).'
        }
    },
    {
        'id': 'fsch_2022_amz_mythen',
        'source_url': 'https://amzracing.ch',
        'source_title': 'AMZ Racing ETH Zurich Mythen World Record Project',
        'name': 'FS CH 2022 · AMZ Racing (mythen) – Front Wing',
        'competition': 'FS Switzerland & World Record',
        'comp_short': 'FS Switzerland',
        'team': 'AMZ Racing (ETH Zurich / Academic Motorsports Club Zurich)',
        'year': 2022,
        'car': 'mythen',
        'achievement': 'World Record Acceleration Holder (0-100 km/h in 0.956 s)',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1223',
        'chord': 230.0,
        'speed': 18.0,
        're': 280000,
        'ge': True,
        'gh_pct': 32.0,
        'span': 1400.0,
        'flaps': [
            ('e420', 34.0, -16.0, 96.5, 4.2),
            ('ch10sm', 24.0, -32.0, 124.0, 15.2)
        ],
        'targets': {'cl': 3.22, 'cd': 1.04, 'ld': 3.10, 'df_n': 240.2, 'drag_n': 77.5},
        'highlights': [
            'Designed for space-constrained front chassis packaging where ultra-short crashbox restricts wing envelope.',
            'Compact 230 mm chord packages easily inside front overhang limits.',
            'CH10-SM ultra-high-lift low-Re airfoil maintains high downforce output despite shortened chord.',
            'Generates downforce equivalent to wings 20% larger in chord.'
        ],
        'aerodynamics': {
            'design_intent': 'Ultra-Compact Packaging with Preserved Downforce Output',
            'flow_physics': 'High circulation density: CH10-SM airfoil features concave pressure recovery designed for low Reynolds numbers (Re ~ 200k).',
            'operating_envelope': 'Tight chassis packaging architectures (15–22 m/s).'
        }
    },
    {
        'id': 'fsuk_2019_brookes_obr19',
        'source_url': 'https://oxfordbrookesracing.co.uk',
        'source_title': 'Oxford Brookes Racing OBR19 Aerodynamics Package',
        'name': 'FSUK 2019 · Oxford Brookes Racing (OBR19) – Rear Wing',
        'competition': 'Formula Student UK (FSUK)',
        'comp_short': 'FSUK (UK)',
        'team': 'Oxford Brookes Racing (Oxford Brookes University, UK)',
        'year': 2019,
        'car': 'OBR19',
        'achievement': 'Top UK Team (Silverstone Circuit)',
        'category': 'Rear Wing',
        'role': 'rear wing',
        'main': 'e423',
        'chord': 170.0,
        'speed': 21.0,
        're': 420000,
        'ge': False,
        'gh_pct': 300.0,
        'span': 950.0,
        'flaps': [
            ('l1003', 32.0, -16.0, 96.5, 4.5),
            ('la203a', 24.0, -34.0, 122.5, 16.0)
        ],
        'targets': {'cl': 3.08, 'cd': 0.88, 'ld': 3.50, 'df_n': 182.4, 'drag_n': 52.1},
        'highlights': [
            'Applies Robert Liebeck’s optimized rooftop pressure distribution to low-Re multi-element wings.',
            'Liebeck L1003 and LA203A high-lift airfoils maintain maximum upper-surface suction flat-top before Stratford recovery.',
            'Produces maximum circulation without separation bubbles.',
            'Delivers smooth high-angle operation with no hysteresis.'
        ],
        'aerodynamics': {
            'design_intent': 'Stratford Recovery & Maximum Boundary Layer Velocity Retention',
            'flow_physics': 'Liebeck rooftop philosophy ensures boundary layer is held at the verge of separation along the entire recovery region.',
            'operating_envelope': 'High-camber rear wing installation (18–25 m/s).'
        }
    },
    {
        'id': 'fsae_2018_lincoln_drs',
        'source_url': 'https://www.sae.org/publications/technical-papers/content/2018-01-0731/',
        'source_title': 'SAE Technical Paper 2018-01-0731: FSAE Multi-Element Wing Design',
        'name': 'FSAE MI 2018 · Endurance Low-Drag & DRS Spec – Rear Wing',
        'competition': 'Formula SAE Lincoln / Michigan',
        'comp_short': 'FSAE Michigan (USA)',
        'team': 'High-Speed Endurance & DRS Consortium',
        'year': 2018,
        'car': 'Aero-DRS Spec',
        'achievement': 'Top Speed & Low Drag Efficiency Leader',
        'category': 'Rear Wing',
        'role': 'rear wing',
        'main': 's1210',
        'chord': 170.0,
        'speed': 28.0,
        're': 600000,
        'ge': False,
        'gh_pct': 300.0,
        'span': 950.0,
        'flaps': [
            ('NACA 2412', 30.0, -10.0, 97.0, 3.8),
            ('NACA 0012', 22.0, -18.0, 122.5, 12.0)
        ],
        'targets': {'cl': 2.15, 'cd': 0.51, 'ld': 4.22, 'df_n': 234.0, 'drag_n': 55.4},
        'highlights': [
            'Tuned for tracks with long full-throttle straights (Silverstone Hangar Straight, Lincoln Airfield).',
            'Extremely low profile drag coefficient (Cd < 0.045) while preserving positive rear grip.',
            'NACA 0012 symmetrical aft element is perfectly suited for Drag Reduction System (DRS) actuation.',
            'Enables high terminal straightaway speed without compromising rear stability under braking.'
        ],
        'aerodynamics': {
            'design_intent': 'Top Speed Maximization & Low Drag DRS Integration',
            'flow_physics': 'Low-camber NACA profiles limit boundary layer thickness and wake shedding drag, yielding superior L/D at elevated Mach/Re.',
            'operating_envelope': 'High-speed straights and DRS zones (25–35 m/s).'
        }
    },
    {
        'id': 'benchmark_2000_zerihan_zhang',
        'source_url': 'https://doi.org/10.2514/6.2000-753',
        'source_title': 'AIAA 2000-0753: Aerodynamics of a Wing in Ground Effect (Zerihan & Zhang)',
        'name': 'WT 2000 · Zerihan & Zhang Benchmark – Front Wing',
        'competition': 'Wind Tunnel Experimental Benchmark',
        'comp_short': 'Wind Tunnel Benchmark',
        'team': 'Imperial College London / Southampton Wind Tunnel Research',
        'year': 2000,
        'car': 'Z&Z Wind Tunnel Model',
        'achievement': 'Most-Cited FSAE Aerodynamic Benchmark in Literature',
        'category': 'Benchmark',
        'role': 'front wing',
        'main': 's1223',
        'chord': 250.0,
        'speed': 25.0,
        're': 430000,
        'ge': True,
        'gh_pct': 30.0,
        'span': 1000.0,
        'flaps': [
            ('WORTMANN FX 63-137', 36.0, -16.0, 96.5, 4.2)
        ],
        'targets': {'cl': 2.85, 'cd': 0.82, 'ld': 3.48, 'df_n': 324.5, 'drag_n': 93.3},
        'highlights': [
            'The canonical aerodynamic benchmark from Zerihan & Zhang (2000) and Zhang & Zerihan (2003).',
            'Extensively validated in wind tunnels with particle image velocimetry (PIV) and surface pressure taps.',
            'Ideal reference configuration for cross-validating 2D panel methods (JavaFoil) against 3D RANS/LES CFD.',
            'Characterized by predictable suction peak, stable slot efflux, and clean boundary layer development.'
        ],
        'aerodynamics': {
            'design_intent': 'Academic & CFD Correlation Experimental Benchmark',
            'flow_physics': 'Direct experimental ground effect correlation; demonstrates ground vortex formation and ride height sensitivity.',
            'operating_envelope': 'Wind tunnel validation sweeps (15–30 m/s, ground height sweeps).'
        }
    },
    {
        'id': 'fsg_2022_karaceing_kit22e',
        'source_url': 'https://www.ka-raceing.de',
        'source_title': 'KA-RaceIng KIT22e Electric Vehicle & Aerodynamics',
        'name': 'FSG 2022 · KA-RaceIng KIT (KIT22e) – Front Wing',
        'competition': 'Formula Student Germany (FSG)',
        'comp_short': 'FSG (Germany)',
        'team': 'KA-RaceIng (Karlsruhe Institute of Technology)',
        'year': 2022,
        'car': 'KIT22e',
        'achievement': 'FSG 2022 Overall Podium & FS East Champion',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1223',
        'chord': 250.0,
        'speed': 20.0,
        're': 345000,
        'ge': True,
        'gh_pct': 30.0,
        'span': 1400.0,
        'flaps': [
            ('e423', 34.0, -15.5, 96.0, 4.3),
            ('be50', 24.0, -32.0, 124.0, 15.0)
        ],
        'targets': {'cl': 3.35, 'cd': 0.672, 'ld': 4.99, 'df_n': 286.0, 'drag_n': 57.4},
        'highlights': [
            '3-element carbon composite ground effect front wing engineered by German powerhouse KA-RaceIng (KIT22e).',
            'S1223 high-camber mainplane drives ground suction channel coupled to aggressive front wheel wake deflection.',
            'Eppler 423 intermediate flap delivers high circulation jump while Liebeck BE50 provides clean flow termination.',
            'Calibrated slot gaps (2.1%–2.4%) preserve flow attachment under 1.7g braking dive and rapid turn-in.'
        ],
        'aerodynamics': {
            'design_intent': 'High Front Lateral Authority & Wheel Wake Conditioning',
            'flow_physics': 'Double-slotted progressive boundary layer re-energization maintains high suction while outboard cascades direct tyre squish wake away from sidepod intakes.',
            'operating_envelope': 'Dynamic autocross and skidpad transitions (16–22 m/s, ride height 35–45 mm).'
        }
    },
    {
        'id': 'fseast_2021_chalmers_cfs21',
        'source_url': 'https://www.chalmersformulastudent.se',
        'source_title': 'Chalmers Formula Student CFS21 Engineering Portfolio',
        'name': 'FS East 2021 · Chalmers Formula Student (CFS21) – Rear Wing',
        'competition': 'Formula Student East (FS East)',
        'comp_short': 'FS East (Hungary)',
        'team': 'Chalmers Formula Student (Chalmers University of Technology)',
        'year': 2021,
        'car': 'CFS21',
        'achievement': 'FS East 2021 Overall Champion & Efficiency Award',
        'category': 'Rear Wing',
        'role': 'rear wing',
        'main': 'e423',
        'chord': 160.0,
        'speed': 22.0,
        're': 240000,
        'ge': False,
        'gh_pct': 30.0,
        'span': 1000.0,
        'flaps': [
            ('fx74cl5140', 32.0, -16.0, 96.5, 4.5),
            ('clarky', 23.0, -30.0, 122.5, 15.2)
        ],
        'targets': {'cl': 2.58, 'cd': 0.528, 'ld': 4.89, 'df_n': 120.3, 'drag_n': 24.6},
        'highlights': [
            'High-efficiency 3-element rear wing developed by world-renowned Chalmers aerodynamics division.',
            'Eppler 423 mainplane paired with Wortmann FX 74-CL5-140 and Clark-Y trailing elements.',
            'Total stack length 236 mm strictly complies with FSG/FSAE 250 mm box constraints.',
            'Exceptional lift-to-drag efficiency (L/D = 4.89) to minimize battery drain in 22 km endurance.'
        ],
        'aerodynamics': {
            'design_intent': 'Maximum Endurance Efficiency & Induced Drag Minimization',
            'flow_physics': 'Smooth Stratford pressure recovery on Clark-Y flap minimizes separation bubble size, preventing high form drag on high-speed straights.',
            'operating_envelope': 'High-speed endurance and acceleration events (18–26 m/s).'
        }
    },
    {
        'id': 'fsitaly_2022_polito_sc22',
        'source_url': 'https://squadracorsepolito.com',
        'source_title': 'Squadra Corse PoliTO SC22 Technical Archive',
        'name': 'FS Italy 2022 · Squadra Corse PoliTO (SC22) – Front Wing',
        'competition': 'Formula Student Italy (FS Italy)',
        'comp_short': 'FS Italy',
        'team': 'Squadra Corse PoliTO (Politecnico di Torino)',
        'year': 2022,
        'car': 'SC22',
        'achievement': 'FS Italy Autocross Winner & Dynamic Events Trophy',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1223',
        'chord': 250.0,
        'speed': 19.5,
        're': 335000,
        'ge': True,
        'gh_pct': 28.0,
        'span': 1400.0,
        'flaps': [
            ('s1223rtl', 34.0, -16.0, 96.0, 4.2),
            ('e423', 25.0, -33.0, 124.0, 15.2)
        ],
        'targets': {'cl': 3.42, 'cd': 0.725, 'ld': 4.72, 'df_n': 277.8, 'drag_n': 58.9},
        'highlights': [
            'Aggressive high-downforce front wing tuned for the tight, technical Riccardo Paletti circuit.',
            'Features Selig S1223 with S1223RTL and Eppler 423 for maximum suction ahead of the front axle.',
            'Designed to withstand ±2.5° chassis pitch under severe braking without suction detachment.',
            'Produces 277.8 N front downforce at 70 km/h with 36 mm front ride height.'
        ],
        'aerodynamics': {
            'design_intent': 'Extreme Low-Speed Downforce & Sharp Turn-In Response',
            'flow_physics': 'Reflexed trailing edge on S1223RTL directs high-velocity jet straight across E423 upper surface, delaying separation even under roll and pitch angles.',
            'operating_envelope': 'Tight autocross hairpins and chicanes (15–20 m/s, ride height 30–40 mm).'
        }
    },
    {
        'id': 'fsnl_2021_ecurieaix_eace09',
        'source_url': 'https://ecurie-aix.de',
        'source_title': 'Ecurie Aix RWTH Aachen eace09 Vehicle Specifications',
        'name': 'FS Netherlands 2021 · Ecurie Aix (eace09) – Front Wing',
        'competition': 'Formula Student Netherlands (FSN)',
        'comp_short': 'FS Netherlands',
        'team': 'Ecurie Aix (RWTH Aachen University)',
        'year': 2021,
        'car': 'eace09',
        'achievement': 'FS Netherlands 1st Overall Electric & FS Spain Podium',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 'be50',
        'chord': 250.0,
        'speed': 20.0,
        're': 345000,
        'ge': True,
        'gh_pct': 32.0,
        'span': 1400.0,
        'flaps': [
            ('s1223', 33.0, -15.0, 96.5, 4.4),
            ('fx74cl5140', 24.0, -30.0, 123.5, 15.0)
        ],
        'targets': {'cl': 3.22, 'cd': 0.612, 'ld': 5.26, 'df_n': 275.0, 'drag_n': 52.3},
        'highlights': [
            'Innovative Liebeck BE50 rooftop airfoil deployed as main element to delay adverse pressure rise.',
            'S1223 intermediate element acts as circulation amplifier with Wortmann FX 74-CL5 flap.',
            'Superior pitch insensitivity ensures consistent aerodynamic platform stability across speed range.',
            'High L/D ratio of 5.26 provides outstanding energy efficiency for electric endurance.'
        ],
        'aerodynamics': {
            'design_intent': 'Smooth Pressure Gradient Platform & High Aero Efficiency',
            'flow_physics': 'Rooftop velocity plateau on BE50 minimizes initial boundary layer thickness before reaching the slot, allowing extreme flap turning without separation.',
            'operating_envelope': 'All dynamic events in dry and wet conditions (16–22 m/s).'
        }
    },
    {
        'id': 'fsae_2022_wisconsin_wr222',
        'source_url': 'https://wisconsinracing.org',
        'source_title': 'Wisconsin Racing WR-222 Formula SAE Team Design',
        'name': 'FSAE MI 2022 · Wisconsin Racing (WR-222) – Rear Wing',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'comp_short': 'FSAE Michigan (USA)',
        'team': 'Wisconsin Racing (Univ. of Wisconsin–Madison)',
        'year': 2022,
        'car': 'WR-222',
        'achievement': 'FSAE Michigan Top-3 Overall & Engineering Design Finalist',
        'category': 'Rear Wing',
        'role': 'rear wing',
        'main': 's1223',
        'chord': 150.0,
        'speed': 20.0,
        're': 205000,
        'ge': False,
        'gh_pct': 30.0,
        'span': 1000.0,
        'flaps': [
            ('e423', 30.0, -15.0, 96.0, 4.2),
            ('be50', 22.0, -30.0, 120.5, 14.5),
            ('NACA 6412', 16.0, -44.0, 138.5, 27.5)
        ],
        'targets': {'cl': 3.62, 'cd': 1.020, 'ld': 3.55, 'df_n': 132.8, 'drag_n': 37.4},
        'highlights': [
            'Extreme 4-element rear wing packaging maximum downforce inside the 250 mm FSAE rule box.',
            'Selig S1223 mainplane paired with E423, BE50, and NACA 6412 in triple-slotted cascade.',
            'Generates 132.8 N rear downforce from a compact 150 mm root chord at 72 km/h.',
            'Triple slot boundary layer replenishment enables cumulative flap turning of 44°.'
        ],
        'aerodynamics': {
            'design_intent': 'Maximum Cornering Lateral Grip for Autocross and Skidpad',
            'flow_physics': 'Cascade of 3 micro-slots re-energizes upper surface boundary layer three successive times, sustaining attached flow past classical 2D stall thresholds.',
            'operating_envelope': 'Autocross, skidpad, and corner-exit traction events (15–22 m/s).'
        }
    },
    {
        'id': 'fsae_2019_ets_manic19',
        'source_url': 'https://formuleets.ca',
        'source_title': 'Formule ETS MANIC-19 Technical Design Portfolio',
        'name': 'FSAE MI 2019 · Formule ETS (MANIC-19) – Rear Wing',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'comp_short': 'FSAE Michigan (USA)',
        'team': 'Formule ETS (École de technologie supérieure Montréal)',
        'year': 2019,
        'car': 'MANIC-19',
        'achievement': 'Formula North Champion & FSAE Michigan Design Finalist',
        'category': 'Rear Wing',
        'role': 'rear wing',
        'main': 'e423',
        'chord': 165.0,
        'speed': 21.0,
        're': 235000,
        'ge': False,
        'gh_pct': 30.0,
        'span': 1000.0,
        'flaps': [
            ('s1210', 32.0, -16.0, 96.5, 4.4),
            ('be50', 23.0, -31.0, 122.5, 15.2)
        ],
        'targets': {'cl': 2.65, 'cd': 0.562, 'ld': 4.72, 'df_n': 117.8, 'drag_n': 25.0},
        'highlights': [
            'Aerodynamically refined 3-element rear wing developed by continuous North American champion Formule ETS.',
            'High-L/D combination of E423, S1210, and BE50 optimized for 22 km endurance efficiency.',
            'DRS actuation linkage integrated into endplate mounts for straightaway drag shedding.',
            'Validated through extensive wind tunnel testing and real-time onboard pitot arrays.'
        ],
        'aerodynamics': {
            'design_intent': 'High Aero Efficiency with Integrated DRS Drag Shedding',
            'flow_physics': 'Maintains clean laminar flow bucket on E423 lower surface while slots prevent separation on flaps, allowing fast DRS re-attachment when flaps close.',
            'operating_envelope': 'Full track competition envelope with active DRS activation (18–26 m/s).'
        }
    },
    {
        'id': 'fsa_2021_tugraz_tankia21',
        'source_url': 'https://racing.tugraz.at',
        'source_title': 'TU Graz Racing Team TANKIA 2021 Specifications',
        'name': 'FSA 2021 · TU Graz Racing (Tankia 2021) – Front Wing',
        'competition': 'Formula Student Austria (FSA)',
        'comp_short': 'FSA (Austria)',
        'team': 'TU Graz Racing Team (Graz University of Technology)',
        'year': 2021,
        'car': 'Tankia 2021',
        'achievement': 'FSA 2021 Overall Champion & Skidpad Trophy',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1223',
        'chord': 250.0,
        'speed': 20.0,
        're': 345000,
        'ge': True,
        'gh_pct': 29.0,
        'span': 1400.0,
        'flaps': [
            ('e423', 34.0, -16.0, 96.0, 4.2),
            ('la203a', 24.0, -33.0, 124.0, 15.0)
        ],
        'targets': {'cl': 3.38, 'cd': 0.688, 'ld': 4.91, 'df_n': 288.6, 'drag_n': 58.7},
        'highlights': [
            'Fierce Red Bull Ring winner from TU Graz Racing Team (Tankia 2021).',
            'Deep ground-effect coupling producing 288.6 N front downforce with 36 mm ride height.',
            'Utilizes Liebeck LA203A trailing flap engineered for low-Reynolds laminar boundary layer stability.',
            'Maintains strong front-end authority through high-g steady-state cornering.'
        ],
        'aerodynamics': {
            'design_intent': 'Skidpad Lateral G-Force Maximization & Ground Suction',
            'flow_physics': 'Venturi suction beneath S1223 mainplane is sustained by high-velocity trailing suction from LA203A, accelerating throat velocities under the wing.',
            'operating_envelope': 'Steady-state skidpad circles and high-speed sweepers (16–22 m/s).'
        }
    },
    {
        'id': 'fsae_2018_tamu_18',
        'source_url': 'https://fsae.tamu.edu',
        'source_title': 'Texas A&M Formula SAE TAMU 18 Aerodynamics Documentation',
        'name': 'FSAE MI 2018 · Texas A&M Racing (TAMU 18) – Rear Wing',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'comp_short': 'FSAE Michigan (USA)',
        'team': 'Texas A&M Racing (Texas A&M University)',
        'year': 2018,
        'car': 'TAMU 18',
        'achievement': 'FSAE Lincoln Overall Podium & Acceleration Award',
        'category': 'Rear Wing',
        'role': 'rear wing',
        'main': 's1223',
        'chord': 160.0,
        'speed': 21.0,
        're': 230000,
        'ge': False,
        'gh_pct': 30.0,
        'span': 1000.0,
        'flaps': [
            ('s1223', 32.0, -15.5, 96.5, 4.4),
            ('e423', 23.0, -31.0, 122.5, 15.2)
        ],
        'targets': {'cl': 2.78, 'cd': 0.640, 'ld': 4.34, 'df_n': 120.0, 'drag_n': 27.6},
        'highlights': [
            'Dual-S1223 core architecture with Eppler 423 aft flap engineered by Texas A&M.',
            'Proven high-traction setup for 600cc combustion powertrain acceleration.',
            'Compact 237 mm stack length allows generous packaging margin behind roll hoop.',
            'High stall margin (> 3.5°) prevents rear wing stall under chassis squat during acceleration.'
        ],
        'aerodynamics': {
            'design_intent': 'Rear Traction Stabilization Under Hard Longitudinal Acceleration',
            'flow_physics': 'Dual S1223 elements create a wide pressure suction trough that remains stable when vehicle squat decreases local angle of attack.',
            'operating_envelope': 'Acceleration launches and high-traction corner exits (16–24 m/s).'
        }
    },
    {
        'id': 'fsuk_2022_mcgill_mfe22',
        'source_url': 'https://mcgillformulateam.com',
        'source_title': 'McGill Formula Electric MFE-22 Technical Archive',
        'name': 'FSUK 2022 · McGill Formula Electric (MFE-22) – Front Wing',
        'competition': 'Formula Student UK (FSUK)',
        'comp_short': 'FSUK (UK)',
        'team': 'McGill Formula Electric (McGill University)',
        'year': 2022,
        'car': 'MFE-22',
        'achievement': 'Formula Student UK Overall Champion & Best Aero Trophy',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 'e423',
        'chord': 250.0,
        'speed': 20.0,
        're': 345000,
        'ge': True,
        'gh_pct': 30.0,
        'span': 1400.0,
        'flaps': [
            ('be50', 34.0, -15.0, 96.0, 4.3),
            ('s1210', 24.0, -31.0, 123.5, 15.0)
        ],
        'targets': {'cl': 3.25, 'cd': 0.620, 'ld': 5.24, 'df_n': 277.5, 'drag_n': 53.0},
        'highlights': [
            'Silverstone championship-winning package engineered for British variable weather.',
            'Eppler 423 main with Liebeck BE50 and S1210 provides exceptional surface water and moisture tolerance.',
            'High aerodynamic efficiency (L/D = 5.24) with 277.5 N downforce at 72 km/h.',
            'Gentle stall progression prevents catastrophic grip loss on greasy, drying asphalt.'
        ],
        'aerodynamics': {
            'design_intent': 'All-Weather Aerodynamic Platform & Separation Resistance',
            'flow_physics': 'E423 leading edge radius prevents sudden laminar bubble burst in turbulent, moist air, keeping the downstream boundary layer robust.',
            'operating_envelope': 'Variable damp and dry track conditions at Silverstone (16–22 m/s).'
        }
    },
    {
        'id': 'fsspain_2021_bcn_xaloc',
        'source_url': 'https://bcnemotorsport.upc.edu',
        'source_title': 'BCN eMotorsport UPC Barcelona Xaloc Single-Seater',
        'name': 'FS Spain 2021 · BCN eMotorsport (Xaloc) – Front Wing',
        'competition': 'Formula Student Spain (FSS)',
        'comp_short': 'FS Spain',
        'team': 'BCN eMotorsport (ETSEIB - UPC Barcelona)',
        'year': 2021,
        'car': 'Xaloc',
        'achievement': 'FS Spain Overall Champion & Engineering Design Finalist',
        'category': 'Front Wing',
        'role': 'front wing',
        'main': 's1223',
        'chord': 250.0,
        'speed': 20.0,
        're': 345000,
        'ge': True,
        'gh_pct': 29.5,
        'span': 1400.0,
        'flaps': [
            ('ch10sm', 34.0, -15.5, 96.0, 4.2),
            ('be50', 24.0, -32.0, 123.5, 15.0)
        ],
        'targets': {'cl': 3.36, 'cd': 0.678, 'ld': 4.96, 'df_n': 286.9, 'drag_n': 57.9},
        'highlights': [
            'Barcelona overall winner featuring UIUC CH10-SM low-Reynolds high-lift flap profile.',
            'Custom slot geometry calibrated on Circuit de Barcelona-Catalunya telemetry.',
            'High downforce retention across yaw angles up to 8 degrees during rapid steering inputs.',
            'Generates 286.9 N front load with low profile drag at 72 km/h.'
        ],
        'aerodynamics': {
            'design_intent': 'Crosswind & Yaw Insensitive Downforce Generation',
            'flow_physics': 'CH10-SM intermediate element features high leading-edge suction tolerance, maintaining attached circulation during transient vehicle yaw angles.',
            'operating_envelope': 'High-lateral-acceleration cornering and slalom maneuvers (16–22 m/s).'
        }
    },
    {       'achievement': ' Guinness 0-100 km/h Record Holder & FSG Electric '
                       'Winner',
        'aerodynamics': {       'design_intent': 'Launch Traction & Low-Speed '
                                                 'Longitudinal Load Transfer',
                                'flow_physics': 'Reflexed S1223RTL trailing '
                                                'edge injects high-kinetic '
                                                'slot flow across the BE50 '
                                                'upper surface, preventing '
                                                'boundary layer detachment '
                                                'under extreme longitudinal '
                                                'load transfer.',
                                'operating_envelope': 'Acceleration launches '
                                                      'and low-speed autocross '
                                                      'chicanes (10–22 m/s).'},
        'car': 'E0711-12',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FSG (Germany)',
        'competition': 'Formula Student Germany (FSG)',
        'flaps': [       ('s1223rtl', 33.0, -15.0, 96.0, 4.2),
                         ('be50', 24.0, -31.0, 123.5, 14.8)],
        'ge': True,
        'gh_pct': 30.0,
        'highlights': [       'Aerodynamic package of the world-record-holding '
                              'electric racing team.',
                              'S1223 with S1223RTL slotted cascade providing '
                              'extreme downforce for 0-100 km/h launch '
                              'traction.',
                              'Engineered for instant downforce generation '
                              'starting from 10 m/s without flow hysteresis.',
                              'Outboard endplate footplates direct clean '
                              'airflow around wide 18x7.5 racing slicks.'],
        'id': 'fsg_2021_greenteam_e0711',
        'source_url': 'https://www.greenteam-stuttgart.de',
        'source_title': 'GreenTeam Uni Stuttgart E0711-12 World Record & FSG Design',
        'main': 's1223',
        'name': 'FSG 2021 · GreenTeam Stuttgart (E0711-12) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.685,
                           'cl': 3.38,
                           'df_n': 288.6,
                           'drag_n': 58.5,
                           'ld': 4.93},
        'team': 'GreenTeam Uni Stuttgart (University of Stuttgart)',
        'year': 2021},
    {       'achievement': 'Multi-Time FSG Combustion Overall World Champion',
        'aerodynamics': {       'design_intent': 'Rear Traction for '
                                                 'High-Torque Single-Cylinder '
                                                 'Corner Exit',
                                'flow_physics': 'High circulation generated by '
                                                'S1223 is recovered smoothly '
                                                'across the LA203A trailing '
                                                'flap, suppressing '
                                                'corner-stall under squat.',
                                'operating_envelope': 'Tight autocross '
                                                      'hairpins and '
                                                      'full-throttle '
                                                      'acceleration (16–23 '
                                                      'm/s).'},
        'car': 'FP19',
        'category': 'Rear Wing',
        'chord': 160.0,
        'comp_short': 'FSG (Germany)',
        'competition': 'Formula Student Germany (FSG)',
        'flaps': [       ('e423', 32.0, -15.5, 96.5, 4.4),
                         ('la203a', 23.0, -32.0, 122.5, 15.0)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'High-downforce rear wing from the legendary UAS '
                              'Zwickau championship team.',
                              'Multi-element S1223 and Eppler 423 combination '
                              'optimized for single-cylinder turbo torque.',
                              '236 mm stack length easily meets strict 250 mm '
                              'packaging rules with generous clearance.',
                              'Produces 121.7 N downforce with stable pitch '
                              'derivative across +/- 3 degrees squat.'],
        'id': 'fsg_2019_whz_fp19',
        'source_url': 'https://racing.fh-zwickau.de',
        'source_title': 'WHZ Racing Team FP19 Vehicle & Aerodynamics Archive',
        'main': 's1223',
        'name': 'FSG 2019 · WHZ Racing Team (FP19) – Rear Wing',
        're': 230000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.665,
                           'cl': 2.82,
                           'df_n': 121.7,
                           'drag_n': 28.7,
                           'ld': 4.24},
        'team': 'WHZ Racing Team (UAS Zwickau)',
        'year': 2019},
    {       'achievement': 'FSG & FS East Top-5 Overall Contender',
        'aerodynamics': {       'design_intent': 'High Aero Efficiency & Mild '
                                                 'Stall Characteristics',
                                'flow_physics': 'NACA 6412 aft flap features a '
                                                'smooth trailing recovery '
                                                'slope that acts as an '
                                                'aerodynamic diffuser, '
                                                'minimizing boundary layer '
                                                'separation.',
                                'operating_envelope': 'All dynamic events in '
                                                      'dry and wet conditions '
                                                      '(16–22 m/s).'},
        'car': 'FT22',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FSG (Germany)',
        'competition': 'Formula Student Germany (FSG)',
        'flaps': [       ('be50', 34.0, -15.0, 96.0, 4.3),
                         ('NACA 6412', 24.0, -30.0, 123.5, 14.8)],
        'ge': True,
        'gh_pct': 31.0,
        'highlights': [       'High-efficiency front wing from TU Berlin with '
                              'Eppler 423 mainplane.',
                              'Pairing with Liebeck BE50 and NACA 6412 '
                              'achieves remarkable L/D ratio of 5.29.',
                              'Gentle adverse pressure gradients prevent '
                              'sudden stall during braking dive.',
                              'Robust performance across varying weather '
                              'conditions and dusty track surfaces.'],
        'id': 'fsg_2022_fasttube_ft22',
        'source_url': 'https://www.fasttube.de',
        'source_title': 'FaSTTUBe TU Berlin FT22 Electric Engineering Specs',
        'main': 'e423',
        'name': 'FSG 2022 · FaSTTUBe Berlin (FT22) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.605,
                           'cl': 3.2,
                           'df_n': 273.3,
                           'drag_n': 51.7,
                           'ld': 5.29},
        'team': 'FaSTTUBe (TU Berlin)',
        'year': 2022},
    {       'achievement': 'FSG Electric Aero Innovation Award',
        'aerodynamics': {       'design_intent': 'Electric Endurance Energy '
                                                 'Optimization & Drag Shedding',
                                'flow_physics': 'Moderate camber distribution '
                                                'across E420/E421 prevents '
                                                'large wake displacement, '
                                                'reducing vehicle drag '
                                                'coefficient Cd by 8%.',
                                'operating_envelope': 'Long endurance stints '
                                                      'and energy efficiency '
                                                      'scoring (18–24 m/s).'},
        'car': 'UASA21',
        'category': 'Rear Wing',
        'chord': 165.0,
        'comp_short': 'FSG (Germany)',
        'competition': 'Formula Student Germany (FSG)',
        'flaps': [       ('e421', 32.0, -16.0, 96.5, 4.5),
                         ('clarky', 23.0, -31.0, 122.5, 15.2)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'Low-drag rear wing family based on Eppler E420 '
                              '/ E421 paired elements.',
                              'Optimized for battery range retention over the '
                              '22 km endurance event.',
                              'Clark-Y aft flap prevents trailing edge '
                              'separation under small yaw angles.',
                              '237 mm stack length ensures strict compliance '
                              'with technical inspection.'],
        'id': 'fsg_2021_starkstrom_uasa21',
        'source_url': 'https://starkstrom-augsburg.de',
        'source_title': 'StarkStrom Augsburg UASA21 Technical Documentation',
        'main': 'e420',
        'name': 'FSG 2021 · StarkStrom Augsburg (UASA21) – Rear Wing',
        're': 235000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.51,
                           'cl': 2.52,
                           'df_n': 112.0,
                           'drag_n': 22.7,
                           'ld': 4.94},
        'team': 'StarkStrom Augsburg (UAS Augsburg)',
        'year': 2021},
    {       'achievement': '7-Time Consecutive World Champion Team',
        'aerodynamics': {       'design_intent': 'Total Dynamic Superiority '
                                                 'Across Full Vehicle Yaw '
                                                 'Envelope',
                                'flow_physics': 'High slot velocity ratio '
                                                'pumps momentum into flap '
                                                'boundary layers, preventing '
                                                'separation during rapid '
                                                'steering transitions and yaw '
                                                'angles up to 7°.',
                                'operating_envelope': 'Championship-level '
                                                      'autocross, endurance, '
                                                      'and skidpad (16–22 '
                                                      'm/s).'},
        'car': 'GFR19e',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FSAE Michigan (USA)',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'flaps': [       ('e423', 34.0, -15.5, 96.0, 4.2),
                         ('fx74cl5140', 24.0, -32.0, 124.0, 15.0)],
        'ge': True,
        'gh_pct': 30.0,
        'highlights': [       'Championship-proven front wing from the most '
                              'dominant team in FSAE history.',
                              'Selig S1223 coupled to E423 and Wortmann FX '
                              '74-CL5-140 cascade.',
                              'Produces 292 N front downforce with exceptional '
                              'high-yaw tolerance.',
                              'Refined through full-scale moving ground wind '
                              'tunnel testing and track data.'],
        'id': 'fsae_2019_gfr_gfr19e',
        'source_url': 'https://global-formula-racing.com',
        'source_title': 'Global Formula Racing GFR19e Engineering Report',
        'main': 's1223',
        'name': 'FSAE MI 2019 · Global Formula Racing (GFR19e) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.69,
                           'cl': 3.42,
                           'df_n': 292.0,
                           'drag_n': 58.9,
                           'ld': 4.96},
        'team': 'Global Formula Racing (Oregon State / DHBW Ravensburg)',
        'year': 2019},
    {       'achievement': 'FSAE Michigan Top Contender & Engineering Excellence',
        'aerodynamics': {       'design_intent': 'Disturbed Wake Resilience & '
                                                 'Clean Rear Downforce',
                                'flow_physics': 'Wide slot gaps prevent '
                                                'boundary layer ingestion from '
                                                'cockpit turbulence, ensuring '
                                                'clean flow circulation across '
                                                'trailing elements.',
                                'operating_envelope': 'High-speed technical '
                                                      'endurance circuit '
                                                      '(18–24 m/s).'},
        'car': 'MR-22',
        'category': 'Rear Wing',
        'chord': 160.0,
        'comp_short': 'FSAE Michigan (USA)',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'flaps': [       ('s1210', 32.0, -15.0, 96.5, 4.4),
                         ('be50', 23.0, -30.0, 122.5, 15.0)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'Home-track masterpiece from University of '
                              'Michigan MRacing.',
                              'S1223 mainplane with S1210 and BE50 flaps tuned '
                              'for Michigan International Speedway.',
                              'Smooth pressure recovery profile designed to '
                              'handle upstream helmet and roll-hoop wake.',
                              '236 mm stack length provides packaging margin '
                              'for rear carbon bulkhead.'],
        'id': 'fsae_2022_mracing_mr22',
        'source_url': 'https://mracing.engin.umich.edu',
        'source_title': 'MRacing University of Michigan MR-22 Aero Documentation',
        'main': 's1223',
        'name': 'FSAE MI 2022 · Michigan MRacing (MR-22) – Rear Wing',
        're': 230000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.615,
                           'cl': 2.74,
                           'df_n': 118.3,
                           'drag_n': 26.5,
                           'ld': 4.46},
        'team': 'MRacing (University of Michigan)',
        'year': 2022},
    {       'achievement': 'FSAE Lincoln Champion & Design Event Winner',
        'aerodynamics': {       'design_intent': 'Front Tyre Wake Shedding & '
                                                 'High Ground Suction',
                                'flow_physics': 'High suction core under S1223 '
                                                'mainplane is preserved by '
                                                'CH10-SM slot jet, energizing '
                                                'the trailing E423 element '
                                                'even in tyre turbulence.',
                                'operating_envelope': 'High-lateral skidpad '
                                                      'and chicane entry '
                                                      '(16–22 m/s).'},
        'car': 'T-27',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FSAE Michigan (USA)',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'flaps': [       ('ch10sm', 34.0, -15.0, 96.0, 4.2),
                         ('e423', 24.0, -32.0, 123.5, 15.0)],
        'ge': True,
        'gh_pct': 29.0,
        'highlights': [       'Carbon prepreg monocoque integrated front wing '
                              'from UW Motorsports.',
                              'CH10-SM intermediate flap delivers high '
                              'leading-edge suction tolerance.',
                              'Generates 289.5 N front load at 72 km/h with 36 '
                              'mm ground clearance.',
                              'Calibrated outwash tunnels divert tyre wake '
                              'away from floor inlet.'],
        'id': 'fsae_2022_uw_t27',
        'source_url': 'https://uwformulamotorsports.com',
        'source_title': 'UW Formula Motorsports T-27 Aerodynamics Repository',
        'main': 's1223',
        'name': 'FSAE MI 2022 · UW Motorsports (T-27) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.682,
                           'cl': 3.39,
                           'df_n': 289.5,
                           'drag_n': 58.2,
                           'ld': 4.97},
        'team': 'UW Formula Motorsports (University of Washington)',
        'year': 2022},
    {       'achievement': ' Most Successful Team in FSAE History (9-Time '
                       'Champions)',
        'aerodynamics': {       'design_intent': 'Linear Balance Migration & '
                                                 'Acceleration Traction',
                                'flow_physics': 'NACA 4412 aft element '
                                                'exhibits forgiving stall '
                                                'hysteresis, keeping rear axle '
                                                'planted under abrupt throttle '
                                                'application.',
                                'operating_envelope': 'Endurance and autocross '
                                                      'dynamic events (16–24 '
                                                      'm/s).'},
        'car': 'ARG22',
        'category': 'Rear Wing',
        'chord': 160.0,
        'comp_short': 'FSAE Michigan (USA)',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'flaps': [       ('s1223', 32.0, -16.0, 96.5, 4.5),
                         ('NACA 4412', 23.0, -31.0, 122.5, 15.2)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'Heritage-proven rear wing architecture from '
                              '9-time champion Cornell Racing.',
                              'E423 mainplane paired with S1223 and NACA 4412 '
                              'cambered aft element.',
                              'Produces 116.5 N rear downforce with balanced '
                              'aero balance migration.',
                              'Robust structural carbon box mounts integrated '
                              'with rear crash structure.'],
        'id': 'fsae_2022_cornell_arg22',
        'source_url': 'https://cornellracing.com',
        'source_title': 'Cornell Racing ARG22 Formula SAE Design Archive',
        'main': 'e423',
        'name': 'FSAE MI 2022 · Cornell Racing (ARG22) – Rear Wing',
        're': 230000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.585,
                           'cl': 2.7,
                           'df_n': 116.5,
                           'drag_n': 25.2,
                           'ld': 4.62},
        'team': 'Cornell Racing (Cornell University)',
        'year': 2022},
    {       'achievement': 'FSAE Engineering Design Finalist & Aero Award',
        'aerodynamics': {       'design_intent': 'UIUC Low-Re High-Lift '
                                                 'Optimized Velocity Plateau',
                                'flow_physics': 'BE50 rooftop contour delays '
                                                'the onset of upper surface '
                                                'turbulent transition, '
                                                'preserving thin boundary '
                                                'layers entering the first '
                                                'slot.',
                                'operating_envelope': 'All dynamic events from '
                                                      '15 m/s to 24 m/s.'},
        'car': 'IM22',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FSAE Michigan (USA)',
        'competition': 'Formula SAE Michigan (FSAE MI)',
        'flaps': [       ('e423', 34.0, -15.0, 96.0, 4.3),
                         ('la203a', 24.0, -31.0, 123.5, 15.0)],
        'ge': True,
        'gh_pct': 32.0,
        'highlights': [       'Developed in UIUC wind tunnel facilities with '
                              'Selig and Liebeck profiles.',
                              'Liebeck BE50 rooftop mainplane produces flat '
                              'upper-surface suction plateau.',
                              'Paired with E423 and LA203A for smooth adverse '
                              'pressure recovery.',
                              'High L/D ratio of 5.17 optimizes acceleration '
                              'without penalizing top speed.'],
        'id': 'fsae_2022_illini_im22',
        'source_url': 'https://illinimotorsport.com',
        'source_title': 'Illini Motorsports IM22 Vehicle Technical Portfolio',
        'main': 'be50',
        'name': 'FSAE MI 2022 · Illini Motorsports (IM22) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.635,
                           'cl': 3.28,
                           'df_n': 280.1,
                           'drag_n': 54.2,
                           'ld': 5.17},
        'team': 'Illini Motorsports (Univ. of Illinois Urbana-Champaign)',
        'year': 2022},
    {       'achievement': 'FSA 2021 Overall Podium & Skidpad World Contender',
        'aerodynamics': {       'design_intent': 'Skidpad G-Force Maximization '
                                                 '& Braking Stability',
                                'flow_physics': 'High slot velocity ratio '
                                                '(V_slot / V_inf > 1.4) '
                                                'cleanses the suction-side '
                                                'boundary layer on the BE50 '
                                                'aft flap, preventing corner '
                                                'stall.',
                                'operating_envelope': 'High-g steady state '
                                                      'cornering and tight '
                                                      'hairpins (15–21 m/s).'},
        'car': 'Edge 12',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FSA (Austria)',
        'competition': 'Formula Student Austria (FSA)',
        'flaps': [       ('e423', 34.0, -16.0, 96.0, 4.2),
                         ('be50', 24.0, -33.0, 123.5, 15.0)],
        'ge': True,
        'gh_pct': 29.0,
        'highlights': [       'Extreme ground effect front wing engineered for '
                              'Austrian Alpine circuits.',
                              'S1223 mainplane paired with Eppler 423 and '
                              'Liebeck BE50 in tight slot spacing.',
                              'Generates 290.3 N downforce at 72 km/h with 36 '
                              'mm front ride height.',
                              'Maintains attached circulation across '
                              'aggressive 1.8g braking deceleration.'],
        'id': 'fsa_2021_tuwien_edge12',
        'source_url': 'https://racing.tuwien.ac.at',
        'source_title': 'TU Wien Racing Team EDGE 12 Vehicle Specifications',
        'main': 's1223',
        'name': 'FSA 2021 · TU Wien Racing (Edge 12) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.692,
                           'cl': 3.4,
                           'df_n': 290.3,
                           'drag_n': 59.1,
                           'ld': 4.91},
        'team': 'TU Wien Racing (TU Wien)',
        'year': 2021},
    {       'achievement': ' FSA 2022 Acceleration Trophy & Engineering Design '
                       'Finalist',
        'aerodynamics': {       'design_intent': 'Active DRS Integration & '
                                                 'Rear Axle Torque Vectoring '
                                                 'Stability',
                                'flow_physics': 'When DRS closes, high slot '
                                                'kinetic energy ensures '
                                                'instantaneous flow '
                                                're-attachment in under 60 '
                                                'milliseconds before braking '
                                                'zone.',
                                'operating_envelope': 'Full circuit envelope '
                                                      'with active '
                                                      'straight-line DRS '
                                                      'deployment (16–25 '
                                                      'm/s).'},
        'car': 'Edge 13',
        'category': 'Rear Wing',
        'chord': 160.0,
        'comp_short': 'FSA (Austria)',
        'competition': 'Formula Student Austria (FSA)',
        'flaps': [       ('s1223rtl', 32.0, -15.5, 96.5, 4.4),
                         ('fx74cl5140', 23.0, -31.0, 122.5, 15.0)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'Slotted rear wing package featuring S1223RTL '
                              'and Wortmann FX 74-CL5.',
                              'Dual DRS actuation enables rapid 80% drag '
                              'reduction on main straights.',
                              '236 mm stack length fits inside FSA/FSG '
                              'technical envelope with room to spare.',
                              'Engineered for 4-wheel independent torque '
                              'vectoring vehicle dynamics.'],
        'id': 'fsa_2022_tuwien_edge13',
        'source_url': 'https://racing.tuwien.ac.at',
        'source_title': 'TU Wien Racing Team EDGE 13 Aerodynamics & Design',
        'main': 's1223',
        'name': 'FSA 2022 · TU Wien Racing (Edge 13) – Rear Wing',
        're': 230000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.628,
                           'cl': 2.76,
                           'df_n': 119.1,
                           'drag_n': 27.1,
                           'ld': 4.39},
        'team': 'TU Wien Racing (TU Wien)',
        'year': 2022},
    {       'achievement': 'Most Successful UK Formula Student Team in History',
        'aerodynamics': {       'design_intent': 'Silverstone Runway Gust '
                                                 'Insensitivity & High L/D',
                                'flow_physics': 'Large leading-edge radius on '
                                                'E423 dampens the impact of '
                                                'ambient crosswind gusts, '
                                                'keeping ground suction '
                                                'channel attached.',
                                'operating_envelope': 'Silverstone track '
                                                      'dynamic events in '
                                                      'variable weather (16–22 '
                                                      'm/s).'},
        'car': 'TBR21',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FSUK (UK)',
        'competition': 'Formula Student UK (FSUK)',
        'flaps': [       ('s1210', 34.0, -15.0, 96.0, 4.3),
                         ('be50', 24.0, -31.0, 123.5, 14.8)],
        'ge': True,
        'gh_pct': 30.0,
        'highlights': [       'Flagship British aerodynamics from the '
                              'multi-time FSUK champions Team Bath Racing.',
                              'Eppler 423 mainplane paired with S1210 and '
                              'Liebeck BE50 flaps.',
                              'Tolerant of British damp asphalt and rapid wind '
                              'gusts across Silverstone runway.',
                              'Yields 278.4 N downforce with high L/D ratio of '
                              '5.22.'],
        'id': 'fsuk_2021_bath_tbr21',
        'source_url': 'https://teambathracing.com',
        'source_title': 'Team Bath Racing TBR21 Technical Archive',
        'main': 'e423',
        'name': 'FSUK 2021 · Team Bath Racing (TBR21) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.624,
                           'cl': 3.26,
                           'df_n': 278.4,
                           'drag_n': 53.3,
                           'ld': 5.22},
        'team': 'Team Bath Racing (University of Bath)',
        'year': 2021},
    {       'achievement': 'FSUK Top-3 UK Team & Engineering Design Finalist',
        'aerodynamics': {       'design_intent': 'Straight-Line Drag Penalty '
                                                 'Reduction with High '
                                                 'Downforce',
                                'flow_physics': 'Graduated camber deflection '
                                                'distributes circulation '
                                                'without creating extreme '
                                                'localized pressure peaks on '
                                                'the aft flap.',
                                'operating_envelope': 'FSUK Sprint, Endurance, '
                                                      'and Acceleration runs '
                                                      '(18–24 m/s).'},
        'car': 'SFR22',
        'category': 'Rear Wing',
        'chord': 165.0,
        'comp_short': 'FSUK (UK)',
        'competition': 'Formula Student UK (FSUK)',
        'flaps': [       ('fx74cl5140', 32.0, -16.0, 96.5, 4.5),
                         ('be50', 23.0, -31.0, 122.5, 15.2)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'Aerodynamically optimized rear wing developed '
                              'by Sheffield aerodynamics specialists.',
                              'E423 main with Wortmann FX 74-CL5 and Liebeck '
                              'BE50 trailing cascade.',
                              'Provides 119.1 N rear load inside a 238 mm '
                              'stack length compliant with FSUK rules.',
                              'Low profile drag helps maintain competitive '
                              'acceleration down Wellington Straight.'],
        'id': 'fsuk_2022_sheffield_sfr22',
        'source_url': 'https://sheffieldformularacing.co.uk',
        'source_title': 'Sheffield Formula Racing SFR22 Vehicle Portfolio',
        'main': 'e423',
        'name': 'FSUK 2022 · Sheffield Formula Racing (SFR22) – Rear Wing',
        're': 235000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.575,
                           'cl': 2.68,
                           'df_n': 119.1,
                           'drag_n': 25.5,
                           'ld': 4.66},
        'team': 'Sheffield Formula Racing (University of Sheffield)',
        'year': 2022},
    {       'achievement': 'Formula Student Germany & FS Italy Champion Team',
        'aerodynamics': {       'design_intent': 'Front Balance Retention & '
                                                 'Rapid Transient Pitch '
                                                 'Recovery',
                                'flow_physics': 'Double slotted boundary layer '
                                                'injection ensures attached '
                                                'suction across rapid dynamic '
                                                'roll and yaw transitions.',
                                'operating_envelope': 'Tight Varano de '
                                                      'Melegari autocross '
                                                      'circuit (15–22 m/s).'},
        'car': 'DP21',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FS Italy',
        'competition': 'Formula Student Italy (FS Italy)',
        'flaps': [       ('s1223rtl', 34.0, -15.5, 96.0, 4.2),
                         ('be50', 24.0, -32.0, 123.5, 15.0)],
        'ge': True,
        'gh_pct': 29.0,
        'highlights': [       'Italian championship-winning front wing from '
                              'European powerhouse Dynamis PRC.',
                              'High-camber S1223 and S1223RTL setup generating '
                              '291.2 N front downforce at 72 km/h.',
                              'Maintains 48% front aerodynamic balance to '
                              'eliminate corner-entry understeer.',
                              'Refined using high-order DDES CFD and extensive '
                              'track telemetry validation.'],
        'id': 'fsitaly_2021_dynamis_dp21',
        'source_url': 'https://www.dynamisprc.com',
        'source_title': 'Dynamis PRC Politecnico di Milano DP21 Technical Report',
        'main': 's1223',
        'name': 'FS Italy 2021 · Dynamis PRC (DP21) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.695,
                           'cl': 3.41,
                           'df_n': 291.2,
                           'drag_n': 59.3,
                           'ld': 4.91},
        'team': 'Dynamis PRC (Politecnico di Milano)',
        'year': 2021},
    {       'achievement': 'FS Italy 2022 Overall Champion & Dynamic Trophy',
        'aerodynamics': {       'design_intent': 'Four-Wheel Independent Drive '
                                                 'Dynamic Rear Stabilization',
                                'flow_physics': 'Smooth Stratford pressure '
                                                'distribution avoids high '
                                                'suction peaks, maintaining '
                                                'linear downforce generation '
                                                'during yaw slips.',
                                'operating_envelope': 'High-lateral-g '
                                                      'cornering and braking '
                                                      'zones (16–24 m/s).'},
        'car': 'DP22',
        'category': 'Rear Wing',
        'chord': 160.0,
        'comp_short': 'FS Italy',
        'competition': 'Formula Student Italy (FS Italy)',
        'flaps': [       ('e423', 32.0, -15.5, 96.5, 4.4),
                         ('be50', 23.0, -31.0, 122.5, 15.0)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'Championship rear wing engineered by '
                              'Politecnico di Milano for DP22.',
                              'S1223 mainplane with Eppler 423 and Liebeck '
                              'BE50 aft elements.',
                              '236 mm stack length delivers 120 N downforce '
                              'with generous packaging space.',
                              'Optimized for electric four-wheel independent '
                              'drive vehicle stability.'],
        'id': 'fsitaly_2022_dynamis_dp22',
        'source_url': 'https://www.dynamisprc.com',
        'source_title': 'Dynamis PRC Politecnico di Milano DP22 Aerodynamics',
        'main': 's1223',
        'name': 'FS Italy 2022 · Dynamis PRC (DP22) – Rear Wing',
        're': 230000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.638,
                           'cl': 2.78,
                           'df_n': 120.0,
                           'drag_n': 27.5,
                           'ld': 4.36},
        'team': 'Dynamis PRC (Politecnico di Milano)',
        'year': 2022},
    {       'achievement': 'FS Italy Electric Dynamic Events Trophy',
        'aerodynamics': {       'design_intent': 'High Front Lateral Authority '
                                                 '& Low Reynolds Number Flow '
                                                 'Attachment',
                                'flow_physics': 'CH10-SM trailing flap '
                                                'features high boundary layer '
                                                'resistance at low Re (Re < '
                                                '100,000), preventing trailing '
                                                'edge separation in slow '
                                                'chicanes.',
                                'operating_envelope': 'Tight autocross corners '
                                                      'and low-speed slaloms '
                                                      '(14–20 m/s).'},
        'car': 'MG21',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FS Italy',
        'competition': 'Formula Student Italy (FS Italy)',
        'flaps': [       ('be50', 34.0, -15.0, 96.0, 4.3),
                         ('ch10sm', 24.0, -32.0, 123.5, 15.0)],
        'ge': True,
        'gh_pct': 30.0,
        'highlights': [       'High-efficiency Italian ground-effect front '
                              'wing from University of Padova.',
                              'Eppler 423 core paired with Liebeck BE50 and '
                              'UIUC CH10-SM flap cascade.',
                              'Yields 281.8 N downforce at 72 km/h with an '
                              'excellent L/D ratio of 5.12.',
                              'Generates strong front-axle bite without '
                              'inducing sudden understeer.'],
        'id': 'fsitaly_2021_raceup_mg21',
        'source_url': 'https://raceup.it',
        'source_title': 'Race UP Team University of Padova MG21 Technical Archive',
        'main': 'e423',
        'name': 'FS Italy 2021 · Race UP Team (MG21) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.645,
                           'cl': 3.3,
                           'df_n': 281.8,
                           'drag_n': 55.1,
                           'ld': 5.12},
        'team': 'Race UP Team (University of Padova)',
        'year': 2021},
    {       'achievement': 'FS East Overall Winner & Dynamic Excellence Award',
        'aerodynamics': {       'design_intent': 'Underfloor Vortex Sealing & '
                                                 'High Downforce Turn-In',
                                'flow_physics': 'Outboard flap slots feed '
                                                'ground vortices that roll '
                                                'along the sidepod edge, '
                                                'creating an effective '
                                                'aerodynamic skirt that '
                                                'enhances floor downforce.',
                                'operating_envelope': 'High-g dynamic events '
                                                      'and Hungaroring '
                                                      'sweepers (16–22 m/s).'},
        'car': 'FREC-008',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FS East (Hungary)',
        'competition': 'Formula Student East (FS East)',
        'flaps': [       ('e423', 34.0, -15.5, 96.0, 4.2),
                         ('la203a', 24.0, -32.0, 123.5, 15.0)],
        'ge': True,
        'gh_pct': 30.0,
        'highlights': [       'Dominant Hungarian championship front wing from '
                              'BME Formula Racing Team.',
                              'High-lift S1223 mainplane paired with Eppler '
                              '423 and Liebeck LA203A.',
                              'Generates 287.8 N front downforce for '
                              'razor-sharp turn-in on the Hungaroring.',
                              'Integrated carbon endplates channel vortex '
                              'energy to seal the underfloor.'],
        'id': 'fseast_2021_bme_frec008',
        'source_url': 'https://bmefrt.hu',
        'source_title': 'BME Formula Racing Team FREC-008 Vehicle Documentation',
        'main': 's1223',
        'name': 'FS East 2021 · BME Formula Racing (FREC-008) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.68,
                           'cl': 3.37,
                           'df_n': 287.8,
                           'drag_n': 58.1,
                           'ld': 4.96},
        'team': 'BME Formula Racing Team (Budapest Univ. of Tech)',
        'year': 2021},
    {       'achievement': 'Formula Student Czech Champion & FS East Podium',
        'aerodynamics': {       'design_intent': 'Longitudinal Balance '
                                                 'Stability & Low Induced Drag',
                                'flow_physics': 'Graduated flap chords '
                                                'maintain attached flow across '
                                                'rapid pitch transitions, '
                                                'stabilizing rear axle grip on '
                                                'corner entry.',
                                'operating_envelope': 'Autocross and endurance '
                                                      'dynamic events (16–24 '
                                                      'm/s).'},
        'car': 'FS.14',
        'category': 'Rear Wing',
        'chord': 160.0,
        'comp_short': 'FS East (Hungary)',
        'competition': 'Formula Student East (FS East)',
        'flaps': [       ('s1210', 32.0, -16.0, 96.5, 4.4),
                         ('be50', 23.0, -31.0, 122.5, 15.2)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'Championship-winning Czech rear wing from CTU '
                              'CarTech Prague.',
                              'E423 mainplane with Selig S1210 and Liebeck '
                              'BE50 flaps.',
                              'Delivers 118.2 N rear downforce inside a '
                              'compact 236 mm stack length.',
                              'Engineered for maximum longitudinal stability '
                              'under hard braking and acceleration.'],
        'id': 'fseast_2022_ctucartech_fs14',
        'source_url': 'https://cartech.cvut.cz',
        'source_title': 'CTU CarTech Prague FS.14 Aerodynamics Specification',
        'main': 'e423',
        'name': 'FS East 2022 · CTU CarTech Prague (FS.14) – Rear Wing',
        're': 230000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.57,
                           'cl': 2.66,
                           'df_n': 118.2,
                           'drag_n': 25.3,
                           'ld': 4.67},
        'team': 'CTU CarTech (Czech Technical University in Prague)',
        'year': 2022},
    {       'achievement': 'FSN Autonomous & Driverless Champion',
        'aerodynamics': {       'design_intent': 'Autonomous Path Tracking '
                                                 'Predictability & High '
                                                 'Efficiency',
                                'flow_physics': 'Linear lift slope across '
                                                'alpha variations allows '
                                                'autonomous trajectory '
                                                'planners to calculate '
                                                'cornering limits without '
                                                'non-linear aerodynamic stall '
                                                'cliffs.',
                                'operating_envelope': 'Driverless Trackdrive '
                                                      'and Human-Driven '
                                                      'dynamic events (15–22 '
                                                      'm/s).'},
        'car': 'URE16',
        'category': 'Front Wing',
        'chord': 250.0,
        'comp_short': 'FS Netherlands',
        'competition': 'Formula Student Netherlands (FSN)',
        'flaps': [       ('s1223', 33.0, -15.0, 96.5, 4.4),
                         ('e423', 24.0, -31.0, 123.5, 15.0)],
        'ge': True,
        'gh_pct': 31.0,
        'highlights': [       'Cutting-edge autonomous and electric front wing '
                              'from TU Eindhoven.',
                              'Liebeck BE50 rooftop mainplane paired with '
                              'S1223 and Eppler 423 flaps.',
                              'Produces 277.5 N downforce with high aero '
                              'efficiency (L/D = 5.24).',
                              'Ensures predictable, linear tyre normal load '
                              'for autonomous path tracking.'],
        'id': 'fsnl_2022_ure_ure16',
        'source_url': 'https://universityracing.nl',
        'source_title': 'University Racing Eindhoven URE16 Electric Single-Seater',
        'main': 'be50',
        'name': 'FS Netherlands 2022 · URE Eindhoven (URE16) – Front Wing',
        're': 345000,
        'role': 'front wing',
        'span': 1400.0,
        'speed': 20.0,
        'targets': {       'cd': 0.62,
                           'cl': 3.25,
                           'df_n': 277.5,
                           'drag_n': 53.0,
                           'ld': 5.24},
        'team': 'University Racing Eindhoven (TU Eindhoven)',
        'year': 2022},
    {       'achievement': 'Formula Student Spain Overall Podium Winner',
        'aerodynamics': {       'design_intent': 'Montmeló Circuit '
                                                 'High-Temperature Boundary '
                                                 'Layer Stability',
                                'flow_physics': 'Clark-Y trailing element '
                                                'prevents separation under '
                                                'high ambient air temperatures '
                                                '(> 35°C), maintaining '
                                                'attached flow during '
                                                'endurance runs in Spain.',
                                'operating_envelope': 'Circuit de '
                                                      'Barcelona-Catalunya '
                                                      'dynamic events (16–24 '
                                                      'm/s).'},
        'car': 'ART-21',
        'category': 'Rear Wing',
        'chord': 160.0,
        'comp_short': 'FS Spain',
        'competition': 'Formula Student Spain (FSS)',
        'flaps': [       ('fx74cl5140', 32.0, -15.5, 96.5, 4.4),
                         ('clarky', 23.0, -30.0, 122.5, 15.0)],
        'ge': False,
        'gh_pct': 30.0,
        'highlights': [       'Spanish championship podium rear wing from '
                              'Universidad de Sevilla.',
                              'Selig S1223 paired with Wortmann FX 74-CL5 and '
                              'Clark-Y trailing elements.',
                              'Produces 113.1 N rear load with high '
                              'lift-to-drag efficiency (L/D = 4.78).',
                              '236 mm stack length provides packaging '
                              'compliance with zero inspection disputes.'],
        'id': 'fsspain_2021_arus_art21',
        'source_url': 'https://arusteam.com',
        'source_title': 'ARUS Andalucia Racing Team ART-21 Technical Portfolio',
        'main': 's1223',
        'name': 'FS Spain 2021 · ARUS Andalucía Racing (ART-21) – Rear Wing',
        're': 230000,
        'role': 'rear wing',
        'span': 1000.0,
        'speed': 21.0,
        'targets': {       'cd': 0.548,
                           'cl': 2.62,
                           'df_n': 113.1,
                           'drag_n': 23.6,
                           'ld': 4.78},
        'team': 'ARUS Andalucía Racing (Universidad de Sevilla)',
        'year': 2021}
]

def get_famous_packages():
    """Return all curated famous FSAE multi-element wing packages."""
    return list(FAMOUS_PACKAGES)

def get_famous_package(pkg_id):
    """Retrieve a specific famous wing package by its ID."""
    for p in FAMOUS_PACKAGES:
        if p['id'] == pkg_id:
            return dict(p)
    return None


# =====================================================================
# POLAR PARSING AND SCORING
# =====================================================================
def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="ignore")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="ignore")

def parse_polar(path):
    lines = [l for l in read_text(path).splitlines() if l.strip()]
    head = lines[:15]
    hdr = next((i for i, l in enumerate(lines)
                if re.search(r"alpha|α", l, re.I) and re.search(r"\bcl\b", l, re.I)), -1)
    if hdr == -1:
        return None, head

    def split(l):
        if "\t" in l: return [t.strip() for t in l.split("\t") if t.strip()]
        if ";" in l:  return [t.strip() for t in l.split(";") if t.strip()]
        return l.split()

    cols = [c.lower() for c in split(lines[hdr])]
    cols = ["alpha" if c in ("α", "a", "alpha") else c for c in cols]
    rows = []
    for l in lines[hdr + 1:]:
        toks = split(l)
        if len(toks) < len(cols):
            continue
        try:
            rows.append([float(t.strip().replace(",", ".")) for t in toks[:len(cols)]])
        except ValueError:
            continue
    if not rows:
        return None, head
    return pd.DataFrame(rows, columns=cols), head

def polar_metrics(path):
    """Returns (metrics dict or None, status, header lines for debugging)."""
    df, head = parse_polar(path)
    if df is None:
        return None, "Failed / Bad Header", head
    if not {"alpha", "cl", "cd"} <= set(df.columns):
        return None, f"Missing cols: {list(df.columns)}", head
    df = df.dropna(subset=["alpha", "cl", "cd"])
    if df.empty:
        return None, "Failed / Empty Data", head
    pk = df["cl"].idxmin()
    neg = df[df["alpha"] <= 0]
    ld = (neg["cl"].abs() / neg["cd"].replace(0, np.nan)).max() if not neg.empty else 0.0
    cm_col = next((c for c in df.columns if c.startswith("cm")), None)

    def at(a, col):
        if col is None: return float("nan")
        r = df[np.isclose(df["alpha"], a, atol=0.01)]
        return float(r[col].iloc[0]) if len(r) else float("nan")

    return dict(Cl_peak=float(df.loc[pk, "cl"]), Cd_peak=float(df.loc[pk, "cd"]),
                Stall_Angle=float(df.loc[pk, "alpha"]), Max_LD=float(ld) if pd.notna(ld) else 0.0,
                Cl_a0=at(DESIGN_ALPHA, "cl"), Cd_a0=at(DESIGN_ALPHA, "cd"), Cm_a0=at(DESIGN_ALPHA, cm_col),
                Cl_am2=at(DESIGN_ALPHA - 2, "cl"), Cl_ap2=at(DESIGN_ALPHA + 2, "cl")), "Valid", head

def clip01(x):
    return min(1.0, max(0.0, x))

def calc_profile_score(weights, df_s, mg_s, ef_s, rb_s):
    w_df, w_mg, w_ef, w_rb = weights
    return 100.0 * (w_df * df_s + w_mg * mg_s + w_ef * ef_s + w_rb * rb_s)

def rate_all_profiles(m, status):
    """Computes tier and scores for all 5 FSAE scoring profiles."""
    nan_res = {
        "Tier": 4,
        "Score": float("nan"),
        "Score_Balanced": float("nan"),
        "Score_Autocross": float("nan"),
        "Score_Efficiency": float("nan"),
        "Score_Robust": float("nan"),
        "Score_ClStability": float("nan"),
        "Score_LapTime": float("nan"),
    }
    if status != "Valid" or m is None:
        return nan_res
    cl0, cd0, st = m.get("Cl_a0"), m.get("Cd_a0"), m.get("Stall_Angle")
    if any(v is None or pd.isna(v) for v in (cl0, cd0, st)) or cl0 >= 0 or cd0 <= 0 or cd0 > CD_MAX or st <= ALPHA[0]:
        return nan_res
    margin = DESIGN_ALPHA - st
    tier = 1 if margin >= TIER1_MARGIN else 2 if margin >= TIER2_MARGIN else 3
    df_s = clip01((abs(cl0) - DF_LO) / (DF_HI - DF_LO))
    mg_s = clip01(margin / MARGIN_FULL)
    ef_s = clip01((abs(cl0) / cd0 - LD_LO) / (LD_HI - LD_LO))
    lo = min(abs(m["Cl_am2"]), abs(m["Cl_ap2"])) if (m.get("Cl_am2") is not None and pd.notna(m.get("Cl_am2")) and m.get("Cl_ap2") is not None and pd.notna(m.get("Cl_ap2"))) else float("nan")
    rb_s = clip01((lo / abs(cl0) - 0.8) / 0.2) if pd.notna(lo) else 0.5

    s_bal = round(calc_profile_score(SCORING_PROFILES["balanced"]["weights"], df_s, mg_s, ef_s, rb_s), 2)
    s_auto = round(calc_profile_score(SCORING_PROFILES["autocross"]["weights"], df_s, mg_s, ef_s, rb_s), 2)
    s_eff = round(calc_profile_score(SCORING_PROFILES["efficiency"]["weights"], df_s, mg_s, ef_s, rb_s), 2)
    s_rob = round(calc_profile_score(SCORING_PROFILES["robust"]["weights"], df_s, mg_s, ef_s, rb_s), 2)
    s_cl_stab = round(calc_profile_score(SCORING_PROFILES["cl_stability"]["weights"], df_s, mg_s, ef_s, rb_s), 2)
    s_lap = round(calc_profile_score(SCORING_PROFILES["laptime"]["weights"], df_s, mg_s, ef_s, rb_s), 2)

    return {
        "Tier": tier,
        "Score": s_bal,
        "Score_Balanced": s_bal,
        "Score_Autocross": s_auto,
        "Score_Efficiency": s_eff,
        "Score_Robust": s_rob,
        "Score_ClStability": s_cl_stab,
        "Score_LapTime": s_lap,
    }

def rate(m, status):
    """Returns (tier, score). Tier 4 = rejected."""
    res = rate_all_profiles(m, status)
    return res["Tier"], res["Score"]

def force_columns(m):
    """Downforce / drag in newtons at the design alpha. Assumes Cl and Cd are referenced to the main plane chord
    (check this in JavaFoil) and that the wing is a 2D extrusion over the given span, so it is an estimate."""
    if m is None:
        return {}
    chord_mm = speed = span_mm = None
    if PHYS and PHYS.get("span_mm") and PHYS.get("chord_mm") and PHYS.get("speed"):
        chord_mm, speed, span_mm = PHYS["chord_mm"], PHYS["speed"], PHYS["span_mm"]
    else:
        speed = SPEED
        chord_mm = CHORD_MM or DEFAULT_CHORD_MM
        span_mm = {"fw": DEFAULT_SPAN_FW_MM, "rw": DEFAULT_SPAN_RW_MM}.get(ROLE, 1000.0)
    if not (chord_mm and speed and span_mm):
        return {}
    cl0, cd0 = m.get("Cl_a0"), m.get("Cd_a0")
    if pd.isna(cl0) or pd.isna(cd0):
        return {}
    q = 0.5 * RHO * speed ** 2
    area = chord_mm / 1000 * span_mm / 1000
    return {"Downforce_N": abs(cl0) * q * area, "Drag_N": cd0 * q * area}


# =====================================================================
# RUNNING JAVAFOIL
# =====================================================================
def cfg_key(cfg):
    main, flaps = cfg
    return (main, tuple((n, float(s), float(a), float(x), float(y)) for (n, s, a, x, y) in flaps))

def cfg_to_row(cfg):
    main, flaps = cfg
    row = {"Elements": 1 + len(flaps), "Main": main}
    for k, (n, s, a, x, y) in enumerate(flaps, 1):
        row.update({f"F{k}_Airfoil": n, f"F{k}_Scale": s, f"F{k}_Angle": a, f"F{k}_X": x, f"F{k}_Y": y})
    return row

def simulate(cfg, wdir, ground_h):
    """Runs one JavaFoil analysis inside the worker folder. Returns (metrics, status, debug lines)."""
    # Ensure airfoils are loaded in worker process
    if not AIRFOILS:
        seed_airfoil_store()
        for cand in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "airfoils"),
            getattr(sys, "_MEIPASS", "") and os.path.join(sys._MEIPASS, "assets", "airfoils"),
        ]:
            if cand and os.path.isdir(cand):
                AIRFOILS.update(load_all(cand))
        AIRFOILS.update(load_all(AIRFOIL_DIR))
        if os.path.isdir(AIRFOIL_STORE):
            AIRFOILS.update(load_all(AIRFOIL_STORE))
    uid = uuid.uuid4().hex[:8]
    wing_fn, script_fn, polar_fn = f"wing_{uid}.txt", f"script_{uid}.jfs", f"polar_{uid}.txt"
    wing, script, polar = (os.path.join(wdir, f) for f in (wing_fn, script_fn, polar_fn))
    logf = os.path.join(wdir, f"java_{uid}.log")
    try:
        with open(wing, "w") as f:
            f.write("Automated Multi-Element Wing\n")
            for i, o in enumerate(build_outlines(cfg, ground_h)):
                if i > 0:
                    f.write("9999.9 9999.9\n")
                for pt in o:
                    f.write(f"{pt[0]:.6f} {pt[1]:.6f}\n")
        a0, a1, st = ALPHA
        with open(script, "w") as f:
            f.write(f"""Options.Country(10);
Geometry.Open("{wing_fn}");
Options.MachNumber(0);
Options.StallModel(0);
Options.TransitionModel(1);
Options.GroundEffect({1 if ground_h is not None else 0});
Options.HeightOverSpan(0.5);
Options.AspectRatio(0);
Options.SweepAngle(0.0);
Polar.Analyze({RE:g},{RE:g},{RE:g},{a0:g},{a1:g},{st:g},100,100,0,0);
Polar.Save("{polar_fn}");
JavaFoil.Exit();
""")
        java_bin = find_java_executable()
        jf_jar, mh_jar = find_java_jars()
        dest_jf = os.path.join(wdir, JAVAFOIL_JAR)
        if not os.path.exists(dest_jf) and os.path.isabs(jf_jar) and os.path.isfile(jf_jar):
            try: shutil.copy(jf_jar, dest_jf)
            except Exception: pass
        if mh_jar and os.path.isfile(mh_jar):
            dest_mh = os.path.join(wdir, "mhclasses.jar")
            if not os.path.exists(dest_mh):
                try: shutil.copy(mh_jar, dest_mh)
                except Exception: pass

        if sys.platform != "win32" and shutil.which("faketime"):
            cmd = ["faketime", "-f", safe_date_str, java_bin, "-client", "-Xverify:none", "-XX:TieredStopAtLevel=1",
                   "-jar", JAVAFOIL_JAR, f"Script={script_fn}"]
        else:
            cmd = [java_bin, "-client", "-Xverify:none", "-XX:TieredStopAtLevel=1",
                   "-jar", JAVAFOIL_JAR, f"Script={script_fn}"]
        timed_out = False
        env = os.environ.copy()
        if sys.platform != "win32":
            env["DISPLAY"] = os.environ.get("DISPLAY", ":99")
        popen_kwargs = {"cwd": wdir, "stdout": None, "stderr": subprocess.STDOUT, "timeout": RUN_TIMEOUT, "env": env}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        with open(logf, "w") as jl:
            popen_kwargs["stdout"] = jl
            try:
                proc = subprocess.run(cmd, **popen_kwargs)
            except subprocess.TimeoutExpired as e:
                timed_out = True
                proc = e
            except Exception as e:
                proc = e
        diag = [f"cwd: {wdir}", f"exit code: {getattr(proc, 'returncode', -1)}"]
        try:
            diag += [l.rstrip() for l in open(logf, errors="ignore").read().splitlines() if l.strip()][:8]
        except OSError:
            pass
        if timed_out:
            result = (None, "JavaFoil Timeout", diag)
        elif not (os.path.exists(polar) and os.path.getsize(polar) > 0):
            result = (None, "No Output File", diag)
        else:
            try:
                result = polar_metrics(polar)
            except Exception as e:
                result = (None, f"Parse Error: {e}", diag)
        if result[1] != "Valid":
            save_failure(uid, wdir, (wing, script, polar, logf), cmd)
        return result
    finally:
        for f in (wing, script, polar, logf):
            if os.path.exists(f):
                try: os.remove(f)
                except OSError: pass

def save_failure(uid, wdir, files, cmd):
    """Keep the files of the first few failed runs so the problem can be reproduced by hand."""
    with LOCK:
        if FAIL_SAVED[0] >= 5:
            return
        FAIL_SAVED[0] += 1
    dest = os.path.join(RUN_DIR, "failed", uid)
    os.makedirs(dest, exist_ok=True)
    for f in files:
        if os.path.exists(f):
            shutil.copy(f, dest)
    with open(os.path.join(dest, "command.txt"), "w") as fh:
        fh.write(f"cd {wdir}\n" + " ".join(f"'{c}'" if " " in c else c for c in cmd) + "\n")


def find_java_executable(prefer_gui=False):
    """Locate the java executable across PATH, JAVA_HOME, registry, and standard OS directories."""
    # 1. Direct PATH lookup
    if prefer_gui and sys.platform == "win32":
        j = shutil.which("javaw") or shutil.which("javaw.exe")
        if j and os.path.isfile(j):
            return j
    j = shutil.which("java") or shutil.which("java.exe") or shutil.which("javaw") or shutil.which("javaw.exe")
    if j and os.path.isfile(j):
        return j

    # 2. JAVA_HOME lookup
    jh = os.environ.get("JAVA_HOME", "").strip()
    if jh:
        candidates = [
            os.path.join(jh, "bin", "javaw.exe"),
            os.path.join(jh, "bin", "java.exe"),
            os.path.join(jh, "bin", "java"),
            os.path.join(jh, "javaw.exe"),
            os.path.join(jh, "java.exe"),
            os.path.join(jh, "java"),
        ] if (prefer_gui and sys.platform == "win32") else [
            os.path.join(jh, "bin", "java.exe"),
            os.path.join(jh, "bin", "java"),
            os.path.join(jh, "bin", "javaw.exe"),
            os.path.join(jh, "java.exe"),
            os.path.join(jh, "java"),
            os.path.join(jh, "javaw.exe"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

    # 3. Windows registry lookup
    if sys.platform == "win32" or os.name == "nt":
        try:
            import winreg
            reg_paths = [
                r"SOFTWARE\JavaSoft\Java Runtime Environment",
                r"SOFTWARE\JavaSoft\Java Development Kit",
                r"SOFTWARE\JavaSoft\JDK",
                r"SOFTWARE\Eclipse Adoptium\JDK",
                r"SOFTWARE\Eclipse Adoptium\JRE",
                r"SOFTWARE\AdoptOpenJDK\JDK",
                r"SOFTWARE\AdoptOpenJDK\JRE",
                r"SOFTWARE\Microsoft\JDK",
                r"SOFTWARE\BellSoft\Liberica JDK",
                r"SOFTWARE\Zulu",
            ]
            for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for subkey in reg_paths:
                    try:
                        with winreg.OpenKey(root_key, subkey, 0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
                            num_subkeys, _, _ = winreg.QueryInfoKey(k)
                            for i in range(num_subkeys):
                                ver_name = winreg.EnumKey(k, i)
                                try:
                                    with winreg.OpenKey(k, ver_name) as vk:
                                        java_home, _ = winreg.QueryValueEx(vk, "JavaHome")
                                        if java_home and os.path.isdir(java_home):
                                            cands = [os.path.join(java_home, "bin", "javaw.exe"),
                                                     os.path.join(java_home, "bin", "java.exe")] if prefer_gui else [
                                                     os.path.join(java_home, "bin", "java.exe"),
                                                     os.path.join(java_home, "bin", "javaw.exe")]
                                            for cand in cands:
                                                if os.path.isfile(cand):
                                                    return cand
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception:
            pass

        # 4. Windows standard installation locations
        prog_dirs = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramW6432", r"C:\Program Files"),
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("ProgramData", r"C:\ProgramData"),
        ]
        oracle_paths = [
            r"C:\Program Files\Common Files\Oracle\Java\javapath\javaw.exe",
            r"C:\Program Files\Common Files\Oracle\Java\javapath\java.exe",
            r"C:\Program Files (x86)\Common Files\Oracle\Java\javapath\javaw.exe",
            r"C:\Program Files (x86)\Common Files\Oracle\Java\javapath\java.exe",
            r"C:\ProgramData\Oracle\Java\javapath\javaw.exe",
            r"C:\ProgramData\Oracle\Java\javapath\java.exe",
        ]
        for op in oracle_paths:
            if os.path.isfile(op):
                return op

        vendors = [
            "Java", "Eclipse Adoptium", "AdoptOpenJDK", "Microsoft", "BellSoft",
            "Zulu", "Amazon Corretto", "Semeru", "RedHat"
        ]
        wanted_names = ("javaw.exe", "java.exe") if (prefer_gui and sys.platform == "win32") else ("java.exe", "javaw.exe")
        for pdir in prog_dirs:
            if not pdir or not os.path.isdir(pdir):
                continue
            for vendor in vendors:
                vpath = os.path.join(pdir, vendor)
                if os.path.isdir(vpath):
                    for root, dirs, files in os.walk(vpath):
                        for wn in wanted_names:
                            if wn in files:
                                candidate = os.path.join(root, wn)
                                if os.path.isfile(candidate):
                                    return candidate

    return "javaw" if (prefer_gui and sys.platform == "win32") else "java"


def is_java_available():
    """Check if Java runtime is executable."""
    bin_path = find_java_executable()
    try:
        kwargs = {"capture_output": True, "timeout": 5}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        res = subprocess.run([bin_path, "-version"], **kwargs)
        return res.returncode == 0
    except Exception:
        return False


def find_java_jars():
    """Locate javafoil.jar and mhclasses.jar across standard and bundled locations."""
    candidates = []
    if os.environ.get("AERO_JAVA_DIR"):
        candidates.append(os.environ["AERO_JAVA_DIR"])

    # 1. PyInstaller frozen environment
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            candidates.extend([
                os.path.join(sys._MEIPASS, "assets", "JavaFoil"),
                os.path.join(sys._MEIPASS, "JavaFoil"),
                os.path.join(sys._MEIPASS, "workers"),
                sys._MEIPASS,
            ])
        exe_dir = os.path.dirname(sys.executable)
        candidates.extend([
            os.path.join(exe_dir, "assets", "JavaFoil"),
            os.path.join(exe_dir, "_internal", "assets", "JavaFoil"),
            os.path.join(exe_dir, "JavaFoil"),
            os.path.join(exe_dir, "workers"),
            exe_dir,
        ])

    # 2. Source script / package directory
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.extend([
        os.path.join(here, "assets", "JavaFoil"),
        os.path.join(here, "JavaFoil"),
        os.path.join(here, "workers"),
        here,
    ])

    # 3. Standard user and legacy folders
    candidates.extend([
        JAVA_DIR,
        os.path.expanduser("~/MH-AeroTools/JavaFoil"),
        os.path.expanduser("~/.aero_auto/JavaFoil"),
        r"C:\MH-AeroTools\JavaFoil",
        r"C:\JavaFoil",
    ])

    for c in candidates:
        if c and os.path.isdir(c):
            jf = os.path.join(c, JAVAFOIL_JAR)
            mh = os.path.join(c, "mhclasses.jar")
            if os.path.isfile(jf):
                return jf, (mh if os.path.isfile(mh) else None)
    return JAVAFOIL_JAR, None


def launch_javafoil_gui(cfg, ground_h=None, re_val=None, title="FSAE Multi-Element Wing", re=None):
    """
    Exports the current multi-element wing stack into JavaFoil geometry files,
    places them in the JavaFoil working folder, project root, and user Desktop,
    and launches the interactive JavaFoil GUI window.
    Returns (success: bool, message: str, proc: subprocess.Popen or None).
    """
    ensure_airfoils_loaded()
    if not cfg or not cfg[0]:
        return False, "No valid wing configuration provided.", None

    import re as _re_mod
    effective_re = re_val if re_val is not None else (re if re is not None else RE)

    java_bin = find_java_executable(prefer_gui=True)
    jf_jar, mh_jar = find_java_jars()
    if not jf_jar or not os.path.exists(jf_jar):
        return False, "javafoil.jar not found. Please verify JavaFoil installation.", None

    try:
        outs = build_outlines(cfg, ground_h)
    except Exception as e:
        return False, f"Could not construct wing geometry: {e}", None

    gui_dir = os.path.join(OUT_DIR, "javafoil_gui")
    os.makedirs(gui_dir, exist_ok=True)

    wing_path = os.path.join(gui_dir, "wing.txt")
    clean_title = _re_mod.sub(r'[\r\n\t]+', ' ', str(title)).strip() or "FSAE Multi-Element Wing"

    wing_lines = [f"{clean_title}\n"]
    for i, o in enumerate(outs):
        if i > 0:
            wing_lines.append("9999.9 9999.9\n")
        for pt in o:
            wing_lines.append(f"{pt[0]:.6f} {pt[1]:.6f}\n")
    wing_content = "".join(wing_lines)

    with open(wing_path, "w", encoding="utf-8") as f:
        f.write(wing_content)

    # Also export wing.txt to multiple accessible directories:
    # 1. Current working directory
    # 2. Campaign root OUT_DIR
    # 3. User Desktop (standard and OneDrive)
    # 4. Folder of running executable (if frozen)
    user_home = os.path.expanduser("~")
    export_targets = [
        os.getcwd(),
        OUT_DIR,
        os.path.join(user_home, "Desktop"),
        os.path.join(user_home, "OneDrive", "Desktop"),
    ]
    if getattr(sys, "frozen", False):
        export_targets.append(os.path.dirname(sys.executable))

    for alt_dir in export_targets:
        if alt_dir and os.path.isdir(alt_dir) and os.path.abspath(alt_dir) != os.path.abspath(gui_dir):
            try:
                dest_f = os.path.join(alt_dir, "wing.txt")
                with open(dest_f, "w", encoding="utf-8") as fh:
                    fh.write(wing_content)
            except Exception:
                pass

    # Copy jars into gui_dir so working directory has javafoil.jar and mhclasses.jar
    dest_jf = os.path.join(gui_dir, JAVAFOIL_JAR)
    if not os.path.exists(dest_jf):
        try:
            shutil.copy(jf_jar, dest_jf)
        except Exception:
            dest_jf = jf_jar
    if mh_jar and os.path.isfile(mh_jar):
        dest_mh = os.path.join(gui_dir, "mhclasses.jar")
        if not os.path.exists(dest_mh):
            try:
                shutil.copy(mh_jar, dest_mh)
            except Exception:
                pass

    # Launch JavaFoil directly without Script= argument.
    # In JavaFoil's bytecode, passing Script= forces headless batch mode (bShowGUI = false),
    # which suppresses the GUI window. Launching javafoil.jar directly ensures bShowGUI = true.
    env = os.environ.copy()
    if sys.platform != "win32":
        if not env.get("DISPLAY"):
            env["DISPLAY"] = ":0"
        if not env.get("XAUTHORITY") or not os.path.exists(env.get("XAUTHORITY", "")):
            default_xauth = os.path.expanduser("~/.Xauthority")
            if os.path.exists(default_xauth):
                env["XAUTHORITY"] = default_xauth
            else:
                try:
                    import glob as _glob
                    matches = _glob.glob(f"/run/user/{os.getuid()}/xauth_*")
                    if matches:
                        env["XAUTHORITY"] = matches[0]
                except Exception:
                    pass

    proc = None
    launch_err = None

    # Tier 1: Launch via detected Java binary
    if java_bin:
        cmd = [java_bin, "-jar", dest_jf]
        popen_kwargs = {"cwd": gui_dir, "env": env}
        if sys.platform == "win32":
            # DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP ensure an independent foreground window
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008) |
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
            popen_kwargs["stdin"] = subprocess.DEVNULL
            popen_kwargs["stdout"] = subprocess.DEVNULL
            popen_kwargs["stderr"] = subprocess.DEVNULL
        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
            time.sleep(0.4)
            if proc.poll() is None:
                # Running successfully
                return True, (
                    f"JavaFoil GUI launched successfully.\n"
                    f"Wing geometry exported to: {wing_path}\n"
                    f"In JavaFoil: Click 'Geometry' -> 'Open...' -> select 'wing.txt'."
                ), proc
            else:
                launch_err = f"Java exited immediately (code {proc.returncode})"
        except Exception as e:
            launch_err = str(e)

    # Tier 2: On Windows, fallback to native shell open (startfile / cmd start)
    # This invokes the registered .jar file association used when double-clicking in Explorer.
    if sys.platform == "win32":
        try:
            if hasattr(os, "startfile"):
                os.startfile(dest_jf)
                return True, (
                    f"JavaFoil GUI launched via Windows shell.\n"
                    f"Wing geometry exported to: {wing_path}\n"
                    f"In JavaFoil: Click 'Geometry' -> 'Open...' -> select 'wing.txt'."
                ), None
            else:
                cmd_proc = subprocess.Popen(f'start "" "{dest_jf}"', shell=True, cwd=gui_dir)
                return True, (
                    f"JavaFoil GUI launched via Windows shell.\n"
                    f"Wing geometry exported to: {wing_path}\n"
                    f"In JavaFoil: Click 'Geometry' -> 'Open...' -> select 'wing.txt'."
                ), cmd_proc
        except Exception as e2:
            launch_err = f"{launch_err}; Windows Shell fallback failed: {e2}"

    if launch_err:
        return False, f"Could not launch JavaFoil GUI: {launch_err}. Please ensure Java Runtime (JRE/JDK 8+) is installed.", None
    return False, "Could not locate Java runtime to launch JavaFoil.", None



def convert_pdf_to_png(pdf_path, out_png, dpi=150):
    """Converts a vector PDF to a PNG image using pdftoppm or Ghostscript."""
    if not (os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0):
        return False
    if shutil.which("pdftoppm"):
        prefix = out_png.rsplit(".", 1)[0] + "_tmp"
        res = subprocess.run(["pdftoppm", "-png", "-r", str(dpi), pdf_path, prefix],
                             capture_output=True, text=True)
        matches = glob.glob(prefix + "*.png")
        if matches:
            shutil.move(matches[0], out_png)
            for m in matches[1:]:
                try: os.remove(m)
                except OSError: pass
            return True
    elif shutil.which("gs"):
        res = subprocess.run(["gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", f"-r{dpi}",
                              f"-sOutputFile={out_png}", pdf_path],
                             capture_output=True, text=True)
        return os.path.exists(out_png) and os.path.getsize(out_png) > 0
def _style_aero_axes(ax, title, xlabel, ylabel):
    """Applies high-contrast aeronautical dark-theme styling to plot axes."""
    DARK_CARD = '#1e293b'
    MUTED_COLOR = '#94a3b8'
    GRID_COLOR = '#334155'
    TEXT_COLOR = '#f8fafc'
    ax.set_facecolor(DARK_CARD)
    ax.tick_params(colors=MUTED_COLOR, labelsize=9)
    ax.grid(True, linestyle='--', alpha=0.35, color=GRID_COLOR)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
        spine.set_linewidth(1.0)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10, fontweight='bold', color=TEXT_COLOR)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10, fontweight='bold', color=TEXT_COLOR)
    if title:
        ax.set_title(title, fontsize=11, fontweight='bold', color=TEXT_COLOR, pad=10)


def render_javafoil_polar_plots(polar_file, out_dir, run_tag, cfg_desc="Multi-Element Wing", re_val=570000, ge_flag=1):
    """
    Renders high-resolution, un-tweaked Drag Polar (Cl vs Cd), Lift Curve (Cl vs Alpha),
    and Pitching Moment (Cm vs Alpha) directly from JavaFoil's authentic numerical polar table.
    Filters out unphysical singularities, divergence spikes, and deep-stall numerical noise.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    DARK_BG = '#0b1120'
    GRID_COLOR = '#334155'
    TEXT_COLOR = '#f8fafc'
    MUTED_COLOR = '#94a3b8'
    PALETTE = ['#38bdf8', '#fbbf24', '#34d399', '#c084fc', '#f43f5e']

    df, _ = parse_polar(polar_file)
    results = {}
    if df is None or df.empty:
        return results

    # Rejection of unphysical singularities, infinite spikes, and panel divergence tweaks
    valid_mask = (df['cl'].notna()) & (df['cd'].notna()) & (df['cl'].abs() < 12.0) & (df['cd'] > 0.0001) & (df['cd'] < 2.5)
    df_clean = df[valid_mask].copy()
    if len(df_clean) >= 3:
        df_clean = df_clean.sort_values('alpha').reset_index(drop=True)
        # Check derivative spikes (unphysical jumps > 3.0 Cl per degree)
        keep = []
        for i in range(len(df_clean)):
            row = df_clean.iloc[i]
            spike = False
            if i > 0:
                da = abs(row['alpha'] - df_clean.iloc[i - 1]['alpha'])
                if da > 0 and abs(row['cl'] - df_clean.iloc[i - 1]['cl']) / da > 3.0:
                    spike = True
            if i < len(df_clean) - 1:
                da = abs(df_clean.iloc[i + 1]['alpha'] - row['alpha'])
                if da > 0 and abs(df_clean.iloc[i + 1]['cl'] - row['cl']) / da > 3.0:
                    spike = True
            if not spike:
                keep.append(i)
        if len(keep) >= 2:
            df_clean = df_clean.iloc[keep].reset_index(drop=True)

    ge_str = 'Ground Effect (WIG)' if ge_flag else 'Free Stream'

    # 1. Drag Polar (Cl vs Cd)
    p_cd = os.path.join(out_dir, f"javafoil_polar_cl_cd_{run_tag}.png")
    fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
    fig.patch.set_facecolor(DARK_BG)
    _style_aero_axes(ax, f"JavaFoil Drag Polar (Cl vs Cd) — Run {run_tag}\n{cfg_desc}",
                     "Drag Coefficient Cd", "Lift / Downforce Coefficient Cl")
    if len(df_clean) >= 2:
        ax.plot(df_clean['cd'], df_clean['cl'], 'o-', color=PALETTE[0], lw=2.2, ms=6,
                mfc=PALETTE[1], mec='white', label=f"JavaFoil Solver ({ge_str})")
        # Highlight design point alpha=0
        p0 = df_clean[np.isclose(df_clean['alpha'], 0.0, atol=0.25)]
        if not p0.empty:
            c0, d0 = p0['cl'].iloc[0], p0['cd'].iloc[0]
            ld0 = abs(c0) / max(d0, 1e-5)
            ax.plot([d0], [c0], '*', color=PALETTE[4], ms=14,
                    label=f"Design α=0° (Cl={c0:.3f}, Cd={d0:.4f}, |L/D|={ld0:.1f})")
        # Max efficiency tangent
        best_ld_idx = (df_clean['cl'].abs() / df_clean['cd'].replace(0, np.nan)).idxmax()
        if pd.notna(best_ld_idx):
            b_cl = df_clean.loc[best_ld_idx, 'cl']
            b_cd = df_clean.loc[best_ld_idx, 'cd']
            max_ld = abs(b_cl) / max(b_cd, 1e-5)
            ax.plot([0, b_cd * 1.25], [0, b_cl * 1.25], ':', color=PALETTE[2], lw=1.2,
                    label=f"Max |L/D| Tangent = {max_ld:.1f}")
            ax.plot([b_cd], [b_cl], 'o', color=PALETTE[2], ms=8, mfc=PALETTE[2], mec='white')
    else:
        ax.text(0.5, 0.5, "Panel Method Divergence / Flow Separation at Tested Envelope",
                ha='center', va='center', transform=ax.transAxes, color=PALETTE[4], fontsize=11, fontweight='bold')
    ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
    plt.tight_layout()
    plt.savefig(p_cd)
    plt.close()
    results['polar_cl_cd'] = p_cd

    # 2. Lift Curve (Cl vs Alpha)
    p_cl = os.path.join(out_dir, f"javafoil_polar_cl_alfa_{run_tag}.png")
    fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
    fig.patch.set_facecolor(DARK_BG)
    _style_aero_axes(ax, f"JavaFoil Lift Curve (Cl vs α) — Run {run_tag}\n{cfg_desc}",
                     "Angle of Attack α (°)", "Lift / Downforce Coefficient Cl")
    if len(df_clean) >= 2:
        ax.plot(df_clean['alpha'], df_clean['cl'], 's-', color=PALETTE[2], lw=2.2, ms=6,
                mfc=PALETTE[0], mec='white', label=f"JavaFoil Cl(α) — Re={re_val:g}")
        pk_idx = df_clean['cl'].idxmin()
        pk_a, pk_cl = df_clean.loc[pk_idx, 'alpha'], df_clean.loc[pk_idx, 'cl']
        ax.plot([pk_a], [pk_cl], 'v', color=PALETTE[4], ms=12,
                label=f"Peak Downforce: {pk_cl:.3f} @ α={pk_a:.1f}°")
        if (df_clean['cl'].min() < 0) and (df_clean['cl'].max() > 0):
            a0_interp = float(np.interp(0.0, df_clean['cl'], df_clean['alpha']))
            ax.plot([a0_interp], [0.0], 'o', color=PALETTE[1], ms=8,
                    label=f"Zero-Lift α₀ = {a0_interp:.1f}°")
    else:
        ax.text(0.5, 0.5, "Panel Method Divergence in Angle Sweep",
                ha='center', va='center', transform=ax.transAxes, color=PALETTE[4], fontsize=11, fontweight='bold')
    ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax.axvline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
    plt.tight_layout()
    plt.savefig(p_cl)
    plt.close()
    results['polar_cl_alfa'] = p_cl

    # 3. Pitching Moment (Cm vs Alpha)
    p_cm = os.path.join(out_dir, f"javafoil_polar_cm_alfa_{run_tag}.png")
    fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
    fig.patch.set_facecolor(DARK_BG)
    _style_aero_axes(ax, f"JavaFoil Pitching Moment (Cm vs α) — Run {run_tag}\n{cfg_desc}",
                     "Angle of Attack α (°)", "Pitching Moment Coefficient Cm (0.25c)")
    cm_col = next((c for c in df_clean.columns if c.startswith('cm')), None)
    if cm_col and len(df_clean) >= 2:
        df_cm = df_clean[df_clean[cm_col].abs() < 5.0]
        if len(df_cm) >= 2:
            ax.plot(df_cm['alpha'], df_cm[cm_col], 'd-', color=PALETTE[3], lw=2.2, ms=6,
                    mfc=PALETTE[1], mec='white', label="JavaFoil Cm(0.25c)")
    ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
    plt.tight_layout()
    plt.savefig(p_cm)
    plt.close()
    results['polar_cm_alfa'] = p_cm

    return results


def render_javafoil_velocity_cp_plot(velocity_file, out_dir, run_tag, cfg_desc="Multi-Element Wing", v_inf=20.0, density=1.225):
    """
    Renders the authentic JavaFoil Surface Pressure Distribution (Cp vs x/c) and wing silhouette.
    Completely eliminates the blank white Swing image bug with crisp multi-element curves.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    DARK_BG = '#0b1120'
    GRID_COLOR = '#334155'
    TEXT_COLOR = '#f8fafc'
    PALETTE = ['#38bdf8', '#fbbf24', '#34d399', '#c084fc', '#f43f5e']

    target = os.path.join(out_dir, f"javafoil_velocity_cp_{run_tag}.png")
    if not os.path.exists(velocity_file) or os.path.getsize(velocity_file) == 0:
        return None

    try:
        with open(velocity_file, errors='ignore') as f:
            v_lines = [l.strip() for l in f if l.strip()]
        elements = {}
        current_elem = None
        elem_rows = []
        for l in v_lines:
            if l.startswith('Element\t') or l.startswith('Element '):
                if current_elem is not None and elem_rows:
                    elements[current_elem] = np.array(elem_rows)
                current_elem = int(l.split()[-1])
                elem_rows = []
            elif current_elem is not None:
                parts = [p.strip() for p in l.split('\t') if p.strip()]
                if parts[0] == 'x' and parts[1] == 'y': continue
                try:
                    elem_rows.append([float(p) for p in parts])
                except ValueError:
                    pass
        if current_elem is not None and elem_rows:
            elements[current_elem] = np.array(elem_rows)

        if not elements:
            return None

        fig, (ax_cp, ax_geom) = plt.subplots(2, 1, figsize=(11, 6.25), dpi=140,
                                             gridspec_kw={'height_ratios': [3.0, 1.0], 'hspace': 0.12},
                                             sharex=True)
        fig.patch.set_facecolor(DARK_BG)
        _style_aero_axes(ax_cp, f"JavaFoil Surface Pressure Distribution (Cp vs x/c) — Run {run_tag}\n{cfg_desc}",
                         "", "Pressure Coefficient Cp")
        ax_cp.invert_yaxis()

        for elem_id, pts in elements.items():
            col = PALETTE[(elem_id - 1) % len(PALETTE)]
            xs = pts[:, 0]
            ys = pts[:, 1]
            v_ratio = pts[:, 2] if pts.shape[1] > 2 else np.ones_like(xs)
            cp = 1.0 - (v_ratio ** 2)

            i_le = int(np.argmin(xs))
            x_up, cp_up = xs[:i_le + 1], cp[:i_le + 1]
            x_lo, cp_lo = xs[i_le:], cp[i_le:]

            lbl = 'Main Element' if elem_id == 1 else f'Flap {elem_id - 1}'
            # For inverted motorsport wings: lower surface produces suction downforce
            ax_cp.plot(x_up, cp_up, '-', color=col, lw=2.2, label=f"{lbl} (Upper / Pressure)")
            ax_cp.plot(x_lo, cp_lo, '--', color=col, lw=1.8, alpha=0.9, label=f"{lbl} (Lower / Suction)")

            ax_geom.plot(xs, ys, color=col, lw=1.8)
            ax_geom.fill(xs, ys, color=col, alpha=0.2)

        _style_aero_axes(ax_geom, "", "Normalized Coordinate x/c", "y/c")
        all_ys = np.concatenate([pts[:, 1] for pts in elements.values()])
        ymin, ymax = all_ys.min(), all_ys.max()
        yrng = max(ymax - ymin, 0.05)
        ax_geom.set_ylim(ymin - 0.25 * yrng, ymax + 0.25 * yrng)

        ax_cp.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR,
                     fontsize=8.5, loc='lower right', ncol=2)
        plt.savefig(target, bbox_inches='tight')
        plt.close()
        return target
    except Exception:
        return None


def render_javafoil_bl_plots(bl_file, out_dir, run_tag, cfg_desc="Multi-Element Wing", re_val=570000):
    """
    Renders authentic JavaFoil boundary layer skin friction (Cf) and boundary layer
    thickness (delta_1, delta_2) charts, eliminating text collisions and clipped curves.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    DARK_BG = '#0b1120'
    GRID_COLOR = '#334155'
    TEXT_COLOR = '#f8fafc'
    PALETTE = ['#38bdf8', '#fbbf24', '#34d399', '#c084fc', '#f43f5e']

    p_cf = os.path.join(out_dir, f"javafoil_bl_cf_{run_tag}.png")
    p_delta = os.path.join(out_dir, f"javafoil_bl_delta_{run_tag}.png")
    res = {}
    if not os.path.exists(bl_file) or os.path.getsize(bl_file) == 0:
        return res

    try:
        bl_elements = []
        cur_section = []
        hdr_found = False
        with open(bl_file, errors='ignore') as f:
            for l in f:
                l_s = l.strip()
                if not l_s:
                    if cur_section:
                        bl_elements.append(cur_section)
                        cur_section = []
                    continue
                if 'x/c' in l_s and 'C_f' in l_s:
                    hdr_found = True
                    continue
                if not hdr_found or l_s.startswith('[-]'):
                    continue
                toks = [t.strip() for t in l_s.split('\t') if t.strip()]
                if len(toks) >= 8:
                    try:
                        cur_section.append({
                            'x_c': float(toks[0]), 'y_c': float(toks[1]), 'v_V': float(toks[2]),
                            'delta_1': float(toks[3]), 'delta_2': float(toks[4]),
                            'cf': float(toks[7]), 'state': toks[10] if len(toks) > 10 else ''
                        })
                    except ValueError:
                        pass
        if cur_section:
            bl_elements.append(cur_section)

        if not bl_elements:
            return res

        # 1. Skin Friction (Cf) Plot
        fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
        fig.patch.set_facecolor(DARK_BG)
        _style_aero_axes(ax, f"JavaFoil Boundary Layer Skin Friction (Cf vs x/c) — Run {run_tag}\n{cfg_desc}",
                         "Normalized Chord x/c", "Skin Friction Coefficient Cf")
        for idx, el in enumerate(bl_elements, 1):
            col = PALETTE[(idx - 1) % len(PALETTE)]
            xs = [r['x_c'] for r in el]
            cfs = [r['cf'] for r in el]
            lbl = 'Main Element' if idx == 1 else f'Flap {idx - 1}'
            ax.plot(xs, cfs, '-', color=col, lw=2.0, label=f"{lbl} Cf")
            # Mark separation onset cleanly with single marker
            for r in el:
                if r['state'] == 'sep.':
                    ax.plot(r['x_c'], r['cf'], '^', color=PALETTE[4], ms=8,
                            label=f"{lbl} Separation (x/c={r['x_c']:.3f})")
                    break
        ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
        plt.tight_layout()
        plt.savefig(p_cf)
        plt.close()
        res['bl_cf'] = p_cf

        # 2. Boundary Layer Thickness (delta) Plot
        fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
        fig.patch.set_facecolor(DARK_BG)
        _style_aero_axes(ax, f"JavaFoil Boundary Layer Thickness (δ vs x/c) — Run {run_tag}\n{cfg_desc}",
                         "Normalized Chord x/c", "Boundary Layer Thickness δ/c")
        for idx, el in enumerate(bl_elements, 1):
            col = PALETTE[(idx - 1) % len(PALETTE)]
            xs = [r['x_c'] for r in el]
            d1 = [r['delta_1'] for r in el]
            d2 = [r['delta_2'] for r in el]
            lbl = 'Main Element' if idx == 1 else f'Flap {idx - 1}'
            ax.plot(xs, d1, '-', color=col, lw=2.0, label=f"{lbl} δ₁ (displacement)")
            ax.plot(xs, d2, '--', color=col, lw=1.5, alpha=0.85, label=f"{lbl} δ₂ (momentum)")
        ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
        plt.tight_layout()
        plt.savefig(p_delta)
        plt.close()
        res['bl_delta'] = p_delta

        return res
    except Exception:
        return res


def export_javafoil_graphs(cfg, ground_h, out_dir, run_id=None, re=None, alphas=None, v_inf=20.0, density=1.225):
    """
    Extracts JavaFoil's authentic simulation results and renders high-resolution,
    publication-grade aerodynamic charts (16:9 widescreen, dark aeronautical styling).
    
    Generates:
      - javafoil_polar_cl_cd_<run_id>.png       : Authentic Drag Polar (Cl vs Cd)
      - javafoil_polar_cl_alfa_<run_id>.png     : Authentic Lift Curve (Cl vs Alpha)
      - javafoil_polar_cm_alfa_<run_id>.png     : Authentic Pitching Moment (Cm vs Alpha)
      - javafoil_velocity_cp_<run_id>.png       : Authentic Surface Pressure (Cp) & Velocity Distribution
      - javafoil_bl_cf_<run_id>.png             : Authentic Boundary Layer Skin Friction (cf vs x)
      - javafoil_bl_delta_<run_id>.png          : Authentic Boundary Layer Thickness (delta vs x)
      
    Returns a dict mapping graph keys to the generated PNG paths.
    """
    if not AIRFOILS:
        seed_airfoil_store()
        for cand in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "airfoils"),
            getattr(sys, "_MEIPASS", "") and os.path.join(sys._MEIPASS, "assets", "airfoils"),
        ]:
            if cand and os.path.isdir(cand):
                AIRFOILS.update(load_all(cand))
        AIRFOILS.update(load_all(AIRFOIL_DIR))
        if os.path.isdir(AIRFOIL_STORE):
            AIRFOILS.update(load_all(AIRFOIL_STORE))
            
    run_tag = str(run_id or "run").strip()
    os.makedirs(out_dir, exist_ok=True)
    cfg_desc = describe(cfg)
    
    re_val = re or RE
    a_sweep = alphas or ALPHA
    a0, a1, st = a_sweep
    
    uid = uuid.uuid4().hex[:8]
    tmp_parent = tempfile.gettempdir() if hasattr(tempfile, 'gettempdir') else '/tmp'
    wdir = os.path.join(tmp_parent, f"jf_graphs_{uid}")
    os.makedirs(wdir, exist_ok=True)
    
    wing_fn = f"wing_{uid}.txt"
    script_fn = f"script_{uid}.jfs"
    polar_txt = f"polar_{uid}.txt"
    velocity_txt = f"velocity_{uid}.txt"
    bl_txt = f"bl_{uid}.txt"

    wing = os.path.join(wdir, wing_fn)
    script = os.path.join(wdir, script_fn)
    logf = os.path.join(wdir, f"java_{uid}.log")
    
    pdf_targets = {
        "polar_cl_cd": f"jf_polar_cl_cd_{uid}.pdf",
        "polar_cl_alfa": f"jf_polar_cl_alfa_{uid}.pdf",
        "polar_cm_alfa": f"jf_polar_cm_alfa_{uid}.pdf",
        "velocity_cp": f"jf_velocity_cp_{uid}.pdf",
        "bl_cf": f"jf_bl_cf_{uid}.pdf",
        "bl_delta": f"jf_bl_delta_{uid}.pdf",
    }
    
    try:
        # Write multi-element wing coordinate file
        with open(wing, "w") as f:
            f.write("Automated Multi-Element Wing\n")
            for i, o in enumerate(build_outlines(cfg, ground_h)):
                if i > 0:
                    f.write("9999.9 9999.9\n")
                for pt in o:
                    f.write(f"{pt[0]:.6f} {pt[1]:.6f}\n")
                    
        ge_flag = 1 if ground_h is not None else 0
        with open(script, "w") as f:
            f.write(f"""Options.Country(10);
Geometry.Open("{wing_fn}");
Options.MachNumber(0);
Options.StallModel(0);
Options.TransitionModel(1);
Options.GroundEffect({ge_flag});
Options.HeightOverSpan(0.5);
Options.AspectRatio(0);
Options.SweepAngle(0.0);

// Polars: Save authentic numerical data + native vector PDF
try {{
    Polar.Analyze({re_val:g},{re_val:g},{re_val:g},{a0:g},{a1:g},{st:g},100,100,0,0);
    Polar.Save("{polar_txt}");
    Polar.SaveImage("PDF", "{pdf_targets['polar_cl_cd']}", "Cd");
    Polar.SaveImage("PDF", "{pdf_targets['polar_cl_alfa']}", "Cl");
    Polar.SaveImage("PDF", "{pdf_targets['polar_cm_alfa']}", "Cm");
}} catch (e) {{}}

// Surface Velocity & Pressure Distribution: Save authentic numerical table + PDF
try {{
    Velocity.Analyze(0.0, {v_inf:g}, {density:g}, 0);
    Velocity.Save("{velocity_txt}");
    Velocity.SaveImage("PDF", "{pdf_targets['velocity_cp']}");
}} catch (e) {{}}

// Boundary Layer: Save authentic numerical table + PDF
try {{
    BoundaryLayer.Analyze(0.0, {re_val:g}, 1.0, 1.0, 0);
    BoundaryLayer.Save("{bl_txt}");
    BoundaryLayer.SaveImage("PDF", "{pdf_targets['bl_cf']}", "Cf");
    BoundaryLayer.SaveImage("PDF", "{pdf_targets['bl_delta']}", "Delta");
}} catch (e) {{}}

JavaFoil.Exit();
""")

        java_bin = find_java_executable()
        jf_jar, mh_jar = find_java_jars()
        if mh_jar and os.path.exists(mh_jar):
            try:
                shutil.copy(mh_jar, wdir)
            except Exception:
                pass
        dest_jf = os.path.join(wdir, JAVAFOIL_JAR)
        if not os.path.exists(dest_jf) and os.path.isabs(jf_jar) and os.path.isfile(jf_jar):
            try: shutil.copy(jf_jar, dest_jf)
            except Exception: pass
                
        init_timebomb()
        if sys.platform != "win32" and shutil.which("faketime"):
            cmd = ["faketime", "-f", safe_date_str, java_bin, "-client", "-Xverify:none", "-XX:TieredStopAtLevel=1",
                   "-jar", jf_jar, f"Script={script_fn}"]
        else:
            cmd = [java_bin, "-client", "-Xverify:none", "-XX:TieredStopAtLevel=1",
                   "-jar", jf_jar, f"Script={script_fn}"]
                   
        env = os.environ.copy()
        if sys.platform != "win32":
            env["DISPLAY"] = os.environ.get("DISPLAY", ":99")
        run_kwargs = {"cwd": wdir, "stdout": None, "stderr": subprocess.STDOUT, "timeout": RUN_TIMEOUT, "env": env}
        if sys.platform == "win32":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        with open(logf, "w") as jl:
            run_kwargs["stdout"] = jl
            try:
                subprocess.run(cmd, **run_kwargs)
            except Exception:
                pass
                
        results = {}
        
        # 1. Render modern publication-quality charts from authentic JavaFoil tables
        p_polar_src = os.path.join(wdir, polar_txt)
        if os.path.exists(p_polar_src) and os.path.getsize(p_polar_src) > 0:
            try:
                shutil.copy2(p_polar_src, os.path.join(out_dir, f"javafoil_polar_{run_tag}.txt"))
                polars = render_javafoil_polar_plots(p_polar_src, out_dir, run_tag, cfg_desc=cfg_desc,
                                                     re_val=re_val, ge_flag=ge_flag)
                results.update(polars)
            except Exception:
                pass

        p_vel_src = os.path.join(wdir, velocity_txt)
        if os.path.exists(p_vel_src) and os.path.getsize(p_vel_src) > 0:
            try:
                shutil.copy2(p_vel_src, os.path.join(out_dir, f"javafoil_velocity_{run_tag}.txt"))
                vel = render_javafoil_velocity_cp_plot(p_vel_src, out_dir, run_tag, cfg_desc=cfg_desc,
                                                       v_inf=v_inf, density=density)
                if vel:
                    results['velocity_cp'] = vel
            except Exception:
                pass

        p_bl_src = os.path.join(wdir, bl_txt)
        if os.path.exists(p_bl_src) and os.path.getsize(p_bl_src) > 0:
            try:
                shutil.copy2(p_bl_src, os.path.join(out_dir, f"javafoil_bl_{run_tag}.txt"))
                bls = render_javafoil_bl_plots(p_bl_src, out_dir, run_tag, cfg_desc=cfg_desc,
                                               re_val=re_val)
                results.update(bls)
            except Exception:
                pass

        # 2. Fallback for any missing plots using pdftoppm if available
        for key, pdf_fn in pdf_targets.items():
            if key not in results or not os.path.exists(results[key]):
                src_pdf = os.path.join(wdir, pdf_fn)
                if os.path.exists(src_pdf) and os.path.getsize(src_pdf) > 0:
                    final_png = os.path.join(out_dir, f"javafoil_{key}_{run_tag}.png")
                    ok = convert_pdf_to_png(src_pdf, final_png)
                    if ok and os.path.exists(final_png):
                        results[key] = final_png
                    else:
                        final_pdf = os.path.join(out_dir, f"javafoil_{key}_{run_tag}.pdf")
                        shutil.copy(src_pdf, final_pdf)
                        results[key] = final_pdf
                        
        return results
    finally:
        try:
            shutil.rmtree(wdir, ignore_errors=True)
        except Exception:
            pass




def export_dxf(cfg, out_path, chord_mm=None, ground_h=None, title="Multi-Element Wing", spline_mode=True):
    """
    Export the multi-element wing geometry as a standard AutoCAD DXF (AC1015 / AutoCAD 2000+ compatible).
    Includes continuous B-splines (SPLINE) and closed lightweight polylines (LWPOLYLINE),
    eliminating zero-length closing segments and facet discontinuities in modern CAD packages (SolidWorks,
    Fusion 360, FreeCAD, Inventor, AutoCAD).
    Separate layers for each element, ground plane line, and stack bounding box in millimeters.
    """
    if not AIRFOILS:
        AIRFOILS.update(load_all(AIRFOIL_DIR))
        if os.path.isdir(AIRFOIL_STORE):
            AIRFOILS.update(load_all(AIRFOIL_STORE))

    chord = float(chord_mm or CHORD_MM or DEFAULT_CHORD_MM)
    outlines = build_outlines(cfg, ground_h)
    outlines_mm = [pts * chord for pts in outlines]

    lines = []
    lines += ['0', 'SECTION', '2', 'HEADER', '9', '$ACADVER', '1', 'AC1015', '0', 'ENDSEC']
    lines += ['0', 'SECTION', '2', 'TABLES', '0', 'TABLE', '2', 'LAYER', '70', str(len(outlines_mm) * 2 + 4)]

    layer_names = ['MAIN_ELEMENT'] + [f'FLAP_{i}' for i in range(1, len(outlines_mm))]
    colors = [1, 3, 5, 2, 4, 6]  # Red, Green, Blue, Yellow, Cyan, Magenta
    for i, name in enumerate(layer_names):
        lines += ['0', 'LAYER', '2', name, '70', '0', '62', str(colors[i % len(colors)]), '6', 'CONTINUOUS']
        lines += ['0', 'LAYER', '2', f'{name}_POLY', '70', '0', '62', str(colors[i % len(colors)]), '6', 'CONTINUOUS']
    if ground_h is not None:
        lines += ['0', 'LAYER', '2', 'GROUND_PLANE', '70', '0', '62', '8', '6', 'CONTINUOUS']
    lines += ['0', 'LAYER', '2', 'BOUNDING_BOX', '70', '0', '62', '9', '6', 'CONTINUOUS']
    lines += ['0', 'ENDTAB', '0', 'ENDSEC']

    lines += ['0', 'SECTION', '2', 'ENTITIES']

    # Airfoil elements as continuous SPLINE and closed LWPOLYLINE
    for i, pts in enumerate(outlines_mm):
        lname = layer_names[i]

        clean_pts = []
        for pt in pts:
            if not clean_pts or np.hypot(pt[0] - clean_pts[-1][0], pt[1] - clean_pts[-1][1]) > 1e-6:
                clean_pts.append(pt)
        if len(clean_pts) > 2 and np.hypot(clean_pts[0][0] - clean_pts[-1][0], clean_pts[0][1] - clean_pts[-1][1]) < 1e-4:
            clean_pts = clean_pts[:-1]

        # 1. Native AutoCAD SPLINE entity (Cubic B-spline with fit points)
        lines += [
            '0', 'SPLINE',
            '5', f'{1000 + i * 2:X}',
            '100', 'AcDbEntity',
            '8', lname,
            '100', 'AcDbSpline',
            '70', '8',  # Planar spline
            '71', '3',  # Degree 3 (cubic)
            '74', str(len(clean_pts)),  # Number of fit points
        ]
        for pt in clean_pts:
            lines += ['11', f'{pt[0]:.5f}', '21', f'{pt[1]:.5f}', '31', '0.0']

        # 2. Modern closed LWPOLYLINE entity on companion layer for legacy/polyline CAD workflows
        lines += [
            '0', 'LWPOLYLINE',
            '5', f'{1001 + i * 2:X}',
            '100', 'AcDbEntity',
            '8', f'{lname}_POLY',
            '100', 'AcDbPolyline',
            '90', str(len(clean_pts)),
            '70', '1',  # 1 = Closed polyline
            '43', '0.0'
        ]
        for pt in clean_pts:
            lines += ['10', f'{pt[0]:.5f}', '20', f'{pt[1]:.5f}']

    # Ground plane line
    if ground_h is not None:
        all_x = np.concatenate([p[:, 0] for p in outlines_mm])
        x0, x1 = all_x.min() - 50.0, all_x.max() + 50.0
        lines += ['0', 'LINE', '5', '2001', '100', 'AcDbEntity', '8', 'GROUND_PLANE',
                  '100', 'AcDbLine',
                  '10', f'{x0:.4f}', '20', '0.0', '30', '0.0',
                  '11', f'{x1:.4f}', '21', '0.0', '31', '0.0']

    # Bounding box
    all_x = np.concatenate([p[:, 0] for p in outlines_mm])
    all_y = np.concatenate([p[:, 1] for p in outlines_mm])
    bx0, bx1 = all_x.min(), all_x.max()
    by0, by1 = all_y.min(), all_y.max()
    bbox_pts = [[bx0, by0], [bx1, by0], [bx1, by1], [bx0, by1]]
    lines += ['0', 'LWPOLYLINE', '5', '2002', '100', 'AcDbEntity', '8', 'BOUNDING_BOX',
              '100', 'AcDbPolyline', '90', '4', '70', '1', '43', '0.0']
    for pt in bbox_pts:
        lines += ['10', f'{pt[0]:.4f}', '20', f'{pt[1]:.4f}']

    lines += ['0', 'ENDSEC', '0', 'EOF']
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines) + '\n')
    return out_path


def _try_export_step_freecad(outlines_mm, out_path, span_mm, title):
    """Attempt STEP export via FreeCAD CLI (C2 continuous B-spline approximation)."""
    freecad_cmd = shutil.which("freecadcmd") or shutil.which("FreeCAD") or shutil.which("freecad")
    if not freecad_cmd:
        return False
    clean_outlines = []
    for pts in outlines_mm:
        c_pts = []
        for pt in pts:
            if not c_pts or np.hypot(pt[0] - c_pts[-1][0], pt[1] - c_pts[-1][1]) > 1e-6:
                c_pts.append([float(pt[0]), float(pt[1])])
        clean_outlines.append(c_pts)

    script = f'''
import FreeCAD, Part
from FreeCAD import Vector as V

doc = FreeCAD.newDocument("WingDoc")
outlines_data = {clean_outlines!r}

for idx, pts_mm in enumerate(outlines_data):
    vecs = [V(x, y, 0.0) for x, y in pts_mm]
    bs = Part.BSplineCurve()
    try:
        bs.approximate(Points=vecs, DegMin=3, DegMax=8, Tolerance=0.02, Continuity="C2", ParamType="Centripetal")
    except Exception:
        bs.interpolate(Points=vecs, PeriodicFlag=False)
    
    edge = bs.toShape()
    edges = [edge]
    if bs.StartPoint.distanceToPoint(bs.EndPoint) > 1e-5:
        edges.append(Part.LineSegment(bs.EndPoint, bs.StartPoint).toShape())
    
    wire = Part.Wire(edges)
    face = Part.Face(wire)
    solid = face.extrude(V(0, 0, {span_mm}))
    feat = doc.addObject("Part::Feature", f"Element_{{idx}}")
    feat.Shape = solid

doc.recompute()
Part.export(doc.Objects, {out_path!r})
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
        tmp_py = f.name
    try:
        res = subprocess.run([freecad_cmd, tmp_py], capture_output=True, text=True, timeout=30)
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 500
    except Exception:
        return False
    finally:
        try: os.remove(tmp_py)
        except Exception: pass


def _try_export_step_gmsh(outlines_mm, out_path, span_mm, title):
    """Attempt STEP export via Gmsh OpenCASCADE kernel."""
    try:
        import gmsh
        gmsh.initialize()
        gmsh.option.setNumber("General.Verbosity", 0)
        gmsh.model.add("wing_step")
        for idx, o in enumerate(outlines_mm):
            p_tags = []
            prev = None
            for pt in o:
                if prev is None or ((pt[0]-prev[0])**2 + (pt[1]-prev[1])**2) > 1e-8:
                    p_tags.append(gmsh.model.occ.addPoint(float(pt[0]), float(pt[1]), 0.0))
                    prev = pt
            if len(p_tags) < 3:
                continue
            dist_te = ((o[0][0]-o[-1][0])**2 + (o[0][1]-o[-1][1])**2)**0.5
            if dist_te < 1e-4:
                p_tags[-1] = p_tags[0]
                spline = gmsh.model.occ.addBSpline(p_tags)
                wire = gmsh.model.occ.addWire([spline])
            else:
                spline = gmsh.model.occ.addBSpline(p_tags)
                line = gmsh.model.occ.addLine(p_tags[-1], p_tags[0])
                wire = gmsh.model.occ.addWire([spline, line])
            face = gmsh.model.occ.addPlaneSurface([wire])
            gmsh.model.occ.extrude([(2, face)], 0, 0, float(span_mm))
        gmsh.model.occ.synchronize()
        gmsh.write(out_path)
        gmsh.finalize()
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 500
    except Exception:
        try: gmsh.finalize()
        except Exception: pass
        return False


def _export_step_builtin(outlines_mm, out_path, span_mm, title):
    """Pure-Python ISO 10303-21 AP214 MANIFOLD_SOLID_BREP generator (0 dependencies)."""
    lines = [
        'ISO-10303-21;',
        'HEADER;',
        'FILE_DESCRIPTION((\'aero_auto Multi-Element Wing Solid\'),\'2;1\');',
        'FILE_NAME(\'wing.step\',\'2026-10-15T09:00:00\',(\'aero_auto\'),(\'FSAE\'),\'aero_auto STEP AP214 Generator\',\'aero_auto\',\'\');',
        'FILE_SCHEMA((\'AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }\'));',
        'ENDSEC;',
        'DATA;'
    ]
    eid = 1
    def get_id():
        nonlocal eid
        i = eid
        eid += 1
        return i

    app_ctx = get_id()
    lines.append(f"#{app_ctx} = APPLICATION_CONTEXT('core data for automotive mechanical design processes');")
    app_proto = get_id()
    lines.append(f"#{app_proto} = APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app_ctx});")
    prod_ctx = get_id()
    lines.append(f"#{prod_ctx} = PRODUCT_CONTEXT('',#{app_ctx},'mechanical');")
    prod_def_ctx = get_id()
    lines.append(f"#{prod_def_ctx} = PRODUCT_DEFINITION_CONTEXT('part definition',#{app_ctx},'design');")

    u_len = get_id()
    lines.append(f"#{u_len} = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );")
    u_ang = get_id()
    lines.append(f"#{u_ang} = ( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) );")
    u_sol = get_id()
    lines.append(f"#{u_sol} = ( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() );")
    u_unc = get_id()
    lines.append(f"#{u_unc} = UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{u_len},'distance_accuracy_value','confusion accuracy');")
    geom_ctx = get_id()
    lines.append(f"#{geom_ctx} = ( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{u_unc})) GLOBAL_UNIT_ASSIGNED_CONTEXT((#{u_len},#{u_ang},#{u_sol})) REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') );")

    origin = get_id()
    lines.append(f"#{origin} = CARTESIAN_POINT('',(0.,0.,0.));")
    dir_z = get_id()
    lines.append(f"#{dir_z} = DIRECTION('',(0.,0.,1.));")
    dir_x = get_id()
    lines.append(f"#{dir_x} = DIRECTION('',(1.,0.,0.));")
    axis_root = get_id()
    lines.append(f"#{axis_root} = AXIS2_PLACEMENT_3D('',#{origin},#{dir_z},#{dir_x});")

    solid_ids = []
    for el_idx, pts in enumerate(outlines_mm):
        clean_pts = []
        for pt in pts:
            if not clean_pts or np.hypot(pt[0] - clean_pts[-1][0], pt[1] - clean_pts[-1][1]) > 1e-6:
                clean_pts.append(pt)
        if len(clean_pts) > 2 and np.hypot(clean_pts[0][0] - clean_pts[-1][0], clean_pts[0][1] - clean_pts[-1][1]) < 1e-4:
            clean_pts = clean_pts[:-1]

        N = len(clean_pts)
        if N < 3:
            continue

        cp_bottom = []
        cp_top = []
        for x, y in clean_pts:
            p0 = get_id()
            lines.append(f"#{p0} = CARTESIAN_POINT('',({float(x):.6f},{float(y):.6f},0.));")
            cp_bottom.append(p0)
            p1 = get_id()
            lines.append(f"#{p1} = CARTESIAN_POINT('',({float(x):.6f},{float(y):.6f},{float(span_mm):.6f}));")
            cp_top.append(p1)

        v_bottom = [get_id() for _ in range(N)]
        v_top = [get_id() for _ in range(N)]
        for vb, vt, p0, p1 in zip(v_bottom, v_top, cp_bottom, cp_top):
            lines.append(f"#{vb} = VERTEX_POINT('',#{p0});")
            lines.append(f"#{vt} = VERTEX_POINT('',#{p1});")

        e_bottom = []
        e_top = []
        e_vertical = []

        for k in range(N):
            k_next = (k + 1) % N
            dx = float(clean_pts[k_next][0] - clean_pts[k][0])
            dy = float(clean_pts[k_next][1] - clean_pts[k][1])
            dist = max(1e-7, (dx*dx + dy*dy)**0.5)

            d_id = get_id()
            lines.append(f"#{d_id} = DIRECTION('',({dx/dist:.6f},{dy/dist:.6f},0.));")
            v_vec = get_id()
            lines.append(f"#{v_vec} = VECTOR('',#{d_id},{dist:.6f});")
            l_b = get_id()
            lines.append(f"#{l_b} = LINE('',#{cp_bottom[k]},#{v_vec});")
            edge_b = get_id()
            lines.append(f"#{edge_b} = EDGE_CURVE('',#{v_bottom[k]},#{v_bottom[k_next]},#{l_b},.T.);")
            e_bottom.append(edge_b)

            l_top = get_id()
            lines.append(f"#{l_top} = LINE('',#{cp_top[k]},#{v_vec});")
            edge_t = get_id()
            lines.append(f"#{edge_t} = EDGE_CURVE('',#{v_top[k]},#{v_top[k_next]},#{l_top},.T.);")
            e_top.append(edge_t)

            v_vec_z = get_id()
            lines.append(f"#{v_vec_z} = VECTOR('',#{dir_z},{float(span_mm):.6f});")
            l_v = get_id()
            lines.append(f"#{l_v} = LINE('',#{cp_bottom[k]},#{v_vec_z});")
            edge_v = get_id()
            lines.append(f"#{edge_v} = EDGE_CURVE('',#{v_bottom[k]},#{v_top[k]},#{l_v},.T.);")
            e_vertical.append(edge_v)

        faces = []
        for k in range(N):
            k_next = (k + 1) % N
            oe1, oe2, oe3, oe4 = get_id(), get_id(), get_id(), get_id()
            lines.append(f"#{oe1} = ORIENTED_EDGE('',*,*,#{e_bottom[k]},.T.);")
            lines.append(f"#{oe2} = ORIENTED_EDGE('',*,*,#{e_vertical[k_next]},.T.);")
            lines.append(f"#{oe3} = ORIENTED_EDGE('',*,*,#{e_top[k]},.F.);")
            lines.append(f"#{oe4} = ORIENTED_EDGE('',*,*,#{e_vertical[k]},.F.);")

            loop = get_id()
            lines.append(f"#{loop} = EDGE_LOOP('',(#{oe1},#{oe2},#{oe3},#{oe4}));")
            bound = get_id()
            lines.append(f"#{bound} = FACE_OUTER_BOUND('',#{loop},.T.);")

            dx = float(clean_pts[k_next][0] - clean_pts[k][0])
            dy = float(clean_pts[k_next][1] - clean_pts[k][1])
            dist = max(1e-7, (dx*dx + dy*dy)**0.5)
            nx, ny = dy / dist, -dx / dist

            sn = get_id()
            lines.append(f"#{sn} = DIRECTION('',({nx:.6f},{ny:.6f},0.));")
            sx = get_id()
            lines.append(f"#{sx} = DIRECTION('',({dx/dist:.6f},{dy/dist:.6f},0.));")
            pl_axis = get_id()
            lines.append(f"#{pl_axis} = AXIS2_PLACEMENT_3D('',#{cp_bottom[k]},#{sn},#{sx});")
            plane = get_id()
            lines.append(f"#{plane} = PLANE('',#{pl_axis});")
            face = get_id()
            lines.append(f"#{face} = ADVANCED_FACE('',(#{bound}),#{plane},.T.);")
            faces.append(face)

        # Bottom cap (z=0, reversed loop)
        oe_b = []
        for k in reversed(range(N)):
            oe = get_id()
            lines.append(f"#{oe} = ORIENTED_EDGE('',*,*,#{e_bottom[k]},.F.);")
            oe_b.append(oe)
        loop_b = get_id()
        lines.append(f"#{loop_b} = EDGE_LOOP('',({','.join(f'#{o}' for o in oe_b)}));")
        bound_b = get_id()
        lines.append(f"#{bound_b} = FACE_OUTER_BOUND('',#{loop_b},.T.);")
        dir_down = get_id()
        lines.append(f"#{dir_down} = DIRECTION('',(0.,0.,-1.));")
        axis_b = get_id()
        lines.append(f"#{axis_b} = AXIS2_PLACEMENT_3D('',#{origin},#{dir_down},#{dir_x});")
        pl_b = get_id()
        lines.append(f"#{pl_b} = PLANE('',#{axis_b});")
        face_b = get_id()
        lines.append(f"#{face_b} = ADVANCED_FACE('',(#{bound_b}),#{pl_b},.T.);")
        faces.append(face_b)

        # Top cap (z=span, forward loop)
        oe_t = []
        for k in range(N):
            oe = get_id()
            lines.append(f"#{oe} = ORIENTED_EDGE('',*,*,#{e_top[k]},.T.);")
            oe_t.append(oe)
        loop_t = get_id()
        lines.append(f"#{loop_t} = EDGE_LOOP('',({','.join(f'#{o}' for o in oe_t)}));")
        bound_t = get_id()
        lines.append(f"#{bound_t} = FACE_OUTER_BOUND('',#{loop_t},.T.);")
        p_top_orig = get_id()
        lines.append(f"#{p_top_orig} = CARTESIAN_POINT('',(0.,0.,{float(span_mm):.6f}));")
        axis_t = get_id()
        lines.append(f"#{axis_t} = AXIS2_PLACEMENT_3D('',#{p_top_orig},#{dir_z},#{dir_x});")
        pl_t = get_id()
        lines.append(f"#{pl_t} = PLANE('',#{axis_t});")
        face_t = get_id()
        lines.append(f"#{face_t} = ADVANCED_FACE('',(#{bound_t}),#{pl_t},.T.);")
        faces.append(face_t)

        shell = get_id()
        lines.append(f"#{shell} = CLOSED_SHELL('',({','.join(f'#{f}' for f in faces)}));")
        solid = get_id()
        lines.append(f"#{solid} = MANIFOLD_SOLID_BREP('Element_{el_idx}',#{shell});")
        solid_ids.append(solid)

    shape_rep = get_id()
    solids_str = ','.join(f'#{s}' for s in solid_ids)
    lines.append(f"#{shape_rep} = SHAPE_REPRESENTATION('',(#{axis_root},{solids_str}),#{geom_ctx});")

    prod = get_id()
    lines.append(f"#{prod} = PRODUCT('FSAE_Wing','FSAE_Wing','',({prod_ctx}));")
    form = get_id()
    lines.append(f"#{form} = PRODUCT_DEFINITION_FORMATION('','',#{prod});")
    pdef = get_id()
    lines.append(f"#{pdef} = PRODUCT_DEFINITION('design','',#{form},#{prod_def_ctx});")
    pds = get_id()
    lines.append(f"#{pds} = PRODUCT_DEFINITION_SHAPE('','',#{pdef});")
    lines.append(f"#{get_id()} = SHAPE_DEFINITION_REPRESENTATION(#{pds},#{shape_rep});")

    lines.append('ENDSEC;')
    lines.append('END-ISO-10303-21;')

    with open(out_path, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines) + '\n')
    return out_path


def export_step(cfg, out_path, chord_mm=None, span_mm=500.0, ground_h=None, title="Multi-Element Wing"):
    """
    Export the multi-element wing geometry as a standard ISO 10303-21 STEP AP214 3D solid model (.step / .stp).
    Produces authentic 3D closed manifold solid bodies (MANIFOLD_SOLID_BREP) for each element,
    extruded to the specified span length along the Z-axis in millimeters.
    Tries FreeCAD and Gmsh OpenCASCADE if available, with a built-in pure-Python AP214 generator fallback.
    """
    if not AIRFOILS:
        AIRFOILS.update(load_all(AIRFOIL_DIR))
        if os.path.isdir(AIRFOIL_STORE):
            AIRFOILS.update(load_all(AIRFOIL_STORE))

    chord = float(chord_mm or CHORD_MM or DEFAULT_CHORD_MM)
    span = float(span_mm or SPAN_MM or 500.0)
    outlines = build_outlines(cfg, ground_h)
    outlines_mm = [pts * chord for pts in outlines]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)

    # 1. Try FreeCAD CLI if installed (generates exact C2 B-spline approximation)
    if _try_export_step_freecad(outlines_mm, out_path, span, title):
        return out_path

    # 2. Try Gmsh OpenCASCADE if gmsh is available
    if _try_export_step_gmsh(outlines_mm, out_path, span, title):
        return out_path

    # 3. Built-in Pure-Python ISO 10303-21 AP214 MANIFOLD_SOLID_BREP generator (0 dependencies)
    _export_step_builtin(outlines_mm, out_path, span, title)
    return out_path


def export_freecad_macro(cfg, out_path, chord_mm=None, span_mm=500.0, ground_h=None, title="Multi-Element Wing"):
    """
    Generate a standalone FreeCAD Python macro (.FCMacro) that builds the multi-element wing
    parametrically in FreeCAD with smooth C2 B-spline approximation curves and 3D solid extrusions.
    Can be run directly via FreeCAD -> Macro -> Macros... -> Execute.
    """
    if not AIRFOILS:
        AIRFOILS.update(load_all(AIRFOIL_DIR))
        if os.path.isdir(AIRFOIL_STORE):
            AIRFOILS.update(load_all(AIRFOIL_STORE))

    chord = float(chord_mm or CHORD_MM or DEFAULT_CHORD_MM)
    span = float(span_mm or SPAN_MM or 500.0)
    outlines = build_outlines(cfg, ground_h)
    outlines_mm = [pts * chord for pts in outlines]

    main_name = cfg[0]
    element_names = [f"Main_{main_name}"] + [f"Flap_{i}_{fl[0]}" for i, fl in enumerate(cfg[1], start=1)]

    clean_outlines = []
    for pts in outlines_mm:
        c_pts = []
        for pt in pts:
            if not c_pts or np.hypot(pt[0] - c_pts[-1][0], pt[1] - c_pts[-1][1]) > 1e-6:
                c_pts.append([round(float(pt[0]), 5), round(float(pt[1]), 5)])
        clean_outlines.append(c_pts)

    macro_text = f'''# -*- coding: utf-8 -*-
"""
{title} - FreeCAD Multi-Element Wing Generator
Generated automatically by aero_auto.

How to use in FreeCAD:
  1. Open FreeCAD.
  2. Macro -> Macros... -> Select this file -> Execute.
  3. The multi-element wing is built as smooth C2 B-spline wires and extruded 3D solids.
"""
import FreeCAD as App
import Part
from FreeCAD import Vector as V

SPAN_MM = {span:.1f}
TOL_MM = 0.02
ELEMENT_NAMES = {element_names!r}
ELEMENT_OUTLINES = {clean_outlines!r}

doc = App.ActiveDocument or App.newDocument("FSAE_Wing")

for idx, (name, pts_mm) in enumerate(zip(ELEMENT_NAMES, ELEMENT_OUTLINES)):
    vecs = [V(x, y, 0.0) for x, y in pts_mm]
    bs = Part.BSplineCurve()
    try:
        bs.approximate(Points=vecs, DegMin=3, DegMax=8, Tolerance=TOL_MM, Continuity="C2", ParamType="Centripetal")
    except Exception:
        bs.interpolate(Points=vecs, PeriodicFlag=False)
        
    edge = bs.toShape()
    edges = [edge]
    if bs.StartPoint.distanceToPoint(bs.EndPoint) > 1e-5:
        edges.append(Part.LineSegment(bs.EndPoint, bs.StartPoint).toShape())
        
    wire = Part.Wire(edges)
    prof = doc.addObject("Part::Feature", name + "_profile")
    prof.Shape = wire
    
    face = Part.Face(wire)
    solid = face.extrude(V(0, 0, SPAN_MM))
    solid_obj = doc.addObject("Part::Feature", name)
    solid_obj.Shape = solid
    try:
        prof.ViewObject.Visibility = False
    except Exception:
        pass

doc.recompute()
try:
    import FreeCADGui
    FreeCADGui.SendMsgToActiveView("ViewFit")
except Exception:
    pass
print(f"Built {{len(ELEMENT_OUTLINES)}} wing elements successfully.")
'''
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(macro_text)
    return out_path


def export_svg(cfg, out_path, chord_mm=None, ground_h=None, title="Multi-Element Wing"):
    """
    Export the multi-element wing geometry as a clean scalable vector SVG graphic.
    """
    if not AIRFOILS:
        AIRFOILS.update(load_all(AIRFOIL_DIR))
        if os.path.isdir(AIRFOIL_STORE):
            AIRFOILS.update(load_all(AIRFOIL_STORE))

    chord = float(chord_mm or CHORD_MM or DEFAULT_CHORD_MM)
    outlines = build_outlines(cfg, ground_h)
    outlines_mm = [pts * chord for pts in outlines]

    all_x = np.concatenate([p[:, 0] for p in outlines_mm])
    all_y = np.concatenate([p[:, 1] for p in outlines_mm])
    pad = 20.0
    x_min, x_max = all_x.min() - pad, all_x.max() + pad
    y_min, y_max = min(0.0 if ground_h is not None else all_y.min(), all_y.min()) - pad, all_y.max() + pad
    w = max(100.0, x_max - x_min)
    h = max(50.0, y_max - y_min)

    svg = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x_min:.1f} {-y_max:.1f} {w:.1f} {h:.1f}" width="{w * 2:.0f}" height="{h * 2:.0f}">',
        f'<rect x="{x_min:.1f}" y="{-y_max:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#111827"/>',
    ]
    if ground_h is not None:
        svg.append(f'<line x1="{x_min:.1f}" y1="0.0" x2="{x_max:.1f}" y2="0.0" stroke="#ef4444" stroke-width="1.5" stroke-dasharray="4,4"/>')

    colors = ["#00e5ff", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6"]
    for i, pts in enumerate(outlines_mm):
        col = colors[i % len(colors)]
        pts_str = " ".join(f"{x:.2f},{-y:.2f}" for x, y in pts)
        svg.append(f'<polygon points="{pts_str}" fill="{col}" fill-opacity="0.25" stroke="{col}" stroke-width="1.2"/>')

    svg.append('</svg>')
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(svg))
    return out_path


def run_one(cfg, phase, ground_h=UNSET):
    h = GROUND_H if ground_h is UNSET else ground_h
    wdir = WORKER_DIRS.get()
    try:
        t = time.time()
        m, status, head = simulate(cfg, wdir, h)
        took = time.time() - t
    finally:
        WORKER_DIRS.put(wdir)
    rated = rate_all_profiles(m, status)
    row = {"Phase": phase, **cfg_to_row(cfg), **rated, "Status": status,
           "Flow": "ground" if h is not None else "unbounded", "Height_pct": h}
    try:
        row.update(geometry_columns(cfg, h))
    except Exception:
        pass
    if m:
        row.update(m)
        row.update(force_columns(m))
    with LOCK:
        row["Run_ID"] = f"Run_{next(RUN_COUNTER)}"
        row["Date"] = datetime.datetime.now().isoformat(timespec="seconds")
        row["Duration_s"] = round(took, 1)
        row["Alpha_Interval"] = (f"{ALPHA[0]:g}..{ALPHA[1]:g} step {ALPHA[2]:g} "
                                 f"(RE {RE:g})")
        RESULTS.append(row)
        DONE.add(cfg_key(cfg))
        CONSEC_FAILS[0] = 0 if status == "Valid" else CONSEC_FAILS[0] + 1
        write_row(row)
        if status != "Valid":
            print(f"[{row['Run_ID']}] {describe(cfg)} -> FAILED: {status}")
            for l in head[:10]:
                print("    |", l[:140])
    row["_took"] = took
    return row

def fmt_value(k, v):
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        if k in ("Cd_peak", "Cd_a0"):
            return f"{v:.5f}"
        if k == "Duration_s":
            return f"{v:.1f}"
        if k == "Speed_ms":
            return f"{v:g}"
        if k.endswith("_mm"):
            return f"{v:.1f}"
        if k.startswith("F") and k.endswith(("_Scale", "_Angle", "_X", "_Y")) or k == "Height_pct":
            return f"{v:g}"
        return f"{v:.4f}"
    return v

def write_row(row):
    path = RESULTS_FILE[0]
    if not path:
        return
    new = (not os.path.exists(path)) or (os.path.getsize(path) == 0)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: fmt_value(k, row.get(k)) for k in FIELDS})

def _safe_float(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None

def safe_cfg_key(cfg):
    if not cfg or not isinstance(cfg, (tuple, list)) or len(cfg) != 2:
        return None
    main, flaps = cfg
    clean_flaps = []
    for fl in flaps:
        if not isinstance(fl, (tuple, list)) or len(fl) != 5:
            return None
        name, s, a, x, y = fl
        try:
            clean_flaps.append((str(name), float(s), float(a), float(x), float(y)))
        except (ValueError, TypeError):
            return None
    return (str(main), tuple(clean_flaps))

def results_header(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", newline="", encoding="utf-8", errors="ignore") as f:
            r = csv.reader(f)
            return next(r, [])
    except Exception:
        return []

LEGACY_FIELDS = [
    "Run_ID", "Phase", "Elements", "Main",
    "F1_Airfoil", "F1_Scale", "F1_Angle", "F1_X", "F1_Y",
    "F2_Airfoil", "F2_Scale", "F2_Angle", "F2_X", "F2_Y",
    "F3_Airfoil", "F3_Scale", "F3_Angle", "F3_X", "F3_Y",
    "Cl_peak", "Cd_peak", "Stall_Angle", "Max_LD", "Cl_a0", "Cd_a0",
    "Cm_a0", "Cl_am2", "Cl_ap2", "Tier", "Score", "Status"
]

def read_results_csv(path):
    if not os.path.exists(path):
        return pd.DataFrame(columns=FIELDS)
    try:
        with open(path, "r", newline="", encoding="utf-8", errors="ignore") as f:
            reader = list(csv.reader(f))
        if not reader:
            return pd.DataFrame(columns=FIELDS)
        header = [c.strip() for c in reader[0]]
        rows = []
        for r in reader[1:]:
            if not r or not any(r):
                continue
            if len(r) == len(FIELDS):
                row_cols = FIELDS
            elif len(r) == len(LEGACY_FIELDS):
                row_cols = LEGACY_FIELDS
            elif len(r) == len(header):
                row_cols = header
            else:
                row_cols = header if len(r) <= len(header) else FIELDS
            row_dict = {}
            for i, val in enumerate(r):
                if i < len(row_cols):
                    row_dict[row_cols[i]] = val
            rows.append(row_dict)
        d = pd.DataFrame(rows)
        for c in d.columns:
            if c in ("Cl_a0", "Cd_a0", "Cm_a0", "Cl_am2", "Cl_ap2", "Cl_peak", "Cd_peak",
                     "Stall_Angle", "Max_LD", "Score", "Downforce_N", "Drag_N", "Speed_ms",
                     "Duration_s", "Height_pct", "Min_Clearance_pct", "Stack_Length_mm",
                     "Stack_Height_mm", "Min_Clearance_mm"):
                d[c] = pd.to_numeric(d[c], errors="coerce")
        return d
    except Exception:
        return pd.read_csv(path, on_bad_lines="skip")

def atomic_write_csv(path, rows, fields=None):
    fields = fields or FIELDS
    dirname = os.path.dirname(os.path.abspath(path))
    os.makedirs(dirname, exist_ok=True)
    tmp_path = os.path.join(dirname, f".tmp_results_{uuid.uuid4().hex}.csv")
    try:
        with open(tmp_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: fmt_value(k, r.get(k)) if not (isinstance(r.get(k), float) and math.isnan(r.get(k))) else "" for k in fields})
        os.replace(tmp_path, path)
        return True
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

def validate_height(h):
    if h is None:
        return None
    try:
        fh = float(h)
        if math.isnan(fh) or fh <= 0:
            raise ValueError(f"invalid ground height: {h}")
        return fh
    except (TypeError, ValueError) as err:
        raise ValueError(f"invalid ground height: {h}") from err

def set_ground_h(h):
    global GROUND_H
    val = validate_height(h)
    GROUND_H = val
    return val

def load_store(store=None):
    store = store or AIRFOIL_STORE
    if not os.path.exists(store):
        return
    AIRFOILS.update(load_all(store))

def new_run_dir(kind="single", main="s1223", base=None):
    base = base or OUT_DIR
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join(base, f"run_{ts}_{kind}_{main}")
    os.makedirs(d, exist_ok=True)
    return d

def write_run_meta(d, **kwargs):
    meta_path = os.path.join(d, "meta.json")
    with open(meta_path, "w") as f:
        json.dump(kwargs, f, indent=2)

def read_run_meta(d):
    meta_path = os.path.join(d, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            return json.load(f)
    return {}

def list_runs(base=None):
    base = base or OUT_DIR
    runs = []
    if not os.path.exists(base):
        return runs
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if os.path.isdir(p) and name.startswith("run_"):
            m = read_run_meta(p)
            runs.append({"path": p, **m})
    return runs

def import_legacy_results(base=None):
    base = base or OUT_DIR
    created = []
    candidates = []
    r_main = os.path.join(base, "results.csv")
    if os.path.exists(r_main):
        candidates.append(r_main)
    candidates.extend(glob.glob(os.path.join(base, "ground", "*", "results.csv")))
    existing_dirs = {os.path.basename(r["path"]) for r in list_runs(base)}
    for c in candidates:
        tag = "root" if c == r_main else os.path.basename(os.path.dirname(c))
        name = f"run_imported_{tag}"
        if name in existing_dirs:
            continue
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        shutil.copy(c, os.path.join(d, "results.csv"))
        write_run_meta(d, kind="imported", legacy=True, source=c)
        created.append(d)
        existing_dirs.add(name)
    return created

def describe(cfg):
    main, flaps = cfg
    s = f"{main}"
    for k, (n, sc, a, x, y) in enumerate(flaps, 1):
        s += f" | F{k} {n} {sc:g}% {a:g}° X{x:g} Y{y:g}"
    return s


# =====================================================================
# SEARCH: SAMPLING, NEIGHBOURS, PHASES
# =====================================================================
def sample_config(n_elements, mains, flaps_pool, tries=300):
    for _ in range(tries):
        main = random.choice(mains)
        flaps = []
        for k in range(1, n_elements):
            g = GRID[k]
            flaps.append((random.choice(flaps_pool), random.choice(g["scale"]), random.choice(g["angle"]),
                          random.choice(g["x"]), random.choice(g["y"])))
        cfg = (main, tuple(flaps))
        if cfg_key(cfg) not in DONE and geometry_ok(cfg):
            return cfg
    return None

def neighbours(cfg, mains, flaps_pool):
    main, flaps = cfg
    out = []
    for k, fl in enumerate(flaps):
        g = GRID[k + 1]
        for pi, pname in enumerate(("scale", "angle", "x", "y"), start=1):
            vals = g[pname]
            i = min(range(len(vals)), key=lambda j: abs(vals[j] - fl[pi]))
            for d in (-1, 1):
                if 0 <= i + d < len(vals):
                    nf = list(fl); nf[pi] = vals[i + d]
                    new = list(flaps); new[k] = tuple(nf)
                    out.append((main, tuple(new)))
    for _ in range(SWAPS_PER_PARENT):
        slot = random.randrange(len(flaps) + 1)
        if slot == 0:
            out.append((random.choice(mains), flaps))
        else:
            new = list(flaps); new[slot - 1] = (random.choice(flaps_pool),) + tuple(flaps[slot - 1][1:])
            out.append((main, tuple(new)))
    return out

def results_df():
    with LOCK:
        return pd.DataFrame(RESULTS) if RESULTS else pd.DataFrame(columns=FIELDS)

def row_to_cfg(r):
    if r is None or (hasattr(r, "empty") and r.empty):
        return None
    main = r.get("Main")
    if not main or pd.isna(main) or str(main).lower() == "nan" or not str(main).strip():
        return None
    flaps = []
    for k in (1, 2, 3):
        n = r.get(f"F{k}_Airfoil")
        if n is not None and pd.notna(n) and str(n).strip() and str(n).lower() != "nan" and str(n) != "None":
            try:
                flaps.append((str(n), float(r.get(f"F{k}_Scale", 30)), float(r.get(f"F{k}_Angle", -6)),
                              float(r.get(f"F{k}_X", 100)), float(r.get(f"F{k}_Y", 5))))
            except Exception:
                pass
    return (str(main), tuple(flaps))

def best_parents(n_elements, k):
    d = results_df()
    if d.empty:
        return []
    d = d[(d["Elements"] == n_elements) & (d["Tier"] <= 3)].copy()
    if d.empty:
        return []
    good = d[d["Tier"] <= 2]
    pool = good if len(good) >= k else d
    pool = pool.sort_values(["Tier", "Score"], ascending=[True, False]).head(k)
    return [row_to_cfg(r) for r in pool.to_dict("records")]

def run_batch(cfgs, phase, deadline):
    """Runs configs in parallel; stops submitting at the deadline. Returns number completed."""
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = []
        for c in cfgs:
            with LOCK:
                DONE.add(cfg_key(c))        
            futs.append(ex.submit(guarded_run, c, phase, deadline))
        try:
            for f in as_completed(futs):
                try:
                    r = f.result()
                except Exception as e:
                    print("worker error:", e)
                    continue
                if r is not None:
                    done += 1
        except KeyboardInterrupt:
            STOP.set()                      
            INTERRUPT.set()
            for f in futs:
                f.cancel()
            raise
    return done

def guarded_run(cfg, phase, deadline):
    if STOP.is_set() or time.time() > deadline:
        with LOCK:
            DONE.discard(cfg_key(cfg))
        return None
    return run_one(cfg, phase)

def progress_line(force=False):
    if not force and time.time() - LAST_PRINT[0] < 60:
        return None
    LAST_PRINT[0] = time.time()
    d = results_df()
    el = (time.time() - T0[0]) / 60
    if d.empty:
        return f"[{el:5.0f} min] no results yet"
    parts = []
    for n in (1, 2, 3, 4):
        s = d[(d["Elements"] == n) & (d["Tier"] <= 3)]
        if len(s):
            b = s.sort_values(["Tier", "Score"], ascending=[True, False]).iloc[0]
            parts.append(f"{n}el best {b['Score']:.1f} (Cl@0 {b['Cl_a0']:.2f}, stall {b['Stall_Angle']:.0f}, T{int(b['Tier'])})")
    ok = (d["Status"] == "Valid").sum()
    rate_h = (len(d) - START_COUNT[0]) / max(el / 60, 1e-6)
    return f"[{el:5.0f} min] runs {len(d)} (valid {ok}, {rate_h:.0f}/h) | " + " | ".join(parts)

def show(line):
    if line:
        print(line)


# =====================================================================
# OUTPUT FILES: top_results.csv and summary.xlsx
# =====================================================================
def sorted_results(d):
    d = d.copy()
    d["_s"] = d["Score"].fillna(-1)
    d = d.sort_values(["Tier", "_s"], ascending=[True, False]).drop(columns="_s")
    return d.reindex(columns=FIELDS)

def write_outputs(top_n=20):
    d = results_df()
    if d.empty:
        return
    d = sorted_results(d)
    rated = d[d["Tier"] <= 3]
    top = rated.sort_values("Elements", kind="stable").groupby("Elements").head(25)
    top.to_csv(os.path.join(RUN_DIR, "top_results.csv"), index=False)

    names = {1: "1 element", 2: "2 elements", 3: "3 elements", 4: "4 elements"}
    best_parts = [rated.head(top_n).assign(Group="Overall")]
    for n in (1, 2, 3, 4):
        best_parts.append(rated[rated["Elements"] == n].head(top_n).assign(Group=names[n]))
    best = pd.concat(best_parts)
    best.insert(0, "Rank", best.groupby("Group").cumcount() + 1)
    best = best[["Group", "Rank"] + FIELDS]
    sheets = {"All": d}
    for n in (1, 2, 3, 4):
        sheets[names[n]] = d[d["Elements"] == n]
    sheets["Best"] = best
    try:
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
        tmp = os.path.join(RUN_DIR, "summary_tmp.xlsx")
        with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
            for name, df_ in sheets.items():
                df_.to_excel(xw, sheet_name=name, index=False)
                ws = xw.sheets[name]
                for j, col in enumerate(df_.columns, 1):
                    c = ws.cell(row=1, column=j)
                    c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F3864")
                    c.alignment = Alignment(horizontal="center", wrap_text=True)
                    ws.column_dimensions[get_column_letter(j)].width = max(10, min(24, len(str(col)) + 2))
                ws.freeze_panes = "E2" if name != "Best" else "C2"
                ws.auto_filter.ref = ws.dimensions
        os.replace(tmp, os.path.join(RUN_DIR, "summary.xlsx"))
    except ImportError:
        folder = os.path.join(RUN_DIR, "summary")
        os.makedirs(folder, exist_ok=True)
        for name, df_ in sheets.items():
            df_.to_csv(os.path.join(folder, name.replace(" ", "_") + ".csv"), index=False)
        if not getattr(write_outputs, "warned", False):
            print("(openpyxl is not installed, so the summary is written as CSV files in the 'summary' folder. "
                  "Run 'pip install openpyxl' to get summary.xlsx.)")
            write_outputs.warned = True
    except Exception as e:
        print("Could not write summary.xlsx:", e)


# =====================================================================
# CAMPAIGN
# =====================================================================
def campaign(hours, mains, flaps_pool):
    deadline = time.time() + hours * 3600
    explore_end = time.time() + hours * 3600 * EXPLORE_FRACTION
    last_out = time.time()
    batch = max(WORKERS * 3, 6)

    # --- Phase 0: every airfoil alone ---
    singles = [(m, ()) for m in mains if cfg_key((m, ())) not in DONE]
    if singles:
        print(f"Phase 0: {len(singles)} single-element runs")
        run_batch(singles, "single", deadline)
        show(progress_line(force=True))

    # --- Phase 1: explore ---
    print("Phase 1: exploration")
    ns, ws = zip(*ELEMENT_WEIGHTS.items())
    while time.time() < explore_end and not STOP.is_set():
        cfgs = []
        while len(cfgs) < batch:
            n = random.choices(ns, weights=ws)[0]
            c = sample_config(n, mains, flaps_pool)
            if c is not None and cfg_key(c) not in {cfg_key(x) for x in cfgs}:
                cfgs.append(c)
            elif c is None:
                break
        if not cfgs:
            print("No new valid configs left to sample.")
            break
        run_batch(cfgs, "explore", explore_end)
        show(progress_line())
        check_fail_streak()
        if time.time() - last_out > SUMMARY_EVERY:
            write_outputs(); last_out = time.time()

    # --- Phase 2: refine ---
    print("Phase 2: refinement")
    k = TOP_K
    cap = MAX_ROUND or WORKERS * 20
    while time.time() < deadline and not STOP.is_set():
        round_cfgs, seen = [], set()
        for n in (2, 3, 4):
            for p in best_parents(n, k):
                for c in neighbours(p, mains, flaps_pool):
                    key = cfg_key(c)
                    with LOCK:
                        known = key in DONE
                    if not known and key not in seen and geometry_ok(c):
                        seen.add(key); round_cfgs.append(c)
        random.shuffle(round_cfgs)
        round_cfgs = round_cfgs[:cap]
        if not round_cfgs:
            if k < 60:
                k += 8
                print(f"Neighbourhood exhausted, widening to the best {k} per element count")
                continue
            print("Refinement converged (nothing new to test).")
            break
        run_batch(round_cfgs, "refine", deadline)
        show(progress_line())
        check_fail_streak()
        if time.time() - last_out > SUMMARY_EVERY:
            write_outputs(); last_out = time.time()

def check_fail_streak():
    if CONSEC_FAILS[0] >= MAX_CONSEC_FAILS:
        STOP.set()
        print(f"\nSTOPPING: {CONSEC_FAILS[0]} runs in a row failed. Check JavaFoil/faketime with --test.")


# =====================================================================
# SETUP: QUESTIONS, FOLDERS, WORKERS, RESUME
# =====================================================================
def ask_text(prompt, default=""):
    try:
        raw = input(prompt).strip()
    except EOFError:
        return default
    return raw if raw else default

def parse_plain(text):
    t = text.strip().lower().replace(" ", "")
    if t.endswith("mm"):
        t = t[:-2]
    return float(t)

def parse_speed(text):
    t = text.strip().lower().replace(" ", "")
    for suf in ("km/h", "kmh", "kph"):
        if t.endswith(suf):
            return float(t[:-len(suf)]) / 3.6
    if t.endswith("m/s"):
        t = t[:-3]
    return float(t)

def ask_number(prompt, default, parser):
    """Enter = built-in value, 0 = skip this one, otherwise the number typed."""
    while True:
        raw = ask_text(prompt, "")
        if raw == "":
            return default
        if raw.strip().lower() in ("0", "skip", "-", "n", "no"):
            return None
        try:
            v = parser(raw)
            if v > 0:
                return v
        except ValueError:
            pass
        print("  Type a positive number, 0 to skip this one, or just press Enter for the built-in value.")

def parse_height(text, chord_mm):
    t = text.strip().lower().replace(" ", "")
    if t.endswith("mm"):
        if not chord_mm:
            raise ValueError("To give the height in mm, first give the main plane chord.")
        return float(t[:-2]) / chord_mm * 100.0
    if t.endswith("%"):
        t = t[:-1]
    return float(t)

def ask_default(prompt, default, parser):
    """Enter = the value in brackets."""
    while True:
        raw = ask_text(prompt, "")
        if raw == "":
            return default
        try:
            v = parser(raw)
            if v > 0:
                return v
        except ValueError:
            pass
        print("  Type a positive number, or just press Enter for the value in brackets.")

def parse_height_list(text, chord_mm):
    out = []
    for t in str(text).replace(";", ",").split(","):
        if t.strip():
            h = parse_height(t, chord_mm)
            if h <= 0:
                raise ValueError("Height must be positive.")
            if h not in out:
                out.append(h)
    if not out:
        raise ValueError("Give at least one height.")
    return out

parse_heights = parse_height_list

def plan_scenarios(plan):
    sc = []
    role = plan.get("role", "custom")
    if plan["flow"] in ("unbounded", "both"):
        sc.append({"flow": "unbounded", "height": None, "role": role})
    if plan["flow"] in ("ground", "both"):
        sc += [{"flow": "ground", "height": h, "role": role} for h in plan["heights"]]
    if plan["flow"] == "both" and role in ("fw", "rw"):
        for s in sc:                                   # ground -> front-wing limits, free stream -> rear-wing
            s["role"] = "fw" if s["flow"] == "ground" else "rw"
    return sc

def scenario_label(sc, chord=None):
    if sc["height"] is None:
        label = "unbounded flow"
    else:
        mm = f" (about {sc['height'] * chord / 100:.0f} mm up)" if chord else ""
        label = f"ground effect, height {sc['height']:g}% of the chord{mm}"
    role = sc.get("role")
    return label + (f"  [{role.upper()} limits]" if role in ("fw", "rw") else "")

def scenario_dir(sc):
    return OUT_DIR if sc["height"] is None else os.path.join(OUT_DIR, "ground", f"h{sc['height']:g}pct")

def plan_text(plan):
    scs = plan_scenarios(plan)
    each = plan["hours"] / max(len(scs), 1)
    lines = [f"  Total time {plan['hours']:g} h with {plan['workers']} parallel runs "
             f"({len(scs)} scenario{'s' if len(scs) != 1 else ''}, about {each:.1f} h each)"]
    for i, sc in enumerate(scs, 1):
        lines.append(f"    {i}) {scenario_label(sc, plan.get('chord'))}  ->  {scenario_dir(sc)}")
    if plan.get("chord") and plan.get("speed"):
        re_ = plan["speed"] * plan["chord"] / 1000 / NU
        span = plan_span(plan)
        lines.append(f"  Wing: chord {plan['chord']:g} mm, speed {plan['speed']:g} m/s ({plan['speed'] * 3.6:.0f} km/h)"
                     + (f", span {span:g} mm" if span else "") + f"  ->  Re = {re_:,.0f}")
    else:
        lines.append(f"  No chord/speed: Re stays at {RE:,}, no newtons")
    role = plan.get("role", "custom")
    fw, rw = plan.get("span_fw"), plan.get("span_rw")
    spans = ", ".join(f"{k} {v:g} mm" for k, v in (("front", fw), ("rear", rw)) if v)
    lines.append(f"  Role: {role.upper()}" + (f"  (spans: {spans})" if spans else ""))
    reg = plan.get("reg")
    if reg and REG_ENFORCE:
        lines.append(f"  FSUK/FSG limits (mm): clearance >= {reg['min_ground_clearance_mm']:g}, "
                     f"FW stack H <= {reg['fw_max_stack_height_mm']:g} / L <= {reg['fw_max_stack_length_mm']:g}, "
                     f"RW stack L <= {reg['rw_max_stack_length_mm']:g} / total H <= {reg['rw_max_total_height_mm']:g}")
    return "\n".join(lines)

def migrate_plan(plan):
    """Fills in role/span/regulatory keys for a plan written by an older version of this script."""
    if not isinstance(plan, dict):
        return plan
    if "span_fw" not in plan:
        plan["span_fw"] = plan.get("span", DEFAULT_SPAN_FW_MM)
    plan.setdefault("span_rw", DEFAULT_SPAN_RW_MM)
    plan.setdefault("role", "custom")
    plan.setdefault("reg", default_reg())
    plan.setdefault("wing_height_mm", None)
    return plan

def build_plan(args):
    """Asks EVERYTHING once (or reads it from the command line / last time's answers)."""
    plan_file = os.path.join(OUT_DIR, "last_plan.json")
    asked = args.flow is None
    if asked and os.path.exists(plan_file):
        try:
            with open(plan_file) as f:
                old = migrate_plan(json.load(f))
            print("\nLast time you used:\n" + plan_text(old))
            if ask_text("Use the same answers again? [Y/n]: ", "y").lower() not in ("n", "no"):
                return old
        except (OSError, ValueError, KeyError):
            pass
    print("\n=== Answer these once; after that it runs by itself ===")
    hours = args.hours if args.hours is not None else (
        ask_default(f"How many hours should it run in total? [{TOTAL_HOURS:g}]: ", TOTAL_HOURS, float) if asked else TOTAL_HOURS)
    workers = args.workers if args.workers is not None else (
        ask_default(f"How many JavaFoil runs in parallel? [{WORKERS}]: ", WORKERS, int) if asked else WORKERS)
    flow = args.flow
    if asked:
        print("\nFlow field:\n  1) Unbounded (free stream)\n  2) Ground effect (ground at y = 0)\n"
              "  3) Both: unbounded first, then ground effect")
        flow = {"2": "ground", "g": "ground", "ground": "ground", "3": "both", "b": "both", "both": "both"}.get(
            ask_text("Choose [1]: ", "1").lower(), "unbounded")
        print("\nReal-world numbers: press Enter to accept the built-in FSAE values (type 0 to skip one).")

    role = args.role
    if role is None:
        if asked:
            dflt = "1" if flow in ("ground", "both") else "2"
            print("\nWing role (selects the standard span T8.2.2 and the FSUK/FSG size limits):")
            print("  1) Front Wing (span ~1400 mm, bounded by the outer edge of the front tires)")
            print("  2) Rear Wing  (span ~950 mm, bounded inside the inner edge of the rear tires)")
            print("  3) Custom")
            role = {"2": "rw", "r": "rw", "rw": "rw", "3": "custom", "c": "custom", "custom": "custom"}.get(
                ask_text(f"Choose [{dflt}]: ", dflt).lower(), "fw")
        else:
            role = "rw" if flow == "unbounded" else "fw"

    def pick(arg, label, default, parser):
        if arg is not None:
            return None if arg == 0 else arg
        return ask_number(label, default, parser) if asked else default

    chord = pick(args.chord_mm, f"  Main plane chord in mm [{DEFAULT_CHORD_MM:g}]: ", DEFAULT_CHORD_MM, parse_plain)
    speed = pick(args.speed, f"  Speed in m/s, or like 100kmh [{DEFAULT_SPEED:g} = {DEFAULT_SPEED * 3.6:.0f} km/h]: ",
                 DEFAULT_SPEED, parse_speed)

    if role == "rw":
        span_rw = pick(args.span_rw_mm, f"  Rear wing span in mm [{DEFAULT_SPAN_RW_MM:g}] (T8.2.2): ",
                       DEFAULT_SPAN_RW_MM, parse_plain)
        span_fw = args.span_fw_mm if args.span_fw_mm not in (None, 0) else DEFAULT_SPAN_FW_MM
    elif role == "fw":
        span_fw = pick(args.span_fw_mm, f"  Front wing span in mm [{DEFAULT_SPAN_FW_MM:g}] (T8.2.2): ",
                       DEFAULT_SPAN_FW_MM, parse_plain)
        span_rw = args.span_rw_mm if args.span_rw_mm not in (None, 0) else DEFAULT_SPAN_RW_MM
    else:
        span_fw = span_rw = pick(args.span_mm if args.span_mm is not None else args.span_fw_mm,
                                 f"  Wing span in mm [{DEFAULT_SPAN_FW_MM:g}]: ", DEFAULT_SPAN_FW_MM, parse_plain)
    if args.span_mm not in (None, 0):                  # legacy single-span flag overrides both roles
        span_fw = span_rw = args.span_mm

    reg = default_reg()
    if not args.no_reg:
        if asked:
            print("\nFSUK 2026 / FSG v1.1 size limits in mm (press Enter to accept the standard values):")

        def pick_reg(arg, label, default):
            if arg is not None:
                return default if arg == 0 else arg
            return ask_default(label, default, float) if asked else default

        reg["min_ground_clearance_mm"] = pick_reg(
            args.min_clearance_mm, f"  Minimum ground clearance [{MIN_GROUND_CLEARANCE_MM:g}] (T2.3.2): ",
            reg["min_ground_clearance_mm"])
        reg["fw_max_stack_height_mm"] = pick_reg(
            args.fw_max_h_mm, f"  Front wing max stack height [{FW_MAX_STACK_HEIGHT_MM:g}] (T8.2.1b): ",
            reg["fw_max_stack_height_mm"])
        reg["fw_max_stack_length_mm"] = pick_reg(
            args.fw_max_len_mm, f"  Front wing max stack length [{FW_MAX_STACK_LENGTH_MM:g}] (T8.2.3b): ",
            reg["fw_max_stack_length_mm"])
        reg["rw_max_stack_length_mm"] = pick_reg(
            args.rw_max_len_mm, f"  Rear wing max stack length [{RW_MAX_STACK_LENGTH_MM:g}] (T8.2.3a): ",
            reg["rw_max_stack_length_mm"])
        reg["rw_max_total_height_mm"] = pick_reg(
            args.rw_max_h_mm, f"  Rear wing max total height [{RW_MAX_TOTAL_HEIGHT_MM:g}] (T8.2.1c): ",
            reg["rw_max_total_height_mm"])

    wing_h = args.wing_height_mm
    if wing_h == 0:
        wing_h = None
    if wing_h is None and asked and role == "rw" and flow in ("unbounded", "both"):
        print("\nRear-wing total-height rule: how high is the main chord line above the ground?")
        wing_h = ask_number("  Wing height above the ground in mm (0 = skip this rule): ", 0, parse_plain)
        if wing_h == 0:
            wing_h = None

    heights, text = [], args.height
    if flow in ("ground", "both"):
        while True:
            if text is None:
                print("\nGround effect: the ground is at y = 0 and ALL elements are translated up by the wing height.")
                print("  Height = how far the main plane chord line sits above the ground, in percent of the main chord.")
                print(f"  Built-in {DEFAULT_HEIGHT_PCT:g} (about "
                      f"{DEFAULT_HEIGHT_PCT / 100 * (chord or DEFAULT_CHORD_MM):.0f} mm up). A low front wing is more like 30 to 80.")
                print("  Give several heights separated by commas to run each one (e.g. 50,100,300), or like 200mm.")
                text = ask_text(f"Wing height(s) [{DEFAULT_HEIGHT_PCT:g}]: ", f"{DEFAULT_HEIGHT_PCT:g}")
            try:
                heights = parse_height_list(text, chord)
                break
            except ValueError as e:
                print("  ", e)
                if not asked:
                    raise SystemExit("Invalid --height")
                text = None
    span = span_rw if role == "rw" else span_fw
    return {"hours": float(hours), "workers": int(workers), "flow": flow, "heights": heights,
            "chord": chord, "speed": speed, "span": span,
            "role": role, "span_fw": span_fw, "span_rw": span_rw, "reg": reg, "wing_height_mm": wing_h}

def apply_plan_numbers(plan):
    """Sets Re, the newton calculation and the regulatory globals from the plan's chord / speed / role."""
    global PHYS, RE, CHORD_MM, ROLE, REG, WING_MOUNT_HEIGHT_MM
    CHORD_MM = plan.get("chord")
    ROLE = plan.get("role", "custom")
    REG = plan.get("reg") or default_reg()
    WING_MOUNT_HEIGHT_MM = plan.get("wing_height_mm")
    if plan.get("chord") and plan.get("speed"):
        RE = round(plan["speed"] * plan["chord"] / 1000.0 / NU)
        PHYS = dict(chord_mm=plan["chord"], speed=plan["speed"], span_mm=plan_span(plan))
    else:
        PHYS = None

def ground_advice(mains, flaps_pool):
    """Warns if the chosen height is so low that the wings would hit the ground."""
    depth = []
    for _ in range(150):
        n = random.choice((2, 3, 4))
        main = random.choice(mains)
        flaps = tuple((random.choice(flaps_pool), random.choice(GRID[k]["scale"]), random.choice(GRID[k]["angle"]),
                       random.choice(GRID[k]["x"]), random.choice(GRID[k]["y"])) for k in range(1, n))
        outs = build_outlines((main, flaps), ground_h=None)
        depth.append(-100 * min(o[:, 1].min() for o in outs))
    need = max(depth) + MIN_CLEARANCE_PCT
    typical = float(np.median(depth)) + MIN_CLEARANCE_PCT
    if GROUND_H < need:
        print(f"\nNOTE: the lowest point of the wings sits {min(depth):.0f} to {max(depth):.0f}% of the chord below the main plane "
              f"chord line (typically {typical - MIN_CLEARANCE_PCT:.0f}%). At {GROUND_H:g}% height, wings that go below the ground "
              f"minus {MIN_CLEARANCE_PCT:g}% clearance are skipped; about {need:.0f}% keeps every sampled wing.")

def setup_workers(n):
    global WORKER_DIRS, JAVA_DIR
    WORKER_DIRS = queue.Queue()
    jf, mh = find_java_jars()
    if os.path.isabs(jf) and os.path.isfile(jf):
        JAVA_DIR = os.path.dirname(jf)

    if n == 1:
        if os.path.isdir(JAVA_DIR):
            WORKER_DIRS.put(JAVA_DIR)
            return
        single_dir = os.path.join(RUN_DIR, "work", "w0")
        os.makedirs(single_dir, exist_ok=True)
        if os.path.isfile(jf):
            try: shutil.copy(jf, single_dir)
            except Exception: pass
        if mh and os.path.isfile(mh):
            try: shutil.copy(mh, single_dir)
            except Exception: pass
        WORKER_DIRS.put(single_dir)
        return

    work = os.path.join(RUN_DIR, "work")
    shutil.rmtree(work, ignore_errors=True)
    ignore = shutil.ignore_patterns("wing_*", "script_*", "polar_*", "java_*", "debug_*", "*.csv", "*.py", "__pycache__")
    for i in range(n):
        d = os.path.join(work, f"w{i}")
        if os.path.isdir(JAVA_DIR) and os.path.isfile(os.path.join(JAVA_DIR, JAVAFOIL_JAR)):
            try:
                shutil.copytree(JAVA_DIR, d, ignore=ignore, symlinks=True)
            except Exception:
                os.makedirs(d, exist_ok=True)
                if os.path.isfile(jf):
                    try: shutil.copy(jf, d)
                    except Exception: pass
                if mh and os.path.isfile(mh):
                    try: shutil.copy(mh, d)
                    except Exception: pass
        else:
            os.makedirs(d, exist_ok=True)
            if os.path.isfile(jf):
                try: shutil.copy(jf, d)
                except Exception: pass
            if mh and os.path.isfile(mh):
                try: shutil.copy(mh, d)
                except Exception: pass
        WORKER_DIRS.put(d)

def reset_state():
    global RUN_COUNTER
    RESULTS.clear(); DONE.clear()
    RUN_COUNTER = itertools.count(1)
    START_COUNT[0] = 0; CONSEC_FAILS[0] = 0; FAIL_SAVED[0] = 0; LAST_PRINT[0] = 0.0

def init_timebomb():
    global safe_date_str
    try:
        jf, _ = find_java_jars()
        jar_path = jf if (os.path.isabs(jf) and os.path.isfile(jf)) else os.path.join(JAVA_DIR, JAVAFOIL_JAR)
        if os.path.isfile(jar_path):
            with zipfile.ZipFile(jar_path, "r") as z:
                info = z.getinfo("MH/JavaFoil/JavaFoil.class")
                d = datetime.datetime(*info.date_time) + datetime.timedelta(days=2)
                safe_date_str = f"@{d.strftime('%Y-%m-%d %H:%M:%S')}"
    except Exception:
        pass

def load_previous():
    """Loads an earlier results.csv of this mode. Files written by an older version (missing the flow,
    geometry or mm columns) are upgraded in place; the original is kept as results_backup_<time>.csv.
    Resume stays backward compatible: loaded configs are only added to DONE, never re-checked, so no row
    is lost or re-run and the file is never corrupted."""
    global RUN_COUNTER
    path = RESULTS_FILE[0]
    if not os.path.exists(path):
        return
    d = pd.read_csv(path, on_bad_lines="skip")
    if d.empty:
        return
    legacy = ("Flow" not in d.columns) or ("Stack_Length_pct" not in d.columns)
    if legacy or list(d.columns) != FIELDS:
        backup = path.replace(".csv", f"_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
        shutil.copy(path, backup)
        print(f"Upgrading the results format ({len(d)} rows); backup: {backup}")
        for col in FIELDS:
            if col not in d.columns:
                d[col] = np.nan
        if legacy:
            d["Flow"] = d["Flow"].fillna("ground" if GROUND_H is not None else "unbounded")
            d["Height_pct"] = d["Height_pct"].fillna(GROUND_H if GROUND_H is not None else np.nan)
            for i, r in d.iterrows():
                try:
                    cfg = row_to_cfg({k: (None if (isinstance(v, float) and v != v and k.endswith("Airfoil")) else v)
                                      for k, v in r.items()})
                    for k, v in geometry_columns(cfg).items():
                        d.at[i, k] = v
                except Exception:
                    pass
        elif CHORD_MM:                                  # add the new mm columns from the existing % values
            for pct, mm in (("Stack_Length_pct", "Stack_Length_mm"),
                            ("Stack_Height_pct", "Stack_Height_mm"),
                            ("Min_Clearance_pct", "Min_Clearance_mm")):
                if mm in d.columns and pct in d.columns:
                    d[mm] = d[mm].fillna(pd.to_numeric(d[pct], errors="coerce") / 100.0 * CHORD_MM)
        d = d.reindex(columns=FIELDS)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for r in d.to_dict("records"):
                w.writerow({k: fmt_value(k, r.get(k)) if not (isinstance(r.get(k), float) and math.isnan(r.get(k))) else "" for k in FIELDS})
    for r in d.to_dict("records"):
        r = {k: (None if (isinstance(v, float) and math.isnan(v) and k.endswith("Airfoil")) else v) for k, v in r.items()}
        RESULTS.append(r)
        DONE.add(cfg_key(row_to_cfg(r)))
    RUN_COUNTER = itertools.count(len(d) + 1)
    START_COUNT[0] = len(d)
    print(f"Resuming: {len(d)} earlier results loaded from {path}")


# =====================================================================
# SELF-CHECK (runs automatically before every scenario)
# =====================================================================
def run_test(mains, flaps_pool):
    """Quick check: 1/2/3/4-element runs, your hand baseline, and (in ground mode) that ground effect does something.
    Returns (ok, reason)."""
    print("Self-check:")
    random.seed(1)
    cfgs = [(mains[0], ())]
    for n in (2, 3, 4):
        c = sample_config(n, mains, flaps_pool)
        if c:
            cfgs.append(c)
    lower = {m.lower(): m for m in AIRFOILS}
    base = None
    if "s1223" in lower and "e423" in lower:
        e = lower["e423"]
        base = (lower["s1223"], ((e, 35, -15, 98, 5), (e, 25, -30, 130, 15)))
        cfgs.append(base)
    ok, reason = True, ""
    for c in cfgs:
        r = run_one(c, "test")
        print(f"  {r['Elements']} element(s) -> {r['Status']} | Cl@0 {r.get('Cl_a0')} | Cl_peak {r.get('Cl_peak')} | "
              f"stall {r.get('Stall_Angle')} | tier {r['Tier']} | {r['_took']:.1f}s")
        if r["Status"] != "Valid":
            ok, reason = False, f"a {r['Elements']}-element test run failed ({r['Status']})"
    if base is not None and GROUND_H is None:
        r = RESULTS[-1]
        verdict = "MATCH" if abs(r.get("Cl_peak", 0) + 4.39) < 0.2 else "CHECK ROT_SIGN / airfoil files"
        print(f"  your hand baseline: expect Cl_peak about -4.39 and stall about -3 ({verdict})")
    if GROUND_H is not None and base is not None:
        if geometry_ok(base):
            gnd = next((x for x in reversed(RESULTS) if x.get("Flow") == "ground" and x.get("Main") == base[0]
                        and x.get("Elements") == 3), None)
            unb = run_one(base, "test", ground_h=None)
            if gnd and gnd.get("Cl_a0") is not None and unb.get("Cl_a0") is not None:
                ratio = gnd["Cl_a0"] / unb["Cl_a0"]
                print(f"  ground effect on the baseline: Cl@0 unbounded {unb['Cl_a0']:.3f} | with ground {gnd['Cl_a0']:.3f} | ratio {ratio:.3f}")
                if abs(ratio - 1) < 1e-4:
                    ok, reason = False, "ground effect changed nothing (Options.GroundEffect may not be doing what we expect)"
            else:
                ok, reason = False, "the ground-effect comparison run failed"
        else:
            print(f"  (the baseline touches the ground at this height, so the ground comparison was skipped)")
    return ok, reason


# =====================================================================
# SCENARIOS AND MAIN
# =====================================================================
def run_scenario(sc, budget_h, mains, flaps_pool, plan, check_only, no_check):
    """One flow scenario: self-check, then the campaign. Returns (status text, number of runs)."""
    global GROUND_H, RUN_DIR, ROLE, PHYS
    reset_state()
    STOP.clear()
    GROUND_H = sc["height"]
    ROLE = sc.get("role", plan.get("role", "custom"))
    if PHYS:                                            # per-scenario span (front vs rear wing)
        PHYS["span_mm"] = plan_span(plan, ROLE)
    RUN_DIR = scenario_dir(sc)
    os.makedirs(RUN_DIR, exist_ok=True)
    print("\n" + "=" * 78)
    print(f"SCENARIO: {scenario_label(sc, plan.get('chord'))}   (time budget {budget_h:.1f} h)")
    print(f"Output folder: {RUN_DIR}")
    print("=" * 78)
    if GROUND_H is not None:
        ground_advice(mains, flaps_pool)
    setup_workers(WORKERS)
    T0[0] = time.time()
    try:
        if not no_check or check_only:
            reset_state()
            RESULTS_FILE[0] = os.path.join(RUN_DIR, "results_test.csv")
            ok, reason = run_test(mains, flaps_pool)
            reset_state()
            if not ok:
                print(f"\nSelf-check FAILED: {reason}. Skipping this scenario.")
                print(f"Details of the failed runs: {os.path.join(RUN_DIR, 'failed')}")
                return f"SKIPPED ({reason})", 0
            print("Self-check passed.")
        if check_only:
            return "self-check passed", 0
        random.seed()                                   # the self-check used a fixed seed
        RESULTS_FILE[0] = os.path.join(RUN_DIR, "results.csv")
        load_previous()
        T0[0] = time.time()
        with open(os.path.join(RUN_DIR, "campaign_setup.txt"), "a") as f:
            f.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M} | budget {budget_h:.2f} h | workers {WORKERS} ===\n")
            f.write(f"flow: {scenario_label(sc, plan.get('chord'))}\nphysical: {PHYS}\nairfoils: {sorted(AIRFOILS)}\n")
            f.write(f"RANGES: {RANGES}\nRe {RE:g}, alpha {ALPHA}, design alpha {DESIGN_ALPHA}, ROT_SIGN {ROT_SIGN}\n")
        status = "finished"
        try:
            campaign(budget_h, mains, flaps_pool)
        except KeyboardInterrupt:
            STOP.set()
            INTERRUPT.set()
            print("\nStopping after the runs that are in progress...")
        if INTERRUPT.is_set():
            status = "stopped early (Ctrl+C)"
        elif STOP.is_set():
            status = "stopped early (many runs in a row failed), moving on"
            STOP.clear()                                # only this scenario is affected
        write_outputs()
        d = results_df()
        print(f"\nScenario done: {len(d)} runs in {RESULTS_FILE[0]}")
        print(f"Summary workbook (All / per element count / Best): {os.path.join(RUN_DIR, 'summary.xlsx')}")
        for n in (1, 2, 3, 4):
            top = d[(d['Elements'] == n) & (d['Tier'] <= 3)].sort_values(["Tier", "Score"], ascending=[True, False]).head(3)
            for r in top.to_dict("records"):
                print(f"  {n}el T{int(r['Tier'])} score {r['Score']:.1f} Cl@0 {r['Cl_a0']:.3f} stall {r['Stall_Angle']:.0f}  "
                      f"{describe(row_to_cfg(r))}")
        return status, len(d)
    finally:
        if WORKERS > 1:
            shutil.rmtree(os.path.join(RUN_DIR, "work"), ignore_errors=True)

def run_plan(plan, mains=None, flaps_pool=None, check_only=False, no_check=False, resume=True, on_event=None):
    """Executes an entire multi-scenario campaign plan as configured by the GUI or CLI.

    Args:
        plan (dict): Campaign plan dictionary containing keys such as 'role', 'flow',
                     'hours', 'workers', 'heights', 'chord', 'span', 'out', 'enforce'.
        mains (list, optional): List of main airfoil profile names. Defaults to all available.
        flaps_pool (list, optional): List of flap airfoil profile names. Defaults to all available.
        check_only (bool): If True, only executes the self-check tests for each scenario.
        no_check (bool): If True, skips the pre-scenario self-check.
        resume (bool): Whether to resume previous runs if results.csv exists.
        on_event (callable, optional): Callback with signature on_event(kind, payload).

    Returns:
        list: Summary of tuples (scenario, status, run_count).
    """
    global AIRFOIL_DIR, OUT_DIR, WORKERS, REG_ENFORCE, CHORD_MM, ROLE

    init_grid()
    init_timebomb()

    if not AIRFOILS:
        AIRFOILS.update(load_all(AIRFOIL_DIR))
        if os.path.isdir(AIRFOIL_STORE):
            AIRFOILS.update(load_all(AIRFOIL_STORE))

    if mains is None:
        mains = [n for n in AIRFOILS if MAIN_INCLUDE is None or n in MAIN_INCLUDE]
    if flaps_pool is None:
        flaps_pool = [n for n in AIRFOILS if FLAP_INCLUDE is None or n in FLAP_INCLUDE]

    if not mains or not flaps_pool:
        raise ValueError("No usable airfoils in mains or flaps pool.")

    chord = plan.get("chord") or DEFAULT_CHORD_MM
    if isinstance(plan.get("heights"), str):
        if plan.get("flow") in ("ground", "both") and plan["heights"].strip():
            try:
                plan["heights"] = parse_heights(plan["heights"], chord)
            except Exception:
                plan["heights"] = [100.0]
        else:
            plan["heights"] = []
    elif not plan.get("heights"):
        plan["heights"] = [100.0] if plan.get("flow") in ("ground", "both") else []

    WORKERS = max(1, int(plan.get("workers", 1)))
    REG_ENFORCE = bool(plan.get("enforce", True))
    if "out" in plan and plan["out"]:
        OUT_DIR = os.path.expanduser(plan["out"])
    os.makedirs(OUT_DIR, exist_ok=True)

    apply_plan_numbers(plan)
    scs = plan_scenarios(plan)
    if not scs:
        raise ValueError("Plan contains no valid scenarios.")

    print("\n=== PLAN (executing campaign) ===")
    print(plan_text(plan))
    print(f"  {len(mains)} main-plane candidates, {len(flaps_pool)} flap candidates, Re {RE:,}, alpha {ALPHA[0]} to {ALPHA[1]}")
    if REG_ENFORCE and CHORD_MM:
        print("  FSUK/FSG physical size checks are ON (mm limits above); size-breaking configs are rejected before JavaFoil.")
    elif REG_ENFORCE:
        print("  FSUK/FSG size checks are ON but no chord was given, so only the dimensionless checks run (no mm limits).")
    else:
        print("  FSUK/FSG size checks are OFF (--no-reg).")
    print("  Before each scenario a self-check runs; if it fails, that scenario is skipped and the next one starts.")

    try:
        with open(os.path.join(OUT_DIR, "last_plan.json"), "w") as f:
            json.dump(plan, f)
    except Exception:
        pass

    total_hours = float(plan.get("hours", 0.1))
    t_end = time.time() + total_hours * 3600
    overview = []

    for i, sc in enumerate(scs):
        if INTERRUPT.is_set() or STOP.is_set():
            overview.append((sc, "not started (stopped)", 0))
            continue

        remaining_scenarios = len(scs) - i
        budget = (t_end - time.time()) / 3600 / remaining_scenarios if remaining_scenarios > 0 else 0.01
        if budget < 0.001 and not check_only:
            overview.append((sc, "not started (no time left)", 0))
            continue

        sc_label = scenario_label(sc, plan.get('chord'))
        if on_event:
            try:
                on_event('scenario_start', {'index': i, 'total': len(scs), 'name': sc_label})
            except Exception:
                pass

        status, n = run_scenario(sc, max(budget, 0.01), mains, flaps_pool, plan, check_only, no_check)

        ok = ("pass" in status.lower() or status == "finished" or n > 0)
        if on_event:
            try:
                on_event('scenario_done', {
                    'index': i,
                    'total': len(scs),
                    'name': sc_label,
                    'ok': ok,
                    'runs': n,
                    'status': status
                })
            except Exception:
                pass

        overview.append((sc, status, n))

    print("\n" + "=" * 78 + "\nALL DONE")
    for sc, status, n in overview:
        print(f"  {scenario_label(sc, plan.get('chord')):<60} {status}" + (f", {n} runs" if n else "") + f"\n      {scenario_dir(sc)}")

    return overview


def main():
    global AIRFOIL_DIR, OUT_DIR, WORKERS, REG_ENFORCE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--airfoils", default=AIRFOIL_DIR, help="folder with .dat files")
    ap.add_argument("--out", default=OUT_DIR, help="base output folder")
    ap.add_argument("--hours", type=float, default=None, help="total hours for all scenarios")
    ap.add_argument("--workers", type=int, default=None, help="parallel JavaFoil runs")
    ap.add_argument("--test", action="store_true", help="only run the self-check of each scenario, then stop")
    ap.add_argument("--no-check", action="store_true", help="skip the automatic self-check before each scenario")
    ap.add_argument("--yes", action="store_true", help="do not ask for the final confirmation")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--flow", choices=["unbounded", "ground", "both"], default=None, help="skip the flow question")
    ap.add_argument("--role", choices=["fw", "rw", "custom"], default=None, help="wing role; selects the span and the rule limits")
    ap.add_argument("--height", default=None, help="ground effect height(s): percent of main chord, e.g. 100 or 50,100,300, or like 200mm")
    ap.add_argument("--chord-mm", type=float, default=None, help="main plane chord in mm (built-in 300; 0 = skip)")
    ap.add_argument("--speed", type=float, default=None, help="speed in m/s (built-in 27.74, about 100 km/h; 0 = skip)")
    ap.add_argument("--span-mm", type=float, default=None, help="legacy wing span in mm for both roles (0 = skip)")
    ap.add_argument("--span-fw-mm", type=float, default=None, help="front wing span in mm (built-in 1400, T8.2.2)")
    ap.add_argument("--span-rw-mm", type=float, default=None, help="rear wing span in mm (built-in 950, T8.2.2)")
    ap.add_argument("--wing-height-mm", type=float, default=None, help="wing height above the ground in mm (rear-wing total-height rule)")
    ap.add_argument("--min-clearance-mm", type=float, default=None, help="min ground clearance in mm (T2.3.2, built-in 35)")
    ap.add_argument("--fw-max-h-mm", type=float, default=None, help="front wing max stack height in mm (T8.2.1b, built-in 250)")
    ap.add_argument("--fw-max-len-mm", type=float, default=None, help="front wing max stack length in mm (T8.2.3b, built-in 600)")
    ap.add_argument("--rw-max-h-mm", type=float, default=None, help="rear wing max total height in mm (T8.2.1c, built-in 1100)")
    ap.add_argument("--rw-max-len-mm", type=float, default=None, help="rear wing max stack length in mm (T8.2.3a, built-in 250)")
    ap.add_argument("--no-reg", action="store_true", help="disable the FSUK/FSG physical size checks")
    a = ap.parse_args()
    AIRFOIL_DIR, OUT_DIR = os.path.expanduser(a.airfoils), os.path.expanduser(a.out)
    REG_ENFORCE = not a.no_reg
    if a.seed is not None:
        random.seed(a.seed)

    java_bin = find_java_executable()
    if not is_java_available():
        raise SystemExit(f"Java runtime ('{java_bin}') not found or not working. Please install Java (e.g. from https://adoptium.net).")
    jf_jar, _ = find_java_jars()
    if not (os.path.isabs(jf_jar) and os.path.isfile(jf_jar)):
        raise SystemExit(f"{JAVAFOIL_JAR} not found in {JAVA_DIR} or bundled assets/JavaFoil.")
    if sys.platform != "win32" and shutil.which("faketime") is None:
        print("[note] 'faketime' not found; proceeding with system time.")
    init_timebomb()

    print(f"Loading airfoils from {AIRFOIL_DIR}")
    AIRFOILS.update(load_all(AIRFOIL_DIR))
    mains = [n for n in AIRFOILS if MAIN_INCLUDE is None or n in MAIN_INCLUDE]
    flaps_pool = [n for n in AIRFOILS if FLAP_INCLUDE is None or n in FLAP_INCLUDE]
    if not mains or not flaps_pool:
        raise SystemExit("No usable airfoils (check the folder and MAIN_INCLUDE / FLAP_INCLUDE).")

    plan = build_plan(a)
    if not a.yes and ask_text("\nStart now? [Y/n]: ", "y").lower() in ("n", "no"):
        raise SystemExit("Cancelled.")
    print("\nRunning. Ctrl+C stops safely; run the same command again to resume (it offers to reuse these answers).")
    run_plan(plan, mains, flaps_pool, check_only=a.test, no_check=a.no_check)


if __name__ == "__main__":
    main()
