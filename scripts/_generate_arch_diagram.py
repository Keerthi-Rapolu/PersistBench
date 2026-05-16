#!/usr/bin/env python3
"""Generate PersistBench dark-mode architecture SVG.

Output: docs/images/persistbench_architecture_dark.svg
Run:    python scripts/_generate_arch_diagram.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1200, 660

BG_TOP        = "#0f1117"
BG_BOT        = "#161b22"
BOX_FILL_TOP  = "#273449"
BOX_FILL_BOT  = "#1e293b"
BOX_BORDER    = "#334155"
TEXT_PRI      = "#f8fafc"
TEXT_SEC      = "#94a3b8"
TEXT_MUT      = "#64748b"
ARROW         = "#94a3b8"

CYAN   = "#38bdf8"   # Evaluation / Scenario
AMBER  = "#f59e0b"   # Defense
GREEN  = "#10b981"   # Memory / Replay
ROSE   = "#fb7185"   # Output / Risk

FONT      = "Inter, 'IBM Plex Sans', system-ui, sans-serif"
FONT_MONO = "'IBM Plex Mono', 'Fira Code', Consolas, monospace"


# ── helpers ──────────────────────────────────────────────────────────────────

def g(tag, attrs="", children="", selfclose=False):
    if selfclose:
        return f"<{tag} {attrs}/>"
    return f"<{tag} {attrs}>{children}</{tag}>"


def rect(x, y, w, h, rx=12, fill="", stroke=BOX_BORDER, sw=1.5, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" ry="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'


def txt(x, y, s, fill=TEXT_PRI, size=13, weight="normal", anchor="middle", font=None, dy=0, extra=""):
    f = font or FONT
    dy_attr = f'dy="{dy}"' if dy else ""
    return f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" font-family="{f}" {dy_attr} {extra}>{s}</text>'


def arrow_h(x1, y, x2, color=ARROW):
    return f'<path d="M{x1},{y} L{x2},{y}" stroke="{color}" stroke-width="2" fill="none" marker-end="url(#ah)"/>'


def arrow_v(x, y1, y2, color=ARROW):
    return f'<path d="M{x},{y1} L{x},{y2}" stroke="{color}" stroke-width="2" fill="none" marker-end="url(#ah)"/>'


def bidirectional_v(x, y1, y2, color=ARROW):
    return (
        f'<path d="M{x},{y1} L{x},{y2}" stroke="{color}" stroke-width="2" fill="none" marker-end="url(#ah)" marker-start="url(#ah_rev)"/>'
    )


def line(x1, y1, x2, y2, stroke=BOX_BORDER, sw=1, dash=""):
    da = f'stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}" {da}/>'


# ── layout constants ──────────────────────────────────────────────────────────

BW, BH  = 172, 195   # main pipeline box width / height
GAP     = 26          # gap between boxes
TOP_Y   = 110         # top of main boxes

TOTAL_W = 5 * BW + 4 * GAP          # 860 + 104 = 964
SX      = (W - TOTAL_W) // 2        # left margin = 118

xs = [SX + i * (BW + GAP) for i in range(5)]

# Replay Engine (index 2) center x
RCX = xs[2] + BW // 2   # = 118 + 2*198 + 86 = 118+396+86 = 600  (perfectly centered)

DEF_W, DEF_H = 380, 96
DEF_X = RCX - DEF_W // 2
DEF_Y = TOP_Y + BH + 52

MEM_W, MEM_H = 280, 76
MEM_X = RCX - MEM_W // 2
MEM_Y = DEF_Y + DEF_H + 32


# ── build SVG ─────────────────────────────────────────────────────────────────

parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',

    # ── defs ──
    f'''<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{BG_TOP}"/>
    <stop offset="100%" stop-color="{BG_BOT}"/>
  </linearGradient>
  <linearGradient id="box" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{BOX_FILL_TOP}"/>
    <stop offset="100%" stop-color="{BOX_FILL_BOT}"/>
  </linearGradient>
  <linearGradient id="defgr" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#2a1e06"/>
    <stop offset="100%" stop-color="#1a1204"/>
  </linearGradient>
  <linearGradient id="memgr" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#0a221a"/>
    <stop offset="100%" stop-color="#051510"/>
  </linearGradient>
  <!-- forward arrowhead (7px, fits in 26px gap) -->
  <marker id="ah" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
    <polygon points="0 0, 7 2.5, 0 5" fill="{ARROW}"/>
  </marker>
  <!-- reverse arrowhead -->
  <marker id="ah_rev" markerWidth="7" markerHeight="5" refX="0" refY="2.5" orient="auto-start-reverse">
    <polygon points="0 0, 7 2.5, 0 5" fill="{ARROW}"/>
  </marker>
</defs>''',

    # background
    f'<rect width="{W}" height="{H}" fill="url(#bg)"/>',

    # title
    txt(W//2, 44, "PersistBench", fill=TEXT_PRI, size=22, weight="700"),
    txt(W//2, 68, "Persistent Agent Security Benchmark  ·  Architecture &amp; Evaluation Pipeline",
        fill=TEXT_SEC, size=12),
    line(SX, 82, SX + TOTAL_W, 82, stroke=BOX_BORDER, sw=1),
]


# ── step connector line (above badges) ────────────────────────────────────────
badge_y = TOP_Y - 22
parts.append(line(xs[0] + BW//2 + 14, badge_y, xs[4] + BW//2 - 14, badge_y,
                  stroke=BOX_BORDER, sw=1, dash="4 4"))

# ── step badges ───────────────────────────────────────────────────────────────
for i, x in enumerate(xs):
    cx = x + BW // 2
    parts.append(f'<circle cx="{cx}" cy="{badge_y}" r="12" fill="{BOX_FILL_BOT}" stroke="{BOX_BORDER}" stroke-width="1.5"/>')
    parts.append(txt(cx, badge_y + 4, str(i + 1), fill=TEXT_SEC, size=11, weight="600"))


# ── stage data ────────────────────────────────────────────────────────────────
stages = [
    {
        "label": ("SCENARIO", "SUITE"),
        "accent": CYAN,
        "items": ["SBMP · 27 scenarios", "TSCC · 25 scenarios", "CACP · 25 scenarios", "YAML spec format"],
    },
    {
        "label": ("TRACE", "GENERATOR"),
        "accent": TEXT_SEC,
        "items": ["Session sequencer", "Payload injector", "Provenance tagger", "Event stream"],
    },
    {
        "label": ("REPLAY", "ENGINE"),
        "accent": GREEN,
        "items": ["Session controller", "Defense hook points", "Memory I/O", "Cross-session state"],
    },
    {
        "label": ("EVALUATION", "ENGINE"),
        "accent": CYAN,
        "items": ["APS · RLS · UPS", "BDI · BDI_sem", "FVS-1–15", "CRA (heuristic)"],
    },
    {
        "label": ("OUTPUT", "&amp; STORE"),
        "accent": ROSE,
        "items": ["DuckDB store", "Streamlit dashboard", "Artifact export", "Provenance log"],
    },
]


# ── main pipeline boxes ───────────────────────────────────────────────────────
for i, (x, stage) in enumerate(zip(xs, stages)):
    cx = x + BW // 2
    acc = stage["accent"]

    # box shadow (subtle)
    parts.append(rect(x + 2, TOP_Y + 3, BW, BH, rx=14,
                      fill="#000000", stroke="none", sw=0, extra='opacity="0.25"'))
    # box
    parts.append(rect(x, TOP_Y, BW, BH, rx=14, fill="url(#box)", stroke=BOX_BORDER, sw=1.5))
    # accent top bar
    parts.append(f'<rect x="{x}" y="{TOP_Y}" width="{BW}" height="4" rx="3" ry="3" fill="{acc}"/>')

    # label (two lines)
    lbl = stage["label"]
    parts.append(txt(cx, TOP_Y + 28, lbl[0], fill=acc, size=11, weight="700"))
    parts.append(txt(cx, TOP_Y + 43, lbl[1], fill=acc, size=11, weight="700"))

    # divider
    parts.append(line(x + 14, TOP_Y + 58, x + BW - 14, TOP_Y + 58, stroke=BOX_BORDER))

    # items
    iy = TOP_Y + 77
    for item in stage["items"]:
        parts.append(txt(cx, iy, item, fill=TEXT_SEC, size=10))
        iy += 26


# ── horizontal arrows between pipeline stages ──────────────────────────────────
arrow_y = TOP_Y + BH // 2 + 4
for i in range(4):
    x1 = xs[i] + BW + 1
    x2 = xs[i + 1] - 1   # arrowhead occupies 7px at x2
    parts.append(arrow_h(x1, arrow_y, x2))


# ── Defense Middleware box ────────────────────────────────────────────────────
DCX = DEF_X + DEF_W // 2
parts.append(rect(DEF_X + 2, DEF_Y + 3, DEF_W, DEF_H, rx=12,
                  fill="#000000", stroke="none", sw=0, extra='opacity="0.25"'))
parts.append(rect(DEF_X, DEF_Y, DEF_W, DEF_H, rx=12, fill="url(#defgr)", stroke=AMBER, sw=1.5))
parts.append(f'<rect x="{DEF_X}" y="{DEF_Y}" width="{DEF_W}" height="4" rx="3" ry="3" fill="{AMBER}"/>')
parts.append(txt(DCX, DEF_Y + 26, "DEFENSE MIDDLEWARE", fill=AMBER, size=11, weight="700"))
parts.append(line(DEF_X + 14, DEF_Y + 36, DEF_X + DEF_W - 14, DEF_Y + 36, stroke=AMBER, sw=0.6))
parts.append(txt(DCX, DEF_Y + 56,
                 "PLS · MW · TOH · DEV · PS · CompositeDefense",
                 fill=TEXT_SEC, size=10.5))
parts.append(txt(DCX, DEF_Y + 75,
                 "on_scenario_start · pre_turn · post_turn · pre_memory_write",
                 fill=TEXT_MUT, size=9.5, font=FONT_MONO))


# ── Memory Backends box ────────────────────────────────────────────────────────
MCX = MEM_X + MEM_W // 2
parts.append(rect(MEM_X + 2, MEM_Y + 3, MEM_W, MEM_H, rx=12,
                  fill="#000000", stroke="none", sw=0, extra='opacity="0.25"'))
parts.append(rect(MEM_X, MEM_Y, MEM_W, MEM_H, rx=12, fill="url(#memgr)", stroke=GREEN, sw=1.5))
parts.append(f'<rect x="{MEM_X}" y="{MEM_Y}" width="{MEM_W}" height="4" rx="3" ry="3" fill="{GREEN}"/>')
parts.append(txt(MCX, MEM_Y + 26, "MEMORY BACKENDS", fill=GREEN, size=11, weight="700"))
parts.append(line(MEM_X + 14, MEM_Y + 34, MEM_X + MEM_W - 14, MEM_Y + 34, stroke=GREEN, sw=0.6))
parts.append(txt(MCX, MEM_Y + 54, "In-Process · Qdrant · Custom Backend", fill=TEXT_SEC, size=10.5))


# ── vertical arrows: Replay Engine ↔ Defense ↔ Memory ─────────────────────────
# Replay Engine bottom → Defense top (bidirectional hook communication)
parts.append(bidirectional_v(
    RCX,
    TOP_Y + BH + 1,
    DEF_Y - 1,
    color=ARROW,
))

# Defense bottom → Memory top
parts.append(arrow_v(RCX, DEF_Y + DEF_H + 1, MEM_Y - 1))


# ── legend ────────────────────────────────────────────────────────────────────
legend = [
    (CYAN,  "Evaluation / Scenario"),
    (AMBER, "Defense Middleware"),
    (GREEN, "Memory / Replay Engine"),
    (ROSE,  "Output / Risk"),
]
# Legend — bottom right, clear of footer text
LX = W - 220
LY = H - 145
parts.append(rect(LX - 10, LY - 14, 210, 116, rx=10, fill="#161b22", stroke=BOX_BORDER, sw=1))
parts.append(txt(LX + 94, LY + 2, "Legend", fill=TEXT_MUT, size=10, weight="600"))
for j, (color, label) in enumerate(legend):
    cy = LY + 20 + j * 22
    parts.append(f'<rect x="{LX}" y="{cy - 7}" width="12" height="12" rx="3" fill="{color}" opacity="0.85"/>')
    parts.append(txt(LX + 18, cy + 3, label, fill=TEXT_SEC, size=10, anchor="start"))


# ── footer ─────────────────────────────────────────────────────────────────────
# Line only spans up to where legend begins horizontally
parts.append(line(SX, H - 28, LX - 24, H - 28, stroke=BOX_BORDER, sw=1))
parts.append(txt((SX + LX - 24) // 2, H - 12,
                 "persistbench.streamlit.app  ·  github.com/Keerthi-Rapolu/PersistBench",
                 fill=TEXT_MUT, size=10))

parts.append("</svg>")


# ── write ──────────────────────────────────────────────────────────────────────
svg = "\n".join(parts)
out = OUT / "persistbench_architecture_dark.svg"
out.write_text(svg, encoding="utf-8")
print(f"Written: {out}  ({out.stat().st_size // 1024} KB)")
