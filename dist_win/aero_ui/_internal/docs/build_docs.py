#!/usr/bin/env python3
"""
build_docs.py - generate the dark-themed documentation for aero_auto.

  python3 build_docs.py [--only report|manual]

Builds, into this docs/ folder:
  TECHNICAL_GUIDE.pdf   large dark technical report - every code addition,
                        with the actual source (extracted verbatim from the
                        modules via inspect.getsource) plus why/how/for-what.
  USER_MANUAL.pdf       dark user manual.

Run with reportlab installed:  python3 -m pip install reportlab
"""
import os
import sys
import argparse

# ------------------------------------------------------------------ paths
HERE = os.path.dirname(os.path.abspath(__file__))
MODROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, MODROOT)

import importlib.util  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (Paragraph, Spacer, Preformatted, PageBreak,  # noqa: E402
                                Image, Flowable, NextPageTemplate)
from reportlab.platypus.doctemplate import SimpleDocTemplate  # noqa: E402

import theme  # noqa: E402
S = theme.register_styles()
BG, PANEL = theme.BG, theme.PANEL

import inspect  # noqa: E402
import textwrap  # noqa: E402
import traceback  # noqa: E402

ICON = os.path.join(os.path.dirname(HERE), "assets", "icon.png")

warnings = []


def load_modules():
    for name in ("aero_auto", "aero_targets", "aero_report", "flowfield",
                 "aero_ui", "render_field", "launcher"):
        spec = importlib.util.find_spec(name)
        if spec is None:
            warnings.append(f"module not importable: {name}")
    import aero_auto as A
    import aero_targets as T
    import aero_report as R
    import flowfield as FF
    import aero_ui as UI
    import render_field as RF
    import launcher as L
    return A, T, R, FF, UI, RF, L


A, T, R, FF, UI, RF, L = load_modules()


# ---------------------------------------------------------------- helpers
def P(txt, st="body"):
    return Paragraph(txt, S[st])


def tag(txt):
    return P(txt, "tag")


def why(txt):
    return P(f"<b>Why.</b> {txt}", "why")


def how(txt):
    return P(f"<b>How.</b> {txt}", "how")


def bullets(items):
    return [P(x, "bullet") for x in items]


def get_code(obj, name=None):
    """Verbatim source of a function/method; returns (code|None, error)."""
    try:
        src = textwrap.dedent(inspect.getsource(obj)).rstrip("\n")
        return src, None
    except Exception as e:
        return None, f"{name or obj}: {e}"


def code_block(src, cap=None):
    out = []
    if cap:
        out.append(P(cap, "codecap"))
    out.append(Preformatted(src, S["code"]))
    return out


def feature(tag_s, title_s, why_s, how_s, for_s, code_obj, cap=None):
    """Standard feature block: tag · title · why · how · what-for · code."""
    e = [tag(tag_s), P(f"<b>{title_s}</b>", "h3")]
    if why_s:
        e.append(why(why_s))
    if how_s:
        e.append(how(how_s))
    if for_s:
        e.append(P(f"<b>Used for:</b> {for_s}", "body"))
    if code_obj is not None:
        src, err = get_code(code_obj)
        if src:
            e += code_block(src, cap)
        else:
            e.append(P(f"[code unavailable: {err}]", "note"))
            warnings.append(err)
    e.append(Spacer(1, 6))
    return e


def note(txt):
    return P(f"<b>Note.</b> {txt}", "note")


# ---------------------------------------------------------------- cover
def cover(e, title, subtitle, abstract, contents):
    if os.path.exists(ICON):
        e.append(Image(ICON, width=30 * mm, height=30 * mm, hAlign="LEFT"))
    e.append(Spacer(1, 6))
    e.append(P(title, "title"))
    e.append(P(subtitle, "subtitle"))
    e.append(Spacer(1, 8))
    e.append(P(abstract, "intro"))
    e.append(Spacer(1, 4))
    e.append(P("Contents", "h2"))
    e += bullets(contents)
    e.append(PageBreak())


# ---------------------------------------------------------------- chapters
def ch_architecture(e):
    e.append(P("1  System architecture", "h1"))
    e.append(P("The toolchain is seven flat modules that import each other by file name "
               "(there is no package install step). The GUI and the CLI launcher share the "
               "same engine, so a wing you sanity-check in the GUI can be run as a campaign "
               "and then reported by the same code path.", "body"))
    rows = [
        [P("<b>Module</b>", "cellb"), P("<b>Responsibility</b>", "cellb")],
        [P("aero_auto.py", "cell"), P("Regulatory defaults, geometry/outlines, JavaFoil runner "
            "(run, diagnose, parse), quality scoring, multi-phase campaign planner, "
            "force/geometry output columns, all-mm rule checks.", "cell")],
        [P("aero_targets.py", "cell"), P("Target report - every valid row compared with the "
            "CL*A design target and the CD*A budget roof.", "cell")],
        [P("aero_report.py", "cell"), P("Report builder - ranked tables, dark-free Excel "
            "workbook, legend, polar/geometry/field graphs, legacy-CSV repair, optional "
            "denser JavaFoil polar re-run (--resim).", "cell")],
        [P("flowfield.py", "cell"), P("Schematic potential-flow model (source panels + "
            "quarter-chord vortices + ground images) for the field images.", "cell")],
        [P("aero_ui.py", "cell"), P("Tkinter shell - Configure, Airfoils, Campaigns, Results "
            "(universal CSV navigator, dynamic table, KPI banner, inspector), and Graphs.", "cell")],
        [P("render_field.py", "cell"), P("CLI to render a single field PNG from a wing "
            "configuration.", "cell")],
        [P("launcher.py", "cell"), P("Cross-platform entry point: ui | campaign | report | "
            "targets | field; environment overrides.", "cell")],
    ]
    e.append(theme.dark_table(rows, [48 * mm, 142 * mm]))
    e.append(Spacer(1, 6))
    e.append(P("Data flow", "h2"))
    rows2 = [
        [P("<b>Stage</b>", "cellb"), P("<b>Where</b>", "cellb"), P("<b>Output</b>", "cellb")],
        [P("geometry gate", "cell"), P("aero_auto.geometry_ok", "cell"),
         P("rejects colliding/oversized/touching-ground stacks before JavaFoil", "cell")],
        [P("simulation", "cell"), P("aero_auto.simulate", "cell"),
         P("metrics dict per configuration (Cl/Cd/Cm, stall, peak)", "cell")],
        [P("campaign", "cell"), P("aero_auto.campaign", "cell"),
         P("rows appended to results.csv (+ per-height ground files)", "cell")],
        [P("analysis", "cell"), P("aero_report / aero_targets", "cell"),
         P("configs.csv, overview.xlsx, graphs, targets_report.csv", "cell")],
        [P("visualisation", "cell"), P("flowfield.compute_field", "cell"),
         P("field_&lt;Run&gt;.png velocity maps", "cell")],
    ]
    e.append(theme.dark_table(rows2, [40 * mm, 60 * mm, 90 * mm]))


def ch_decisions(e):
    e.append(P("2  Design decisions and rationale", "h1"))
    e.append(P("This chapter answers \"why does the code look the way it does?\". Every "
               "decision below was made against a measured failure or a concrete constraint, "
               "not taste.", "body"))

    e.append(P("2.1  A calibrated field model instead of an in-house solver", "h2"))
    e.append(P("The first implementation derived circulation from a constant-strength "
               "vortex-panel linear system whose boundary condition was zero normal velocity "
               "at collocation points. Releasing the TE Kutta condition in several "
               "arrangements (extra row, replacing the TE row, sources + one global "
               "circulation vortex at the TE then at the quarter chord, ridge/Tikhonov "
               "regularisation) never converged: residuals ~193 and absurd Cl (48) or "
               "negative Cl for cambered airfoils (-10.2 on s1223), plus a flat plate that "
               "still carried Cl 4.3 at zero angle. The normal-BC matrix is near-singular for "
               "multi-element stacks, TE-adjacent panels swamp the Kutta sensitivity, and "
               "sign extraction of Q = u - i v was a constant source of error. The pragmatic "
               "answer: keep JavaFoil as the authority and drive the field with the "
               "circulation it already produces. See chapter 7.", "body"))
    e.append(note("Polar numbers are always the authoritative data. The field images are "
                  "illustrative and labelled as such in every generated graph."))

    e.append(P("2.2  One source of truth with call-your-own fallbacks", "h2"))
    e.append(P("Campaign CSVs got richer over time - the 2025-era root results.csv carries "
               "neither geometry columns nor forces, the ground-effect files carry percent "
               "geometry but no millimetres. Rather than force a re-campaign, the report "
               "layer rebuilds what is missing (ensure_mm_columns, ensure_force_columns) so "
               "any historical file produces a complete report today."))

    e.append(P("2.3  Forces are magnitudes, drag is a budget", "h2"))
    e.append(P("Downforce_N is stored as |Cl| q A (a magnitude, matching the aero_auto "
               "force_columns convention) because the steering/clamping side of the team "
               "writes it as a positive number; sign flips (ground vs inverted airfoil) are "
               "a property of the polar graph, not of the force model. CD*A is a roof: a "
               "budget shared with the rest of the car.", "body"))

    e.append(P("2.4  Tk is not thread-safe - so nothing touches it off the main thread", "h2"))
    e.append(P("Running a JavaFoil analysis inside the Tk event loop freezes the window for "
               "5-40 s. Running widgets from a worker thread crashes Tcl/Tk (observed with "
               "StringVar.get and widget.after directly). Resolution: workers only push "
               "messages to a queue.Queue; the main loop drains it on a 50 ms timer, so the "
               "UI is never mutated off the Tk thread (see 8.3).", "body"))

    e.append(P("2.5  Clock pinning and Windows portability", "h2"))
    e.append(P("JavaFoil checks its release date at startup, so Linux runs wrap java in "
               "faketime pinned to @2020-01-01. Windows has no faketime; simulate now probes "
               "shutil.which('faketime') and falls back to a direct java call (best-effort - "
               "keep the machine clock sane, or run under WSL).", "body"))


def ch_engine(e):
    e.append(P("3  aero_auto.py - the engine", "h1"))
    e.append(P("Everything below was added on top of the original single-element planner, in "
               "priority order: regulations first, geometry bookkeeping second, then the "
               "Windows-neutral runner and the force model.", "body"))

    e.append(tag("CONSTANTS"))
    e.append(P("<b>Run surface & regulatory constants</b>", "h3"))
    e.append(why("JavaFoil is sensitive to RE and the alpha sweep; the regulatory numbers "
                 "come from FSUK 2026 / FSG v1.1 tables."))
    e.append(how("Module-level defaults keep the CLI questions short; the 120 s timeout "
                 "protects against a hung java process; ELEMENT_WEIGHTS steer the campaign's "
                 "exploration."))
    e.append(P("<b>Used for:</b> set once, overridable from the GUI and the CLI flags.", "body"))
    e.append(Preformatted(
        "RE = 570000               # Reynolds number (replaced if you give chord+speed)\n"
        "ALPHA = (-20, 5, 1)       # polar start, end, step (deg)\n"
        "RUN_TIMEOUT = 120         # seconds per JavaFoil run before it is killed\n"
        "MIN_CLEARANCE_PCT = 1.0   # dimensionless ground-clearance gate\n"
        "ELEMENT_WEIGHTS = {2: 0.25, 3: 0.45, 4: 0.30}\n"
        "FW_MAX_STACK_HEIGHT_MM = 250    FW_MAX_STACK_LENGTH_MM = 600\n"
        "RW_MAX_TOTAL_HEIGHT_MM = 1100    RW_MAX_STACK_LENGTH_MM = 250\n"
        "MIN_GROUND_CLEARANCE_MM = 35", S["code"]))
    e.append(Spacer(1, 5))
    src, err = get_code(A.default_reg)
    if src:
        e += code_block(src, "aero_auto.py - default_reg() (the rule table)")
    e.append(Spacer(1, 5))

    for it in feature(
            "GEOMETRY", "transform_coords / outlines_intersect / build_outlines",
            "Element placement is defined in percent-of-main-chord so any chord in mm can be "
            "applied later; intersection tests reject colliding stacks cheaply.",
            "Each outline is resampled, rotated, scaled and translated from its unit-chord "
            "DAT profile; build_outlines optionally lifts the stack by the ground height so "
            "the geometry is available both translated (for thickness rules) and untranslated "
            "(rotation-invariant clash checks).",
            "all millimetre columns, gap/overlap numbers, field images and GUI preview.",
            A.build_outlines,
            cap="aero_auto.py - build_outlines()"):
        e.append(it)

    for it in feature(
            "REGULATION", "regulatory_reject / geometry_ok",
            "Offending stacks must not reach JavaFoil at all - feedback should be instant, "
            "not 5 s after a failed solve.",
            "geometry_ok chains the cheap checks (neighbour clash heuristic, polygon "
            "intersection, dimensionless ground clearance) and then defers to "
            "regulatory_reject, which returns the first FSUK/FSG rule that is violated so "
            "the GUI can print exactly which limit broke.",
            "the green/red PASS verdict in the GUI preview and the campaign's DONE gate.",
            A.geometry_ok,
            cap="aero_auto.py - geometry_ok()"):
        e.append(it)

    for it in feature(
            "AUDIT", "geometry_columns",
            "The team needs the numbers behind a verdict, comparable across runs.",
            "Computes per-slot-pair gap/overlap/step and stack length/height/clearance in "
            "both % chord and millimetres once a chord is configured.",
            "columns written into every result row and reused by the report/regression tests.",
            A.geometry_columns,
            cap="aero_auto.py - geometry_columns()"):
        e.append(it)
    for it in feature(
            "FORCES", "force_columns",
            "Dimensionless polars say nothing about how much downforce the car actually "
            "makes.",
            "Downforce_N = |Cl_a0| q A and Drag_N = Cd_a0 q A with q = 0.5 * 1.225 * v^2 and "
            "A from chord * role span (fw 1400 mm / rw 950 mm).",
            "every report table, the target report and the GUI result line.",
            A.force_columns,
            cap="aero_auto.py - force_columns()"):
        e.append(it)

    e.append(P("3.1  The JavaFoil runner", "h2"))
    for it in feature(
            "SIMULATE", "simulate()",
            "A single, scriptable path was needed to analyse any stack reproducibly on both "
            "Linux and Windows.",
            "One wing file is written per run (Automated Multi-Element Wing header, 9999.9 "
            "9999.9 element separators, 6-decimal coordinate lines), a JFS script drives "
            "Polar.Analyze over the RE/alpha surface, and java runs with faketime when "
            "present or bare otherwise. A per-run worker directory, its own session and a "
            "timeout keep a hang from killing the campaign.",
            "all polars flowing into results.csv.",
            A.simulate,
            cap="aero_auto.py - simulate() - cmd construction incl. faketime fallback"):
        e.append(it)
    for it in feature(
            "PARSE", "parse_polar / polar_metrics",
            "JavaFoil's .txt export needs tolerant parsing (header rows, unit rows).",
            "parse_polar returns a frame plus the machine-readable headline; "
            "polar_metrics extracts Cl_peak, Cd_peak, Stall_Angle, Max_LD, Cl/Cd/Cm at the "
            "three design alphas (-2, 0, +2)",
            "the FIELDS written into each row and consumed by reports and the GUI.",
            A.parse_polar,
            cap="aero_auto.py - parse_polar()"):
        e.append(it)

    e.append(P("3.2  The campaign planner", "h2"))
    for it in feature(
            "PLANNER", "campaign() - three phases",
            "A brute-force sweep of the design space is far too large; a deadline-driven "
            "search fits a fixed pit session.",
            "Phase 0 runs every main profile alone. Phase 1 (60% of the budget) samples "
            "random 2-4 element stacks weighted per ELEMENT_WEIGHTS; Phase 2 mutates the "
            "leaders via neighbours() until the deadline. Configs are deduplicated by "
            "cfg_key so nothing is solved twice.",
            "autonomous exploration during pit changes, in-garage at home, and CI smoke runs.",
            A.campaign,
            cap="aero_auto.py - campaign()"):
        e.append(it)
    for it in feature(
            "SCORING", "rate() + run_one()",
            "The search needs a single scalar that rewards lift while punishing drag so it "
            "does not chase oversized stacks.",
            "rate converts the metrics into a 0-100 score (uplift dominant, drag as a "
            "discount); run_one wraps the simulate->rate pipeline and appends the enriched "
            "row under a lock, tagging it into DONE.",
            "leader selection, Tier/Score in every results file.",
            A.rate,
            cap="aero_auto.py - rate()"):
        e.append(it)
    for it in feature(
            "OUTPUT", "write_row / fmt_value",
            "CSV columns must stay stable across versions even if the dict grows.",
            "A canonical FIELDS order is enforced at write time with per-column number "
            "formatting; extrasaction=ignore keeps new diagnostics from breaking older "
            "readers. Every row is stamped with a wall-clock Date (ISO, seconds), the "
            "Duration_s it took to compute and the Alpha_Interval + RE it was run at, so "
            "a results file doubles as the log of how many simulations were done, when, "
            "and the total time invested.",
            "results.csv in the campaign output folder.",
            A.write_row,
            cap="aero_auto.py - write_row()"):
        e.append(it)

    e.append(P("3.3  Native JavaFoil graph extraction engine", "h2"))
    for it in feature(
            "JAVA-GRAPHS", "export_javafoil_graphs()",
            "Engineers requested authentic, native JavaFoil graph captures (drag polars, "
            "lift/moment curves, surface velocity & Cp distributions, boundary layer friction "
            "and thickness) rather than solely custom code-generated polars.",
            "Executes a dedicated ECMAScript (Nashorn) runner inside JavaFoil invoking internal "
            "Card methods (Polar.SaveImage, Velocity.Analyze & Velocity.SaveImage, "
            "BoundaryLayer.Analyze & BoundaryLayer.SaveImage). Headless BMP exports crash AWT peers, "
            "so vector PDF is exported directly and converted to crisp 150 DPI PNGs via convert_pdf_to_png.",
            "headless generation of all 6 native JavaFoil plots into <results-dir>/graphs/.",
            A.export_javafoil_graphs,
            cap="aero_auto.py - export_javafoil_graphs()"):
        e.append(it)
    for it in feature(
            "PDF-RASTER", "convert_pdf_to_png()",
            "JavaFoil's headless Nashorn engine outputs vector PDF streams which must be "
            "rasterized cleanly into PNGs for embedded GUI previews and report HTML/PDF integration.",
            "Invokes pdftoppm (-png -r 150) with sub-second latency, falling back to Ghostscript "
            "if pdftoppm is unavailable; safely cleans up intermediate PDF vector files.",
            "converting headless JavaFoil PDF card exports into PNG images.",
            A.convert_pdf_to_png,
            cap="aero_auto.py - convert_pdf_to_png()"):
        e.append(it)


def ch_targets(e):
    e.append(P("4  aero_targets.py - the target report", "h1"))
    e.append(P("Design goals are set as (CL*A target, CD*A roof). The guide-targets tool "
               "compares every valid row and prints the deviation against the ±0.4 "
               "tolerance band.", "body"))
    for it in feature(
            "TARGETS", "evaluate()",
            "After a campaign the team needs to know which stacks hit the design point, "
            "not just which is fastest.",
            "Computes CL*A and CD*A with the role span and the row chord, then scores the "
            "deviation from the target and flags how much drag budget remains.",
            "targets_report.csv plus the ranked console list.",
            T.evaluate,
            cap="aero_targets.py - evaluate()"):
        e.append(it)
    for it in feature(
            "REPORT", "sorted_report()",
            "The report must be stable and direction-consistent (closer to CL*A first, "
            "lower CD*A when equal).",
            "Sorts on |deviation| then CD*A ascending, keeping the leader compact.",
            "the ordered table exported next to the results file.",
            T.sorted_report,
            cap="aero_targets.py - sorted_report()"):
        e.append(it)


def ch_flowfield(e):
    e.append(P("5  flowfield.py - the schematic potential-flow model", "h1"))
    e.append(P("The field model is deliberately not a force solver. It produces a believable "
               "velocity map whose circulation comes from the config's own polar Cl, so the "
               "picture always agrees with the numbers.", "body"))
    e.append(Preformatted(
        "Q(z)  =  sum over source panels            (geometry blocking, block = 0.18 per panel)\n"
        "      +  sink at each 1/4-chord point      (cancels the element's net source flux)\n"
        "      +  point vortex at each 1/4 chord    Gamma_e = -Cl_e * U * c_e / 2\n"
        "      +  ground image terms                mirror at y = 0;\n"
        "                                            sources/sinks keep sign, vortices flip sign\n"
        "\n"
        "softening: 1/(z-zk)  ->  conj(z-zk) / (|z-zk|^2 + rc^2)      rc = 1e-2\n"
        "field interior: points inside any element outline are NaN (meshed away)", S["code"]))
    e.append(Spacer(1, 4))
    for it in feature(
            "PANELS", "build_panels / _orient_out",
            "Continuous source sheets are cheaper and smoother than many point sources, and "
            "the orientation drives the outward-normal sign convention.",
            "Each outline is oriented counter-clockwise, then subdivided into short "
            "panels (max spacing 0.008 chords) whose strengths are scaled by the panel "
            "length * block factor.",
            "the blocking term that stops the freestream from leaking through the wings.",
            FF.build_panels,
            cap="flowfield.py - build_panels()"):
        e.append(it)
    for it in feature(
            "KERNELS", "_soft / _vel_source / _vel_sink_pt / _vel_vortex_pt",
            "Raw point potentials blow up to |V| ~ 30x freestream at the singular cores; "
            "the softening radius caps them so the colour map stays readable.",
            "Each kernel is the standard complex-potential velocity folded through the "
            "softening cap; the vortex sign matches the Cl convention verified in section 2.1.",
            "the three building blocks of the field.",
            FF._soft,
            cap="flowfield.py - _soft()"):
        e.append(it)
    for it in feature(
            "CIRCULATION", "element_circulation / element_quarter",
            "The vortices must encode the polar's lift at the alpha the user asked for.",
            "Gamma_e = -Cl_e * U * c_e / 2; Cl_e is split across the stack's elements; "
            "each vortex sits at its element's quarter chord.",
            "makes the image agree with the p o l a r at every plotted run.",
            FF.element_circulation,
            cap="flowfield.py - element_circulation()"):
        e.append(it)
    for it in feature(
            "FIELD", "compute_field() - chunked, vectorised",
            "A 300x300 four-element ground field must render in ~20-30 s, not minutes.",
            "Source-panel velocities are summed over panel batches (chunk = 4096) against "
            "the full grid of points; the interior-mask is decided by "
            "_points_in_poly_many over all elements; ground images are folded in at the "
            "sensor level.",
            "every field_&lt;Run&gt;.png and the render_field CLI.",
            FF.compute_field,
            cap="flowfield.py - compute_field()"):
        e.append(it)
    for it in feature(
            "TRACES", "streamlines",
            "Streamlines make separation and the ground jet readable in one glance.",
            "Uni-directional tracing from a list of seeds, integrated in normalised data "
            "coordinates and stopped at NaN or near-zero speed.",
            "the white trace overlay on the field images.",
            FF.streamlines,
            cap="flowfield.py - streamlines()"):
        e.append(it)

    e.append(P("5.1  Validation invariants", "h2"))
    e.append(P("The model was checked against physical invariants during development. "
               "Numbers are from the 240x240 self-test field.", "body"))
    rows = [
        [P("<b>Check</b>", "cellb"), P("<b>Result</b>", "cellb")],
        [P("ground impermeability, max |v|/U", "cell"),
         P("< 0.15, confined to a narrow near-wall strip (wall artifacts)", "cell")],
        [P("far-field freestream, corners", "cell"),
         P("within ±10% of U", "cell")],
        [P("minimum speed (stagnation-like)", "cell"),
         P("~ 0.01 at the leading-edge cores", "cell")],
        [P("max speed", "cell"),
         P("~14-15, localised at softened singular cores (clipped at display)", "cell")],
        [P("interior masking", "cell"),
         P("NaN inside element polygons, meshed out of the colour map", "cell")],
    ]
    e.append(theme.dark_table(rows, [95 * mm, 95 * mm]))


def ch_report(e):
    e.append(P("6  aero_report.py - reporting pipeline", "h1"))
    e.append(P("The report layer turns any results CSV into a folder of ranked tables, an "
               "Excel workbook, a legend, and graphs - without requiring a re-campaign.", "body"))
    for it in feature(
            "LOAD", "load() + quality_rank()",
            "Reports must survive messy historical CSVs and sort on the same criteria the "
            "campaign used.",
            "Filters Tier<=3/Valid/dropNa, keeps only the requested airfoils, then sorts on "
            "Score, Max_LD, Downforce_N desc and Drag_N asc (only for columns that exist) "
            "and stamps a Rank.",
            "the ranked view used everywhere downstream.",
            R.quality_rank,
            cap="aero_report.py - quality_rank()"):
        e.append(it)
    for it in feature(
            "SELECT", "select_top()",
            "A naive top-N would be wall-to-wall four-element stacks; the report should show "
            "the best of every family.",
            "Round-robins across the distinct Elements counts, then ranks each bucket with "
            "quality_rank.",
            "Best/configs.csv.",
            R.select_top,
            cap="aero_report.py - select_top()"):
        e.append(it)
    for it in feature(
            "REPAIR", "ensure_mm_columns / ensure_force_columns",
            "Older result files (2025-era root, ground-effect files) lack millimetre "
            "geometry or forces.",
            "Rebuilds the mm columns from build_outlines * chord, and the force columns "
            "from q = 0.5 rho v^2 with the role span; only for missing columns so fresh "
            "files are untouched.",
            "full reports from any historical results file.",
            R.ensure_mm_columns,
            cap="aero_report.py - ensure_mm_columns()"):
        e.append(it)
    for it in feature(
            "NAMES", "rename_columns() - duplicate-safe human names",
            "Both Stack_Length_pct and Stack_Length_mm read as \"Stack length\"; found as "
            "duplicate headers in generated CSVs.",
            "Renames via the LEGEND table and, when a human title repeats, appends the unit "
            "in parentheses (Stack length vs Stack length (mm)).",
            "clean, self-explanatory results_human.csv headers.",
            R.rename_columns,
            cap="aero_report.py - rename_columns()"):
        e.append(it)
    for it in feature(
            "LEGEND", "write_legend() / write_xlsx()",
            "Every column must be explainable to someone who did not write the code; the "
            "workbook has to open in Excel/LibreOffice without pandas-specific types.",
            "write_legend dumps the column/unit/description table and now intentionally "
            "includes Status and Rank; write_xlsx emits Top configs, All rows (chunked to "
            "500 per block) and Legend sheets.",
            "columns_legend.csv and Best/overview.xlsx.",
            R.write_legend,
            cap="aero_report.py - write_legend()"):
        e.append(it)
    for it in feature(
            "GRAPHS", "plot_polar / plot_geometry / plot_field",
            "Engineers want the three views together: the numbers, the placement, and the "
            "flow shape.",
            "plot_polar fits a quadratic through Cl at -2/0/+2 deg and marks Cl_peak and "
            "stall; plot_geometry draws the stack in millimetres with gap/overlap and the "
            "ground line; plot_field reuses flowfield for the velocity map with masked "
            "wings, clipped speed and streamlines.",
            "graphs/polar_&lt;Run&gt;.png, geometry_&lt;Run&gt;.png, field_&lt;Run&gt;.png.",
            R.plot_polar,
            cap="aero_report.py - plot_polar()"):
        e.append(it)
    for it in feature(
            "RESIM", "resim_polar_curve()",
            "Campaign polars use a coarse alpha step; the top few configs deserve a smooth, "
            "denser curve for the report.",
            "Writes a fresh wing/JFS pair for the chosen config, runs Polar.Analyze over a "
            "finer sweep (default 4..26 step 2), parses and returns the denser frame, and "
            "cleans up its temp files. Uses the absolute jar path (the bare basename only "
            "worked inside campaign worker dirs).",
            "the --resim report flag.",
            R.resim_polar_curve,
            cap="aero_report.py - resim_polar_curve()"):
        e.append(it)
    for it in feature(
            "NATIVE-GRAPHS", "plot_javafoil_graphs()",
            "Report consumers need native JavaFoil plots alongside custom matplotlib graphs "
            "for complete aerodynamic verification and multi-element Cp/boundary layer analysis.",
            "Calls aero_auto.export_javafoil_graphs for each reported configuration row, extracting "
            "polar Cl-Cd, Cl-alpha, Cm-alpha, surface velocity/Cp distributions across all flap elements, "
            "skin friction Cf, and displacement/momentum thickness delta into the graphs/ directory.",
            "generating all 6 native JavaFoil plots during report creation.",
            R.plot_javafoil_graphs,
            cap="aero_report.py - plot_javafoil_graphs()"):
        e.append(it)


def ch_ui(e):
    e.append(P("7  aero_ui.py - the threaded GUI", "h1"))
    e.append(P("Five tabs wrap the engine: Configure, Airfoils, Campaigns, Results and "
               "Graphs. Every long-lived operation runs in a daemon thread; nothing "
               "touches Tk except the main loop.", "body"))
    for it in feature(
            "APP", "App.__init__ - queue-based thread bridge",
            "See 2.4: Tk cannot be driven off the main thread without corruption/crashes.",
            "A queue.Queue plus a 50 ms main-loop drain (see 8.3) moves all widget updates "
            "to the Tk thread; the icon is resolved from the bundle (sys._MEIPASS) or the "
            "'assets' folder next to the code.",
            "all worker->UI traffic in the app.",
            UI.App.__init__,
            cap="aero_ui.py - App.__init__()"):
        e.append(it)
    for it in feature(
            "ICON", "_bundle_root / _load_icon",
            "The same source must work from the working tree, the installed ~/Applications "
            "copy, and the frozen PyInstaller exe.",
            "Chooses sys._MEIPASS when frozen, otherwise the module directory; tries "
            "icon.ico, then icon.png, then the original logo, and finally an AERO_ICON env "
            "override - silently skipping whatever is absent.",
            "window icon on every platform and build mode.",
            UI.App._load_icon,
            cap="aero_ui.py - App._load_icon()"):
        e.append(it)
    for it in feature(
            "CHECK", "on_check() / on_simulate()",
            "Instant geometry feedback and one-click real simulation are the two entry "
            "points everyone uses; both must be non-blocking.",
            "on_check routes through geometry_ok + geometry_columns and redraws the "
            "embedded matplotlib preview; on_simulate reads all inputs on the main thread, "
            "then runs run_one in a worker and posts the result through the queue.",
            "the Configure tab buttons.",
            UI.App.on_simulate,
            cap="aero_ui.py - App.on_simulate()"):
        e.append(it)
    for it in feature(
            "CAMPAIGN", "on_campaign()",
            "A campaign must stream progress into the window instead of locking it.",
            "stdout is redirected into a StringIO on the worker thread, flushed in chunks "
            "to the queue, then drained to the Campaigns log; the campaign writes the same "
            "results.csv the CLI does.",
            "the Campaigns tab Start button.",
            UI.App.on_campaign,
            cap="aero_ui.py - App.on_campaign()"):
        e.append(it)
    for it in feature(
            "REPORT/VIEW", "on_report / on_targets",
            "The user should not leave the GUI to read the numbers they just generated.",
            "Both launch the corresponding headless tool as a subprocess-style call inside "
            "a worker thread with stdout redirected into the queue; on_report points at "
            "aero_report.main.",
            "the Report and Show-targets buttons.",
            UI.App.on_report,
            cap="aero_ui.py - App.on_report()"):
        e.append(it)
    for it in feature(
            "STORE", "install_airfoil / list_store",
            "Users asked to manage profiles inside the app without hunting .dat files on "
            "disk.",
            "The GUI imports a .dat into APP_DATA_DIR/airfoils under a type-in name "
            "(sanitised with a regex), reloads the combos, and can list/remove store "
            "entries; the store folder auto-created on first use.",
            "the Airfoils tab and every airfoil combo in the app.",
            A.install_airfoil,
            cap="aero_auto.py - install_airfoil()"):
        e.append(it)
    for it in feature(
            "GRAPHS", "on_gen_graphs / refresh_graph_files",
            "All generated data - custom polars, geometry, velocity fields, and native JavaFoil plots - "
            "should be reachable from one tab.",
            "on_gen_graphs renders custom polar/geometry/field PNGs and extracts all 6 native JavaFoil "
            "plots (polar Cl-Cd, Cl-alpha, Cm-alpha, surface velocity/Cp, skin friction, and boundary layer delta) "
            "for the selected results row, handing the path to refresh_graph_files to display thumbnails inline.",
            "the Graphs tab; the Results tab's 'Graphs for selected run' button.",
            UI.App.on_gen_graphs,
            cap="aero_ui.py - App.on_gen_graphs()"):
        e.append(it)
    for it in feature(
            "EXTRACT-JAVA-GRAPHS", "on_extract_configured_graphs()",
            "Allow users to instantly generate native JavaFoil graphs directly from the Configure tab "
            "without needing to execute a full campaign or navigate through the Results tab first.",
            "Reads current main and flap configurations, spins up a worker thread running "
            "aero_auto.export_javafoil_graphs, generates all 6 native plots, and automatically "
            "switches to the Graphs tab with the newly generated images selected.",
            "the Configure tab 'Extract JavaFoil Graphs (Native)' button.",
            UI.App.on_extract_configured_graphs,
            cap="aero_ui.py - App.on_extract_configured_graphs()"):
        e.append(it)
    for it in feature(
            "DRAIN", "_drain_ui",
            "Decouples widget mutation from the worker threads completely.",
            "A 50 ms after() loop pops the queue and applies 'log', 'camp', 'load', "
            "'aflog' and 'refreshgr' messages to the right widgets on the Tk thread; "
            "re-arms itself each pass. 'refreshgr' can carry a results-file path so the "
            "Graphs tab switches to the file that was just written.",
            "thread-safety of the entire UI.",
            UI.App._drain_ui,
            cap="aero_ui.py - App._drain_ui()"):
        e.append(it)
    for it in feature(
            "NAVIGATOR", "discover_all_csvs / _render_csv_file_tree",
            "Engineers need to browse between arbitrary simulation outputs, ground effect sweeps, "
            "iteration sheets, and custom runs without manually typing paths.",
            "Recursively scans campaign roots, ground folders, the user home directory, and custom "
            "folders; categorizes files (Campaign Root, Ground Sweep, Workspace, Custom) and computes "
            "row counts and file sizes; renders into a searchable tree with 1-click quick-switch combo.",
            "the Results tab left sidebar dataset navigator.",
            UI.App.discover_all_csvs,
            cap="aero_ui.py - App.discover_all_csvs()"):
        e.append(it)
    for it in feature(
            "UNIVERSAL-LOAD", "load_results_cache",
            "Results files have diverse column structures (results.csv vs iteration_sheet.csv vs "
            "optimizer logs); a fixed 12-column schema breaks on new or legacy files.",
            "Dynamically reads any CSV header with pandas, places primary aerodynamic metrics first "
            "(Run_ID, Downforce, Drag, Max_LD, Cl_a0, Cd_a0), binds interactive click-to-sort headings, "
            "populates Status/Tier filter combos, and initializes table state.",
            "loading any CSV file in the Results tab.",
            UI.App.load_results_cache,
            cap="aero_ui.py - App.load_results_cache()"):
        e.append(it)
    for it in feature(
            "TABLE-SORT", "sort_by_column",
            "Lexicographical sorting fails on floating-point numbers (e.g. 10.5 sorts before 2.1).",
            "Tests if column values can be parsed as numbers (>40% numeric); sorts numerically using "
            "pd.to_numeric if so, else lexicographically. Toggles ascending/descending order and updates "
            "table header indicator glyphs (▲ / ▼).",
            "interactive column sorting on every table header.",
            UI.App.sort_by_column,
            cap="aero_ui.py - App.sort_by_column()"):
        e.append(it)
    for it in feature(
            "FILTER-KPI", "_filter_and_render_table",
            "Engineers need to filter thousands of runs in real time by keyword, legality, or tier, "
            "while viewing instant aerodynamic totals.",
            "Applies substring search across all columns, filters by Status ('Valid'/'Failed'/custom) and "
            "Tier, virtualizes the top 1,000 matches into the Treeview with alternating row striping and "
            "colored badges, and calculates real-time summary KPIs (Rows, Max Downforce, Max L/D, Best Score, "
            "Valid % percentage).",
            "table filtering and the KPI summary banner in the Results tab.",
            UI.App._filter_and_render_table,
            cap="aero_ui.py - App._filter_and_render_table()"):
        e.append(it)
    for it in feature(
            "INSPECTOR-WORKFLOW", "row_detail / on_apply_to_config",
            "Inspecting a run must show every aerodynamic metric and enable seamless workflow "
            "handoff into Configure or the Optimizer without manual re-entry.",
            "row_detail builds a formatted aerodynamic telemetry card (polar, force model, geometry); "
            "the Property Grid displays every raw key-value attribute; on_apply_to_config parses profile "
            "names and flap coordinates (scale, angle, X, Y), switches to the Configure tab, applies the "
            "stack, and triggers a sanity check & preview redraw.",
            "the Results tab inspection pane and 'Load to Configure' / 'Send to Optimizer' buttons.",
            UI.App.on_apply_to_config,
            cap="aero_ui.py - App.on_apply_to_config()"):
        e.append(it)


def ch_entrypoints(e):
    e.append(P("8  render_field.py + launcher.py - CLI and packaging entry points", "h1"))
    for it in feature(
            "FIELD-CLI", "render_field.main()",
            "The field images needed a non-GUI path for scripting and CI.",
            "Reads --main/--flap/--alpha/--ground-height, grabs the best Cl_a0 it can find "
            "in existing results (fallback -2.0), runs compute_field and writes a dark-free "
            "viridis contour PNG with dimensionless axes.",
            "headless field renders from any configuration.",
            RF.main,
            cap="render_field.py - main()"):
        e.append(it)
    for it in feature(
            "LAUNCHER", "launcher.launcher()",
            "One executable name across tools and platforms (ui/campaign/report/targets/"
            "field).",
            "Argparse sub-tool selection with parse_known_args forwarding, plus environment "
            "overrides AERO_JAVA_DIR / AERO_AIRFOILS / AERO_OUT before dispatch; 'aero-ui' "
            "and 'aero' console scripts from pyproject.toml call it.",
            "run_ui.sh / run_ui.bat / desktop entry and the installed CLI.",
            L.launcher,
            cap="launcher.py - launcher()"):
        e.append(it)


def ch_validation(e):
    e.append(P("9  Validation and performance", "h1"))
    e.append(P("Reported runtime from an x86-64 laptop, Python 3.14, single-threaded:", "body"))
    rows = [
        [P("<b>Operation</b>", "cellb"), P("<b>Cost</b>", "cellb")],
        [P("single-element JavaFoil polar (25 alphas)", "cell"), P("~ 5 s", "cell")],
        [P("four-element stack polar", "cell"), P("~ 20-60 s", "cell")],
        [P("300x300 four-element ground field", "cell"), P("~ 19-33 s", "cell")],
        [P("3-config FW ground report incl. all graphs", "cell"), P("~ 71-92 s total", "cell")],
        [P("3-config report with images off", "cell"), P("~ 10 s", "cell")],
    ]
    e.append(theme.dark_table(rows, [115 * mm, 75 * mm]))
    e.append(Spacer(1, 6))
    e.append(P("Artifact read-back checks performed while building the report layer:", "body"))
    for it in ("every column in results_human.csv is explained by columns_legend.csv "
               "(Status and Rank included)",
               "no duplicate/'.1' headers after rename_columns (mm columns carry their unit)",
               "overview.xlsx opens with the expected Top configs / All rows / Legend sheets",
               "resim_polar_curve output matched the stored Cl_a0 exactly (-1.338 on s1223)"):
        e.append(P(it, "bullet"))


def ch_packaging(e):
    e.append(P("10  Packaging and build", "h1"))
    e.append(P("The same five modules ship in four forms: source kit (Linux tar.gz, Windows "
               "zip), the installed ~/Applications/aero_auto desktop app, and a standalone "
               "PyInstaller exe built under wine on this machine.", "body"))
    rows = [
        [P("<b>Artifact</b>", "cellb"), P("<b>Built by</b>", "cellb"), P("<b>Notes</b>", "cellb")],
        [P("aero_auto_linux.tar.gz", "cell"), P("build_dist.py", "cell"),
         P("./run_ui.sh; python3.9+ + deps", "cell")],
        [P("aero_auto_windows.zip", "cell"), P("build_dist.py", "cell"),
         P("run_ui.bat; needs installed Python", "cell")],
        [P("aero_auto_windows_app.zip", "cell"), P("hand-rolled zip of dist/aero_ui", "cell"),
         P("self-contained exe, no Python needed", "cell")],
        [P("desktop app", "cell"), P("~/.local/share/applications/aero_auto.desktop", "cell"),
         P("launches run_ui.sh; icon from assets", "cell")],
        [P("aero_ui.exe", "cell"), P("PyInstaller under wine (win python 3.12)", "cell"),
         P("--onedir --windowed; assets+docs bundled via --add-data", "cell")],
    ]
    e.append(theme.dark_table(rows, [62 * mm, 62 * mm, 66 * mm]))
    e.append(Spacer(1, 6))
    e.append(P("Icon pipeline (make_icon.py)", "h2"))
    e.append(P("Priorities: assets/Logoertblanc.png, then assets/source.png, then a generated "
               "placeholder. Pillow produces assets/icon.png (512) and a multi-size "
               "icon.ico for Windows; the GUI prefers the .ico and falls back to .png or "
               "AERO_ICON.", "body"))
    e.append(P("Windows note", "h2"))
    e.append(P("Faketime is unavailable on Windows; simulate() auto-detects it and runs a "
               "bare java when missing (2.5). The .exe was built with the same flag surface "
               "documented in create_standalone.bat.", "body"))


def ch_changelog(e):
    e.append(P("11  Changelog - everything added, and why", "h1"))
    rows = [
        [P("<b>Addition</b>", "cellb"), P("<b>Why / for what</b>", "cellb")],
        [P("regulatory engine (FSUK/FSG) + GUI verdict", "cell"),
         P("instant legality feedback and a cheap campaign gate before JavaFoil", "cell")],
        [P("geometry_columns, all-mm fields", "cell"),
         P("comparable audit numbers for stack/gap/clearance", "cell")],
        [P("force_columns (Downforce_N, Drag_N)", "cell"),
         P("physical downforce/drag from dimensionless polars", "cell")],
        [P("ground-effect campaigns + per-height files", "cell"),
         P("graph realism at fixed ride height", "cell")],
        [P("target report (CL*A / CD*A roofs)", "cell"),
         P("the design point, not just the fastest stack", "cell")],
        [P("calibrated flowfield model", "cell"),
         P("fast, stable images after the linear solver failed (2.1)", "cell")],
        [P("report pipeline + xlsx + legend + duplicate-safe names", "cell"),
         P("self-explanatory deliverables from any historical CSV", "cell")],
        [P("--resim denser JavaFoil polar", "cell"),
         P("smooth top-config curves; absolute jar path", "cell")],
        [P("threaded Tk GUI, queue bridge", "cell"),
         P("non-blocking UI without Tk-thread corruption", "cell")],
        [P("faketime fallback", "cell"),
         P("Windows portability of the simulation runner", "cell")],
        [P("launcher/render_field + platform launchers", "cell"),
         P("one command surface on Linux and Windows", "cell")],
        [P("packaging: desktop entry, wine exe, icon pipeline", "cell"),
         P("run it as an app, ship it as an exe", "cell")],
        [P("Results CSV Dataset Navigator", "cell"),
         P("multi-folder recursive scanner across campaign roots, ground sweeps, and workspace", "cell")],
        [P("universal dynamic table + numeric sorting", "cell"),
         P("handles arbitrary CSV schemas (iteration sheets, optimizer logs) with ▲/▼ click-to-sort", "cell")],
        [P("real-time KPI summary banner", "cell"),
         P("instant telemetry metrics (Rows, Max Downforce, Max L/D, Best Score, Valid %)", "cell")],
        [P("dual-view run inspector & 1-click workflows", "cell"),
         P("formatted aero card + property grid; 'Load to Configure' and 'Send to Optimizer'", "cell")],
        [P("raw CSV data viewer & editor", "cell"),
         P("in-app raw text inspection and modification with line/char stats", "cell")],
        [P("aeronautical dark theme & terminal launcher", "cell"),
         P("slate aesthetic, alternating row striping, status tags, and multi-terminal support", "cell")],
        [P("native JavaFoil graph extraction engine", "cell"),
         P("headless vector export & 150 DPI rasterization of Polar, Velocity/Cp, and BoundaryLayer cards", "cell")],
        [P("Configure & Results native graph integration", "cell"),
         P("1-click 'Extract JavaFoil Graphs (Native)' in Configure tab and multi-graph generation in Results tab", "cell")],
    ]
    e.append(theme.dark_table(rows, [78 * mm, 112 * mm]))


# ---------------------------------------------------------------- report
def build_report(out):
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title="aero_auto technical guide 1.0 (dark edition)",
                            author="aero_auto toolchain")
    doc.onFirstPage = theme.cover_bg
    doc.onLaterPages = theme.draw_bg
    e = []
    cover(e,
          "aero_auto 1.0\nTechnical Guide",
          "Multi-element wing design, simulation and reporting toolchain built on JavaFoil. "
          "Dark edition - code, reasons and wiring for every addition.",
          "This report documents the code as it exists today: the topology, the design "
          "decisions and their measured rationale, and - for every feature added - the exact "
          "source, why it exists, how it works and what it is for. Source snippets are "
          "extracted verbatim from the modules at build time, so the document can never "
          "drift from the code.",
          ["1  System architecture",
           "2  Design decisions and rationale",
           "3  aero_auto.py - the engine",
           "4  aero_targets.py - the target report",
           "5  flowfield.py - the schematic potential-flow model",
           "6  aero_report.py - reporting pipeline",
           "7  aero_ui.py - the threaded GUI",
           "8  render_field.py + launcher.py - entry points",
           "9  Validation and performance",
           "10 Packaging and build",
           "11 Changelog - everything added and why"])
    ch_architecture(e)
    ch_decisions(e)
    ch_engine(e)
    ch_targets(e)
    ch_flowfield(e)
    ch_report(e)
    ch_ui(e)
    ch_entrypoints(e)
    ch_validation(e)
    ch_packaging(e)
    ch_changelog(e)
    if warnings:
        e.append(P(f"Build warnings: {len(warnings)} - see console.", "small"))
    doc.build(e)


# ---------------------------------------------------------------- manual
def build_manual(out):
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title="aero_auto user manual 1.0 (dark edition)",
                            author="aero_auto toolchain")
    doc.onFirstPage = theme.cover_bg
    doc.onLaterPages = theme.draw_bg
    e = []
    cover(e,
          "aero_auto 1.0\nUser Manual",
          "Dark edition - run the GUI, schedule campaigns, read the reports.",
          "The practical guide: what you need, how to install it, how to run every tool from "
          "the GUI or the command line, and what lands in the report folder. Engineers "
          "looking for the \"why\" behind the code should open the technical guide.",
["1  Overview",
            "2  Requirements and dependencies",
            "3  Install",
            "4  Run",
            "5  The GUI, tab by tab (run_ui.sh / aero_ui.exe)",
            "6  File locations at a glance",
            "7  Environment overrides",
            "8  What a campaign writes",
            "9  The report folder",
            "10 Regulatory reference",
            "11 Packaging and platform notes",
            "12 Changelog highlights"])
    e.append(P("1  Overview", "h1"))
    rows = [
        [P("<b>Module</b>", "cellb"), P("<b>Purpose</b>", "cellb")],
        [P("aero_auto.py", "cell"), P("core engine - rules, geometry, JavaFoil, planner", "cell")],
        [P("aero_targets.py", "cell"), P("CL*A / CD*A target report", "cell")],
        [P("aero_report.py", "cell"), P("ranked tables, workbook, graphs, --resim", "cell")],
        [P("flowfield.py", "cell"), P("schematic potential-flow model for field images", "cell")],
        [P("aero_ui.py", "cell"), P("the GUI shell", "cell")],
        [P("render_field.py", "cell"), P("headless field PNG renderer", "cell")],
        [P("launcher.py", "cell"), P("one entry point for every tool", "cell")],
    ]
    e.append(theme.dark_table(rows, [52 * mm, 138 * mm]))
    e.append(Spacer(1, 6))

    e.append(P("2  Requirements and dependencies", "h1"))
    e.append(P("Python packages (requirements.txt): numpy, pandas, matplotlib, openpyxl, "
               "Pillow (icon build); pyinstaller is only needed for standalone builds.", "body"))
    rows = [
        [P("<b>System tool</b>", "cellb"), P("<b>Needed for</b>", "cellb"), P("<b>Notes</b>", "cellb")],
        [P("Python 3.9+ with Tkinter", "cell"), P("everything; the GUI uses Tk", "cell"),
         P("python.org installer bundles Tk on Windows", "cell")],
        [P("Java 8+ (java)", "cell"), P("simulation", "cell"),
         P("javafoil.jar required in JAVA_DIR", "cell")],
        [P("faketime", "cell"), P("Linux only", "cell"),
         P("skipped automatically on Windows (2.3 of the guide)", "cell")],
        [P("javafoil.jar + mhclasses.jar", "cell"), P("simulation", "cell"),
         P("~/ MH-AeroTools / JavaFoil / - verified present", "cell")],
        [P("airfoil .dat library", "cell"), P("geometry and polars", "cell"),
         P("override with AERO_AIRFOILS", "cell")],
    ]
    e.append(theme.dark_table(rows, [52 * mm, 45 * mm, 93 * mm]))
    e.append(Spacer(1, 6))

    e.append(P("3  Install", "h1"))
    e.append(Preformatted(
        "python3 -m pip install -r requirements.txt\n"
        "\n"
        "# optional standalone (no Python on the target machine):\n"
        "python3 create_standalone.sh     # linux/macos -> dist/aero_ui/\n"
        "create_standalone.bat            # windows     -> dist\\aero_ui\\aero_ui.exe",
        S["code"]))
    e.append(Spacer(1, 5))

    e.append(P("4  Run", "h1"))
    e.append(P("GUI", "h2"))
    e.append(Preformatted(
        "./run_ui.sh            # linux/macos\n"
        "run_ui.bat             # windows\n"
        "# or\n"
        "python3 launcher.py ui",
        S["code"]))
    e.append(Spacer(1, 5))
    e.append(P("Headless tools", "h2"))
    e.append(Preformatted(
        "python3 launcher.py campaign --role fw --flow ground --height 300 --hours 0.5\n"
        "python3 launcher.py report   --results ~/aero_campaign/results.csv --top 3\n"
        "python3 launcher.py report   --results .../ground/h300pct/results.csv --resim\n"
        "python3 launcher.py targets  --results ~/aero_campaign/results.csv --role fw\n"
        "python3 launcher.py field    --main s1223 --flap e423,30,-6,100,5 --out f.png\n"
        "                              --ground-height 300",
        S["code"]))
    e.append(Spacer(1, 5))

    e.append(P("5  The GUI, tab by tab (run_ui.sh / aero_ui.exe)", "h1"))
    e.append(P("Five tabs wrap the engine: Configure, Airfoils, Campaigns, Results and "
               "Graphs. Launch the GUI with <b>run_ui.sh</b> on Linux, <b>run_ui.bat</b> on "
               "Windows, or simply double-click <b>aero_ui.exe</b> in the standalone "
               "distribution (dist/aero_ui/). The same engine runs behind the window, so a "
               "config you have just sanity-checked can be simulated or campaigned without "
               "ever leaving the app. Every JavaFoil operation runs in a worker thread - "
               "the window never freezes while a polar is computed.", "body"))

    e.append(P("5.1  Configure tab", "h2"))
    rows = [
        [P("<b>Control</b>", "cellb"), P("<b>What it does</b>", "cellb")],
        [P("Main element", "cell"),
         P("the airfoil that defines the wing; the combo lists every profile found in "
           "your .dat folder", "cell")],
        [P("Role: front / rear / custom", "cell"),
         P("sets the span used by CL*A and the force model (fw 1400 / rw 950 / custom "
           "1000 mm) and the FSUK/FSG rule set that is checked", "cell")],
        [P("Main chord (mm)", "cell"),
         P("physical chord in millimetres; enables the all-mm geometry columns and the "
           "force conversion", "cell")],
        [P("Speed (m/s)", "cell"),
         P("freestream speed for q = 0.5 * rho * V^2 in the force model", "cell")],
        [P("Reynolds number", "cell"),
         P("run Reynolds number sent to JavaFoil (default 570 000)", "cell")],
        [P("Alpha start / end / step (deg)", "cell"),
         P("polar sweep angles; the default -20..+5 step 1 covers the stall search", "cell")],
        [P("Flap rows F1..F3", "cell"),
         P("per slot: airfoil combo + S% scale of main chord, A deg mount angle, X% "
           "position, Y% position; tick the checkbutton to enable the row", "cell")],
        [P("enforce FSUK/FSG size limits", "cell"),
         P("master switch for the regulatory checks (stack height/length, ground "
           "clearance)", "cell")],
        [P("Ground height (% chord)", "cell"),
         P("wing height above the ground for ground-effect runs; leave empty or \"none\" "
           "for unbounded flow", "cell")],
        [P("Sanity check geometry", "cell"),
         P("instant PASS/FAIL against the size limits - prints the exact mm value vs "
           "limit and the per-pair gap/overlap in %, then redraws the preview "
           "(green PASS / red FAIL, ground line drawn when a ground height is set)",
         "cell")],
        [P("Simulate this wing now (JavaFoil)", "cell"),
         P("runs the real JavaFoil analysis in a worker thread, appends the row to "
           "&lt;OUT_DIR&gt;/results.csv and logs Run_ID, Status, Cl@0, Cd@0, max L/D, stall "
           "angle and Downforce_N", "cell")],
        [P("Simulate in Terminal", "cell"),
         P("launches the simulation inside an external terminal (konsole, alacritty, "
           "gnome-terminal, xterm) for real-time stdout tracking", "cell")],
        [P("Batch Simulate", "cell"),
         P("sweeps multiple wing configurations or angle cases sequentially in worker threads", "cell")],
        [P("Extract JavaFoil Graphs (Native)", "cell"),
         P("runs JavaFoil headlessly and extracts all 6 native plots (drag polar, lift curve, moment curve, "
           "surface velocity/Cp distribution, skin friction, and boundary layer thickness) straight to the Graphs tab", "cell")],
        [P("status log + geometry preview", "cell"),
         P("right-hand pane: live log of every action and an embedded interactive matplotlib "
           "drawing of the element stack scaled to mm with ground line indicator", "cell")],
    ]
    e.append(theme.dark_table(rows, [58 * mm, 132 * mm]))
    e.append(Spacer(1, 5))

    e.append(P("5.2  Airfoils tab", "h2"))
    rows = [
        [P("<b>Control</b>", "cellb"), P("<b>What it does</b>", "cellb")],
        [P("store location label", "cell"),
         P("shows the internal airfoil store folder "
           "&lt;APP_DATA_DIR&gt;/airfoils (default ~/.aero_auto/airfoils), auto-created on "
           "first use", "cell")],
        [P("Import .dat...", "cell"),
         P("copies any airfoil .dat file into the internal store under the name you "
           "type; the profile is then available in every combo - you no longer have to "
           "remember which folder holds a profile", "cell")],
        [P("Remove selected", "cell"),
         P("deletes the selected stored profile from the internal store (only affects "
           "the store, never your original .dat files)", "cell")],
        [P("Open store folder", "cell"),
         P("opens the store folder in the file manager when you want to inspect or "
           "manually drop files in", "cell")],
        [P("Refresh", "cell"),
         P("re-scans the store (and AIRFOIL_DIR) in case files changed on disk", "cell")],
        [P("store list", "cell"),
         P("shows every profile currently inside the internal store with its full path; "
           "select a row to remove it", "cell")],
    ]
    e.append(theme.dark_table(rows, [58 * mm, 132 * mm]))
    e.append(Spacer(1, 5))

    e.append(P("5.3  Campaigns tab", "h2"))
    rows = [
        [P("<b>Control</b>", "cellb"), P("<b>What it does</b>", "cellb")],
        [P("Hours", "cell"), P("campaign time budget for the planner (can be small, 0.1 "
            "works)", "cell")],
        [P("Workers", "cell"), P("number of parallel JavaFoil worker directories", "cell")],
        [P("Pool", "cell"), P("comma-separated airfoil names restricting exploration to "
            "profiles you actually have .dat files for", "cell")],
        [P("Start campaign", "cell"), P("runs the 3-phase planner; progress streams into "
            "the log; rows are written to &lt;OUT_DIR&gt;/results.csv", "cell")],
        [P("live stats label", "cell"),
         P("during a campaign shows the elapsed time, how many new simulations have "
            "been finished and the current runs/second - you can see the campaign "
            "progressing without counting rows", "cell")],
        [P("Write report", "cell"), P("builds the full report folder (Best/, graphs/) for "
            "&lt;OUT_DIR&gt;/results.csv without leaving the app", "cell")],
    ]
    e.append(theme.dark_table(rows, [58 * mm, 132 * mm]))
    e.append(Spacer(1, 5))

    e.append(P("5.4  Results tab & CSV Dataset Navigator", "h2"))
    e.append(P("The Results tab is a universal dataset browser and configuration inspector that "
               "navigates across all simulation and optimization files (results.csv, iteration_sheet.csv, "
               "top_results.csv, ground-effect sweeps, and custom CSVs).", "body"))
    rows = [
        [P("<b>Component</b>", "cellb"), P("<b>Capabilities and Workflow</b>", "cellb")],
        [P("CSV Dataset Navigator", "cell"),
         P("Left sidebar recursively discovering all CSV files across ~/aero_campaign, ground/ folders, "
           "the workspace root, backups, and custom user folders. Displays classified tree with category badges, "
           "row counts and file sizes. Includes live search filter, 1-click Quick Switch combo, 'Browse Any CSV...' "
           "file picker, and 'Open Ext ↗' spreadsheet launcher.", "cell")],
        [P("Universal Dynamic Table", "cell"),
         P("Automatic schema detection for arbitrary CSVs (iteration sheets, optimization logs) without hardcoded "
           "limits. Prioritizes primary metrics (Run_ID, Downforce, Drag, Max_LD, Cl_a0, Cd_a0), features numeric-aware "
           "click-to-sort headers (▲/▼), real-time global multi-column search, Status filter (Valid/Failed/custom), "
           "Tier filter (1/2/3), alternating row striping, status color badges, and 'Export Filtered CSV...'.", "cell")],
        [P("Dynamic KPI Banner", "cell"),
         P("Real-time summary strip calculating active/filtered statistics: Rows count (e.g. 1,420 / 23,272), "
           "Max Downforce (supporting both N and CL units), Max L/D efficiency ratio, Best Score, and Valid % legality compliance.", "cell")],
        [P("Run Inspector", "cell"),
         P("Dual-view inspection: formatted Aerodynamic Telemetry Card (Run ID, Status, Elements, Polars, Forces, "
           "and mm geometry) plus a comprehensive Property Grid listing every key-value attribute of the selected run.", "cell")],
        [P("Action Workflows", "cell"),
         P("'Load to Configure': pushes selected profile and flap coordinates (scale, angle, X, Y) to Configure tab and "
           "triggers instant sanity check and preview redraw.<br/>"
           "'Send to Optimizer': passes selected configuration as baseline for automated sweeps.<br/>"
           "'Graphs for selected run': renders custom polar, geometry, and flowfield PNGs, plus headlessly "
           "extracts all 6 authentic JavaFoil native graphs, and opens Graphs tab.", "cell")],
        [P("Raw CSV Data Editor", "cell"),
         P("Dedicated sub-tab displaying the raw text representation of the active CSV file, with line and character "
           "counters and in-place 'Save CSV Changes' with automatic cache reloading.", "cell")],
    ]
    e.append(theme.dark_table(rows, [58 * mm, 132 * mm]))
    e.append(Spacer(1, 5))

    e.append(P("5.5  Graphs tab", "h2"))
    e.append(P("The Graphs tab is the image side of the app. It discovers every results "
               "file on disk - the main one plus each ground-effect folder - and any "
               "generated graph images, previewing them right inside the window.", "body"))
    rows = [
        [P("<b>Control</b>", "cellb"), P("<b>What it does</b>", "cellb")],
        [P("results file combo", "cell"),
         P("lists &lt;OUT_DIR&gt;/results.csv, each ground folder's results.csv and the file "
            "you last loaded; pick one to inspect that campaign's data", "cell")],
        [P("Write report", "cell"),
         P("builds the full report folder for the selected results file (also used to "
            "update the images after a new campaign)", "cell")],
        [P("Refresh", "cell"),
         P("re-scans the selected results folder for polar, geometry, field, and native javafoil_* PNGs", "cell")],
        [P("Open in viewer", "cell"),
         P("opens the current image in your system image viewer", "cell")],
        [P("image list", "cell"),
         P("every &lt;results-dir&gt;/graphs/*.png found for the chosen results file (including custom and native JavaFoil plots)", "cell")],
        [P("preview", "cell"),
         P("click an image name to see it scaled inside the app (needs Pillow; without "
            "it the list still works, just no inline preview)", "cell")],
    ]
    e.append(theme.dark_table(rows, [58 * mm, 132 * mm]))
    e.append(Spacer(1, 5))

    e.append(P("6  File locations at a glance", "h1"))
    e.append(P("Where airfoils are read from and every kind of output lands. All paths "
               "can be moved with the environment overrides in chapter 7.", "body"))
    rows = [
        [P("<b>Artifact</b>", "cellb"), P("<b>Location</b>", "cellb")],
        [P("airfoil .dat files", "cell"),
         P("default AIRFOIL_DIR "
           "\"/mnt/data/FSEA/AIRFOILS JAVAFOIL/AIRFOILS\" - put one .dat per profile in "
           "this folder (top-level files only, no sub-folders). The GUI combos are built "
           "from these filenames. Set AERO_AIRFOILS to point elsewhere", "cell")],
        [P("single simulations / GUI + CLI campaigns", "cell"),
         P("&lt;OUT_DIR&gt;/results.csv (default ~/aero_campaign/results.csv), appended after "
           "every run", "cell")],
        [P("ground-effect campaigns (CLI)", "cell"),
         P("&lt;OUT_DIR&gt;/ground/&lt;height&gt;pct/results.csv - one file per ride height", "cell")],
        [P("ranked tables", "cell"),
         P("&lt;results-dir&gt;/Best/configs.csv, Best/overview.txt, Best/overview.xlsx (next to "
           "whichever results.csv you reported)", "cell")],
        [P("readable CSV + legend", "cell"),
         P("&lt;results-dir&gt;/results_human.csv and &lt;results-dir&gt;/columns_legend.csv", "cell")],
        [P("polar and geometry graphs", "cell"),
         P("&lt;results-dir&gt;/graphs/polar_&lt;Run&gt;.png and geometry_&lt;Run&gt;.png", "cell")],
        [P("native JavaFoil graphs", "cell"),
         P("&lt;results-dir&gt;/graphs/javafoil_polar_cl_cd_&lt;Run&gt;.png, "
           "javafoil_polar_cl_alfa_&lt;Run&gt;.png, javafoil_polar_cm_alfa_&lt;Run&gt;.png, "
           "javafoil_velocity_cp_&lt;Run&gt;.png, javafoil_bl_cf_&lt;Run&gt;.png, "
           "javafoil_bl_delta_&lt;Run&gt;.png - native headless captures from JavaFoil's internal cards", "cell")],
        [P("velocity maps (field sims)", "cell"),
         P("&lt;results-dir&gt;/graphs/field_&lt;Run&gt;.png - schematic potential-flow velocity "
           "field for that config; the render_field.py CLI produces a single picture from "
           "any configuration", "cell")],
        [P("target report", "cell"),
         P("targets_report.csv next to the results file you pointed the tool at", "cell")],
    ]
    e.append(theme.dark_table(rows, [62 * mm, 128 * mm]))
    e.append(Spacer(1, 5))
    e.append(note("The polar graphs are the authoritative data. field_*.png images are a "
                  "schematic potential-flow visualisation whose circulation comes from "
                  "each config's own JavaFoil Cl - not a second force solver."))

    e.append(P("7  Environment overrides", "h1"))
    rows = [
        [P("<b>Variable</b>", "cellb"), P("<b>Effect</b>", "cellb")],
        [P("AERO_JAVA_DIR", "cell"), P("folder that contains javafoil.jar", "cell")],
        [P("AERO_AIRFOILS", "cell"), P("folder with the .dat profiles", "cell")],
        [P("AERO_OUT", "cell"), P("campaign output folder (default ~/aero_campaign)", "cell")],
        [P("AERO_ICON", "cell"), P("explicit GUI icon path", "cell")],
    ]
    e.append(theme.dark_table(rows, [55 * mm, 135 * mm]))
    e.append(Spacer(1, 6))

    e.append(P("8  What a campaign writes", "h1"))
    e.append(P("~/aero_campaign/results.csv holds unbounded runs; ground-effect runs land in "
               "~/aero_campaign/ground/<height>/results.csv. Rows carry the configuration, "
               "the polar metrics, per-pair geometry, forces and quality:", "body"))
    e.append(Preformatted(
        "Run_ID Phase Main F1_Airfoil F1_Scale F1_Angle F1_X F1_Y F2_* F3_* \\\n"
        "Cl_peak Cd_peak Stall_Angle Max_LD Cl_a0 Cd_a0 Cm_a0 Cl_am2 Cl_ap2 \\\n"
        "Downforce_N Drag_N Tier Score Status  + per-pair gap/overlap/step + mm geometry",
        S["code"]))
    e.append(Spacer(1, 5))

    e.append(P("9  The report folder", "h1"))
    rows = [
        [P("<b>File</b>", "cellb"), P("<b>Content</b>", "cellb")],
        [P("Best/configs.csv", "cell"), P("the top-N, round-robin across stack sizes", "cell")],
        [P("Best/overview.txt", "cell"), P("human summary incl. spans, q and force model", "cell")],
        [P("Best/overview.xlsx", "cell"), P("Top configs / All rows / Legend sheets", "cell")],
        [P("results_human.csv", "cell"), P("every valid row, readable column names", "cell")],
        [P("columns_legend.csv", "cell"), P("column - unit - description for everything", "cell")],
        [P("graphs/*.png", "cell"), P("polar, geometry, field, and native JavaFoil engine graphs (polars, Cp, BL) per config", "cell")],
    ]
    e.append(theme.dark_table(rows, [62 * mm, 128 * mm]))
    e.append(Spacer(1, 5))
    e.append(note("Polar graphs are the authoritative data. field_*.png images are a "
                  "schematic potential-flow visualisation, not a second force solver."))

    e.append(P("10  Regulatory reference (FSUK 2026 / FSG v1.1)", "h1"))
    rows = [
        [P("<b>Rule</b>", "cellb"), P("<b>Limit</b>", "cellb")],
        [P("Min ground clearance", "cell"), P("35 mm", "cell")],
        [P("Front wing max stack height", "cell"), P("250 mm", "cell")],
        [P("Front wing max stack length", "cell"), P("600 mm", "cell")],
        [P("Rear wing max total height", "cell"), P("1100 mm", "cell")],
        [P("Rear wing max stack length", "cell"), P("250 mm", "cell")],
        [P("Front wing span", "cell"), P("1400 mm", "cell")],
        [P("Rear wing span", "cell"), P("950 mm", "cell")],
        [P("Targets CL*A / CD*A roof", "cell"),
         P("fw 1.75 / 0.45 - rw/beam 1.85 / 0.95 (tol ±0.4)", "cell")],
    ]
    e.append(theme.dark_table(rows, [120 * mm, 70 * mm]))
    e.append(Spacer(1, 6))

    e.append(P("11  Packaging and platform notes", "h1"))
    e.append(P("Four distributions come from the same modules: the Linux tar.gz, the Windows "
               "zip, the installed desktop app (~/Applications/aero_auto, registered via the "
               ".desktop entry), and the standalone aero_ui.exe built with PyInstaller under "
               "wine. The exe bundles assets and docs with --add-data. Rebuild with "
               "create_standalone.bat on Windows or the wine command in the technical "
               "guide's packaging chapter.", "body"))

    e.append(P("12  Changelog highlights", "h1"))
    for it in ("regulatory engine + GUI verdict, geometry_ok gate before JavaFoil",
               "ground-effect campaigns and per-height result files",
               "force model (Downforce_N / Drag_N) and all-mm geometry columns",
               "target report against CL*A / CD*A roofs",
               "calibrated potential-flow model (replaces the abandoned linear solver)",
               "full report pipeline: workbook, legend, duplicate-safe headers, --resim",
               "threaded Tk GUI with a queue-based thread bridge and icon support",
               "cross-platform packaging: launcher, field CLI, desktop app, wine-built exe",
               "Results tab CSV Dataset Navigator with recursive multi-folder discovery and live filter",
               "universal dynamic table supporting arbitrary CSV schemas with numeric sorting (▲/▼)",
               "real-time aerodynamic KPI banner (Rows, Max Downforce, Max L/D, Best Score, Valid %)",
               "dual-view run inspector (aero telemetry card + property grid)",
               "1-click engineering handoff: 'Load to Configure' and 'Send to Optimizer'",
               "raw CSV data viewer and editor with live line/char stats and in-place save",
               "aeronautical dark UI theme polish and multi-terminal simulation launcher",
               "native JavaFoil graph extraction engine: headless vector capture of Polar, Velocity/Cp, and Boundary Layer cards",
               "'Extract JavaFoil Graphs (Native)' instant button in Configure tab and automated multi-artifact generation in Results tab"):
        e.append(P(it, "bullet"))
    doc.build(e)


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="build dark aero_auto PDFs")
    ap.add_argument("--only", choices=("report", "manual"), default=None)
    args = ap.parse_args(argv)

    report_out = os.path.join(HERE, "TECHNICAL_GUIDE.pdf")
    manual_out = os.path.join(HERE, "USER_MANUAL.pdf")
    if args.only in (None, "report"):
        build_report(report_out)
        print("wrote", report_out, f"({os.path.getsize(report_out)/1024:.0f} KB)")
    if args.only in (None, "manual"):
        build_manual(manual_out)
        print("wrote", manual_out, f"({os.path.getsize(manual_out)/1024:.0f} KB)")
    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(" -", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())