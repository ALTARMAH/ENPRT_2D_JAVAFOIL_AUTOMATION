#!/usr/bin/env python3
"""
render_field.py - save a potential-flow field image for one wing configuration.

  python render_field.py --main s1223 --flap e423,30,-6,100,5 --out field.png \
      --alpha 0 --ground-height 300 --chord-mm 300 --nx 300 --ny 300

Writes a velocity-magnitude contour map (streamlines overlaid) with the same
schematic coloring as the aero_report field graphs.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import aero_auto as A  # noqa: E402
import flowfield as FF  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="render_field")
    ap.add_argument("--main", required=True, help="main element airfoil name")
    ap.add_argument("--flap", action="append", default=[],
                    help="flap as 'airfoil,scale,angle,x,y' (repeatable up to 3)")
    ap.add_argument("--alpha", type=float, default=0.0, help="angle of attack, deg")
    ap.add_argument("--ground-height", type=float, default=None,
                    help="main height above ground as percent of chord (rows the wing up; ground at y=0)")
    ap.add_argument("--chord-mm", type=float, default=300.0, help="chord in mm for the metric overlay")
    ap.add_argument("--out", default="field.png")
    ap.add_argument("--nx", type=int, default=300)
    ap.add_argument("--ny", type=int, default=300)
    ap.add_argument("--version", action="version", version=f"render_field {A.VERSION}")
    args = ap.parse_args(argv)

    if args.ground_height is not None and args.ground_height <= 0:
        raise SystemExit("--ground-height must be a positive percent of the chord")
    af_dir = os.path.expanduser(A.AIRFOIL_DIR)
    if os.path.isdir(af_dir):
        A.AIRFOILS.update(A.load_all(af_dir))
    else:
        raise SystemExit(f"airfoil folder not found: {af_dir}")
    if os.path.isdir(A.AIRFOIL_STORE):
        A.AIRFOILS.update(A.load_all(A.AIRFOIL_STORE))
    flaps = []
    for f in args.flap:
        bits = f.split(",")
        if len(bits) != 5:
            raise SystemExit("flap must be 'airfoil,scale,angle,x,y'")
        name, s, a, x, y = bits
        flaps.append((name.strip(), float(s), float(a), float(x), float(y)))
    cfg = (args.main, tuple(flaps))

    try:
        outs = A.build_outlines(cfg, ground_h=args.ground_height)
    except (KeyError, ValueError) as e:
        raise SystemExit(f"cannot build geometry: {e}")
    ground_h = args.ground_height
    # circulation estimate from the most recent JavaFoil Cl if a report cache exists
    cl = _best_cl(cfg)
    print(f"using Cl@{args.alpha:g} deg = {cl:.3f} (from results, or -2.0 fallback)", file=sys.stderr)

    X, Y, U, V = FF.compute_field(outs, alpha=args.alpha, ground_h=ground_h, Cls=[cl] * len(outs),
                                  nx=args.nx, ny=args.ny)
    sp = np.hypot(U, V)
    sp = np.clip(sp, 0, 3)

    fig, ax = plt.subplots(figsize=(8.5, 6), dpi=110)
    cm = ax.pcolormesh(X, Y, sp, cmap="viridis", vmin=0, vmax=3, shading="auto")
    fig.colorbar(cm, ax=ax, label="|V| / U (clipped to 3; white = inside the wing)")
    for o in outs:
        ax.plot(np.append(o[:, 0], o[0, 0]), np.append(o[:, 1], o[0, 1]), color="black", lw=1.4)
    for x0, y0 in _seed_lines(X, Y):
        pts = FF.streamlines(X, Y, U, V, seeds=[(x0, y0)], n=220, ds=0.02)
        if pts and len(pts[0]) > 2:
            line = np.asarray(pts[0], float)
            ax.plot(line[:, 0], line[:, 1], color="white", lw=0.6, alpha=0.55)
    if args.ground_height:
        ax.axhline(0, color="red", lw=1.4)
    ax.set_aspect("equal")
    ax.set_xlabel("x (chords)")
    ax.set_ylabel("y (chords)")
    ax.set_title(f"{cfg[0]} + {len(cfg[1])} flaps  alpha {args.alpha:g} deg  "
                 f"(chord {args.chord_mm:g} mm = shown distance)")
    fig.tight_layout()
    fig.savefig(args.out, dpi=110)
    print("wrote", args.out)
    return 0


def _seed_lines(X, Y):
    lines = []
    for i in range(4, 16, 2):
        lines.append((X[0, 0] + (i / 20) * (X[0, -1] - X[0, 0]), Y[1, 0] + 0.02 * (Y[-1, 0] - Y[1, 0])))
    return lines


def _best_cl(cfg):
    """Quick lookup of a representative Cl_a0 for this main airfoil from an existing results file."""
    import glob
    main = cfg[0]
    for path in (os.path.join(A.OUT_DIR, "results.csv"),
                 os.path.join(A.OUT_DIR, "ground", "**", "results.csv")):
        for p in glob.glob(path, recursive=True):
            try:
                import pandas as pd
                d = pd.read_csv(p, on_bad_lines="skip")
            except Exception:
                continue
            if d.empty or "Cl_a0" not in d.columns:
                continue
            if "Main" in d.columns:
                match = d[d["Main"] == main]
                if not match.empty:
                    d = match
            d = d[pd.to_numeric(d["Cl_a0"], errors="coerce").notna()]
            if d.empty:
                continue
            return float(d["Cl_a0"].iloc[len(d) // 2])
    return -2.0


if __name__ == "__main__":
    sys.exit(main())