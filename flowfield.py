#!/usr/bin/env python3
"""
flowfield.py - simple 2D potential-flow model for the aero_report flow-field images.

NOT a force solver. The polars in aero_report always come from JavaFoil. This module only
produces an illustrative velocity field around a given multi-element geometry, calibrated so
that each element carries the circulation its JavaFoil polar actually predicts:

    Gamma_e = -Cl_e * U * c_e / 2     (plus ground image: mirrored vortices of opposite sign)

The geometry's blocking is represented by a source distribution over the element outlines
(source per unit length = U, sink of equal net strength placed at the quarter chord inside
the wing), so the far field stays source-free and the flow visibly deflects around the
airfoils. All singular cores sit inside the wing outline and are hidden by the interior mask.
"""
import numpy as np

UINF = 1.0


# ----------------------------------------------------------------------
# geometry helpers
# ----------------------------------------------------------------------
def _orient_out(pts):
    """Clockwise traversal (interior on the right). Consecutive duplicate vertices dropped."""
    keep = np.ones(len(pts), dtype=bool)
    if len(pts) > 1:
        d = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        keep[1:] = d > 1e-9
    pts = pts[keep]
    if len(pts) < 3:
        return pts
    xs = pts[:, 0]
    ys = pts[:, 1]
    area = 0.5 * np.sum(xs[:-1] * ys[1:] - xs[1:] * ys[:-1] + xs[-1] * ys[0] - xs[0] * ys[-1])
    return pts[::-1].copy() if area > 0 else pts


def build_panels(outs, max_spacing=0.008):
    """Panel list {p1, p2, m, s, t, n, el} for each element outline, cw, outward normals."""
    panels = []
    starts = []
    decs = []
    centroid = np.zeros(2)
    total = sum(len(o) for o in outs)
    for o in outs:
        centroid += o.sum(axis=0)
    centroid /= max(total, 1)
    for ei, o0 in enumerate(outs):
        o = _orient_out(o0)
        if max_spacing > 0:
            cum = np.concatenate([[0], np.cumsum(np.hypot(np.diff(o[:, 0]), np.diff(o[:, 1])))])
            want = max(8, int(cum[-1] / max_spacing))
            if want < len(o):
                idx = np.unique(np.linspace(0, len(o) - 1, want).astype(int))
                o = o[idx]
        starts.append(len(panels))
        decs.append(o)
        n = len(o)
        for i in range(n):
            p1 = o[i]
            p2 = o[(i + 1) % n]
            m = (p1 + p2) / 2.0
            d = p2 - p1
            s = np.hypot(d[0], d[1])
            if s < 1e-12:
                continue
            t = d / s
            nvec = np.array([t[1], -t[0]])
            if np.dot(nvec, m - centroid) < 0:
                nvec = -nvec
            panels.append(dict(p1=p1, p2=p2, m=m, s=s, t=t, n=nvec, el=ei))
    return panels, np.array(starts), decs


# ----------------------------------------------------------------------
# elementary potentials (complex plane, Q = u - i*v)
# ----------------------------------------------------------------------
def _soft(z, rc):
    """Return z with any values inside the core radius rc pushed to its boundary."""
    m = np.abs(z)
    small = m < rc
    if np.any(small):
        z = np.where(small, rc * z / np.where(m == 0, 1.0, m), z)
    return z


def _vel_source(z, z1, z2):
    """Velocity at complex root set z from a constant source sheet of unit strength/len."""
    out = np.zeros_like(z, dtype=complex)
    dz1 = _soft(z - z1, 1e-2)
    dz2 = _soft(z - z2, 1e-2)
    ok = (np.abs(dz1) > 1e-9) & (np.abs(dz2) > 1e-9)
    out[ok] = np.log(dz1[ok] / dz2[ok]) / (2 * np.pi)
    return out


def _vel_sink_pt(z, zk, m):
    """Velocity at z from a point sink of strength m (>0 inflow) located at zk."""
    dz = _soft(z - zk, 1e-2)
    out = np.zeros_like(z, dtype=complex)
    ok = np.abs(dz) > 1e-9
    out[ok] = -m / (2 * np.pi * dz[ok])
    return out


def _vel_vortex_pt(z, zk, gam):
    """Velocity at z from a point vortex of strength gam located at zk.\n    Positive gam = counter-clockwise."""
    dz = _soft(z - zk, 1e-2)
    out = np.zeros_like(z, dtype=complex)
    ok = np.abs(dz) > 1e-9
    out[ok] = -1j * gam / (2 * np.pi * dz[ok])
    return out


# ----------------------------------------------------------------------
# element quantities for the model
# ----------------------------------------------------------------------
def element_circulation(outs, Cls, alpha):
    """Per element: normalised strength Gamma_e (uses Cl per element or a thin-airfoil guess)."""
    a = np.radians(alpha)
    G = np.zeros(len(outs))
    for ei, o in enumerate(outs):
        c = o[:, 0].max() - o[:, 0].min()
        cl = Cls[ei] if Cls is not None and ei < len(Cls) and Cls[ei] is not None else 2 * np.pi * np.sin(a)
        G[ei] = -cl * UINF * max(c, 1e-9) / 2.0
    return G


def element_quarter(o):
    """Point on the element's camber-like line at its quarter chord (used for sink core)."""
    x0 = o[:, 0].min()
    xmax = o[:, 0].max()
    c = xmax - o[:, 0].min()
    xt = x0 + 0.25 * c
    best = np.argsort(np.abs(o[:, 0] - xt))[:2]
    return float(np.mean(o[best, 0])), float(np.mean(o[best, 1]))


# ----------------------------------------------------------------------
# field
# ----------------------------------------------------------------------
def compute_field(outs, alpha=0.0, ground_h=None, Cls=None, bounds=None, nx=240, ny=240,
                  block=0.18):
    """Illustrative velocity field. Returns X, Y, U, V (inside elements = NaN).

    Cls: per-element lift coefficients (in the aero_convention, so s1223 inverted is ~ -1.6).
    ground_h: distance from ground (y=0) to the leading edge. Enables the mirrored ground.
    """
    outs = [np.asarray(o, float) for o in outs]
    a = np.radians(alpha)
    vinf = np.array([np.cos(a), np.sin(a)]) * UINF
    panels, _starts, decs = build_panels(outs)
    Gamma = element_circulation(outs, Cls, alpha)
    qpts = [element_quarter(o) for o in decs]
    z1a = np.array([p["p1"][0] + 1j * p["p1"][1] for p in panels])
    z2a = np.array([p["p2"][0] + 1j * p["p2"][1] for p in panels])
    sa = np.array([p["s"] for p in panels])
    qx = np.array([q[0] + 1j * q[1] for q in qpts])
    mivec = np.array([block * UINF * float(sum(p["s"] for p in panels if p["el"] == ei))
                      for ei in range(len(outs))])
    mirror_on = ground_h is not None

    if bounds is None:
        xmin = min(o[:, 0].min() for o in outs)
        xmax = max(o[:, 0].max() for o in outs)
        ymin = min(o[:, 1].min() for o in outs)
        ymax = max(o[:, 1].max() for o in outs)
        if mirror_on:
            ymin = min(ymin, 0.0)
        span = max(xmax - xmin, ymax - ymin, 0.5)
        bounds = (xmin - 0.35 * span, xmax + 0.45 * span, ymin - 0.7 * span, ymax + 0.7 * span)
    x, y = np.meshgrid(np.linspace(bounds[0], bounds[1], nx), np.linspace(bounds[2], bounds[3], ny))
    xf = x.ravel()
    yf = y.ravel()
    z = xf + 1j * yf

    u = np.full(z.shape, vinf[0])
    v = np.full(z.shape, vinf[1])
    chunk = 4096
    for i in range(0, len(z), chunk):
        zc = z[i:i + chunk]
        dz1 = _soft(zc[:, None] - z1a[None, :], 1e-2)
        dz2 = _soft(zc[:, None] - z2a[None, :], 1e-2)
        src = (np.log(dz1) - np.log(dz2)) / (2 * np.pi)
        vel = (src * sa[None, :] * (block * UINF)).sum(axis=1)
        if mirror_on:
            zd = zc.real[:, None] + 1j * (-zc.imag[:, None])
            mdz1 = _soft(zd - z1a[None, :], 1e-2)
            mdz2 = _soft(zd - z2a[None, :], 1e-2)
            msrc = (np.log(mdz1) - np.log(mdz2)) / (2 * np.pi)
            vel = vel + (msrc * sa[None, :] * (block * UINF)).sum(axis=1)
        # sinks + circulation vortices, and their ground images
        for ei in range(len(outs)):
            vel = vel + _vel_sink_pt(zc, qx[ei], mivec[ei])
            vel = vel + _vel_vortex_pt(zc, qx[ei], Gamma[ei])
            if mirror_on:
                vel = vel + _vel_sink_pt(zc, qx[ei].conjugate(), mivec[ei])
                vel = vel + _vel_vortex_pt(zc, qx[ei].conjugate(), -Gamma[ei])
        u[i:i + chunk] = u[i:i + chunk] + np.real(vel)
        v[i:i + chunk] = v[i:i + chunk] + (-np.imag(vel))

    inside = _points_in_poly_many(outs, xf, yf)
    u[inside] = np.nan
    v[inside] = np.nan
    return x, y, u.reshape(x.shape), v.reshape(x.shape)


def _points_in_poly_many(outs, x, y):
    mask = np.zeros(len(x), dtype=bool)
    for o in outs:
        px = o[:, 0]
        py = o[:, 1]
        n = len(o)
        j = n - 1
        for i in range(n):
            xi = px[i]
            yi = py[i]
            xj = px[j]
            yj = py[j]
            cond = (yi > y) != (yj > y)
            idx = np.where(cond)[0]
            if len(idx) == 0:
                j = i
                continue
            xc = (xj - xi) * (y[idx] - yi) / (yj - yi + 1e-12) + xi
            mask[idx] ^= xc < x[idx]
            j = i
    return mask


def streamlines(x, y, u, v, seeds, n=600, ds=None):
    """Trace streamlines from seeds (list of (x0, y0)) both up- and down-flow. Returns list of
    point lists in data coordinates."""
    if ds is None:
        ds = (x[0, -1] - x[0, 0]) / (u.shape[1] * 4)
    ok = np.isfinite(u)
    uu = np.where(ok, u, 0.0)
    vv = np.where(ok, v, 0.0)
    x0 = x[0, 0]
    y0 = y[0, 0]
    hx = (x[0, 1] - x[0, 0])
    hy = (y[1, 0] - y[0, 0])
    nx_, ny_ = u.shape
    lines = []

    def step(cur, sx0, sy0, dirn):
        c = np.array([sx0, sy0], float)
        out = []
        for _ in range(n):
            ix = int((c[0] - x0) / hx)
            iy = int((c[1] - y0) / hy)
            if not (0 <= ix < nx_ and 0 <= iy < ny_):
                break
            s = float(np.hypot(uu[iy, ix], vv[iy, ix]))
            if s < 1e-5 or not ok[iy, ix]:
                break
            c = c + dirn * np.array([uu[iy, ix], vv[iy, ix]]) / s * ds
            out.append((float(c[0]), float(c[1])))
        return out

    for (sx0, sy0) in seeds:
        up = step(0, sx0, sy0, +1)
        down = step(0, sx0, sy0, -1)
        pts = list(reversed(down)) + [(sx0, sy0)] + list(up)
        lines.append(pts)
    return lines


if __name__ == "__main__":
    import os
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    import aero_auto as A
    dat = os.path.join(os.path.expanduser(A.AIRFOIL_DIR), "s1223.dat")
    if not os.path.exists(dat):
        raise SystemExit(f"demo needs s1223.dat in {A.AIRFOIL_DIR}")
    A.AIRFOILS["s1223"] = A.load_airfoil(dat)[0]
    outs = A.build_outlines(("s1223", ()), ground_h=None)
    X, Y, U, V = compute_field(outs, alpha=-5.0, Cls=[-1.55])
    print("field", U.shape, "valid", int(np.isfinite(U).sum()), "of", U.size)
    print("U range", float(np.nanmin(U)), float(np.nanmax(U)), "V range", float(np.nanmin(V)), float(np.nanmax(V)))