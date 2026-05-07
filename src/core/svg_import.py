"""
svg_import.py — Parse SVG files into plotter polyline paths.

Handles: <path>, <line>, <rect>, <circle>, <ellipse>, <polyline>, <polygon>.
Cubic/quadratic bezier curves are approximated with 16 line segments.
Output: list of [(x_norm, y_norm), ...] paths, each normalised to [0, 1].
"""
from __future__ import annotations
import math
import re
import xml.etree.ElementTree as ET


# ── SVG namespace ─────────────────────────────────────────────────────────────

_NS = {"svg": "http://www.w3.org/2000/svg"}


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


# ── number tokeniser ──────────────────────────────────────────────────────────

_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _nums(s: str) -> list[float]:
    return [float(m) for m in _NUM_RE.findall(s)]


# ── bezier approximation ──────────────────────────────────────────────────────

def _cubic(p0, p1, p2, p3, n=16):
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
        y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts


def _quad(p0, p1, p2, n=12):
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**2*p0[0] + 2*mt*t*p1[0] + t**2*p2[0]
        y = mt**2*p0[1] + 2*mt*t*p1[1] + t**2*p2[1]
        pts.append((x, y))
    return pts


def _arc(x0, y0, rx, ry, phi, large, sweep, x1, y1, n=20):
    """Approximate SVG arc with line segments."""
    if rx == 0 or ry == 0:
        return [(x0, y0), (x1, y1)]
    phi_r = math.radians(phi)
    cos_phi, sin_phi = math.cos(phi_r), math.sin(phi_r)
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    x1p = cos_phi*dx + sin_phi*dy
    y1p = -sin_phi*dx + cos_phi*dy
    lam = (x1p/rx)**2 + (y1p/ry)**2
    if lam > 1:
        rx *= math.sqrt(lam); ry *= math.sqrt(lam)
    sq = math.sqrt(max(0, ((rx*ry)**2 - (rx*y1p)**2 - (ry*x1p)**2) /
                         ((rx*y1p)**2 + (ry*x1p)**2)))
    if large == sweep:
        sq = -sq
    cxp = sq*rx*y1p/ry
    cyp = -sq*ry*x1p/rx
    cx = cos_phi*cxp - sin_phi*cyp + (x0+x1)/2
    cy = sin_phi*cxp + cos_phi*cyp + (y0+y1)/2
    theta1 = math.atan2((y1p-cyp)/ry, (x1p-cxp)/rx)
    dtheta = math.atan2((-y1p-cyp)/ry, (-x1p-cxp)/rx) - theta1
    if not sweep and dtheta > 0:
        dtheta -= 2*math.pi
    elif sweep and dtheta < 0:
        dtheta += 2*math.pi
    pts = []
    for i in range(n+1):
        t = theta1 + dtheta*i/n
        x = cos_phi*rx*math.cos(t) - sin_phi*ry*math.sin(t) + cx
        y = sin_phi*rx*math.cos(t) + cos_phi*ry*math.sin(t) + cy
        pts.append((x, y))
    return pts


# ── path `d` parser ───────────────────────────────────────────────────────────

def _parse_d(d: str) -> list[list[tuple[float, float]]]:
    """Return a list of polylines from an SVG path `d` attribute."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUM_RE.pattern, d)
    paths, current, cx, cy, last_cmd, last_ctrl = [], [], 0.0, 0.0, "", (0.0, 0.0)
    i = 0

    def consume(n):
        nonlocal i
        vals = [float(tokens[i+k]) for k in range(n)]
        i += n
        return vals

    while i < len(tokens):
        cmd = tokens[i]
        if not cmd.isalpha():
            i += 1
            continue
        i += 1
        rel = cmd.islower()
        c = cmd.lower()

        def ax(v):
            return cx + v if rel else v

        def ay(v):
            return cy + v if rel else v

        if c == "m":
            if current: paths.append(current)
            x, y = consume(2)
            cx, cy = ax(x), ay(y)
            current = [(cx, cy)]
            last_cmd = "m"

        elif c == "l":
            x, y = consume(2)
            cx, cy = ax(x), ay(y)
            current.append((cx, cy))
            last_cmd = "l"

        elif c == "h":
            x, = consume(1)
            cx = ax(x)
            current.append((cx, cy))

        elif c == "v":
            y, = consume(1)
            cy = ay(y)
            current.append((cx, cy))

        elif c == "c":
            x1, y1, x2, y2, x, y = consume(6)
            p1 = (ax(x1), ay(y1))
            p2 = (ax(x2), ay(y2))
            p3 = (ax(x), ay(y))
            pts = _cubic((cx, cy), p1, p2, p3)
            current.extend(pts[1:])
            last_ctrl = p2
            cx, cy = p3

        elif c == "s":
            x2, y2, x, y = consume(4)
            p1 = (2*cx - last_ctrl[0], 2*cy - last_ctrl[1])
            p2 = (ax(x2), ay(y2))
            p3 = (ax(x), ay(y))
            pts = _cubic((cx, cy), p1, p2, p3)
            current.extend(pts[1:])
            last_ctrl = p2
            cx, cy = p3

        elif c == "q":
            x1, y1, x, y = consume(4)
            p1 = (ax(x1), ay(y1))
            p2 = (ax(x), ay(y))
            pts = _quad((cx, cy), p1, p2)
            current.extend(pts[1:])
            last_ctrl = p1
            cx, cy = p2

        elif c == "t":
            x, y = consume(2)
            p1 = (2*cx - last_ctrl[0], 2*cy - last_ctrl[1])
            p2 = (ax(x), ay(y))
            pts = _quad((cx, cy), p1, p2)
            current.extend(pts[1:])
            last_ctrl = p1
            cx, cy = p2

        elif c == "a":
            rx, ry, phi, large, sweep, x, y = consume(7)
            nx, ny = ax(x), ay(y)
            pts = _arc(cx, cy, abs(rx), abs(ry), phi, int(large), int(sweep), nx, ny)
            current.extend(pts[1:])
            cx, cy = nx, ny

        elif c == "z":
            if current:
                current.append(current[0])  # close
                paths.append(current)
            current = []
            cx, cy = (current[0] if current else (cx, cy))

    if current:
        paths.append(current)
    return [p for p in paths if len(p) >= 2]


# ── element parsers ───────────────────────────────────────────────────────────

def _parse_element(el) -> list[list[tuple[float, float]]]:
    tag = _strip_ns(el.tag)
    a = el.attrib
    paths = []

    if tag == "path":
        d = a.get("d", "")
        if d:
            paths = _parse_d(d)

    elif tag == "line":
        pts = [(float(a.get("x1", 0)), float(a.get("y1", 0))),
               (float(a.get("x2", 0)), float(a.get("y2", 0)))]
        paths = [pts]

    elif tag == "rect":
        x, y = float(a.get("x", 0)), float(a.get("y", 0))
        w, h = float(a.get("width", 0)), float(a.get("height", 0))
        rx = float(a.get("rx", 0))
        if w > 0 and h > 0:
            if rx > 0:
                n = 8
                arc = lambda cx, cy, r, a0, a1: [
                    (cx+r*math.cos(a0+t*(a1-a0)/n), cy+r*math.sin(a0+t*(a1-a0)/n)) for t in range(n+1)]
                pts = (arc(x+rx, y+rx, rx, math.pi, 3*math.pi/2) +
                       arc(x+w-rx, y+rx, rx, 3*math.pi/2, 2*math.pi) +
                       arc(x+w-rx, y+h-rx, rx, 0, math.pi/2) +
                       arc(x+rx, y+h-rx, rx, math.pi/2, math.pi))
                pts.append(pts[0])
                paths = [pts]
            else:
                paths = [[(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)]]

    elif tag in ("circle", "ellipse"):
        cx = float(a.get("cx", 0))
        cy = float(a.get("cy", 0))
        rx = float(a.get("r", a.get("rx", 0)))
        ry = float(a.get("r", a.get("ry", rx)))
        n = max(32, int(2*math.pi*max(rx, ry)/3))
        pts = [(cx+rx*math.cos(2*math.pi*i/n), cy+ry*math.sin(2*math.pi*i/n)) for i in range(n+1)]
        paths = [pts]

    elif tag in ("polyline", "polygon"):
        vals = _nums(a.get("points", ""))
        pts = list(zip(vals[::2], vals[1::2]))
        if tag == "polygon" and pts:
            pts.append(pts[0])
        if len(pts) >= 2:
            paths = [pts]

    elif tag in ("g", "svg"):
        for child in el:
            paths.extend(_parse_element(child))

    return [p for p in paths if len(p) >= 2]


# ── public API ────────────────────────────────────────────────────────────────

def parse_svg(filepath: str, bed_mm: float = 220.0) -> list[list[tuple[float, float]]]:
    """
    Parse an SVG file and return paths as normalised (0-1) coordinates
    scaled to fit within a square of *bed_mm* × *bed_mm*.

    Returns list of paths, each a list of (nx, ny) tuples.
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Determine coordinate space from viewBox or width/height
    vb = root.get("viewBox", "")
    if vb:
        vb_nums = _nums(vb)
        if len(vb_nums) == 4:
            vx, vy, vw, vh = vb_nums
        else:
            vx, vy, vw, vh = 0, 0, 1, 1
    else:
        vx, vy = 0, 0
        vw = _nums(root.get("width", "220"))[0] if root.get("width") else 220
        vh = _nums(root.get("height", "220"))[0] if root.get("height") else 220

    if vw <= 0 or vh <= 0:
        return []

    # Collect all raw paths
    raw_paths = []
    for child in root:
        raw_paths.extend(_parse_element(child))

    if not raw_paths:
        return []

    # Fit to [0,1] maintaining aspect ratio, centred
    all_x = [p[0] for path in raw_paths for p in path]
    all_y = [p[1] for path in raw_paths for p in path]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    span_x = max_x - min_x or 1
    span_y = max_y - min_y or 1
    scale = 1.0 / max(span_x, span_y)
    ox = (1 - span_x * scale) / 2
    oy = (1 - span_y * scale) / 2

    normalised = []
    for path in raw_paths:
        norm = [((px - min_x) * scale + ox,
                 1.0 - ((py - min_y) * scale + oy))   # flip Y
                for px, py in path]
        normalised.append(norm)

    return normalised
