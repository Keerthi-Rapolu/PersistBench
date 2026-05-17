#!/usr/bin/env python3
"""Generate publication-native adversarial fragment lifecycle figure.

Output: docs/images/provenance_lifecycle.svg

Style: academic systems/security paper — white background, pastel,
       causal left-to-right flow. Matches Figure 1 (architecture) palette.

Core idea: an adversarial fragment propagates, reactivates, and
partially survives deletion through a derived descendant.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1000, 400

# ── Palette ──────────────────────────────────────────────────────────────────
BG          = "#FFFFFF"         # pure white paper background

# Adversarial lineage — soft rose (Create, Trigger)
ADV_FILL    = "#FFF1F2"
ADV_ACCENT  = "#FCA5A5"         # top accent bar + border
ADV_LABEL   = "#991B1B"         # header text

# Benign retrieval — soft blue (Retrieve)
BLU_FILL    = "#EFF6FF"
BLU_ACCENT  = "#93C5FD"
BLU_LABEL   = "#1E40AF"

# Derived / consolidated — soft violet (Consolidate, Residual)
PUR_FILL    = "#F5F3FF"
PUR_ACCENT  = "#C4B5FD"
PUR_LABEL   = "#5B21B6"

# Deleted — muted neutral (Delete)
GRY_FILL    = "#F8FAFC"
GRY_ACCENT  = "#CBD5E1"
GRY_LABEL   = "#64748B"

# Typography & chrome
TEXT_DARK   = "#1E293B"         # primary node labels
TEXT_MED    = "#475569"         # secondary / sub-labels
TEXT_MUTED  = "#94A3B8"         # timeline, phase annotations
ARROW_COL   = "#94A3B8"         # arrow stroke
RULE_COL    = "#E2E8F0"         # separator lines inside nodes

FONT        = "Inter, 'IBM Plex Sans', system-ui, sans-serif"
FONT_MONO   = "'IBM Plex Mono', 'Fira Code', Consolas, monospace"

# ── Node geometry ─────────────────────────────────────────────────────────────
NW, NH, NR  = 138, 62, 9        # width, height, corner-radius
ACCENT_H    = 4                  # accent bar height at top of each node

# Top-row horizontal layout (5 nodes, symmetric margins)
# Total span = 5×138 + 4×42 = 690 + 168 = 858   →  margin = (1000-858)/2 = 71
GAP         = 42
TOP_Y       = 128               # center-y of top-row nodes
CX          = [71 + NW // 2 + i * (NW + GAP) for i in range(5)]
# CX  ≈ [140, 320, 500, 680, 860]

# Derived (Residual Descendant) node — directly below Consolidate (CX[2])
DW, DH      = 152, 62
DCX         = CX[2]             # same column
DCY         = 293               # center-y

# Persistence dashed arrow runs from right edge of Derived → right margin
PERSIST_X1  = DCX + DW // 2 + 4
PERSIST_X2  = W - 28            # arrowhead tip near right edge

# Session-axis strip
AXIS_Y      = 173               # y of session line (below node bottoms at 128+31=159)
TICK_H      = 5

SESSION_LABELS = ["S₁", "S₂", "S₃–₄", "S₅", "S₆"]
PHASE_SPANS  = [
    (CX[0], CX[1], "Attack Phase"),
    (CX[2], CX[2], ""),
    (CX[3], CX[3], "Trigger"),
    (CX[4], CX[4], "Deletion"),
]


# ── SVG helpers ───────────────────────────────────────────────────────────────

def box(cx, cy, w, h, rx, fill, accent, dashed=False, extra=""):
    x, y = cx - w // 2, cy - h // 2
    dash = 'stroke-dasharray="6 3"' if dashed else ""
    return (
        # main rect
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" ry="{rx}" '
        f'fill="{fill}" stroke="{accent}" stroke-width="1.5" {dash} {extra}/>\n'
        # accent bar (clipped to top rounded corners via separate rect, small height)
        f'<rect x="{x}" y="{y}" width="{w}" height="{ACCENT_H}" rx="{rx}" ry="{rx}" fill="{accent}"/>\n'
        # flatten bottom of accent bar
        f'<rect x="{x}" y="{y + ACCENT_H // 2}" width="{w}" height="{ACCENT_H // 2}" fill="{accent}"/>'
    )


def txt(x, y, s, fill=TEXT_DARK, size=12, weight="600", anchor="middle",
        italic=False, extra=""):
    style = f'font-style="italic"' if italic else ""
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}" '
        f'font-family="{FONT}" {style} {extra}>{s}</text>'
    )


def htxt(x, y, s, fill=TEXT_MUTED, size=9.5, anchor="middle"):
    """Tiny helper-text for phase / timeline labels."""
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
        f'text-anchor="{anchor}" font-family="{FONT}">{s}</text>'
    )


def seg(x1, y1, x2, y2, stroke=RULE_COL, sw=1, dash=""):
    da = f'stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}" {da}/>'


def arrow_h(x1, y, x2, col=ARROW_COL, dash=""):
    da = f'stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<path d="M{x1},{y} L{x2},{y}" stroke="{col}" stroke-width="1.5" '
        f'fill="none" {da} marker-end="url(#ah)"/>'
    )


def arrow_v(x, y1, y2, col=ARROW_COL):
    return (
        f'<path d="M{x},{y1} L{x},{y2}" stroke="{col}" stroke-width="1.5" '
        f'fill="none" marker-end="url(#ah)"/>'
    )


def arrow_curve_diag(x1, y1, x2, y2, col=ARROW_COL):
    """Cubic-bezier from (x1,y1) to (x2,y2) with vertical control points."""
    my = (y1 + y2) // 2
    return (
        f'<path d="M{x1},{y1} C{x1},{my} {x2},{my} {x2},{y2}" '
        f'stroke="{col}" stroke-width="1.5" fill="none" marker-end="url(#ah)"/>'
    )


# ── Node renderer ─────────────────────────────────────────────────────────────

def node(cx, cy, w, h, rx, fill, accent, label_color, lines,
         sub=None, dashed=False, deleted=False):
    """Return SVG string for one node with accent bar + label(s) + optional sub-label."""
    parts = [box(cx, cy, w, h, rx, fill, accent, dashed=dashed)]

    # Separator line below accent bar
    pad = 12
    sep_y = cy - h // 2 + ACCENT_H + 14
    parts.append(seg(cx - w // 2 + pad, sep_y, cx + w // 2 - pad, sep_y,
                     stroke=accent, sw=0.75))

    # Text block: one or two lines, centered in content area
    content_top  = cy - h // 2 + ACCENT_H + 14 + 1   # below separator
    content_h    = h - ACCENT_H - 14 - 1
    n_lines      = len(lines)
    lh           = 15                                   # line-height px

    if sub:
        total_text_h = n_lines * lh + 5 + 10           # lines + gap + sub
    else:
        total_text_h = n_lines * lh

    text_start_y = content_top + (content_h - total_text_h) // 2 + lh - 2

    fs = 11
    fw = "600"
    # If deleted, render label in strikethrough style via SVG text-decoration
    td_attr = 'text-decoration="line-through"' if deleted else ""

    for i, line in enumerate(lines):
        y = text_start_y + i * lh
        parts.append(
            f'<text x="{cx}" y="{y}" fill="{label_color}" font-size="{fs}" '
            f'font-weight="{fw}" text-anchor="middle" font-family="{FONT}" '
            f'{td_attr}>{line}</text>'
        )

    if sub:
        sub_y = text_start_y + n_lines * lh + 5
        parts.append(
            f'<text x="{cx}" y="{sub_y}" fill="{TEXT_MUTED}" font-size="9" '
            f'text-anchor="middle" font-family="{FONT_MONO}" font-style="italic">'
            f'{sub}</text>'
        )

    return "\n".join(parts)


# ── Build SVG ─────────────────────────────────────────────────────────────────

parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
    f'viewBox="0 0 {W} {H}">',

    # ── defs: arrowhead ───────────────────────────────────────────────────────
    f'''<defs>
  <!-- compact arrowhead matching Figure 1 style -->
  <marker id="ah" markerWidth="7" markerHeight="5"
          refX="7" refY="2.5" orient="auto">
    <polygon points="0 0, 7 2.5, 0 5" fill="{ARROW_COL}"/>
  </marker>
  <!-- reversed for bidirectional if needed -->
  <marker id="ah_rev" markerWidth="7" markerHeight="5"
          refX="0" refY="2.5" orient="auto-start-reverse">
    <polygon points="0 0, 7 2.5, 0 5" fill="{ARROW_COL}"/>
  </marker>
</defs>''',

    # ── background ────────────────────────────────────────────────────────────
    f'<rect width="{W}" height="{H}" fill="{BG}"/>',

    # ── title ─────────────────────────────────────────────────────────────────
    txt(W // 2, 28,
        "Adversarial Fragment Lifecycle",
        fill="#1E293B", size=13, weight="700"),
    txt(W // 2, 46,
        "persistent state propagates, reactivates, and survives incomplete deletion",
        fill=TEXT_MED, size=10, weight="400", italic=True),
]


# ── Top-row nodes ─────────────────────────────────────────────────────────────

node_specs = [
    # (cx, fill, accent, label_color, lines, sub, dashed, deleted)
    (CX[0], ADV_FILL, ADV_ACCENT, ADV_LABEL, ["Create"],        "adversarial write",   False, False),
    (CX[1], BLU_FILL, BLU_ACCENT, BLU_LABEL, ["Retrieve"],      "cross-session read",  False, False),
    (CX[2], PUR_FILL, PUR_ACCENT, PUR_LABEL, ["Consolidate"],   "summary derived",     False, False),
    (CX[3], ADV_FILL, ADV_ACCENT, ADV_LABEL, ["Trigger"],       "reactivation",        False, False),
    (CX[4], GRY_FILL, GRY_ACCENT, GRY_LABEL, ["Delete"],        "deletion attempt",    True,  True),
]

for cx, fill, acc, lc, lines, sub, dash, deleted in node_specs:
    parts.append(node(cx, TOP_Y, NW, NH, NR, fill, acc, lc, lines, sub=sub,
                      dashed=dash, deleted=deleted))


# ── Horizontal arrows (top row) ───────────────────────────────────────────────
for i in range(4):
    x1 = CX[i] + NW // 2 + 2
    x2 = CX[i + 1] - NW // 2 - 2
    parts.append(arrow_h(x1, TOP_Y, x2))


# ── Session axis ──────────────────────────────────────────────────────────────
# thin horizontal rule
axis_x1 = CX[0] - NW // 2 + 8
axis_x2 = CX[4] + NW // 2 - 8
parts.append(seg(axis_x1, AXIS_Y, axis_x2, AXIS_Y,
                 stroke=RULE_COL, sw=1))

# ticks and session labels
for i, (cx, sl) in enumerate(zip(CX, SESSION_LABELS)):
    parts.append(seg(cx, AXIS_Y - TICK_H, cx, AXIS_Y + TICK_H,
                     stroke=TEXT_MUTED, sw=1))
    parts.append(htxt(cx, AXIS_Y + 14, sl, size=9))

# phase bracket labels
phase_data = [
    ((CX[0] + CX[1]) // 2, "Attack Phase"),
    (CX[2],                 "Dormancy"),
    (CX[3],                 "Trigger Session"),
    (CX[4],                 "Deletion"),
]
for (px, label) in phase_data:
    parts.append(htxt(px, AXIS_Y + 26, label, fill="#B0BEC5", size=8.5))


# ── Derived node: Residual Descendant ─────────────────────────────────────────
parts.append(node(
    DCX, DCY, DW, DH, NR,
    PUR_FILL, PUR_ACCENT, PUR_LABEL,
    ["Residual", "Descendant"],
    sub="derived state persists",
    dashed=True,
))


# ── Arrow: Consolidate → Residual Descendant ──────────────────────────────────
# straight vertical from bottom of Consolidate to top of Derived
v_x  = DCX
v_y1 = TOP_Y + NH // 2 + 3
v_y2 = DCY - DH // 2 - 3
parts.append(arrow_v(v_x, v_y1, v_y2))

# "derives" label: left of the vertical arrow, italic, muted
derives_lbl_y = (v_y1 + v_y2) // 2 + 4
parts.append(
    f'<text x="{v_x - 8}" y="{derives_lbl_y}" fill="{TEXT_MUTED}" '
    f'font-size="9.5" text-anchor="end" font-family="{FONT}" '
    f'font-style="italic">derives</text>'
)


# ── Dashed persistence arrow: Residual → right edge ───────────────────────────
parts.append(arrow_h(PERSIST_X1, DCY, PERSIST_X2,
                     col=PUR_ACCENT, dash="6 4"))

# "persists →" label above the dashed arrow
persist_mid = (PERSIST_X1 + PERSIST_X2) // 2
parts.append(
    f'<text x="{persist_mid}" y="{DCY - 10}" fill="{PUR_LABEL}" '
    f'font-size="9.5" text-anchor="middle" font-family="{FONT}" '
    f'font-style="italic" font-weight="500">survives deletion</text>'
)


# ── Subtle "deletion boundary" vertical marker at Delete column ───────────────
# a thin dashed vertical line from axis down to the dashed persistence arrow
bdry_x = CX[4]
bdry_y1 = AXIS_Y + 30
bdry_y2 = DCY
parts.append(seg(bdry_x, bdry_y1, bdry_x, bdry_y2,
                 stroke="#FCA5A5", sw=1, dash="3 3"))


# ── Legend pill row (compact) ─────────────────────────────────────────────────
legend = [
    (ADV_ACCENT, ADV_LABEL, "Adversarial lineage"),
    (BLU_ACCENT, BLU_LABEL, "Benign retrieval"),
    (PUR_ACCENT, PUR_LABEL, "Derived / consolidated"),
    (GRY_ACCENT, GRY_LABEL, "Deleted (incomplete)"),
]

leg_y   = H - 22
leg_x0  = 60
leg_gap = 220

for j, (fill, text_col, label) in enumerate(legend):
    lx = leg_x0 + j * leg_gap
    # swatch
    parts.append(
        f'<rect x="{lx}" y="{leg_y - 7}" width="10" height="10" rx="2" '
        f'fill="{fill}" stroke="{text_col}" stroke-width="1.2"/>'
    )
    # label
    parts.append(
        f'<text x="{lx + 15}" y="{leg_y + 2}" fill="{TEXT_MED}" '
        f'font-size="9.5" text-anchor="start" font-family="{FONT}">'
        f'{label}</text>'
    )


# ── Thin top and bottom rules ─────────────────────────────────────────────────
parts.append(seg(40, 58, W - 40, 58, stroke=RULE_COL, sw=1))
parts.append(seg(40, H - 48, W - 40, H - 48, stroke=RULE_COL, sw=1))


# ── Close SVG ─────────────────────────────────────────────────────────────────
parts.append("</svg>")

svg = "\n".join(parts)
out = OUT / "provenance_lifecycle.svg"
out.write_text(svg, encoding="utf-8")
print(f"SVG written: {out}  ({out.stat().st_size // 1024} KB)")

# ── PNG export via Playwright (for LaTeX/pdflatex) ────────────────────────────
try:
    import time
    from playwright.sync_api import sync_playwright

    png_out = OUT / "provenance_lifecycle.png"
    # Wrap SVG in HTML that scales it to exactly 2× the design size
    html = f"""<!DOCTYPE html>
<html><head><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#fff; width:{W*2}px; height:{H*2}px; overflow:hidden; }}
  svg  {{ width:{W*2}px; height:{H*2}px; display:block; }}
</style></head><body>
{svg}
</body></html>"""
    html_tmp = OUT / "_provenance_lifecycle_tmp.html"
    html_tmp.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": W * 2, "height": H * 2})
        page.goto(html_tmp.as_uri(), wait_until="networkidle")
        time.sleep(0.4)
        png = page.screenshot(
            full_page=False,
            clip={"x": 0, "y": 0, "width": W * 2, "height": H * 2},
        )
        browser.close()
    html_tmp.unlink(missing_ok=True)
    png_out.write_bytes(png)
    print(f"PNG written: {png_out}  ({png_out.stat().st_size // 1024} KB)")
except Exception as e:
    print(f"PNG export skipped ({e}). Run: pip install playwright && python -m playwright install chromium")
