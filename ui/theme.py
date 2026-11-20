"""Visual design system for the consul Streamlit workspace.

The direction follows the TerraTrace mission console: warm near-black panels,
one signal-orange accent, a heavy display face (Dela Gothic One) for headlines,
Archivo for body copy and Geist Mono for labels and numbers. Hairline borders
and 4px corners instead of shadows. Fonts are bundled in ``ui/assets/fonts`` and
inlined as data URIs, so the app stays fully offline. Tokens are centralised
here so every page shares one scale for colour, type, spacing and state.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from string import Template

import streamlit as st

FONTS_DIR = Path(__file__).parent / "assets" / "fonts"

DARK = {
    "bg": "#0F0806",
    "surface": "#170D0A",
    "surface_alt": "#1E120D",
    "text": "#F7EDE6",
    "muted": "#A38B81",
    "border": "#2E1C16",
    "brand": "#FF5A1F",
    "brand_soft": "#2A140C",
    "on_brand": "#1A0700",
    "accent": "#FF5A1F",
    "accent_soft": "rgba(255,90,31,0.10)",
    "success": "#5DBF7E",
    "success_soft": "#132219",
    "warn": "#E2B54A",
    "warn_soft": "#261E0E",
    "danger": "#E2584E",
    "danger_soft": "#2A1210",
    "rule": "#2E1C16",
    "sidebar": "#0B0605",
    "sidebar_alt": "#1F120D",
    "sidebar_text": "#F7EDE6",
    "sidebar_muted": "#A38B81",
    "sidebar_active": "#26140C",
    "hero": "#0B0605",
    "hero_text": "#F7EDE6",
    "hero_muted": "#CDB8AE",
    "card": "#FFF8F3",
    "card_text": "#1A0B06",
}

# Daylight variant: the TerraTrace badge card (warm paper, ink, same orange).
LIGHT = {
    "bg": "#FFF8F3",
    "surface": "#FFFFFF",
    "surface_alt": "#F6EAE2",
    "text": "#1A0B06",
    "muted": "#7A5C50",
    "border": "#E3D2C8",
    "brand": "#D9480F",
    "brand_soft": "#FBE3D6",
    "on_brand": "#FFF8F3",
    "accent": "#D9480F",
    "accent_soft": "rgba(255,90,31,0.10)",
    "success": "#2E7D4F",
    "success_soft": "#DFF0E5",
    "warn": "#8A5A10",
    "warn_soft": "#F7EBCF",
    "danger": "#B3322A",
    "danger_soft": "#F8DEDB",
    "rule": "#E3D2C8",
    "sidebar": "#0B0605",
    "sidebar_alt": "#1F120D",
    "sidebar_text": "#F7EDE6",
    "sidebar_muted": "#A38B81",
    "sidebar_active": "#26140C",
    "hero": "#0B0605",
    "hero_text": "#F7EDE6",
    "hero_muted": "#CDB8AE",
    "card": "#FFF8F3",
    "card_text": "#1A0B06",
}

FONT_DISPLAY = "'Dela Gothic One', 'Archivo', sans-serif"
FONT_SANS = "'Archivo', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_MONO = "'Geist Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"


@lru_cache(maxsize=1)
def font_css() -> str:
    """@font-face rules with the bundled fonts inlined as data URIs."""
    rules = []
    for family, file in (
        ("Dela Gothic One", "DelaGothicOne-latin.woff2"),
        ("Archivo", "Archivo-latin-wght.woff2"),
        ("Geist Mono", "GeistMono-Variable.woff2"),
    ):
        path = FONTS_DIR / file
        if not path.exists():
            continue
        data = base64.b64encode(path.read_bytes()).decode()
        rules.append(
            f"@font-face{{font-family:'{family}';src:url(data:font/woff2;base64,{data}) "
            "format('woff2');font-weight:100 900;font-display:swap;}"
        )
    return "\n".join(rules)


_CSS = Template(
    """
    <style>
    $fonts
    :root {
        --consul-bg: $bg;
        --consul-surface: $surface;
        --consul-surface-alt: $surface_alt;
        --consul-text: $text;
        --consul-muted: $muted;
        --consul-border: $border;
        --consul-brand: $brand;
        --consul-brand-soft: $brand_soft;
        --consul-on-brand: $on_brand;
        --consul-accent: $accent;
        --consul-accent-soft: $accent_soft;
        --consul-success: $success;
        --consul-success-soft: $success_soft;
        --consul-warn: $warn;
        --consul-warn-soft: $warn_soft;
        --consul-danger: $danger;
        --consul-danger-soft: $danger_soft;
        --consul-rule: $rule;
        --consul-sidebar: $sidebar;
        --consul-sidebar-alt: $sidebar_alt;
        --consul-sidebar-text: $sidebar_text;
        --consul-sidebar-muted: $sidebar_muted;
        --consul-sidebar-active: $sidebar_active;
        --consul-hero: $hero;
        --consul-hero-text: $hero_text;
        --consul-hero-muted: $hero_muted;
        --consul-signal: #FF5A1F;
        --consul-display: $font_display;
        --consul-sans: $font_sans;
        --consul-mono: $font_mono;
        --consul-radius: 6px;
        --consul-radius-sm: 4px;
        --consul-ease: cubic-bezier(0.16, 1, 0.3, 1);
    }

    html, body, [class*="css"], .stApp, [data-testid="stAppViewContainer"] {
        font-family: var(--consul-sans);
    }
    .stApp {
        background: var(--consul-bg);
        color: var(--consul-text);
    }
    .stApp::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 0;
        background: radial-gradient(900px 520px at 85% -10%, $accent_soft, transparent 60%);
    }
    header[data-testid="stHeader"] { background: transparent !important; }
    [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"],
    [data-testid="stMainMenu"], [data-testid="stDecoration"] { display: none !important; }
    .block-container {
        max-width: 1320px;
        padding-top: 2.2rem;
        padding-bottom: 4.5rem;
    }
    h1, h2, h3 {
        font-family: var(--consul-display);
        color: var(--consul-text);
        letter-spacing: -.03em;
        font-weight: 400;
    }
    h4 {
        font-family: var(--consul-sans);
        color: var(--consul-text);
        font-weight: 650;
        letter-spacing: -.01em;
    }
    h5 {
        font-family: var(--consul-mono);
        color: var(--consul-accent);
        letter-spacing: .04em;
        font-size: .78rem !important;
        font-weight: 500 !important;
        margin-top: 1.7rem !important;
        padding-bottom: .4rem;
        border-bottom: 1px solid var(--consul-border);
    }
    p, span, label, li {
        color: var(--consul-text);
    }
    small, .consul-muted {
        color: var(--consul-muted) !important;
    }
    a { color: var(--consul-accent); text-underline-offset: 3px; }
    hr { border-color: var(--consul-border); }
    code, pre, kbd {
        font-family: var(--consul-mono) !important;
        font-size: .8rem !important;
    }
    [data-testid="stIconMaterial"], .material-symbols-rounded {
        font-family: "Material Symbols Rounded" !important;
    }

    /* ---- Sidebar ------------------------------------------------------- */
    [data-testid="stSidebar"] {
        background: var(--consul-sidebar);
        border-right: 1px solid #2E1C16;
    }
    [data-testid="stSidebar"] .block-container {
        padding: 1.3rem 1rem 2rem 1rem;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] li {
        color: var(--consul-sidebar-text);
    }
    [data-testid="stSidebar"] small,
    [data-testid="stSidebar"] .consul-muted,
    [data-testid="stSidebar"] .consul-side-muted {
        color: var(--consul-sidebar-muted) !important;
    }
    [data-testid="stSidebar"] .stButton > button {
        position: relative;
        width: 100%;
        justify-content: flex-start;
        text-align: left;
        min-height: 2.3rem;
        padding: .5rem .75rem;
        border: 1px solid transparent;
        border-radius: var(--consul-radius-sm);
        background: transparent;
        color: var(--consul-sidebar-muted);
        font-family: var(--consul-sans);
        font-size: .9rem;
        font-weight: 500;
        box-shadow: none;
        transition: background .2s, color .2s;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: var(--consul-sidebar-alt);
        color: var(--consul-sidebar-text);
        border-color: transparent;
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"] {
        background: var(--consul-sidebar-active);
        color: var(--consul-sidebar-text);
        border-color: transparent;
        font-weight: 650;
        box-shadow: inset 3px 0 0 var(--consul-signal);
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
        background: var(--consul-sidebar-active);
        color: var(--consul-sidebar-text);
        transform: none;
    }
    [data-testid="stSidebar"] .stButton > button > div {
        width: 100%;
        justify-content: flex-start;
    }
    [data-testid="stSidebar"] .stButton > button p {
        text-align: left;
        color: inherit !important;
    }
    [data-testid="stSidebar"] [data-testid="stToggle"] label span {
        color: var(--consul-sidebar-muted) !important;
    }
    [data-testid="stSidebar"] .stAlert {
        background: var(--consul-sidebar-alt);
        border: 1px solid #2E1C16;
    }

    .consul-brandmark {
        display: flex;
        align-items: center;
        gap: .7rem;
        margin: .1rem 0 1.4rem 0;
    }
    .consul-brandmark .mark {
        width: 38px;
        height: 38px;
        border-radius: var(--consul-radius-sm);
        background: var(--consul-signal);
        color: #1A0700;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: var(--consul-display);
        font-size: 1.2rem;
        line-height: 1;
    }
    .consul-brandmark .name {
        color: var(--consul-sidebar-text);
        font-family: var(--consul-display);
        font-size: 1.55rem;
        letter-spacing: -.02em;
        line-height: 1;
    }
    .consul-brandmark .name span { color: var(--consul-signal); }
    .consul-brandmark .tag {
        color: var(--consul-sidebar-muted);
        font-family: var(--consul-mono);
        font-size: .68rem;
        letter-spacing: .04em;
        margin-top: .3rem;
    }
    .consul-nav-label {
        color: var(--consul-signal);
        font-family: var(--consul-mono);
        font-size: .68rem;
        letter-spacing: .06em;
        text-transform: uppercase;
        margin: 1.15rem 0 .35rem .75rem;
    }
    .consul-side-profile {
        display: flex;
        gap: .65rem;
        align-items: center;
        border-top: 1px solid #2E1C16;
        padding: .9rem .2rem .2rem .2rem;
        margin-top: .6rem;
    }
    .consul-avatar {
        width: 32px;
        height: 32px;
        flex: 0 0 32px;
        border-radius: var(--consul-radius-sm);
        border: 1px solid #2E1C16;
        background: var(--consul-sidebar-alt);
        color: var(--consul-signal);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: var(--consul-mono);
        font-size: .72rem;
    }
    .consul-side-name {
        color: var(--consul-sidebar-text);
        font-size: .86rem;
        font-weight: 600;
        line-height: 1.2;
    }
    .consul-side-muted {
        color: var(--consul-sidebar-muted);
        font-family: var(--consul-mono);
        font-size: .64rem;
        line-height: 1.5;
    }
    [data-testid="stSidebar"] .consul-divider {
        background: #2E1C16;
        margin: 1rem 0;
    }
    .consul-side-footer {
        color: #6E5A52;
        font-family: var(--consul-mono);
        font-size: .64rem;
        line-height: 1.5;
        border-top: 1px solid #2E1C16;
        margin-top: 1rem;
        padding-top: .8rem;
    }

    /* ---- Page header --------------------------------------------------- */
    .consul-page-head {
        border-bottom: 1px solid var(--consul-rule);
        padding-bottom: 1.2rem;
        margin-bottom: 1.6rem;
    }
    .consul-eyebrow {
        color: var(--consul-accent);
        font-family: var(--consul-mono);
        font-size: .8rem;
        font-weight: 500;
        letter-spacing: .04em;
        margin-bottom: .35rem;
    }
    .consul-page-title {
        font-family: var(--consul-display);
        font-size: clamp(2.2rem, 3.8vw, 3.2rem);
        letter-spacing: -.035em;
        line-height: 1.04;
        margin: 0 0 .55rem 0;
        color: var(--consul-text);
    }
    .consul-page-sub {
        color: var(--consul-muted);
        font-size: 1.05rem;
        line-height: 1.5;
        max-width: 62ch;
        margin: 0;
    }
    .consul-section-intro {
        color: var(--consul-muted);
        font-size: .92rem;
        margin: -.2rem 0 .8rem 0;
    }

    /* ---- Cards / hero -------------------------------------------------- */
    .consul-card {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 1rem 1.15rem;
        transition: background .2s, border-color .2s;
    }
    .consul-card:hover { border-color: color-mix(in srgb, var(--consul-accent) 35%, var(--consul-border)); }
    .consul-card + .consul-card { margin-top: .75rem; }

    /* Colour-block opening: dark panel, diagonal orange slab, giant headline. */
    .consul-hero {
        position: relative;
        overflow: hidden;
        isolation: isolate;
        background: var(--consul-hero);
        color: var(--consul-hero-text);
        border-radius: 8px;
        border: 1px solid #2E1C16;
        padding: 2.6rem 44% 2.4rem 2.4rem;
        min-height: 250px;
    }
    .consul-hero::before {
        content: "";
        position: absolute;
        inset: 0;
        z-index: -1;
        background: var(--consul-signal);
        clip-path: polygon(70% 0, 100% 0, 100% 100%, 56% 100%);
    }
    .consul-hero::after {
        content: "C";
        position: absolute;
        right: 6%;
        top: 50%;
        transform: translateY(-50%) rotate(-7deg);
        z-index: -1;
        font-family: var(--consul-display);
        font-size: 15rem;
        line-height: 1;
        color: #1A0700;
        opacity: .9;
    }
    .consul-hero h1, .consul-hero p, .consul-hero span { color: var(--consul-hero-text) !important; }
    .consul-hero h1 {
        font-family: var(--consul-display);
        font-size: clamp(2.2rem, 4.4vw, 3.6rem) !important;
        letter-spacing: -.045em;
        line-height: .98;
    }
    .consul-hero p { color: var(--consul-hero-muted) !important; opacity: 1 !important; }
    .consul-hero .consul-eyebrow { color: var(--consul-signal) !important; }
    .consul-hero .consul-hero-note {
        display: inline-block;
        color: #A38B81 !important;
        font-family: var(--consul-mono);
        font-size: .76rem;
        border: 1px solid #2E1C16;
        border-radius: var(--consul-radius-sm);
        padding: .45rem .7rem;
        margin-top: 1.3rem;
        background: rgba(11,6,5,.6);
    }

    /* ---- Metrics / pipeline -------------------------------------------- */
    [data-testid="stMetric"] {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 1rem 1.1rem .9rem 1.1rem;
    }
    [data-testid="stMetricLabel"] p {
        color: var(--consul-muted);
        font-family: var(--consul-sans);
        font-size: .82rem !important;
    }
    [data-testid="stMetricValue"] {
        color: var(--consul-text);
        font-family: var(--consul-mono);
        font-weight: 500;
        letter-spacing: -.02em;
        font-variant-numeric: tabular-nums;
    }
    [data-testid="stColumn"]:first-child [data-testid="stMetricValue"] { color: var(--consul-accent); }
    .consul-pipeline {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 1.1rem 1.25rem 1.2rem 1.25rem;
        margin-top: .9rem;
    }
    .consul-pipeline-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 1rem;
        margin-bottom: .8rem;
    }
    .consul-pipeline-head b {
        font-family: var(--consul-display);
        font-size: 1.15rem;
        font-weight: 400;
        letter-spacing: -.02em;
    }
    .consul-pipeline-head span {
        color: var(--consul-accent);
        font-family: var(--consul-mono);
        font-size: .72rem;
    }
    .consul-pipeline-row {
        display: grid;
        grid-template-columns: 7.2rem 1fr 2.4rem;
        align-items: center;
        gap: .8rem;
        margin: .42rem 0;
    }
    .consul-pipeline-label {
        color: var(--consul-muted);
        font-size: .82rem;
    }
    .consul-pipeline-track {
        height: 4px;
        border-radius: 2px;
        background: var(--consul-surface-alt);
        overflow: hidden;
    }
    .consul-pipeline-fill {
        height: 100%;
        border-radius: 2px;
        background: var(--consul-accent);
        transform-origin: left;
    }
    .consul-pipeline-value {
        color: var(--consul-text);
        font-family: var(--consul-mono);
        font-size: .86rem;
        text-align: right;
        font-variant-numeric: tabular-nums;
    }

    /* ---- Badges / flags ------------------------------------------------ */
    .consul-badge {
        display: inline-flex;
        align-items: center;
        gap: .3rem;
        padding: .2rem .55rem;
        border-radius: var(--consul-radius-sm);
        font-family: var(--consul-mono);
        font-size: .7rem;
        font-weight: 500;
        border: 1px solid transparent;
        white-space: nowrap;
    }
    .consul-badge.neutral {
        background: var(--consul-surface-alt);
        color: var(--consul-muted);
        border-color: var(--consul-border);
    }
    .consul-badge.brand { background: var(--consul-brand-soft); color: var(--consul-brand); }
    .consul-badge.success { background: var(--consul-success-soft); color: var(--consul-success); }
    .consul-badge.warn { background: var(--consul-warn-soft); color: var(--consul-warn); }
    .consul-badge.danger { background: var(--consul-danger-soft); color: var(--consul-danger); }
    .consul-flag {
        border-left: 2px solid var(--consul-warn);
        background: var(--consul-warn-soft);
        padding: .55rem .75rem;
        border-radius: 0 var(--consul-radius-sm) var(--consul-radius-sm) 0;
        font-size: .88rem;
        margin: .35rem 0;
    }
    .consul-flag.error { border-left-color: var(--consul-danger); background: var(--consul-danger-soft); }
    .consul-flag.ok { border-left-color: var(--consul-success); background: var(--consul-success-soft); }

    /* ---- Jobs ---------------------------------------------------------- */
    .consul-job-title {
        font-family: var(--consul-sans);
        font-weight: 650;
        font-size: 1.12rem;
        line-height: 1.25;
        margin: 0;
        letter-spacing: -.01em;
    }
    .consul-job-meta {
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: .74rem;
        margin-top: .3rem;
        line-height: 1.55;
    }
    .consul-score {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-width: 64px;
        padding: .4rem .55rem;
        border-radius: var(--consul-radius-sm);
        background: var(--consul-surface-alt);
        border: 1px solid var(--consul-border);
    }
    .consul-score b {
        font-family: var(--consul-mono);
        font-weight: 500;
        font-size: 1.4rem;
        line-height: 1.05;
        color: var(--consul-accent);
        font-variant-numeric: tabular-nums;
    }
    .consul-score span {
        font-family: var(--consul-mono);
        font-size: .62rem;
        color: var(--consul-muted);
    }

    /* ---- Buttons / inputs ---------------------------------------------- */
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
        border-radius: var(--consul-radius-sm);
        border: 1px solid var(--consul-border);
        background: var(--consul-surface);
        color: var(--consul-text);
        font-family: var(--consul-sans);
        font-size: .9rem;
        font-weight: 600;
        min-height: 2.5rem;
        transition: transform .15s var(--consul-ease), background .2s, border-color .2s, color .2s;
        box-shadow: none;
    }
    .stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
        border-color: var(--consul-accent);
        color: var(--consul-accent);
        background: var(--consul-surface);
    }
    .stButton > button:active, .stDownloadButton > button:active,
    .stFormSubmitButton > button:active { transform: scale(.98); }
    .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
        background: var(--consul-signal);
        border-color: var(--consul-signal);
        color: #1A0700;
        font-weight: 700;
    }
    .stButton > button[kind="primary"] p, .stFormSubmitButton > button[kind="primary"] p { color: #1A0700; }
    .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
        background: #FF7238;
        border-color: #FF7238;
        color: #1A0700;
        transform: translateY(-1px);
    }
    .stButton > button:focus-visible,
    .stFormSubmitButton > button:focus-visible,
    .stDownloadButton > button:focus-visible,
    a:focus-visible, input:focus-visible, textarea:focus-visible {
        outline: 2px solid var(--consul-signal);
        outline-offset: 2px;
        box-shadow: none;
    }
    [data-testid="stWidgetLabel"] label,
    [data-testid="stWidgetLabel"] p {
        color: var(--consul-muted) !important;
        font-family: var(--consul-sans);
        font-size: .86rem !important;
    }
    [data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
    [data-baseweb="select"] > div {
        background: var(--consul-surface) !important;
        border-color: var(--consul-border) !important;
        color: var(--consul-text) !important;
        border-radius: var(--consul-radius-sm) !important;
    }
    [data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within,
    [data-baseweb="select"] > div:focus-within {
        border-color: var(--consul-accent) !important;
        box-shadow: 0 0 0 1px var(--consul-accent) !important;
    }
    [data-testid="stSliderThumbValue"], [data-testid="stSliderTickBarMin"],
    [data-testid="stSliderTickBarMax"] { font-family: var(--consul-mono) !important; }

    /* ---- Tabs / expanders / tables ------------------------------------- */
    .stTabs [data-baseweb="tab-list"] {
        gap: 1.4rem;
        border-bottom: 1px solid var(--consul-border);
    }
    .stTabs [data-baseweb="tab"] {
        font-family: var(--consul-mono);
        font-size: .78rem;
        color: var(--consul-muted);
        padding-left: 0;
        padding-right: 0;
    }
    .stTabs [aria-selected="true"] { color: var(--consul-text) !important; }
    .stTabs [data-baseweb="tab-highlight"] { background-color: var(--consul-accent); height: 2px; }

    [data-testid="stExpander"] {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border) !important;
        border-radius: var(--consul-radius-sm) !important;
        box-shadow: none;
        margin-bottom: .65rem;
    }
    [data-testid="stExpander"] summary {
        font-family: var(--consul-sans);
        font-size: .92rem;
        font-weight: 600;
        color: var(--consul-text);
    }
    [data-testid="stDataFrame"] {
        border-radius: var(--consul-radius);
        overflow: hidden;
        border: 1px solid var(--consul-border);
    }
    [data-testid="stDataFrame"] * { font-family: var(--consul-sans); }

    /* ---- Feedback ------------------------------------------------------ */
    .stAlert, [data-testid="stAlert"] {
        border-radius: var(--consul-radius-sm);
    }
    .stProgress > div > div > div > div { background-color: var(--consul-accent); }
    .stSpinner > div { border-top-color: var(--consul-accent) !important; }

    /* ---- Empty state --------------------------------------------------- */
    .consul-empty {
        background: var(--consul-surface);
        border: 1px dashed var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 2.7rem 1.5rem;
        text-align: center;
    }
    .consul-empty .consul-empty-mark {
        width: 46px;
        height: 46px;
        border-radius: var(--consul-radius-sm);
        margin: 0 auto .9rem auto;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--consul-brand-soft);
        color: var(--consul-accent);
        font-family: var(--consul-mono);
        font-size: .85rem;
    }
    .consul-empty h3 {
        margin: 0 0 .45rem 0;
        font-family: var(--consul-display);
        font-size: 1.5rem;
    }
    .consul-empty p {
        color: var(--consul-muted);
        margin: 0 auto;
        max-width: 52ch;
        font-size: .95rem;
        line-height: 1.55;
    }

    /* ---- Key/value and divider ----------------------------------------- */
    .consul-kv {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        padding: .45rem 0;
        border-bottom: 1px solid var(--consul-border);
        font-size: .9rem;
    }
    .consul-kv:last-child { border-bottom: 0; }
    .consul-kv span:first-child {
        color: var(--consul-muted);
        padding-top: .05rem;
    }
    .consul-kv span:last-child {
        font-family: var(--consul-mono);
        font-weight: 500;
        text-align: right;
    }
    .consul-divider {
        height: 1px;
        background: var(--consul-border);
        margin: 1.6rem 0;
    }

    /* ---- CV preview (paper card, like the TerraTrace mission badge) ---- */
    .consul-cv {
        background: $card;
        color: $card_text;
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 2.2rem 2.4rem;
        max-width: 820px;
        font-size: .88rem;
        line-height: 1.45;
    }
    .consul-cv, .consul-cv p, .consul-cv span, .consul-cv li, .consul-cv div, .consul-cv b {
        color: $card_text;
    }
    .consul-cv h1 { color: $card_text; font-size: 1.7rem; margin: 0 0 .1rem 0; }
    .consul-cv .cv-title { color: #3c4a5a; font-weight: 600; margin-bottom: .2rem; }
    .consul-cv .cv-contact { color: #526171; font-size: .8rem; margin-bottom: .9rem; }
    .consul-cv h2 {
        color: $card_text;
        font-size: .82rem;
        letter-spacing: .08em;
        text-transform: uppercase;
        border-bottom: 1px solid #d7dde5;
        padding-bottom: .2rem;
        margin: 1rem 0 .4rem 0;
    }
    .consul-cv .cv-entry { margin-bottom: .55rem; }
    .consul-cv .cv-entry-head { display: flex; justify-content: space-between; gap: 1rem; }
    .consul-cv .cv-dates { color: #667085; font-size: .78rem; white-space: nowrap; }
    .consul-cv ul { margin: .25rem 0 .2rem 1.05rem; padding: 0; }
    .consul-cv li { margin-bottom: .16rem; }
    .consul-cv .cv-skills { color: #26323f; }

    /* ---- Footer -------------------------------------------------------- */
    .consul-app-footer {
        margin-top: 3rem;
        border-top: 1px solid var(--consul-border);
        padding-top: .8rem;
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: .7rem;
        text-align: center;
    }

    #MainMenu, footer { visibility: hidden; }
    [data-testid="stSidebarNav"] { display: none; }

    /* ---- Motion -------------------------------------------------------- */
    @media (prefers-reduced-motion: no-preference) {
        .consul-page-head > *, .consul-hero > * { animation: consulRise .9s var(--consul-ease) both; }
        .consul-page-head > :nth-child(2), .consul-hero > :nth-child(2) { animation-delay: .08s; }
        .consul-page-head > :nth-child(3), .consul-hero > :nth-child(3) { animation-delay: .16s; }
        .consul-hero > :nth-child(4) { animation-delay: .24s; }
        .consul-hero::before { animation: consulWipe 1s var(--consul-ease) both; }
        .consul-hero::after { animation: consulDrop 1.2s cubic-bezier(.34,1.56,.64,1) .3s both; }
        .consul-pipeline-fill { animation: consulGrow .9s var(--consul-ease) both; }
        @keyframes consulRise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
        @keyframes consulWipe { from { clip-path: polygon(100% 0, 100% 0, 100% 100%, 100% 100%); } }
        @keyframes consulDrop {
            from { opacity: 0; transform: translateY(-90%) rotate(14deg); }
            to { opacity: .9; transform: translateY(-50%) rotate(-7deg); }
        }
        @keyframes consulGrow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
    }

    @media (max-width: 820px) {
        .block-container { padding-top: 1.4rem; padding-left: 1rem; padding-right: 1rem; }
        .consul-page-title { font-size: 2.1rem; }
        .consul-hero { padding: 1.6rem 1.4rem; }
        .consul-hero::before { clip-path: polygon(88% 0, 100% 0, 100% 100%, 80% 100%); }
        .consul-hero::after { display: none; }
        .consul-cv { padding: 1.3rem; }
        .consul-pipeline-row { grid-template-columns: 5.8rem 1fr 2rem; }
    }
    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            animation-duration: .01ms !important;
            transition-duration: .01ms !important;
            scroll-behavior: auto !important;
        }
    }
    </style>
    """
)

PAGE_KICKERS = {
    "Dashboard": "Workspace overview",
    "Ground Truth CV": "Foundation",
    "Job Discovery": "Discover",
    "Search Configuration": "Configure",
    "Saved Jobs": "Shortlist",
    "CV Studio": "Apply",
    "Application Tracker": "Apply",
    "Search Diagnostics": "Operations",
    "Settings": "Operations",
}


def palette() -> dict[str, str]:
    # Dark is the default look; the daylight variant is opt-out via the toggle.
    return DARK if st.session_state.get("dark_mode", True) else LIGHT


def inject_css() -> None:
    colors = palette()
    st.markdown(
        _CSS.substitute(
            **colors,
            fonts=font_css(),
            font_display=FONT_DISPLAY,
            font_sans=FONT_SANS,
            font_mono=FONT_MONO,
        ),
        unsafe_allow_html=True,
    )


def apply_branding() -> None:
    st.sidebar.markdown(
        """
        <div class="consul-brandmark">
            <div class="mark">C</div>
            <div>
                <div class="name">consul<span>.</span></div>
                <div class="tag">Career mission console</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
