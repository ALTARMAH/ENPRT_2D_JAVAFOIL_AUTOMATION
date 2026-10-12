#!/usr/bin/env python3
"""
aero_targets.py - find multi-element wings (S1223 + E423 by default) that hit the CL*A target while keeping
CD*A under its roof, and respecting the FSUK 2026 / FSG v1.1 size limits. A = chord x span (T8.2.2):

  Front Wing:         CL*A = 1.75 m2, CD*A <= 0.45 m2   (span 1400 mm)
  Rear Wing & Beam:   CL*A = 1.85 m2, CD*A <= 0.95 m2   (span 950 mm)

CD*A is treated as a ceiling: 2D section drag is a floor estimate and 3D effects raise it, so the drag target is
a sanity bound, not a value to chase. Within_Tol therefore reflects the CL*A match only; Dev_CD_A is reported.

It reuses the campaign's results.csv first (so it can just rank what has already been run) and can also
generate fresh random S1223/E423 configs with --run. The report includes the geometry of every element, the
physical stack sizes, the aerodynamic numbers and the deviation from each target.

Usage
  python aero_targets.py --results ~/aero_campaign/ground/h300pct/results.csv --role fw --chord-mm 300
  python aero_targets.py --role rw --chord-mm 250 --span-rw-mm 950 --top 15 --run 40
  python aero_targets.py --role fw --chord-mm 300 --height 100 --tolerance 0.3
"""
import os
import sys
import random
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aero_auto as A

TARGETS = {
    "fw": dict(cl_a=1.75, cd_a=0.45, label="Front Wing"),
    "rw": dict(cl_a=1.85, cd_a=0.95, label="Rear Wing & Beam Wing"),
}
ROLE_KEY = {"fw": "span_fw", "rw": "span_rw"}


def role_span(role, args):
    return {"rw": args.span_rw_mm, "fw": args.span_fw_mm}[role]


def allowed_names(airfoils, only_s12_e4):
    if not only_s12_e4:
        return set(airfoils)
    lower = {m.lower(): m for m in airfoils}
    return {lower[n] for n in ("s1223", "e423") if n in lower}


def evaluate(d, area, tol, tgt_cl_a, tgt_cd_a, tgt_ld):
    d = d.copy()
    d["Area_m2"] = area
    d["CL_A_actual"] = d["Cl_a0"].abs() * area
    d["CD_A_actual"] = d["Cd_a0"] * area
    d["LD_actual"] = d["CL_A_actual"] / d["CD_A_actual"].replace(0, np.nan)
    d["Dev_CL_A"] = d["CL_A_actual"] - tgt_cl_a
    d["Dev_CD_A"] = d["CD_A_actual"] - tgt_cd_a
    d["Dev_LD"] = d["LD_actual"] - tgt_ld
    d["Within_Tol"] = d["Dev_CL_A"].abs() <= tol
    d["CD_A_under_roof"] = d["CD_A_actual"] <= tgt_cd_a
    band = d.reindex(columns=["Cl_am2", "Cl_a0", "Cl_ap2"]).apply(pd.to_numeric, errors="coerce").abs()
    d["Band_MinAbs"] = band.min(axis=1, skipna=True)
    d["Band_Swing"] = (band.max(axis=1) - band.min(axis=1)).where(
        band.notna().all(axis=1), np.nan)
    d["Dev_Sum"] = d["Dev_CL_A"].abs() + 0.1 * d["Dev_CD_A"].abs()
    return d


def sorted_report(d):
    d = d.sort_values(["Within_Tol", "Dev_Sum", "Band_Swing", "Score"],
                      ascending=[False, True, True, False]).dropna(subset=["Cl_a0"])
    d.insert(0, "Rank", range(1, len(d) + 1))
    out_cols = ["Rank", "Within_Tol", "Area_m2", "CL_A_actual", "CD_A_actual", "LD_actual",
                "Dev_CL_A", "Dev_CD_A", "Dev_LD", "CD_A_under_roof", "Band_MinAbs", "Band_Swing"] + A.FIELDS
    return d.reindex(columns=[c for c in out_cols if c in d.columns])


def build_geometry_ok_filter():
    def ok(row):
        try:
            clean = {k: (None if (isinstance(v, float) and v != v and k.endswith("Airfoil")) else v)
                     for k, v in row.items()}
            return bool(A.geometry_ok(A.row_to_cfg(clean)))
        except Exception:
            return False
    return ok


def run_fresh(count, names, out_dir):
    A.GRID.clear()
    for k, r in A.RANGES.items():
        A.GRID[k] = {p: A.frange(*r[p]) for p in ("scale", "angle", "x", "y")}
    A.RUN_DIR = out_dir
    os.makedirs(out_dir, exist_ok=True)
    A.setup_workers(1)
    A.RESULTS_FILE[0] = os.path.join(out_dir, "targets_runs.csv")
    A.reset_state()
    A.load_previous()
    names = sorted(names)
    made = 0
    tries = 0
    while made < count and tries < count * 40:
        tries += 1
        n = random.randint(2, 4)
        main = random.choice(names)
        flaps = []
        for k in range(1, n):
            g = A.GRID[k]
            flaps.append((random.choice(names), random.choice(g["scale"]), random.choice(g["angle"]),
                          random.choice(g["x"]), random.choice(g["y"])))
        cfg = (main, tuple(flaps))
        if A.cfg_key(cfg) in A.DONE:
            continue
        if not A.geometry_ok(cfg):
            continue
        r = A.run_one(cfg, "targets")
        made += 1
        print(f"  ran {A.describe(cfg)} -> {r['Status']} Cl@0 {r.get('Cl_a0')}")
    return made


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(A.OUT_DIR, "results.csv"),
                    help="results.csv of an earlier campaign (default ~/aero_campaign/results.csv)")
    ap.add_argument("--airfoils", default=A.AIRFOIL_DIR, help="folder with the .dat files")
    ap.add_argument("--role", choices=["fw", "rw"], default="rw", help="wing role; picks the span and the targets")
    ap.add_argument("--chord-mm", type=float, default=A.DEFAULT_CHORD_MM, help="main plane chord in mm")
    ap.add_argument("--span-fw-mm", type=float, default=A.DEFAULT_SPAN_FW_MM, help="front wing span in mm")
    ap.add_argument("--span-rw-mm", type=float, default=A.DEFAULT_SPAN_RW_MM, help="rear wing span in mm")
    ap.add_argument("--tolerance", type=float, default=0.4, help="absolute tolerance on CL*A, CD*A and L/D")
    ap.add_argument("--elements", default="2,3,4", help="element counts to consider, e.g. 2,3,4")
    ap.add_argument("--top", type=int, default=15, help="configs to report")
    ap.add_argument("--flow", choices=["ground", "unbounded"], default="unbounded", help="flow for the regulatory checks")
    ap.add_argument("--height", type=float, default=None, help="ground effect height as a percent of the chord (ground mode)")
    ap.add_argument("--wing-height-mm", type=float, default=None, help="wing height above the ground in mm (RW total-height rule)")
    ap.add_argument("--all-airfoils", action="store_true",
                    help="use every airfoil in the folder instead of just S1223/E423")
    ap.add_argument("--run", type=int, default=0, help="generate this many fresh random S1223/E423 configs first")
    ap.add_argument("--out", default=None, help="target report CSV file (default next to the results file)")
    ap.add_argument("--no-reg", action="store_true", help="ignore the FSUK/FSG size limits")
    ap.add_argument("--version", action="version", version=f"aero_targets {A.VERSION}")
    a = ap.parse_args()

    role = a.role
    tgt = TARGETS[role]
    chord = a.chord_mm or A.DEFAULT_CHORD_MM
    span = role_span(role, a)
    area = chord / 1000.0 * span / 1000.0
    tgt_cl_a = tgt["cl_a"]
    tgt_cd_a = tgt["cd_a"]
    tgt_ld = tgt["cl_a"] / tgt["cd_a"]
    res_path = os.path.abspath(os.path.expanduser(a.results))
    res_dir = os.path.dirname(res_path)

    A.AIRFOILS.update(A.load_all(os.path.expanduser(a.airfoils)))
    A.load_store()
    names = allowed_names(A.AIRFOILS, not a.all_airfoils)
    if not names:
        raise SystemExit("No S1223/E423 profiles found in the airfoil folder (or use --all-airfoils).")

    A.CHORD_MM = chord
    A.ROLE = role
    A.REG = A.default_reg()
    A.REG_ENFORCE = not a.no_reg
    if a.flow == "ground" and a.height is None:
        raise SystemExit("--flow ground requires --height (percent of the chord)")
    try:
        A.set_ground_h(a.height if a.flow == "ground" else None)
    except ValueError as e:
        raise SystemExit(f"Invalid --height: {e}")
    A.WING_MOUNT_HEIGHT_MM = a.wing_height_mm

    rows = []
    if a.run:
        made = run_fresh(a.run, names, res_dir)
        print(f"Generated {made} new configurations into {os.path.join(res_dir, 'targets_runs.csv')}")
        gen = os.path.join(res_dir, "targets_runs.csv")
        if os.path.exists(gen):
            rows.append(A.read_results_csv(gen))
    if os.path.exists(res_path):
        rows.append(A.read_results_csv(res_path))
    if not rows:
        raise SystemExit("No results file found; point --results at a results.csv or use --run N.")

    d = pd.concat(rows, ignore_index=True)
    need = {"Elements", "Tier", "Status", "Cl_a0", "Cd_a0", "Main"}
    missing = sorted(c for c in need if c not in d.columns)
    if missing:
        raise SystemExit(f"results file is missing required column(s): {', '.join(missing)}")
    elements = [int(e) for e in a.elements.split(",") if e.strip()]
    d["Elements"] = pd.to_numeric(d["Elements"], errors="coerce")
    d = d[(d["Elements"].isin(elements)) & (d["Tier"] <= 3) & (d["Status"] == "Valid")
          & d["Cl_a0"].notna() & d["Cd_a0"].notna()].copy()
    d = d[d["Main"].isin(names)].copy()
    for k in (1, 2, 3):
        col = f"F{k}_Airfoil"
        if col in d.columns:
            d = d[d[col].isna() | d[col].isin(names)].copy()
    if d.empty:
        print("No usable rows in the results file.")
        return

    d = evaluate(d, area, a.tolerance, tgt_cl_a, tgt_cd_a, tgt_ld)
    ok = build_geometry_ok_filter()
    d["Reg_OK"] = [ok(r) for r in d.to_dict("records")]
    prior = len(d)
    d = d if a.no_reg else d[d["Reg_OK"]]
    print(f"{prior - len(d)} of {prior} candidate rows break the FSUK/FSG size limits and were dropped "
          f"(--no-reg keeps them).")

    report = sorted_report(d)
    top = report.head(a.top)
    out = a.out or os.path.join(res_dir, "targets_report.csv")
    top.to_csv(out, index=False)
    print(f"\n{top['Within_Tol'].sum():.0f} of the top {len(top)} configs hit CL*A within +/-{a.tolerance}.")
    print(f"CD*A: every candidate sits far below the {tgt_cd_a} roof (2D drag is a floor estimate; "
          f"3D effects push it up), dev shown for reference but not used for Within_Tol.")
    print(f"Role {role.upper()} ({tgt['label']}): CL*A target {tgt_cl_a}, CD*A roof {tgt_cd_a}, "
          f"A = {chord / 1000:.3f} m x {span / 1000:.3f} m = {area:.4f} m2")
    print(f"Target report: {out}\n")

    def _mm(v):
        f = A._safe_float(v)
        return f"{f:.0f}" if f is not None else "?"

    for r in top.to_dict("records"):
        flag = "OK" if r["Within_Tol"] else "  "
        extra = (f"\n     clearance {_mm(r.get('Min_Clearance_mm'))} mm, "
                 f"stack {_mm(r.get('Stack_Length_mm'))} x {_mm(r.get('Stack_Height_mm'))} mm"
                 if A._safe_float(r.get("Stack_Length_mm")) is not None else "")
        print(f"[{flag}] #{int(r['Rank']):>2} {int(r['Elements'])}el score {r['Score']:.1f} | "
              f"CL_A {r['CL_A_actual']:.3f} (dev {r['Dev_CL_A']:+.3f}) | CD_A {r['CD_A_actual']:.3f} "
              f"(roof {tgt_cd_a}) | L/D {r['LD_actual']:.1f} | band swing {r['Band_Swing']:.2f}\n"
              f"     {A.describe(A.row_to_cfg(r))}" + extra)


if __name__ == "__main__":
    main()