"""
sea_glass.py -- visual theme for the InfraDriftGuard dashboard.

(The module keeps its original name so imports and tests do not change.)
An editorial, report-style look: warm paper background, a serif headline,
plain hairline-bordered panels, ink-black buttons, one deep-teal accent
and muted risk colours. No gradients, no shadows.

Pure presentation: every function here only returns CSS/HTML strings, so
app.py's logic and tests are untouched.
"""

PALETTE = {
    "paper": "#FAF8F3",      # page
    "card": "#FFFFFF",
    "card2": "#FFFFFF",
    "line": "#E4DFD3",       # hairlines
    "ink": "#1B1B1F",
    "mist": "#6A675F",
    "accent": "#0F5C4D",     # deep teal
    "accent2": "#0F5C4D",
    "accent_soft": "rgba(15,92,77,.07)",
    "sky": "#0F5C4D",
    "lavender": "#F1EEE6",
    "seafoam": "#2E7D5B",
    "honey": "#B7791F",
    "bottle": "#C2561B",
    "ruby": "#B3261E",
    "violet": "#6B5B95",
}

RISK_GLASS = {
    "Low": PALETTE["seafoam"],
    "Medium": PALETTE["honey"],
    "High": PALETTE["bottle"],
    "Critical": PALETTE["ruby"],
    "Review": PALETTE["violet"],
    "No drift": "#8C887E",
}


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgba(hex_color, alpha):
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha})"


def css():
    p = PALETTE
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600;8..60,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, .stApp, .stMarkdown, p, li, label, input, textarea, button, [data-baseweb] {{
  font-family: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}
.stApp {{ background: {p['paper']}; color: {p['ink']}; font-size: 14.5px; }}
[data-testid="stHeader"] {{ background: transparent; height: 0; }}
[data-testid="stToolbar"], [data-testid="stDecoration"] {{ display: none; }}
.block-container {{ padding-top: 2rem !important; padding-bottom: 2rem !important; max-width: 1180px; }}
[data-testid="stVerticalBlock"] {{ gap: .8rem; }}

h1, h2, h3, h4 {{ color: {p['ink']} !important; padding: 0 !important; letter-spacing: -0.005em; }}
h2, h3 {{ font-family: 'Source Serif 4', Georgia, serif !important; font-weight: 600 !important; }}
h2 {{ font-size: 1.35rem !important; margin: 0 0 .3rem !important; }}
h3 {{ font-size: 1.1rem !important; }}
p, li, span, label {{ color: {p['ink']}; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {p['mist']} !important; font-size: .82rem !important; }}
a {{ color: {p['accent']} !important; }}
code {{ background: #F1EEE6 !important; color: {p['ink']} !important; border-radius: 3px; font-family: 'IBM Plex Mono', monospace !important; font-size: .84em; }}
pre, [data-testid="stCode"] {{ background: #F6F3EC !important; border: 1px solid {p['line']}; border-radius: 4px; }}
pre code {{ background: transparent !important; }}

[data-testid="stSidebar"] {{ display: none; }}
[data-testid="stSidebarCollapsedControl"] {{ display: none; }}

/* ---------- masthead ---------- */
.sg-hero {{ padding: 1.5rem 0 1.6rem; }}
.sg-kicker {{ font-size: .74rem; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: {p['accent']}; margin-bottom: .6rem; }}
.sg-hero h1 {{ font-family: 'Source Serif 4', Georgia, serif !important; font-size: 4rem !important; font-weight: 700 !important;
  line-height: 1.02; margin: 0 0 .8rem; max-width: 20ch; }}
.sg-hero p {{ font-size: 1.05rem; color: {p['mist']}; margin: 0; max-width: 62ch; line-height: 1.55; }}
.sg-stats {{ display: flex; gap: 2.4rem; flex-wrap: wrap; margin-top: 1.3rem; }}
.sg-stat b {{ display: block; font-family: 'Source Serif 4', Georgia, serif; font-size: 1.7rem; font-weight: 600; line-height: 1; }}
.sg-stat span {{ font-size: .76rem; color: {p['mist']}; }}

/* ---------- explainer ---------- */
.sg-section {{ margin: 1.6rem 0 .5rem; font-size: .74rem; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: {p['mist']}; }}
.sg-explain {{ display: grid; grid-template-columns: 1.05fr 1fr; gap: 2.2rem; align-items: start; }}
@media (max-width: 900px) {{ .sg-explain {{ grid-template-columns: 1fr; }} }}
.sg-why {{ font-size: 1.02rem; line-height: 1.65; margin: 0 0 1rem; }}
.sg-list {{ margin: 0; padding: 0; list-style: none; counter-reset: s; }}
.sg-list li {{ counter-increment: s; display: grid; grid-template-columns: 1.6rem 1fr; padding: .55rem 0; border-top: 1px solid {p['line']}; line-height: 1.5; }}
.sg-list li::before {{ content: counter(s) "."; font-family: 'IBM Plex Mono', monospace; color: {p['accent']}; font-weight: 500; }}
.sg-list b {{ font-weight: 600; }}
.sg-list span {{ color: {p['mist']}; }}
.sg-diff {{ border: 1px solid {p['line']}; border-radius: 4px; background: #fff; overflow: hidden; }}
.sg-diff-head {{ padding: .5rem .8rem; border-bottom: 1px solid {p['line']}; font-size: .74rem; letter-spacing: .08em; text-transform: uppercase; color: {p['mist']}; font-weight: 600; }}
.sg-diff pre {{ margin: 0; border: 0 !important; border-radius: 0; background: #fff !important; padding: .6rem 0; font-family: 'IBM Plex Mono', monospace; font-size: .8rem; line-height: 1.7; }}
.sg-diff .ln {{ display: block; padding: 0 .9rem; white-space: pre; }}
.sg-diff .del {{ background: #FBE9E7; color: #8C1D18; }}
.sg-diff .add {{ background: #E6F2EA; color: #1E5B3A; }}
.sg-diff-out {{ border-top: 1px solid {p['line']}; padding: .7rem .8rem; display: grid; gap: .35rem; font-size: .86rem; }}
.sg-diff-out div {{ display: grid; grid-template-columns: 6.5rem 1fr; }}
.sg-diff-out em {{ font-style: normal; color: {p['mist']}; }}

/* ---------- panels ---------- */
[class*="st-key-sg_"] {{
  background: {p['card']} !important; border: 1px solid {p['line']} !important;
  border-radius: 6px !important; box-shadow: none; padding: 1.1rem 1.3rem !important;
}}
[data-testid="stMetric"] {{ background: transparent; border: 0; border-top: 1px solid {p['line']}; border-radius: 0; padding: .5rem 0 0; }}
[data-testid="stMetricLabel"] p {{ font-size: .7rem; color: {p['mist']}; text-transform: uppercase; letter-spacing: .08em; }}
[data-testid="stMetricValue"] {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 1.4rem; font-weight: 600; }}

/* ---------- tabs ---------- */
.stTabs [role="tablist"] {{ gap: 1.4rem; border-bottom: 1px solid {p['line']} !important; padding: 0; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: {p['ink']} !important; height: 2px; }}
.stTabs [data-baseweb="tab-border"] {{ display: none; }}
.stTabs [role="tab"] {{ background: transparent; padding: .55rem 0; height: auto; }}
.stTabs [role="tab"] p {{ font-weight: 500; color: {p['mist']}; font-size: .92rem; }}
.stTabs [role="tab"][aria-selected="true"] p {{ color: {p['ink']}; font-weight: 600; }}
.stTabs [role="tab"]:hover p {{ color: {p['ink']}; }}

/* ---------- buttons ---------- */
.stButton > button, [data-testid="stFormSubmitButton"] > button {{
  border-radius: 4px !important; border: 1px solid {p['ink']} !important;
  background: transparent !important; color: {p['ink']} !important;
  font-weight: 500; font-size: .86rem; padding: .42rem 1rem !important; min-height: 0; box-shadow: none;
}}
.stButton > button:hover {{ background: {p['ink']} !important; color: #fff !important; }}
.stButton > button:hover p {{ color: #fff !important; }}
.stButton > button[kind="primary"], [data-testid="stBaseButton-primary"], [data-testid="stFormSubmitButton"] > button {{
  background: {p['ink']} !important; color: #fff !important; padding: .6rem 1.2rem !important; font-size: .92rem;
}}
.stButton > button[kind="primary"] p, [data-testid="stFormSubmitButton"] > button p {{ color: #fff !important; font-weight: 500; }}
.stButton > button[kind="primary"]:hover {{ background: {p['accent']} !important; border-color: {p['accent']} !important; }}
button:focus-visible {{ outline: 2px solid {p['accent']} !important; outline-offset: 2px; }}

/* ---------- inputs ---------- */
.stTextArea textarea, [data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{
  background: #fff !important; border-radius: 4px !important; border-color: {p['line']} !important; color: {p['ink']} !important;
}}
.stTextArea textarea {{ font-family: 'IBM Plex Mono', ui-monospace, monospace !important; font-size: .78rem !important; line-height: 1.5; }}
[data-baseweb="input"] input, [data-baseweb="select"] * {{ color: {p['ink']} !important; }}
[data-testid="stWidgetLabel"] p {{ font-size: .78rem; font-weight: 500; color: {p['mist']}; }}
[data-baseweb="popover"] ul {{ background: #fff !important; }}
[data-baseweb="popover"] li:hover {{ background: {p['accent_soft']} !important; }}
[role="radiogroup"] label p {{ font-size: .86rem; }}

/* ---------- notes, tables ---------- */
[data-testid="stAlert"], [data-testid="stAlertContainer"] {{
  border-radius: 4px !important; background: #F1EEE6 !important; border: 1px solid {p['line']}; color: {p['ink']} !important; padding: .5rem .8rem;
}}
[data-testid="stAlert"] p {{ color: {p['ink']} !important; font-size: .86rem; }}
[data-testid="stDataFrame"], [data-testid="stJson"], [data-testid="stTable"] {{ border: 1px solid {p['line']}; border-radius: 4px; }}
.sg-empty {{ border: 1px dashed #CFC8B8; border-radius: 4px; padding: 2rem 1.5rem; text-align: center; color: {p['mist']}; line-height: 1.6; }}
.sg-empty b {{ color: {p['ink']}; }}

/* ---------- sections (Momus-style long page) ---------- */
.sg-links {{ display: flex; gap: .7rem; margin-top: 1.4rem; flex-wrap: wrap; }}
.sg-btn {{ display: inline-block; padding: .55rem 1.1rem; border-radius: 4px; font-weight: 500; font-size: .9rem;
  text-decoration: none !important; border: 1px solid {p['ink']}; color: {p['ink']} !important; }}
.sg-btn.primary {{ background: {p['ink']}; color: #fff !important; }}
.sg-sec {{ margin: 3.2rem 0 1rem; scroll-margin-top: 1rem; }}
.sg-eyebrow {{ font-size: .74rem; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: {p['accent']}; margin-bottom: .45rem; }}
.sg-sec h2 {{ font-family: 'Source Serif 4', Georgia, serif !important; font-size: 2rem !important; font-weight: 700 !important; margin: 0 !important; line-height: 1.15; }}
.sg-sec p {{ color: {p['mist']}; font-size: 1rem; line-height: 1.6; margin: .55rem 0 0; max-width: 72ch; }}
.sg-steps2 {{ display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 1.4rem; border-top: 1px solid {p['ink']}; padding-top: 1rem; }}
@media (max-width: 900px) {{ .sg-steps2, .sg-callouts, .sg-cards {{ grid-template-columns: 1fr 1fr !important; }} }}
.sg-steps2 i {{ font-style: normal; font-family: 'IBM Plex Mono', monospace; color: {p['accent']}; font-size: .9rem; }}
.sg-steps2 h4 {{ font-family: 'Source Serif 4', Georgia, serif !important; font-size: 1.15rem !important; margin: .3rem 0 .35rem !important; }}
.sg-steps2 p {{ margin: 0; color: {p['mist']}; font-size: .9rem; line-height: 1.55; }}
.sg-table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
.sg-table th {{ text-align: left; font-size: .72rem; letter-spacing: .1em; text-transform: uppercase; color: {p['mist']};
  border-bottom: 1px solid {p['ink']}; padding: .5rem .6rem .5rem 0; font-weight: 600; }}
.sg-table td {{ border-bottom: 1px solid {p['line']}; padding: .75rem .6rem .75rem 0; vertical-align: top; line-height: 1.5; }}
.sg-table td:first-child {{ font-weight: 600; white-space: nowrap; }}
.sg-table td:last-child {{ font-family: 'IBM Plex Mono', monospace; }}
.sg-callouts {{ display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 1.4rem; border-top: 1px solid {p['ink']}; padding-top: 1rem; }}
.sg-callouts b {{ display: block; font-family: 'Source Serif 4', Georgia, serif; font-size: 2.1rem; font-weight: 700; line-height: 1.05; }}
.sg-callouts span {{ display: block; margin-top: .4rem; color: {p['mist']}; font-size: .88rem; line-height: 1.45; }}
.sg-cards {{ display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 1rem; }}
.sg-card {{ background: #fff; border: 1px solid {p['line']}; border-radius: 6px; padding: 1rem 1.1rem; }}
.sg-card small {{ font-size: .7rem; letter-spacing: .1em; text-transform: uppercase; color: {p['ruby']}; font-weight: 600; }}
.sg-card h4 {{ font-family: 'Source Serif 4', Georgia, serif !important; font-size: 1.15rem !important; margin: .35rem 0 .3rem !important; }}
.sg-card p {{ margin: 0; color: {p['mist']}; font-size: .9rem; line-height: 1.5; }}
.sg-foot {{ margin-top: 3.5rem; padding: 1.4rem 0 .5rem; border-top: 1px solid {p['ink']}; color: {p['mist']}; font-size: .86rem; line-height: 1.6;
  display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }}
.sg-foot a {{ color: {p['ink']} !important; }}
[data-testid="stExpander"] {{ border: 1px solid {p['line']}; border-radius: 6px; background: #fff; }}
[data-testid="stVideo"], video {{ border-radius: 6px; border: 1px solid {p['line']}; }}

/* ---------- risk ---------- */
.sg-chip {{ display: inline-block; padding: .05rem .55rem; border-radius: 3px; font-weight: 600; font-size: .76rem; color: #fff; vertical-align: middle; }}
.sg-verdict {{ display: flex; align-items: baseline; gap: 1.2rem; flex-wrap: wrap; margin: .1rem 0 .6rem;
  padding: .2rem 0 .9rem .9rem; border-bottom: 1px solid {p['line']}; border-left: 5px solid var(--rc); }}
.sg-stone {{ min-width: 0; padding: 0; background: none; text-align: left; }}
.sg-stone span {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 2rem; font-weight: 700; color: var(--rc); line-height: 1.1; }}
.sg-verdict-text h3 {{ margin: 0 0 .1rem 0; font-family: 'IBM Plex Sans', sans-serif !important; font-size: .9rem !important; font-weight: 600 !important; }}
.sg-verdict-text p {{ margin: 0; color: {p['mist']}; font-size: .86rem; max-width: 70ch; }}
[class*="st-key-sg_results"] h2 {{ margin-bottom: .6rem !important; }}
</style>
"""


def hero_html(eyebrow, title, tagline, stats=(), links=()):
    cells = "".join(f"<div class='sg-stat'><b>{n}</b><span>{label}</span></div>" for n, label in stats)
    btns = "".join(
        f"<a class='sg-btn{' primary' if i == 0 else ''}' href='{url}' target='{'_self' if url.startswith('#') else '_blank'}'>{text}</a>"
        for i, (text, url) in enumerate(links))
    return (
        f"<div class='sg-hero'><div class='sg-kicker'>{eyebrow}</div>"
        f"<h1>{title}</h1><p>{tagline}</p>"
        f"<div class='sg-stats'>{cells}</div><div class='sg-links'>{btns}</div></div>"
    )


def section_html(eyebrow, title, sub=None, anchor=None):
    aid = f" id='{anchor}'" if anchor else ""
    p = f"<p>{sub}</p>" if sub else ""
    return f"<div class='sg-sec'{aid}><div class='sg-eyebrow'>{eyebrow}</div><h2>{title}</h2>{p}</div>"


def steps_html(steps):
    return "<div class='sg-steps2'>" + "".join(
        f"<div><i>{i + 1:02d}</i><h4>{t}</h4><p>{d}</p></div>" for i, (t, d) in enumerate(steps)) + "</div>"


def table_html(head, rows):
    th = "".join(f"<th>{h}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table class='sg-table'><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


def callouts_html(items):
    return "<div class='sg-callouts'>" + "".join(f"<div><b>{n}</b><span>{l}</span></div>" for n, l in items) + "</div>"


def cards_html(cards):
    return "<div class='sg-cards'>" + "".join(
        f"<div class='sg-card'><small>{c}</small><h4>{t}</h4><p>{d}</p></div>" for c, t, d in cards) + "</div>"


def footer_html(text, links=()):
    a = " · ".join(f"<a href='{u}' target='_blank'>{t}</a>" for t, u in links)
    return f"<div class='sg-foot'><div style='max-width:70ch'>{text}</div><div>{a}</div></div>"


def risk_chip(label):
    color = RISK_GLASS.get(label, "#8C887E")
    return f"<span class='sg-chip' style='background:{color}'>{label}</span>"


def verdict_html(label, detail):
    color = RISK_GLASS.get(label, "#8C887E")
    return (
        f"<div class='sg-verdict' style='--rc:{color}'>"
        f"<div class='sg-stone'><span>{label}</span></div>"
        f"<div class='sg-verdict-text'><h3>Predicted risk: {label}</h3><p>{detail}</p></div>"
        "</div>"
    )
