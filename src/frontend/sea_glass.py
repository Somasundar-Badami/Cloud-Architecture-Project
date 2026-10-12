"""
sea_glass.py -- "sea glass" visual theme for the InfraDriftGuard dashboard.

Matte, grainy, frosted pastel pills (lavender, sky, peach) resting on a
pale lavender-white surface, each with a soft tinted shadow underneath --
like tactile Material buttons made of sea glass.

Pure presentation: every function here only returns CSS/HTML strings, so
app.py's logic and tests are untouched.
"""

PALETTE = {
    "paper": "#F5F2FA",      # pale lavender-white surface
    "ink": "#2A2340",        # deep plum text and icons
    "mist": "#675F7C",       # secondary text
    "sky": "#A8D1F4",        # primary action pill ("Compose" blue)
    "lavender": "#E2C6F8",   # selected / toolbar pill
    "peach": "#F5C39C",
    "cream": "#FAE6CF",
    "blush": "#F4C1C6",
    "seafoam": "#8FD3BA",
    "honey": "#EDB653",
    "bottle": "#B86B43",
    "ruby": "#C9475F",
    "violet": "#9D8FD6",
}

# Risk levels follow sea glass rarity: common seafoam for Low, honey for
# Medium, bottle brown for High, rare ruby for Critical.
RISK_GLASS = {
    "Low": PALETTE["seafoam"],
    "Medium": PALETTE["honey"],
    "High": PALETTE["bottle"],
    "Critical": PALETTE["ruby"],
    "Review": PALETTE["violet"],
    "No drift": "#B9B3C8",
}


def _noise(alpha):
    return (
        "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'>"
        "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/>"
        f"<feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 {alpha} 0'/></filter>"
        "<rect width='100%' height='100%' filter='url(%23n)'/></svg>\")"
    )


GRAIN = _noise(.16)
FINE_GRAIN = _noise(.07)


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgba(hex_color, alpha):
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha})"


def glass_fill(hex_color, strength=0.55):
    """Frosted glass: a lit top edge fading into the tint (grain is added by CSS)."""
    return (
        f"linear-gradient(180deg, {_rgba('#FFFFFF', .55)} 0%, "
        f"{_rgba(hex_color, strength * .75)} 45%, {_rgba(hex_color, strength)} 100%)"
    )


def glass_shadow(hex_color, depth=1.0):
    """Soft tinted shadow pooling directly underneath, plus a lit rim."""
    d = depth
    return (
        f"0 {12*d:.0f}px {20*d:.0f}px -{8*d:.0f}px {_rgba(hex_color, .55)}, "
        f"0 {3*d:.0f}px {6*d:.0f}px -{2*d:.0f}px rgba(42,35,64,.12), "
        "inset 0 2px 2px rgba(255,255,255,.75), "
        "inset 0 -4px 8px rgba(42,35,64,.08)"
    )


def css():
    p = PALETTE
    milk_fill = f"{GRAIN}, linear-gradient(180deg, rgba(255,255,255,.92), rgba(250,248,253,.78))"
    milk_shadow = ("0 14px 26px -16px rgba(42,35,64,.35), 0 2px 4px -2px rgba(42,35,64,.10), "
                   "inset 0 1px 1px rgba(255,255,255,.9), inset 0 -3px 8px rgba(42,35,64,.05)")
    teal_fill = (f"{GRAIN}, linear-gradient(180deg, #C4E1F9 0%, {p['sky']} 100%)")
    teal_shadow = (f"0 12px 18px -8px {_rgba(p['sky'], .95)}, 0 3px 5px -2px rgba(42,35,64,.15), "
                   "inset 0 2px 2px rgba(255,255,255,.7), inset 0 -4px 8px rgba(42,35,64,.08)")
    lav_fill = (f"{GRAIN}, linear-gradient(180deg, #EEDCFB 0%, {p['lavender']} 100%)")
    lav_shadow = (f"0 12px 18px -8px {_rgba(p['lavender'], 1)}, 0 3px 5px -2px rgba(42,35,64,.15), "
                  "inset 0 2px 2px rgba(255,255,255,.7), inset 0 -4px 8px rgba(42,35,64,.08)")
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800&display=swap');

/* ---------- surface: pale paper, faint pastel light ---------- */
.stApp {{
  background:
    {FINE_GRAIN},
    radial-gradient(600px 420px at 85% 0%, {_rgba(p['cream'], .55)}, transparent 70%),
    radial-gradient(700px 500px at 10% 0%, {_rgba(p['lavender'], .35)}, transparent 70%),
    radial-gradient(800px 600px at 50% 100%, {_rgba(p['sky'], .18)}, transparent 70%),
    {p['paper']};
  background-attachment: fixed;
  color: {p['ink']};
}}
[data-testid="stHeader"] {{ background: transparent; }}
html, body, .stApp, .stMarkdown, p, li, label, input, textarea, button, [data-baseweb] {{
  font-family: 'Figtree', system-ui, sans-serif;
}}
h1, h2, h3, h4 {{
  font-family: 'Figtree', system-ui, sans-serif !important;
  color: {p['ink']} !important;
  letter-spacing: -0.015em;
}}
h2 {{ font-weight: 700 !important; font-size: 1.5rem !important; }}
h3 {{ font-weight: 650 !important; font-size: 1.12rem !important; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {p['mist']} !important; }}
code {{ background: rgba(226,198,248,.35) !important; color: {p['ink']} !important; border-radius: 8px; }}

/* ---------- sidebar: one tall pane of milky glass ---------- */
[data-testid="stSidebar"] {{
  background: {FINE_GRAIN}, linear-gradient(180deg, #F1E6FB, #ECE6F7);
  border-right: 1px solid rgba(42,35,64,.06);
}}
[data-testid="stSidebar"] * {{ color: {p['ink']}; }}
[data-testid="stSidebar"] h1 {{ font-size: 1.55rem !important; font-weight: 800 !important; }}
[data-testid="stSidebar"] h3 {{ font-size: 1rem !important; margin-top: .6rem; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(42,35,64,.12); }}

/* ---------- hero ---------- */
.sg-hero {{ position: relative; padding: 2.4rem 0 1.4rem; min-height: 220px; }}
.sg-hero h1 {{
  font-size: clamp(2.5rem, 5vw, 3.7rem) !important;
  font-weight: 800 !important;
  line-height: 1.0; margin: 0 0 .75rem 0; padding: 0 !important;
  position: relative; z-index: 2;
}}
.sg-hero p {{
  font-size: 1.1rem; color: {p['mist']}; max-width: 44ch; line-height: 1.55;
  margin: 0; position: relative; z-index: 2;
}}
.sg-pieces {{ position: absolute; inset: 0; pointer-events: none; z-index: 1; }}
.sg-piece {{
  position: absolute; display: grid; place-items: center;
  border: 1px solid rgba(255,255,255,.55);
  backdrop-filter: blur(6px);
  animation: sg-drop .9s cubic-bezier(.2,.9,.25,1.15) both;
}}
.sg-piece svg {{ width: 42%; height: 42%; }}
.sg-toolbar {{ display: flex !important; gap: 1.5rem; align-items: center; height: 74px; padding: 0 2rem; border-radius: 999px; }}
.sg-action {{ display: flex !important; gap: .8rem; align-items: center; height: 74px; padding: 0 2.2rem 0 1.6rem; border-radius: 26px; }}
.sg-action b {{ font-size: 1.15rem; font-weight: 600; color: {p['ink']}; position: relative; z-index: 1; }}
.sg-ico {{ display: inline-grid; width: 26px; height: 26px; position: relative; z-index: 1; }}
.sg-ico svg {{ width: 100%; height: 100%; }}
@keyframes sg-drop {{
  from {{ opacity: 0; transform: translateY(-18px) scale(.96); }}
  to   {{ opacity: 1; transform: translateY(0) scale(1); }}
}}
@media (prefers-reduced-motion: reduce) {{ .sg-piece, .sg-stone {{ animation: none !important; }} }}
@media (max-width: 1000px) {{ .sg-pieces {{ opacity: .3; }} }}

/* ---------- frosted panels ---------- */
[class*="st-key-sg_"] {{
  background: {FINE_GRAIN}, linear-gradient(180deg, rgba(255,255,255,.85), rgba(252,250,254,.7)) !important;
  border: 1px solid rgba(255,255,255,.9) !important;
  border-radius: 30px !important;
  box-shadow: {milk_shadow};
  padding: 1.4rem 1.6rem !important;
}}

[data-testid="stMetric"] {{
  background: {milk_fill};
  border: 1px solid rgba(255,255,255,.7);
  border-radius: 26px;
  padding: .9rem 1.4rem;
  box-shadow: {milk_shadow};
}}

/* ---------- tabs: quick-settings tiles ---------- */
.stTabs [role="tablist"] {{ gap: .7rem; border-bottom: none !important; padding: .3rem 0 1rem; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"],
.stTabs [role="tablist"] > div:not([role="tab"]) {{ display: none !important; }}
.stTabs [role="tab"] {{
  background: {milk_fill};
  border: 1px solid rgba(255,255,255,.7);
  border-radius: 999px;
  padding: .7rem 1.4rem;
  height: auto;
  box-shadow: {milk_shadow};
  transition: background .25s ease, box-shadow .25s ease;
}}
.stTabs [role="tab"] p {{ font-weight: 600; color: {p['ink']}; font-size: .98rem; }}
.stTabs [role="tab"][aria-selected="true"] {{ background: {lav_fill}; box-shadow: {lav_shadow}; }}
.stTabs [role="tab"][aria-selected="true"] p {{ color: {p['ink']}; }}

/* ---------- buttons: chunky tactile pills ---------- */
.stButton > button, [data-testid="stFormSubmitButton"] > button {{
  border-radius: 999px !important;
  border: 1px solid rgba(255,255,255,.7) !important;
  background: {milk_fill} !important;
  color: {p['ink']} !important;
  font-weight: 600;
  padding: .65rem 1.5rem !important;
  box-shadow: {milk_shadow};
  transition: transform .15s ease, box-shadow .15s ease;
}}
.stButton > button:hover {{ transform: translateY(-2px); }}
.stButton > button:active {{ transform: translateY(1px); }}
.stButton > button[kind="primary"], [data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"] > button {{
  background: {teal_fill} !important;
  color: {p['ink']} !important;
  box-shadow: {teal_shadow} !important;
  padding: .8rem 2.1rem !important;
  font-size: 1.04rem;
}}
.stButton > button[kind="primary"] p, [data-testid="stFormSubmitButton"] > button p {{ color: {p['ink']} !important; font-weight: 700; }}
button:focus-visible {{ outline: 3px solid {_rgba(p['violet'], .8)} !important; outline-offset: 3px; }}

/* ---------- inputs ---------- */
.stTextArea textarea, [data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{
  background: rgba(255,255,255,.8) !important;
  border-radius: 20px !important;
  border-color: rgba(42,35,64,.08) !important;
  color: {p['ink']} !important;
}}
.stTextArea textarea {{
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace !important;
  font-size: .84rem !important; line-height: 1.5;
}}
[data-baseweb="input"] input {{ color: {p['ink']} !important; }}

/* ---------- notes, tables, json ---------- */
[data-testid="stAlert"], [data-testid="stAlertContainer"] {{
  border-radius: 24px !important;
  background: {FINE_GRAIN}, linear-gradient(180deg, {_rgba(p['sky'], .38)}, {_rgba(p['sky'], .26)}) !important;
  border: 1px solid rgba(255,255,255,.7);
  color: {p['ink']} !important;
}}
[data-testid="stAlert"] p {{ color: {p['ink']} !important; }}
[data-testid="stJson"], [data-testid="stTable"], [data-testid="stDataFrame"] {{
  background: rgba(255,255,255,.75); border-radius: 20px; padding: .5rem;
}}
[data-testid="stTable"] table {{ background: transparent; }}

.sg-empty {{
  border: 2px dashed {_rgba(p['violet'], .35)}; border-radius: 26px;
  padding: 3.2rem 2rem; text-align: center; color: {p['mist']}; line-height: 1.6;
  background: {_rgba(p['lavender'], .12)};
}}
.sg-verdict {{ margin-top: .2rem !important; }}
[class*="st-key-sg_results"] .stTabs [role="tab"] {{ padding: .45rem 1rem; }}
[class*="st-key-sg_results"] .stTabs [role="tab"] p {{ font-size: .9rem; }}
[class*="st-key-sg_results"] [data-testid="stMetric"] {{ padding: .6rem 1rem; border-radius: 20px; }}
[class*="st-key-sg_results"] [data-testid="stMetricValue"] {{ font-size: 1.35rem; }}

/* grain on inline-tinted glass pieces */
.sg-piece, .sg-stone, .sg-chip {{ position: relative; overflow: hidden; }}
.sg-piece::after, .sg-stone::after, .sg-chip::after {{
  content: ""; position: absolute; inset: 0; border-radius: inherit;
  background: {GRAIN}; pointer-events: none;
}}
.sg-piece {{ position: absolute; }}
.sg-piece svg, .sg-stone span {{ position: relative; z-index: 1; }}

/* ---------- risk ---------- */
.sg-chip {{
  display: inline-block; padding: .25rem .95rem; border-radius: 999px;
  font-weight: 700; font-size: .9rem; color: #fff;
  text-shadow: 0 1px 1px rgba(0,0,0,.25);
  border: 1px solid rgba(255,255,255,.45); vertical-align: middle;
}}
.sg-verdict {{ display: flex; align-items: center; gap: 1.6rem; flex-wrap: wrap; margin: .6rem 0 1.2rem; }}
.sg-stone {{
  min-width: 170px; height: 80px; padding: 0 1.8rem;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,.45);
  display: grid; place-items: center;
  animation: sg-drop .8s cubic-bezier(.2,.9,.25,1.15) both;
}}
.sg-stone span {{
  font-size: 1.7rem; font-weight: 800; color: #fff;
  text-shadow: 0 1px 2px rgba(0,0,0,.25);
}}
.sg-verdict-text h3 {{ margin: 0 0 .25rem 0; }}
.sg-verdict-text p {{ margin: 0; color: {p['mist']}; max-width: 48ch; }}
</style>
"""


_ICONS = {
    "cloud": "<path d='M7 18h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.1 9.5 4.3 4.3 0 0 0 7 18Z'/>",
    "shield": "<path d='M12 3 5 6v5c0 4.4 3 8.3 7 10 4-1.7 7-5.6 7-10V6l-7-3Z'/>",
    "pulse": "<path d='M3 12h4l2-5 4 10 2-5h6'/>",
    "lock": "<rect x='6' y='10' width='12' height='10' rx='2'/><path d='M8.5 10V7.5a3.5 3.5 0 0 1 7 0V10'/>",
    "plus": "<path d='M12 6v12M6 12h12'/>",
    "pencil": "<path d='M4 20h4L19 9l-4-4L4 16v4Z'/>",
}


def _icon(name, color):
    return (f"<svg viewBox='0 0 24 24' fill='none' stroke='{color}' stroke-width='2' "
            f"stroke-linecap='round' stroke-linejoin='round'>{_ICONS[name]}</svg>")


def _piece(color, left, top, w, h, radius, delay, strength=.6, icon=None, icon_color="#17343A"):
    inner = _icon(icon, icon_color) if icon else ""
    return (
        f"<div class='sg-piece' style='left:{left};top:{top};width:{w}px;height:{h}px;"
        f"border-radius:{radius};background:{glass_fill(color, strength)};"
        f"box-shadow:{glass_shadow(color, 1.1)};animation-delay:{delay}s'>{inner}</div>"
    )


def _toolbar(icons, color, left, top, delay):
    svgs = "".join(f"<span class='sg-ico'>{_icon(n, PALETTE['ink'])}</span>" for n in icons)
    return (
        f"<div class='sg-piece sg-toolbar' style='left:{left};top:{top};"
        f"background:{glass_fill(color, .95)};box-shadow:{glass_shadow(color, 1.2)};"
        f"animation-delay:{delay}s'>{svgs}</div>"
    )


def _action(label, icon, color, left, top, delay):
    return (
        f"<div class='sg-piece sg-action' style='left:{left};top:{top};"
        f"background:{glass_fill(color, .95)};box-shadow:{glass_shadow(color, 1.2)};"
        f"animation-delay:{delay}s'><span class='sg-ico'>{_icon(icon, PALETTE['ink'])}</span>"
        f"<b>{label}</b></div>"
    )


def hero_html(title, subtitle):
    p = PALETTE
    pieces = "".join([
        _toolbar(["cloud", "shield", "pulse", "lock"], p["lavender"], "57%", "4%", .0),
        _piece(p["blush"], "87%", "4%", 74, 74, "24px", .08, .95, "plus", p["ink"]),
        _action("Scan", "pencil", p["sky"], "62%", "48%", .16),
        _piece(p["cream"], "78%", "50%", 62, 62, "50%", .24, .95),
        _piece("#F7D3B4", "84.5%", "50%", 62, 62, "50%", .30, .95),
        _piece(p["peach"], "91%", "50%", 62, 62, "50%", .36, .95),
    ])
    return (
        f"<div class='sg-hero'><div class='sg-pieces'>{pieces}</div>"
        f"<h1>{title}</h1><p>{subtitle}</p></div>"
    )


def risk_chip(label):
    color = RISK_GLASS.get(label, "#B9B3C8")
    return (
        f"<span class='sg-chip' style='background:{glass_fill(color, .95)};"
        f"box-shadow:{glass_shadow(color, .5)}'>{label}</span>"
    )


def verdict_html(label, detail):
    color = RISK_GLASS.get(label, "#B9B3C8")
    return (
        "<div class='sg-verdict'>"
        f"<div class='sg-stone' style='background:{glass_fill(color, .95)};box-shadow:{glass_shadow(color, 1.4)}'>"
        f"<span>{label}</span></div>"
        f"<div class='sg-verdict-text'><h3>Predicted risk: {label}</h3><p>{detail}</p></div>"
        "</div>"
    )
