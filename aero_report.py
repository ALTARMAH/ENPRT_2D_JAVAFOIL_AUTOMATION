#!/usr/bin/env python3
"""
aero_report.py - compile a campaign's results.csv into a readable engineering report.

For the given results file it builds, next to the CSV:
    Best/configs.csv           the top configurations recommended to the car
    Best/overview.txt          one-page human summary of those configs
    Best/overview.xlsx         workbook with the top configs, all rows, and a legend
    results_human.csv          every valid row with readable column names
    columns_legend.csv         technical column name -> meaning
    graphs/polar_<Run>.png     Cl vs alpha / drag inset per recommended config
    graphs/geometry_<Run>.png  element stack sketch with slot data, in mm
    graphs/field_<Run>.png     illustrative velocity field (circulation from that config's Cl)

The velocity-field images are a schematic potential-flow model whose circulation comes from
the config's own JavaFoil Cl values; the real force numbers always come from the polars.
Use --resim to re-run JavaFoil with a denser alpha sweep for smoother polar curves
(needs the JavaFoil folder and faketime, like the campaign itself).
"""
import argparse
import os
import subprocess
import sys
import time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__) or "."))
import aero_auto as A  # noqa: E402
import flowfield   # noqa: E402

COLUMNS = list(A.FIELDS)
if "Rank" not in COLUMNS:
    COLUMNS.append("Rank")

# column name -> (human title, unit, description)
LEGEND = {
    "Run_ID": ("Run", "", "unique id of the JavaFoil run"),
    "Phase": ("Phase", "", "campaign phase that produced the row"),
    "Status": ("Status", "", "run outcome: Valid, or the JavaFoil failure reason"),
    "Rank": ("Rank", "", "quality position 1..N (Score, then Max L/D, downforce, drag)"),
    "Date": ("Date", "ISO", "when the run finished (local time, to the second)"),
    "Duration_s": ("Duration", "s", "how long the JavaFoil analysis took"),
    "Alpha_Interval": ("Alpha sweep", "", "polar interval and Reynolds number of the run"),
    "Elements": ("Elements", "", "number of lifting elements (main + flaps)"),
    "Main": ("Main airfoil", "", "main element profile"),
    "F1_Airfoil": ("Flap 1", "", "first flap profile"),
    "F1_Scale": ("Flap 1 scale", "% main chord", "flap chord as a percent of the main chord"),
    "F1_Angle": ("Flap 1 angle", "deg", "flap deflection relative to the main chord"),
    "F1_X": ("Flap 1 X", "% main chord", "flap leading-edge x position"),
    "F1_Y": ("Flap 1 Y", "% main chord", "flap leading-edge y position"),
    "F2_Airfoil": ("Flap 2", "", "second flap profile"),
    "F2_Scale": ("Flap 2 scale", "% main chord", "flap chord as a percent of the main chord"),
    "F2_Angle": ("Flap 2 angle", "deg", "flap deflection relative to the main chord"),
    "F2_X": ("Flap 2 X", "% main chord", "flap leading-edge x position"),
    "F2_Y": ("Flap 2 Y", "% main chord", "flap leading-edge y position"),
    "F3_Airfoil": ("Flap 3", "", "third flap profile"),
    "F3_Scale": ("Flap 3 scale", "% main chord", "flap chord as a percent of the main chord"),
    "F3_Angle": ("Flap 3 angle", "deg", "flap deflection relative to the main chord"),
    "F3_X": ("Flap 3 X", "% main chord", "flap leading-edge x position"),
    "F3_Y": ("Flap 3 Y", "% main chord", "flap leading-edge y position"),
    "Flow": ("Flow", "", "\"ground\" or \"unbounded\""),
    "Height_pct": ("Wing height", "% chord", "main chord height above the ground in ground flow"),
    "Min_Clearance_pct": ("Min ground clearance", "% chord", "lowest point of the stack above the ground"),
    "Stack_Length_pct": ("Stack length", "% chord", "x extent of the whole element stack"),
    "Stack_Height_pct": ("Stack height", "% chord", "y extent of the whole element stack"),
    "Stack_Ymin_pct": ("Stack Y min", "% chord", "lowest point of the stack"),
    "Stack_Ymax_pct": ("Stack Y max", "% chord", "highest point of the stack"),
    "Stack_Length_mm": ("Stack length", "mm", "x extent of the stack (chord in mm)"),
    "Stack_Height_mm": ("Stack height", "mm", "y extent of the stack (chord in mm)"),
    "Min_Clearance_mm": ("Min ground clearance", "mm", "lowest stack point above the ground"),
    "Cl_peak": ("Cl peak", "", "maximum negative-lift coefficient (peak downforce)"),
    "Cd_peak": ("Cd peak", "", "drag coefficient at Cl peak"),
    "Stall_Angle": ("Stall angle", "deg", "angle where Cl peaks (stall)"),
    "Max_LD": ("Max |Cl|/Cd", "", "best lift-to-drag ratio in the negative-alpha range"),
    "Cl_a0": ("Cl at 0 deg", "", "lift coefficient at the design angle"),
    "Cd_a0": ("Cd at 0 deg", "", "drag coefficient at the design angle"),
    "Cm_a0": ("Cm at 0 deg", "", "pitching-moment coefficient at the design angle"),
    "Cl_am2": ("Cl at -2 deg", "", "lift coefficient two degrees below the design angle"),
    "Cl_ap2": ("Cl at +2 deg", "", "lift coefficient two degrees above the design angle"),
    "Downforce_N": ("Downforce", "N", "Cl_a0 * q * wing area"),
    "Drag_N": ("Drag", "N", "Cd_a0 * q * wing area"),
    "Tier": ("Tier", "", "campaign exploration tier (lower = better sampled)"),
    "Score": ("Score", "", "campaign score (higher = better round)"),
}
for pair in A.PAIRS:
    a, b = pair.split("_to_")
    for k in ("Gap", "Overlap", "Step"):
        col = f"{pair}_{k}_pct"
        unit = "deg" if k == "Step" else "% chord"
        desc = (f"slot {k.lower()} between {a} and {b} "
                f"(overlap>0: {b} LE ahead of {a} TE)")
        LEGEND[col] = (f"{a}-to-{b} {k.lower()}", unit, desc)


def human_name(col):
    if col in LEGEND:
        return LEGEND[col][0]
    return col.replace("_", " ").title()


def load(df, names):
    d = df.copy()
    for k in ("Elements", "Tier", "Score", "Cl_a0", "Cd_a0", "Downforce_N", "Drag_N"):
        if k in d.columns:
            d[k] = pd.to_numeric(d[k], errors="coerce")
    d = d[d["Tier"] <= 3] if "Tier" in d.columns else d
    d = d[d["Status"] == "Valid"] if "Status" in d.columns else d
    keep = ["Cl_a0", "Cd_a0", "Downforce_N", "Drag_N"]
    d = d.dropna(subset=[c for c in keep if c in d.columns])
    if names:
        if "Main" in d.columns:
            d = d[d["Main"].isin(names)]
        for k in (1, 2, 3):
            col = f"F{k}_Airfoil"
            if col in d.columns:
                d = d[d[col].isna() | d[col].isin(names)]
    return d


def quality_rank(d):
    d = d.copy()
    order = ("Score", "Max_LD", "Downforce_N", "Drag_N")
    cols = [c for c in order if c in d.columns]
    asc = [c == "Drag_N" for c in cols]
    d = d.sort_values(cols, ascending=asc) if cols else d.sort_index()
    d["Rank"] = np.arange(1, len(d) + 1)
    return d


def select_top(d, n):
    """Round-robin across element counts so the top list contains every stack type if possible."""
    if "Elements" not in d.columns or n < 2 or len(d) <= n:
        return quality_rank(d).head(n)
    d = d.copy()
    groups = [g for _, g in d.groupby("Elements") if not g.empty]
    picked = []
    i = 0
    while len(picked) < n and groups:
        for g in groups:
            if len(picked) >= n:
                break
            if i < len(g):
                picked.append(g.iloc[i])
        i += 1
        groups = [g for g in groups if i < len(g)]
    top = pd.DataFrame(picked)
    return quality_rank(pd.concat([top, d.drop(top.index)]))[:n]


def geometry_mm(r, ground_h, chord):
    cfg = A.row_to_cfg(r)
    outs = A.build_outlines(cfg, ground_h=ground_h)
    xs, ys = [], []
    for o in outs:
        o = np.asarray(o, float) * chord
        xs.append(o[:, 0])
        ys.append(o[:, 1])
    return outs, xs, ys


def element_area(p):
    p = np.asarray(p, float)
    x, y = p[:, 0], p[:, 1]
    return 0.5 * abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def split_cl(outs, cl_total):
    areas = np.array([element_area(o) for o in outs])
    if areas.sum() <= 0:
        return np.array([cl_total] + [0.0] * (len(outs) - 1))
    return cl_total * areas / areas.sum()


def plot_geometry(r, out_png, chord):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    height = None if str(r.get("Flow", "")).lower() != "ground" else float(r.get("Height_pct", 0) or 0)
    outs, xs, ys = geometry_mm(r, height, chord)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = ["#0b3d91", "#c8102e", "#0e7c4b", "#f59e0b", "#6f42c1"]
    labels = ["Main"]
    cfg = A.row_to_cfg(r)
    for k, (n, s, a, x, y) in enumerate(cfg[1], 1):
        labels.append(f"F{k} {n} {s:g}% {a:g}deg")
    for i, o in enumerate(outs):
        ax.plot(np.append(o[:, 0], o[0, 0]) * chord, np.append(o[:, 1], o[0, 1]) * chord,
                color=colors[i % len(colors)], lw=1.8)
        ax.fill(np.append(o[:, 0], o[0, 0]) * chord, np.append(o[:, 1], o[0, 1]) * chord,
                color=colors[i % len(colors)], alpha=0.16)
        m = o.mean(axis=0) * chord
        ax.annotate(labels[i], (m[0], m[1]), fontsize=9, ha="center", color=colors[i % len(colors)])
    for k in range(len(outs) - 1):
        p_, q_ = outs[k], outs[k + 1]
        te = p_[np.argmax(p_[:, 0])] * chord
        le = q_[np.argmin(q_[:, 0])] * chord
        mx = (te[0] + le[0]) / 2
        ax.plot([te[0], le[0]], [te[1], le[1]], ls=":", color="0.45", lw=1)
        ax.annotate(f"gap {(le[1]-te[1]):.0f} mm / {le[0]-te[0]:+.0f} mm",
                    (mx, (te[1] + le[1]) / 2), fontsize=8, color="0.35", ha="center")
    if height is not None:
        ax.axhline(0, color="k", lw=1.4)
        ax.set_ylim(-0.35 * chord, max(ys[-1].max(), 1) + 0.25 * chord)
    ax.set_aspect("equal")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    flow = "ground flow" if height is not None else "unbounded flow"
    ax.set_title(f"{r['Run_ID']}  {int(r['Elements'])} elements  {flow}"
                 + (f"  h={height:g}% chord" if height is not None else "")
                 + f"\n{cfg[0]}    chord {chord:.0f} mm")
    ax.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(out_png, dpi=110)
    plt.close(fig)


def plot_polar(r, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    rid = str(r.get('Run_ID', '')).strip()
    out_dir = os.path.dirname(out_png)
    base_dir = os.path.dirname(out_dir) if os.path.basename(out_dir).startswith("run_") else out_dir

    alphas = []
    cls = []
    cds = []
    source_name = "JavaFoil"

    # 1. Search for authentic polar data in run dir or parent graphs dir
    candidate_jf = [os.path.join(out_dir, f"javafoil_polar_{rid}.txt"),
                    os.path.join(base_dir, f"javafoil_polar_{rid}.txt")]
    candidate_su2 = [os.path.join(out_dir, f"su2_polar_{rid}.csv"),
                     os.path.join(base_dir, f"su2_polar_{rid}.csv")]

    for jf_txt in candidate_jf:
        if os.path.isfile(jf_txt) and os.path.getsize(jf_txt) > 50:
            try:
                df_jf, _ = A.parse_polar(jf_txt)
                if df_jf is not None and not df_jf.empty and 'alpha' in df_jf.columns and 'cl' in df_jf.columns:
                    alphas = df_jf['alpha'].astype(float).values
                    cls = df_jf['cl'].astype(float).values
                    cds = df_jf['cd'].astype(float).values if 'cd' in df_jf.columns else np.zeros_like(alphas)
                    source_name = "JavaFoil Polar"
                    break
            except Exception:
                pass

    if len(alphas) == 0:
        for su2_csv in candidate_su2:
            if os.path.isfile(su2_csv) and os.path.getsize(su2_csv) > 50:
                try:
                    df_su2 = pd.read_csv(su2_csv)
                    if 'alpha' in df_su2.columns and 'Cl' in df_su2.columns:
                        alphas = df_su2['alpha'].astype(float).values
                        cls = df_su2['Cl'].astype(float).values
                        cds = df_su2['Cd'].astype(float).values if 'Cd' in df_su2.columns else np.zeros_like(alphas)
                        source_name = "SU2 2D RANS"
                        break
                except Exception:
                    pass

    if len(alphas) == 0:
        # Check dictionary columns from results row
        raw_alphas = [-2.0, 0.0, 2.0]
        raw_cls = [r.get(c) for c in ("Cl_am2", "Cl_a0", "Cl_ap2")]
        valid = [(a, float(c)) for a, c in zip(raw_alphas, raw_cls) if c is not None and str(c).strip() not in ('', 'nan', 'NaN')]
        if len(valid) >= 2:
            alphas = np.array([v[0] for v in valid])
            cls = np.array([v[1] for v in valid])
            cds = np.zeros_like(cls)
            source_name = "JavaFoil Points"

    if len(alphas) == 0:
        # Check single point fallback
        c0 = r.get("Cl_a0", r.get("su2_cl", r.get("jf_cl", r.get("Cl", None))))
        if c0 is not None and str(c0).strip() not in ('', 'nan', 'NaN', 'None'):
            try:
                c0_val = float(c0)
                alphas = np.array([0.0])
                cls = np.array([c0_val])
                cds = np.array([float(r.get("Cd_a0", r.get("su2_cd", r.get("Cd", 0.15))) or 0.15)])
                source_name = "Design Point α=0°"
            except Exception:
                pass

    fig, ax = plt.subplots(figsize=(8.5, 5.6), dpi=120)
    DARK_BG = '#0b1120'
    CARD_BG = '#1e293b'
    TEXT_COLOR = '#f8fafc'
    GRID_COLOR = '#334155'
    ACCENT_CYAN = '#38bdf8'
    AMBER_COLOR = '#fbbf24'

    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(CARD_BG)
    ax.tick_params(colors='#94a3b8', labelsize=9)
    ax.grid(True, linestyle='--', alpha=0.35, color=GRID_COLOR)
    for s in ax.spines.values():
        s.set_color(GRID_COLOR)

    if len(alphas) >= 3:
        ax.plot(alphas, cls, "o", color=ACCENT_CYAN, ms=6, mfc=ACCENT_CYAN, mec='white', label=f"{source_name} Points")
        deg = min(2, len(alphas) - 1)
        p = np.polyfit(alphas, cls, deg)
        aa = np.linspace(min(alphas), max(alphas), 100)
        ax.plot(aa, np.polyval(p, aa), color=AMBER_COLOR, lw=1.8, alpha=0.9, label=f"Polynomial Fit ({source_name})")
        for a_, c_ in zip(alphas, cls):
            ax.annotate(f"{c_:.2f}", (a_, c_), textcoords="offset points", xytext=(0, 6),
                        fontsize=7.5, color='#cbd5e1', ha="center")
    elif len(alphas) >= 1:
        ax.plot(alphas, cls, "o", color=ACCENT_CYAN, ms=8, mfc=ACCENT_CYAN, mec='white', label=f"{source_name} Point")
        for a_, c_ in zip(alphas, cls):
            ax.axhline(c_, color=AMBER_COLOR, ls='--', lw=1.2, alpha=0.8, label=f"Cl = {c_:.3f} @ α={a_:g}°")
            ax.annotate(f"Cl = {c_:.3f}", (a_, c_), textcoords="offset points", xytext=(0, 8),
                        fontsize=8.5, color=TEXT_COLOR, fontweight='bold', ha="center")
    else:
        ax.text(0.5, 0.5, "Polar sweep not yet simulated for this configuration.\nClick 'Regenerate Run Graphs' to compute polars.",
                ha='center', va='center', color='#94a3b8', fontsize=10, transform=ax.transAxes,
                bbox=dict(boxstyle='round,pad=0.5', fc=DARK_BG, ec=GRID_COLOR))

    pk = float(r.get("Cl_peak", np.nan)) if str(r.get("Cl_peak", "")).strip() not in ('', 'nan', 'NaN') else np.nan
    st = float(r.get("Stall_Angle", np.nan)) if str(r.get("Stall_Angle", "")).strip() not in ('', 'nan', 'NaN') else np.nan
    if not np.isnan(pk):
        ax.plot([st], [pk], "v", color='#f43f5e', ms=9, label=f"Peak Cl {pk:.3f} @ {st:+.0f}°")

    ax.axhline(0, color='#64748b', lw=0.8, linestyle=':')
    ax.set_xlabel("Angle of Attack α (°)", fontsize=9.5, fontweight='bold', color=TEXT_COLOR)
    ax.set_ylabel("Lift / Downforce Coefficient Cl", fontsize=9.5, fontweight='bold', color=TEXT_COLOR)

    cd = float(r.get("Cd_a0", np.nan)) if str(r.get("Cd_a0", "")).strip() not in ('', 'nan', 'NaN') else np.nan
    ld = float(r.get("Max_LD", np.nan)) if str(r.get("Max_LD", "")).strip() not in ('', 'nan', 'NaN') else np.nan
    dn = float(r.get("Downforce_N", np.nan)) if str(r.get("Downforce_N", "")).strip() not in ('', 'nan', 'NaN') else np.nan

    parts = []
    c0_val = r.get("Cl_a0")
    if c0_val is not None and str(c0_val).strip() not in ('', 'nan', 'NaN'):
        try: parts.append(f"Cl@0: {float(c0_val):.3f}")
        except Exception: pass
    if not np.isnan(cd): parts.append(f"Cd@0: {cd:.4f}")
    if not np.isnan(ld): parts.append(f"|Cl|/Cd: {ld:.1f}")
    if not np.isnan(dn): parts.append(f"Downforce: {dn:.1f} N")
    extra = " | ".join(parts)

    try:
        cfg = A.row_to_cfg(r)
        cfg_title = A.describe(cfg)
    except Exception:
        cfg_title = str(r.get('Main_Airfoil', r.get('Run_ID', 'Wing')))

    ax.set_title(f"Aerodynamic Polar — {r.get('Run_ID', 'Run')}: {cfg_title}\n{extra}",
                 fontsize=10.5, fontweight='bold', color=TEXT_COLOR, pad=8)
    ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8, loc="best")
    plt.tight_layout()
    plt.savefig(out_png, dpi=120)
    plt.close(fig)


def plot_field(r, out_png, chord, span_fw, span_rw):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import flowfield as F
    height = None if str(r.get("Flow", "")).lower() != "ground" else float(r.get("Height_pct", 0) or 0)
    cfg = A.row_to_cfg(r)
    outs = A.build_outlines(cfg, ground_h=height)
    cl_total = float(r.get("Cl_a0", 0) or 0)
    cls = split_cl(outs, cl_total)
    alpha = 0.0
    X, Y, U, V = F.compute_field(outs, alpha=alpha, ground_h=height, Cls=cls, nx=300, ny=300)
    sp = np.hypot(U, V)
    display = np.clip(sp, 0, 3.0)
    fig, ax = plt.subplots(figsize=(9.5, 7))
    cf = ax.contourf(X, Y, display, levels=24, cmap="cividis")
    seeds = []
    ylo = float(np.nanmin(Y)) + 0.05
    yhi = float(np.nanmax(Y)) - 0.05
    for y in np.linspace(ylo, yhi, 8):
        seeds += [(x, y) for x in (-0.3, 0.4, 1.0, 1.6)]
    lns = F.streamlines(X, Y, U, V, [s for s in seeds if not np.isnan(display[
        int(np.clip(np.searchsorted(Y[:, 0], s[1]), 0, Y.shape[0] - 1)),
        int(np.clip(np.searchsorted(X[0], s[0]), 0, X.shape[1] - 1))])], n=240)
    for l in lns:
        ax.plot([p[0] for p in l], [p[1] for p in l], color="white", lw=0.6, alpha=0.8)
    if height is not None:
        ax.axhline(0, color="tab:red", lw=1.4)
    for o in outs:
        ax.plot(np.append(o[:, 0], o[0, 0]), np.append(o[:, 1], o[0, 1]), color="k", lw=1.4)
        ax.fill(np.append(o[:, 0], o[0, 0]), np.append(o[:, 1], o[0, 1]), color="0.15")
    cb = fig.colorbar(cf, ax=ax, label="|V| / Vinf  (clipped at 3)")
    ax.set_aspect("equal")
    flow = "ground flow" if height is not None else "unbounded flow"
    q = 0.5 * A.DEFAULT_SPEED ** 2 * 1.225
    span = span_fw if height is not None else span_rw
    area = chord / 1000 * span / 1000
    ax.set_title(f"Velocity field {r['Run_ID']} - {flow}"
                 + (f"  h={height:g}% chord" if height is not None else "")
                 + f"\nCl@0 {cl_total:+.3f} -> downforce {abs(cl_total) * q * area:.0f} N (q*area model)"
                 if not np.isnan(cl_total) else "")
    plt.tight_layout()
    plt.savefig(out_png, dpi=110)
    plt.close(fig)


def plot_javafoil_graphs(r, graph_dir, chord=None, run_id=None):
    """Extracts JavaFoil's native aerodynamic graphs directly from JavaFoil's internal solver canvas."""
    rid = run_id or r.get("Run_ID") or r.get("Config_ID") or "Run"
    cfg = A.row_to_cfg(r)
    if not cfg:
        return {}
    height = None if str(r.get("Flow", "")).lower() != "ground" else float(r.get("Height_pct", 0) or 0)
    return A.export_javafoil_graphs(cfg, height, graph_dir, run_id=rid)


def resim_polar_curve(r, wdir, chord, alphas=(-18, 20, 2)):
    """Re-run JavaFoil with a denser alpha sweep for one config. Returns (alpha, cl, cd) rows."""
    import uuid
    height = None if str(r.get("Flow", "")).lower() != "ground" else float(r.get("Height_pct", 0) or 0)
    cfg = A.row_to_cfg(r)
    os.makedirs(wdir, exist_ok=True)
    uid = uuid.uuid4().hex[:8]
    wing = os.path.join(wdir, f"wing_{uid}.txt")
    script = os.path.join(wdir, f"script_{uid}.jfs")
    polar = os.path.join(wdir, f"polar_{uid}.txt")
    logf = os.path.join(wdir, f"java_{uid}.log")
    with open(wing, "w") as f:
        f.write("Automated Multi-Element Wing\n")
        for i, o in enumerate(A.build_outlines(cfg, ground_h=height)):
            if i > 0:
                f.write("9999.9 9999.9\n")
            for pt in o:
                f.write(f"{pt[0]:.6f} {pt[1]:.6f}\n")
    a0, a1, st = alphas
    with open(script, "w") as f:
        f.write(f"""Options.Country(10);
Geometry.Open("{wing}");
Options.MachNumber(0);
Options.StallModel(0);
Options.TransitionModel(1);
Options.GroundEffect({1 if height is not None else 0});
Options.HeightOverSpan(0.5);
Options.AspectRatio(0);
Options.SweepAngle(0.0);
Polar.Analyze({A.RE:g},{A.RE:g},{A.RE:g},{a0:g},{a1:g},{st:g},100,100,0,0);
Polar.Save("{os.path.basename(polar)}");
JavaFoil.Exit();
""")
    cmd = ["faketime", "-f", A.safe_date_str, "java", "-client", "-Xverify:none", "-XX:TieredStopAtLevel=1",
           "-jar", os.path.join(A.JAVA_DIR, A.JAVAFOIL_JAR), f"Script={os.path.basename(script)}"]
    with open(logf, "w") as jl:
        proc = subprocess.Popen(cmd, cwd=wdir, stdout=jl, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            proc.wait(timeout=3 * A.RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    for f in (wing, script, logf):
        try:
            os.remove(f)
        except OSError:
            pass
    if not (os.path.exists(polar) and os.path.getsize(polar) > 0):
        return None
    df, _ = A.parse_polar(polar)
    try:
        os.remove(polar)
    except OSError:
        pass
    if df is None or not {"alpha", "cl", "cd"} <= set(df.columns):
        return None
    return df.dropna(subset=["alpha", "cl", "cd"])


def write_legend(out_path):
    rows = []
    for col in COLUMNS:
        if col in LEGEND:
            title, unit, desc = LEGEND[col]
        else:
            title, unit, desc = human_name(col), "", ""
        rows.append({"column": col, "meaning": title, "unit": unit, "description": desc})
    pd.DataFrame(rows).to_csv(out_path, index=False)


def rename_columns(d):
    renamed = {}
    for c in d.columns:
        name = LEGEND[c][0] if c in LEGEND else human_name(c)
        if name in renamed.values():
            unit = LEGEND[c][1] if c in LEGEND else ""
            name = f"{name} ({unit})" if unit else f"{name}*"
        renamed[c] = name
    out = d.rename(columns=renamed)
    for c in ("Flow", "Elements", "Run", "Phase", "Main airfoil"):
        if c in out.columns:
            out[c] = out[c].astype(str)
    return out


def write_xlsx(top, all_rows, legend, path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Top configs"
    ws.append(["aero_report - top configurations"])
    ws.append([])
    ws.append(list(top.columns))
    for r in top.to_dict("records"):
        ws.append([r[c] for c in top.columns])
    ws2 = wb.create_sheet("All rows")
    ws2.append(list(all_rows.columns))
    for chunk in np.array_split(np.arange(len(all_rows)), max(1, int(np.ceil(len(all_rows) / 500)))):
        for i in chunk:
            r = all_rows.iloc[i]
            ws2.append([r[c] for c in all_rows.columns])
    ws3 = wb.create_sheet("Legend")
    ws3.append(list(legend.columns))
    for r in legend.to_dict("records"):
        ws3.append([r[c] for c in legend.columns])
    wb.save(path)


def overview_text(top, res_path, chord, span_fw, span_rw, ntotal):
    area_fw = chord / 1000 * span_fw / 1000
    area_rw = chord / 1000 * span_rw / 1000
    q = 0.5 * A.DEFAULT_SPEED ** 2 * 1.225
    lines = [
        "=" * 78,
        "AERO REPORT - BEST CONFIGURATIONS",
        "=" * 78,
        f"Results file : {res_path}",
        f"Valid rows   : {ntotal} (Tier <= 3, Valid, Cl/Cd present)",
        f"Main chord   : {chord:.0f} mm   speed {A.DEFAULT_SPEED:.2f} m/s   q {q:.1f} Pa",
        f"Front wing   : span {span_fw:.0f} mm -> A = {area_fw:.4f} m2 -> downforce/Cl {q * area_fw:.1f} N",
        f"Rear wing    : span {span_rw:.0f} mm -> A = {area_rw:.4f} m2 -> downforce/Cl {q * area_rw:.1f} N",
        "",
        "Interpretation (from aero_targets.py):",
        "  - 2D Cl/Cd values are chordwise; CD.A from a 2D polar is a FLOOR estimate, 3D effects",
        "    (tip vortices, interference) push drag up. Treat Cl.A as the match target and Cd.A",
        "    as a ceiling, not a number to chase.",
        "  - The field images are a schematic potential-flow model whose circulation comes from",
        "    that config's own JavaFoil Cl. The polar numbers are the authoritative data.",
        "",
    ]
    for i, r in enumerate(top.to_dict("records"), 1):
        lines.append(f"#{i} {r['Run_ID']}  {A.describe(A.row_to_cfg(r))}")
        fnum = lambda c: float(r.get(c)) if r.get(c) is not None and str(r[c]).lower() not in ("nan", "") else float("nan")
        lines.append(f"    Score {fnum('Score'):.1f} | Cl@0 {fnum('Cl_a0'):+.3f} | "
                     f"Cd@0 {fnum('Cd_a0'):.4f} | max|Cl|/Cd {fnum('Max_LD'):.1f} | "
                     f"stall {fnum('Stall_Angle'):+.0f} deg")
        dn = fnum('Downforce_N')
        gap_extra = (f" | clearance {fnum('Min_Clearance_mm'):.0f} mm"
                     if not np.isnan(fnum('Min_Clearance_mm')) else "")
        lines.append(f"    downforce model {dn:.1f} N | stack "
                     f"{fnum('Stack_Length_mm'):.0f} x {fnum('Stack_Height_mm'):.0f} mm{gap_extra}")
        lines.append("")
    return "\n".join(lines)


def ensure_mm_columns(d, chord):
    """results.csv from older campaigns may lack the mm geometry columns; rebuild them."""
    d = d.copy()
    needs = [c for c in ("Stack_Length_mm", "Stack_Height_mm", "Min_Clearance_mm") if c not in d.columns]
    if not needs:
        return d
    for i in range(len(d)):
        height = None if str(d.iloc[i].get("Flow", "")).lower() != "ground" \
            else float(d.iloc[i].get("Height_pct", 0) or 0)
        cfg = A.row_to_cfg(d.iloc[i])
        outs = A.build_outlines(cfg, ground_h=height)
        allp = np.vstack(outs) * chord
        vals = {"Stack_Length_mm": float(allp[:, 0].max() - allp[:, 0].min()),
                "Stack_Height_mm": float(allp[:, 1].max() - allp[:, 1].min())}
        if height is not None:
            vals["Min_Clearance_mm"] = float(allp[:, 1].min())
        for c in needs:
            d.at[d.index[i], c] = vals.get(c, np.nan)
    return d


def ensure_force_columns(d, chord, span_fw, span_rw):
    """Older results.csv have no force columns; compute them from the polar data instead."""
    if "Downforce_N" in d.columns and "Drag_N" in d.columns:
        return d
    d = d.copy()
    q = 0.5 * A.DEFAULT_SPEED ** 2 * 1.225
    span_row = []
    for i in range(len(d)):
        flow = str(d.iloc[i].get("Flow", "")).lower()
        span = span_rw if flow != "ground" else span_fw
        area = chord / 1000 * span / 1000
        try:
            cl = float(d.iloc[i].get("Cl_a0"))
        except (TypeError, ValueError):
            cl = float("nan")
        try:
            cd = float(d.iloc[i].get("Cd_a0"))
        except (TypeError, ValueError):
            cd = float("nan")
        d.at[d.index[i], "Downforce_N"] = abs(cl) * q * area
        d.at[d.index[i], "Drag_N"] = cd * q * area
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(A.OUT_DIR, "results.csv"),
                    help="results.csv of an earlier campaign")
    ap.add_argument("--airfoils", default=A.AIRFOIL_DIR, help="folder with the .dat files")
    ap.add_argument("--chord-mm", type=float, default=A.DEFAULT_CHORD_MM,
                    help="main plane chord in mm (needed for the mm geometry and forces)")
    ap.add_argument("--span-fw-mm", type=float, default=A.DEFAULT_SPAN_FW_MM)
    ap.add_argument("--span-rw-mm", type=float, default=A.DEFAULT_SPAN_RW_MM)
    ap.add_argument("--top", type=int, default=5, help="configurations to recommend")
    ap.add_argument("--graph-count", type=int, default=0,
                    help="how many of the top configs get graphs (default: all)")
    ap.add_argument("--no-images", action="store_true", help="skip the PNG graphs")
    ap.add_argument("--resim", action="store_true", help="re-run JavaFoil with a denser alpha sweep "
                    "for the polar graphs (slow for multi-element stacks)")
    ap.add_argument("--alpha-range", default="4,26,2",
                    help="resim alpha sweep 'start,end,step' in degrees (default 4,26,2)")
    ap.add_argument("--out", default=None, help="output folder (default: next to the results file)")
    a = ap.parse_args()

    import matplotlib
    if not a.no_images:
        matplotlib.use("Agg")
    res_path = os.path.abspath(os.path.expanduser(a.results))
    res_dir = os.path.dirname(res_path)
    out_dir = os.path.abspath(os.path.expanduser(a.out)) if a.out else res_dir
    best_dir = os.path.join(out_dir, "Best")
    graph_dir = os.path.join(out_dir, "graphs")
    os.makedirs(best_dir, exist_ok=True)
    if not a.no_images:
        os.makedirs(graph_dir, exist_ok=True)

    A.AIRFOILS.update(A.load_all(os.path.expanduser(a.airfoils)))
    names = set(A.AIRFOILS.keys())
    if not os.path.exists(res_path):
        raise SystemExit(f"no results file at {res_path}")

    chord = a.chord_mm or A.DEFAULT_CHORD_MM
    A.CHORD_MM = chord
    A.GROUND_H = None

    d = pd.read_csv(res_path, on_bad_lines="skip")
    d = load(d, names)
    if d.empty:
        raise SystemExit("No usable rows (need Tier<=3, Status=Valid, Cl_a0/Cd_a0 present).")
    d = ensure_mm_columns(d, chord)
    d = ensure_force_columns(d, chord, a.span_fw_mm, a.span_rw_mm)
    ranked = quality_rank(d).copy()
    top = select_top(d, a.top)

    top.to_csv(os.path.join(best_dir, "configs.csv"), index=False)
    write_legend(os.path.join(out_dir, "columns_legend.csv"))
    human = rename_columns(ranked)
    human.to_csv(os.path.join(out_dir, "results_human.csv"), index=False)
    overview = overview_text(top, res_path, chord, a.span_fw_mm, a.span_rw_mm, len(ranked))
    with open(os.path.join(best_dir, "overview.txt"), "w") as f:
        f.write(overview + "\n")
    legend = pd.read_csv(os.path.join(out_dir, "columns_legend.csv"))
    try:
        write_xlsx(top, human, legend, os.path.join(best_dir, "overview.xlsx"))
    except Exception as e:
        print(f"(xlsx skipped: {e})")

    print(overview)
    print("Written:",
          os.path.join(best_dir, "configs.csv"), "|", os.path.join(best_dir, "overview.txt"), "|",
          os.path.join(best_dir, "overview.xlsx"))
    print("         ", os.path.join(out_dir, "results_human.csv"), "|", os.path.join(out_dir, "columns_legend.csv"))

    if a.no_images:
        return
    n_graphs = a.graph_count if a.graph_count > 0 else len(top)
    n_graphs = min(n_graphs, len(top))
    for i, r in enumerate(top.head(n_graphs).to_dict("records"), 1):
        rid = r["Run_ID"]
        try:
            plot_geometry(r, os.path.join(graph_dir, f"geometry_{rid}.png"), chord)
            plot_polar(r, os.path.join(graph_dir, f"polar_{rid}.png"))
            print(f"  [{i}/{n_graphs}] {rid} geometry + polar done")
        except Exception as e:
            print(f"  [{i}/{n_graphs}] {rid} graph failed: {e}")
        try:
            plot_field(r, os.path.join(graph_dir, f"field_{rid}.png"), chord,
                       a.span_fw_mm, a.span_rw_mm)
            print(f"  [{i}/{n_graphs}] {rid} field done")
        except Exception as e:
            print(f"  [{i}/{n_graphs}] {rid} field failed: {e}")
        try:
            jf_outs = plot_javafoil_graphs(r, graph_dir, chord, rid)
            if jf_outs:
                print(f"  [{i}/{n_graphs}] {rid} JavaFoil native graphs extracted ({len(jf_outs)} plots: polar, Cp, BL)")
        except Exception as e:
            print(f"  [{i}/{n_graphs}] {rid} JavaFoil native graphs skipped: {e}")
        if a.resim:
            lo, hi, st = [int(x) for x in a.alpha_range.split(",")]
            wdir = os.path.join(out_dir, "resim_tmp")
            print(f"  [{i}/{n_graphs}] {rid} resim alpha {lo}..{hi} step {st} ...")
            t0 = time.time()
            df = resim_polar_curve(r, wdir, chord, alphas=(lo, hi, st))
            dt = time.time() - t0
            if df is not None and len(df):
                att = [df.columns.tolist()] + df.round(4).values.tolist()
                with open(os.path.join(graph_dir, f"polar_{rid}.csv"), "w") as f:
                    for ln in att:
                        f.write(",".join(str(x) for x in ln) + "\n")
                print(f"  [{i}/{n_graphs}] {rid} resim done ({len(df)} rows, {dt:.0f}s)")
            else:
                print(f"  [{i}/{n_graphs}] {rid} resim failed ({dt:.0f}s)")


if __name__ == "__main__":
    main()