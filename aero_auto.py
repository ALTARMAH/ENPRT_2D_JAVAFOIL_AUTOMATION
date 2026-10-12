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

# Sweep ranges per flap position: (min, max, step). Flap 1 follows the main plane, flap 2 follows flap 1...
RANGES = {
    1: dict(scale=(30, 40, 5), angle=(-24, -6, 6),  x=(98, 101, 1),   y=(3, 9, 2)),
    2: dict(scale=(20, 30, 5), angle=(-40, -15, 5), x=(126, 140, 2),  y=(12, 22, 2)),
    3: dict(scale=(15, 25, 5), angle=(-50, -20, 10), x=(148, 164, 4), y=(22, 36, 4)),
}

TOP_K = 8                # parents per element count in each refine round
SWAPS_PER_PARENT = 3     # airfoil-swap neighbours per parent
MAX_ROUND = None         # cap on runs per refine round (None = workers * 20)
MAX_CONSEC_FAILS = 40    # stop if this many runs in a row fail (JavaFoil/faketime broken)
SUMMARY_EVERY = 1800     # seconds between summary.xlsx refreshes

# Score (uses the Cl at the design alpha, not the peak)
W_DF, W_MG, W_EF, W_RB = 0.40, 0.30, 0.20, 0.10
DF_LO, DF_HI = 1.0, 5.0          # |Cl| at design alpha -> 0..1
MARGIN_FULL = 3.0                # deg of stall margin for a full score
LD_LO, LD_HI = 40.0, 120.0       # |Cl|/Cd at design alpha -> 0..1
TIER1_MARGIN, TIER2_MARGIN = 2.0, 1.0
CD_MAX = 0.3

PAIRS = ["Main_to_F1", "F1_to_F2", "F2_to_F3"]
GEO_FIELDS = ([f"{p}_{m}_pct" for p in PAIRS for m in ("Gap", "Overlap", "Step")]
              + ["Stack_Length_pct", "Stack_Height_pct", "Stack_Ymin_pct", "Stack_Ymax_pct"])
FIELDS = (["Run_ID", "Phase", "Elements", "Main"]
          + [f"F{k}_{p}" for k in (1, 2, 3) for p in ("Airfoil", "Scale", "Angle", "X", "Y")]
          + GEO_FIELDS
          + ["Flow", "Height_pct", "Min_Clearance_pct",
             "Stack_Length_mm", "Stack_Height_mm", "Min_Clearance_mm"]
          + ["Date", "Duration_s", "Alpha_Interval"]
          + ["Cl_peak", "Cd_peak", "Stall_Angle", "Max_LD", "Cl_a0", "Cd_a0", "Cm_a0", "Cl_am2", "Cl_ap2",
             "Downforce_N", "Drag_N", "Tier", "Score", "Status", "Speed_ms"])

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

def init_grid():
    """Initialize GRID from RANGES. Call before running campaigns."""
    global GRID
    GRID.clear()
    for k, r in RANGES.items():
        GRID[k] = {p: frange(*r[p]) for p in ("scale", "angle", "x", "y")}
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
def frange(lo, hi, step):
    n = int(math.floor((hi - lo) / step + 1e-9)) + 1
    return [round(lo + i * step, 6) for i in range(n)]

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
    existing = [f for f in os.listdir(store) if f.lower().endswith(".dat")]
    if not existing:
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
                    if fn.lower().endswith(".dat"):
                        try:
                            shutil.copy2(os.path.join(sdir, fn), os.path.join(store, fn))
                        except Exception:
                            pass
                existing = [f for f in os.listdir(store) if f.lower().endswith(".dat")]
                if existing:
                    break


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

def rate(m, status):
    """Returns (tier, score). Tier 4 = rejected."""
    if status != "Valid" or m is None:
        return 4, float("nan")
    cl0, cd0, st = m["Cl_a0"], m["Cd_a0"], m["Stall_Angle"]
    if any(pd.isna(v) for v in (cl0, cd0, st)) or cl0 >= 0 or cd0 <= 0 or cd0 > CD_MAX or st <= ALPHA[0]:
        return 4, float("nan")
    margin = DESIGN_ALPHA - st
    tier = 1 if margin >= TIER1_MARGIN else 2 if margin >= TIER2_MARGIN else 3
    df_s = clip01((abs(cl0) - DF_LO) / (DF_HI - DF_LO))
    mg_s = clip01(margin / MARGIN_FULL)
    ef_s = clip01((abs(cl0) / cd0 - LD_LO) / (LD_HI - LD_LO))
    lo = min(abs(m["Cl_am2"]), abs(m["Cl_ap2"])) if pd.notna(m["Cl_am2"]) and pd.notna(m["Cl_ap2"]) else float("nan")
    rb_s = clip01((lo / abs(cl0) - 0.8) / 0.2) if pd.notna(lo) else 0.5
    return tier, 100 * (W_DF * df_s + W_MG * mg_s + W_EF * ef_s + W_RB * rb_s)

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


def find_java_executable():
    """Locate the java executable across PATH, JAVA_HOME, and standard OS directories."""
    # 1. Direct PATH lookup
    j = shutil.which("java") or shutil.which("java.exe")
    if j and os.path.isfile(j):
        return j

    # 2. JAVA_HOME lookup
    jh = os.environ.get("JAVA_HOME", "").strip()
    if jh:
        for candidate in [
            os.path.join(jh, "bin", "java.exe"),
            os.path.join(jh, "bin", "java"),
            os.path.join(jh, "java.exe"),
            os.path.join(jh, "java"),
        ]:
            if os.path.isfile(candidate):
                return candidate

    # 3. Windows standard installation locations
    if sys.platform == "win32" or os.name == "nt":
        prog_dirs = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramW6432", r"C:\Program Files"),
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("ProgramData", r"C:\ProgramData"),
        ]
        oracle_paths = [
            r"C:\Program Files\Common Files\Oracle\Java\javapath\java.exe",
            r"C:\Program Files (x86)\Common Files\Oracle\Java\javapath\java.exe",
            r"C:\ProgramData\Oracle\Java\javapath\java.exe",
        ]
        for op in oracle_paths:
            if os.path.isfile(op):
                return op

        vendors = [
            "Java", "Eclipse Adoptium", "AdoptOpenJDK", "Microsoft", "BellSoft",
            "Zulu", "Amazon Corretto", "Semeru", "RedHat"
        ]
        for pdir in prog_dirs:
            if not pdir or not os.path.isdir(pdir):
                continue
            for vendor in vendors:
                vpath = os.path.join(pdir, vendor)
                if os.path.isdir(vpath):
                    for root, dirs, files in os.walk(vpath):
                        if "java.exe" in files:
                            candidate = os.path.join(root, "java.exe")
                            if os.path.isfile(candidate):
                                return candidate

    return "java"


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




def export_dxf(cfg, out_path, chord_mm=None, ground_h=None, title="Multi-Element Wing"):
    """
    Export the multi-element wing geometry as a standard AutoCAD ASCII DXF (R12 / AC1009 compatible).
    Includes separate layers for each element, ground plane line, and stack bounding box in millimeters.
    """
    if not AIRFOILS:
        AIRFOILS.update(load_all(AIRFOIL_DIR))
        if os.path.isdir(AIRFOIL_STORE):
            AIRFOILS.update(load_all(AIRFOIL_STORE))

    chord = float(chord_mm or CHORD_MM or DEFAULT_CHORD_MM)
    outlines = build_outlines(cfg, ground_h)
    outlines_mm = [pts * chord for pts in outlines]

    lines = []
    lines += ['0', 'SECTION', '2', 'HEADER', '9', '', '1', 'AC1009', '9', '', '70', '4', '0', 'ENDSEC']
    lines += ['0', 'SECTION', '2', 'TABLES', '0', 'TABLE', '2', 'LAYER', '70', '10']

    layer_names = ['MAIN_ELEMENT'] + [f'FLAP_{i}' for i in range(1, len(outlines_mm))]
    colors = [1, 3, 5, 2, 4, 6]  # Red, Green, Blue, Yellow, Cyan, Magenta
    for i, name in enumerate(layer_names):
        lines += ['0', 'LAYER', '2', name, '70', '0', '62', str(colors[i % len(colors)]), '6', 'CONTINUOUS']
    if ground_h is not None:
        lines += ['0', 'LAYER', '2', 'GROUND_PLANE', '70', '0', '62', '8', '6', 'CONTINUOUS']
    lines += ['0', 'LAYER', '2', 'BOUNDING_BOX', '70', '0', '62', '9', '6', 'CONTINUOUS']
    lines += ['0', 'ENDTAB', '0', 'ENDSEC']

    lines += ['0', 'SECTION', '2', 'ENTITIES']

    # Airfoil elements as closed polylines
    for i, pts in enumerate(outlines_mm):
        lname = layer_names[i]
        lines += ['0', 'POLYLINE', '8', lname, '66', '1', '70', '1']
        for pt in pts:
            lines += ['0', 'VERTEX', '8', lname, '10', f'{pt[0]:.4f}', '20', f'{pt[1]:.4f}', '30', '0.0']
        lines += ['0', 'SEQEND', '8', lname]

    # Ground plane line
    if ground_h is not None:
        all_x = np.concatenate([p[:, 0] for p in outlines_mm])
        x0, x1 = all_x.min() - 50.0, all_x.max() + 50.0
        lines += ['0', 'LINE', '8', 'GROUND_PLANE', '10', f'{x0:.4f}', '20', '0.0', '30', '0.0',
                  '11', f'{x1:.4f}', '21', '0.0', '31', '0.0']

    # Bounding box
    all_x = np.concatenate([p[:, 0] for p in outlines_mm])
    all_y = np.concatenate([p[:, 1] for p in outlines_mm])
    bx0, bx1 = all_x.min(), all_x.max()
    by0, by1 = all_y.min(), all_y.max()
    bbox_pts = [[bx0, by0], [bx1, by0], [bx1, by1], [bx0, by1]]
    lines += ['0', 'POLYLINE', '8', 'BOUNDING_BOX', '66', '1', '70', '1']
    for pt in bbox_pts:
        lines += ['0', 'VERTEX', '8', 'BOUNDING_BOX', '10', f'{pt[0]:.4f}', '20', f'{pt[1]:.4f}', '30', '0.0']
    lines += ['0', 'SEQEND', '8', 'BOUNDING_BOX']

    lines += ['0', 'ENDSEC', '0', 'EOF']
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines) + '\n')
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
    tier, score = rate(m, status)
    row = {"Phase": phase, **cfg_to_row(cfg), "Tier": tier, "Score": score, "Status": status,
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

    for tool in ("faketime", "java"):
        if shutil.which(tool) is None:
            raise SystemExit(f"'{tool}' not found in PATH")
    if not os.path.isfile(os.path.join(JAVA_DIR, JAVAFOIL_JAR)):
        raise SystemExit(f"{JAVAFOIL_JAR} not found in {JAVA_DIR}")
    init_timebomb()

    print(f"Loading airfoils from {AIRFOIL_DIR}")
    AIRFOILS.update(load_all(AIRFOIL_DIR))
    mains = [n for n in AIRFOILS if MAIN_INCLUDE is None or n in MAIN_INCLUDE]
    flaps_pool = [n for n in AIRFOILS if FLAP_INCLUDE is None or n in FLAP_INCLUDE]
    if not mains or not flaps_pool:
        raise SystemExit("No usable airfoils (check the folder and MAIN_INCLUDE / FLAP_INCLUDE).")
    for k, r in RANGES.items():
        GRID[k] = {p: frange(*r[p]) for p in ("scale", "angle", "x", "y")}

    plan = build_plan(a)
    WORKERS = plan["workers"]
    apply_plan_numbers(plan)
    scs = plan_scenarios(plan)
    print("\n=== PLAN (nothing more will be asked after this) ===")
    print(plan_text(plan))
    print(f"  {len(mains)} main-plane candidates, {len(flaps_pool)} flap candidates, Re {RE:,}, alpha {ALPHA[0]} to {ALPHA[1]}")
    if REG_ENFORCE and CHORD_MM:
        print("  FSUK/FSG physical size checks are ON (mm limits above); size-breaking configs are rejected before JavaFoil.")
    elif REG_ENFORCE:
        print("  FSUK/FSG size checks are ON but no chord was given, so only the dimensionless checks run (no mm limits).")
    else:
        print("  FSUK/FSG size checks are OFF (--no-reg).")
    print("  Before each scenario a ~1 minute self-check runs; if it fails, that scenario is skipped and the next one starts.")
    print("  Ground-effect runs are slower than unbounded ones, so expect fewer runs in those scenarios.")
    if not a.yes and ask_text("\nStart now? [Y/n]: ", "y").lower() in ("n", "no"):
        raise SystemExit("Cancelled.")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "last_plan.json"), "w") as f:
        json.dump(plan, f)
    print("\nRunning. Ctrl+C stops safely; run the same command again to resume (it offers to reuse these answers).")

    t_end = time.time() + plan["hours"] * 3600
    overview = []
    for i, sc in enumerate(scs):
        if INTERRUPT.is_set():
            overview.append((sc, "not started (stopped)", 0))
            continue
        budget = (t_end - time.time()) / 3600 / (len(scs) - i)
        if budget < 0.005 and not a.test:
            overview.append((sc, "not started (no time left)", 0))
            continue
        status, n = run_scenario(sc, max(budget, 0.01), mains, flaps_pool, plan, a.test, a.no_check)
        overview.append((sc, status, n))

    print("\n" + "=" * 78 + "\nALL DONE")
    for sc, status, n in overview:
        print(f"  {scenario_label(sc, plan.get('chord')):<60} {status}" + (f", {n} runs" if n else "") + f"\n      {scenario_dir(sc)}")


if __name__ == "__main__":
    main()
