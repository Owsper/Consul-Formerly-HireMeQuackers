"""Visual design system for the consul Streamlit workspace.

Direction (unslop pass, after Damir Sokolovsky's unslop skill, CC BY 4.0):

- Product: a local job-search desk that finds roles, scores them against the
  evidence in your own CV, tailors CVs and tracks applications.
- Character: exact, checkable, a little warm.
- World: a case file, documents, stamps and a ledger of evidence.
- Moments: the match score with its reasons, and the CV preview as paper.
- Signature: the small "evidenced" stamp wherever a fact has a source.

Chrome stays quiet: graphite surfaces, hairlines, three text roles and one
ember accent used for the primary action, focus and progress only. Archivo for
the interface, Geist Mono for figures and meta, both bundled in
``ui/assets/fonts`` and inlined so nothing loads from the network.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from string import Template

import streamlit as st

FONTS_DIR = Path(__file__).parent / "assets" / "fonts"

DARK = {
    "sidebar": "#0F0F10",
    "bg": "#141415",
    "surface": "#19191B",
    "surface_alt": "#232325",
    "text": "#EDEDED",
    "secondary": "#A1A1A6",
    "muted": "#85858B",
    "border": "rgba(237,237,237,0.08)",
    "border_strong": "rgba(237,237,237,0.14)",
    "highlight": "inset 0 1px 0 rgba(255,255,255,0.06)",
    "accent": "#FF6A2B",
    "accent_ink": "#FF8A57",
    "on_accent": "#1A0A03",
    "accent_hover": "#FF7D45",
    "track": "#2A2A2D",
    "fill": "#6E6E74",
    "success": "#4CC38A",
    "success_soft": "rgba(76,195,138,0.12)",
    "warn": "#D9A441",
    "warn_soft": "rgba(217,164,65,0.12)",
    "danger": "#E5484D",
    "danger_soft": "rgba(229,72,77,0.12)",
    "paper": "#FDFBF7",
    "paper_text": "#1F1B16",
}

LIGHT = {
    "sidebar": "#F4F4F5",
    "bg": "#FAFAFA",
    "surface": "#FFFFFF",
    "surface_alt": "#F4F4F5",
    "text": "#171717",
    "secondary": "#525252",
    "muted": "#737373",
    "border": "rgba(23,23,23,0.08)",
    "border_strong": "rgba(23,23,23,0.14)",
    "highlight": "0 1px 2px rgba(0,0,0,0.05)",
    "accent": "#FF6A2B",
    "accent_ink": "#C2410C",
    "on_accent": "#1A0A03",
    "accent_hover": "#FF7D45",
    "track": "#ECECEE",
    "fill": "#A1A1A6",
    "success": "#16A34A",
    "success_soft": "rgba(22,163,74,0.10)",
    "warn": "#A16207",
    "warn_soft": "rgba(161,98,7,0.10)",
    "danger": "#DC2626",
    "danger_soft": "rgba(220,38,38,0.08)",
    "paper": "#FFFFFF",
    "paper_text": "#1F1B16",
}

FONT_SANS = "'Archivo', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_MONO = "'Geist Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"


@lru_cache(maxsize=1)
def font_css() -> str:
    """@font-face rules with the bundled fonts inlined as data URIs."""
    rules = []
    for family, file in (
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
        --consul-sidebar: $sidebar;
        --consul-bg: $bg;
        --consul-surface: $surface;
        --consul-surface-alt: $surface_alt;
        --consul-text: $text;
        --consul-secondary: $secondary;
        --consul-muted: $muted;
        --consul-border: $border;
        --consul-border-strong: $border_strong;
        --consul-accent: $accent;
        --consul-accent-ink: $accent_ink;
        --consul-on-accent: $on_accent;
        --consul-success: $success;
        --consul-success-soft: $success_soft;
        --consul-warn: $warn;
        --consul-warn-soft: $warn_soft;
        --consul-danger: $danger;
        --consul-danger-soft: $danger_soft;
        --consul-sans: $font_sans;
        --consul-mono: $font_mono;
        --consul-r-sm: 6px;
        --consul-r: 8px;
        --consul-r-card: 12px;
        --consul-r-panel: 16px;
        --consul-ease: cubic-bezier(0.22, 1, 0.36, 1);
    }

    html, body, [class*="css"], .stApp, [data-testid="stAppViewContainer"] {
        font-family: var(--consul-sans);
    }
    .stApp {
        background: var(--consul-bg);
        color: var(--consul-text);
    }
    header[data-testid="stHeader"] { background: transparent !important; }
    [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"],
    [data-testid="stMainMenu"], [data-testid="stDecoration"] { display: none !important; }
    .block-container {
        max-width: 1440px;
        padding: 32px 32px 64px 32px;
    }
    h1, h2, h3, h4 {
        font-family: var(--consul-sans);
        color: var(--consul-text);
        font-weight: 500;
        letter-spacing: 0;
    }
    h1 { letter-spacing: -0.02em; }
    h5 {
        font-family: var(--consul-sans);
        color: var(--consul-secondary);
        font-size: 14px !important;
        font-weight: 500 !important;
        margin-top: 32px !important;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--consul-border);
    }
    p, span, label, li { color: var(--consul-text); }
    small, .consul-muted { color: var(--consul-muted) !important; }
    a { color: var(--consul-accent-ink); text-underline-offset: 3px; }
    hr { border-color: var(--consul-border); }
    code, pre, kbd {
        font-family: var(--consul-mono) !important;
        font-size: 13px !important;
    }
    [data-testid="stIconMaterial"], .material-symbols-rounded {
        font-family: "Material Symbols Rounded" !important;
    }

    /* ---- Sidebar ------------------------------------------------------- */
    [data-testid="stSidebar"] {
        background: var(--consul-sidebar);
        border-right: 1px solid var(--consul-border);
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 2px; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: 24px 16px 32px 16px; }
    [data-testid="stSidebar"] .stButton > button {
        width: 100%;
        min-height: 34px;
        padding: 6px 12px;
        border: 1px solid transparent;
        border-radius: var(--consul-r);
        background: transparent;
        color: var(--consul-secondary);
        font-family: var(--consul-sans);
        font-size: 14px;
        font-weight: 400;
        box-shadow: none;
        transition: background-color .15s var(--consul-ease), color .15s var(--consul-ease);
    }
    [data-testid="stSidebar"] .stButton > button > div { width: 100%; justify-content: flex-start; }
    [data-testid="stSidebar"] .stButton > button p { text-align: left; color: inherit !important; font-size: 14px; }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: var(--consul-surface);
        color: var(--consul-text);
        border-color: transparent;
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"],
    [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
        background: var(--consul-surface-alt);
        color: var(--consul-text);
        border-color: var(--consul-border);
        box-shadow: $highlight;
        font-weight: 500;
    }

    .consul-brandmark {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 0 0 24px 4px;
    }
    .consul-brandmark .mark {
        width: 28px;
        height: 28px;
        border-radius: var(--consul-r-sm);
        background: var(--consul-accent);
        color: var(--consul-on-accent);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: var(--consul-sans);
        font-weight: 600;
        font-size: 15px;
        line-height: 1;
    }
    .consul-brandmark .name {
        color: var(--consul-text);
        font-size: 17px;
        font-weight: 600;
        line-height: 1;
    }
    .consul-brandmark .tag {
        color: var(--consul-muted);
        font-size: 12px;
        margin-top: 4px;
    }
    .consul-nav-label {
        color: var(--consul-muted);
        font-size: 12px;
        font-weight: 500;
        line-height: 16px;
        margin: 0;
        padding: 20px 0 8px 12px;
    }
    .consul-side-profile {
        display: flex;
        gap: 10px;
        align-items: center;
        border-top: 1px solid var(--consul-border);
        padding: 16px 4px 4px 4px;
        margin-top: 8px;
    }
    .consul-avatar {
        width: 32px;
        height: 32px;
        flex: 0 0 32px;
        border-radius: 50%;
        border: 1px solid var(--consul-border-strong);
        background: var(--consul-surface-alt);
        color: var(--consul-secondary);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: var(--consul-mono);
        font-size: 12px;
    }
    .consul-side-name { color: var(--consul-text); font-size: 14px; font-weight: 500; line-height: 1.3; }
    .consul-side-muted { color: var(--consul-muted); font-family: var(--consul-mono); font-size: 12px; line-height: 1.5; }
    [data-testid="stSidebar"] .consul-divider { margin: 16px 0; }
    .consul-side-footer {
        color: var(--consul-muted);
        font-size: 12px;
        line-height: 1.5;
        border-top: 1px solid var(--consul-border);
        margin-top: 16px;
        padding-top: 12px;
    }

    /* ---- Page header --------------------------------------------------- */
    .consul-page-head {
        border-bottom: 1px solid var(--consul-border);
        padding-bottom: 20px;
        margin-bottom: 24px;
    }
    .consul-eyebrow {
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: 12px;
        margin-bottom: 8px;
    }
    .consul-page-title {
        font-size: 32px;
        font-weight: 500;
        letter-spacing: -0.01em;
        line-height: 1.15;
        margin: 0 0 8px 0;
        color: var(--consul-text);
    }
    .consul-page-sub {
        color: var(--consul-secondary);
        font-size: 15px;
        line-height: 1.5;
        max-width: 64ch;
        margin: 0;
    }
    .consul-section-intro { color: var(--consul-secondary); font-size: 14px; margin: -4px 0 12px 0; }

    /* ---- Cards / hero -------------------------------------------------- */
    .consul-card {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-r-card);
        padding: 20px;
        transition: border-color .15s var(--consul-ease);
    }
    .consul-card:hover { border-color: var(--consul-border-strong); }
    .consul-card + .consul-card { margin-top: 12px; }

    .consul-hero {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-r-panel);
        padding: 32px;
    }
    .consul-hero h1 {
        font-size: 40px !important;
        font-weight: 500 !important;
        letter-spacing: -0.02em;
        line-height: 1.08;
        max-width: 22ch;
    }
    .consul-hero p { color: var(--consul-secondary) !important; max-width: 36rem; }
    .consul-hero .consul-hero-note {
        color: var(--consul-muted) !important;
        font-family: var(--consul-mono);
        font-size: 12px;
        margin-top: 20px;
        font-variant-numeric: tabular-nums;
    }

    /* ---- Metrics / pipeline -------------------------------------------- */
    [data-testid="stMetric"] {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-r-card);
        padding: 20px;
    }
    [data-testid="stMetricLabel"] p { color: var(--consul-secondary); font-size: 14px !important; }
    [data-testid="stMetricValue"] {
        color: var(--consul-text);
        font-family: var(--consul-mono);
        font-weight: 500;
        font-size: 30px !important;
        font-variant-numeric: tabular-nums;
    }
    .consul-pipeline {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-r-card);
        padding: 20px 24px 24px 24px;
        margin-top: 16px;
    }
    .consul-pipeline-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 16px;
        margin-bottom: 16px;
    }
    .consul-pipeline-head b { font-size: 16px; font-weight: 500; }
    .consul-pipeline-head span { color: var(--consul-muted); font-family: var(--consul-mono); font-size: 12px; }
    .consul-pipeline-row {
        display: grid;
        grid-template-columns: 120px 1fr 48px;
        align-items: center;
        gap: 12px;
        margin: 8px 0;
    }
    .consul-pipeline-label { color: var(--consul-secondary); font-size: 14px; }
    .consul-pipeline-track { height: 6px; border-radius: 3px; background: $track; overflow: hidden; }
    .consul-pipeline-fill { height: 100%; border-radius: 3px; background: $fill; }
    .consul-pipeline-row:nth-child(3) .consul-pipeline-fill { background: var(--consul-accent); }
    .consul-pipeline-value {
        color: var(--consul-text);
        font-family: var(--consul-mono);
        font-size: 14px;
        text-align: right;
        font-variant-numeric: tabular-nums;
    }

    /* ---- Badges / flags / signature ------------------------------------ */
    .consul-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        border-radius: var(--consul-r-sm);
        font-family: var(--consul-mono);
        font-size: 12px;
        font-weight: 400;
        border: 1px solid transparent;
        white-space: nowrap;
    }
    .consul-badge.neutral, .consul-badge.brand {
        background: var(--consul-surface-alt);
        color: var(--consul-secondary);
        border-color: var(--consul-border);
    }
    .consul-badge.brand { color: var(--consul-text); }
    .consul-badge.success { background: var(--consul-success-soft); color: var(--consul-success); }
    .consul-badge.warn { background: var(--consul-warn-soft); color: var(--consul-warn); }
    .consul-badge.danger { background: var(--consul-danger-soft); color: var(--consul-danger); }
    .consul-stamp {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 0 6px;
        height: 20px;
        border: 1px solid var(--consul-success);
        border-radius: 4px;
        color: var(--consul-success);
        font-family: var(--consul-mono);
        font-size: 11px;
        line-height: 1;
        vertical-align: 2px;
    }
    .consul-stamp::before { content: "\\2713"; }
    .consul-flag {
        border-left: 2px solid var(--consul-warn);
        background: var(--consul-warn-soft);
        padding: 8px 12px;
        border-radius: 0 var(--consul-r-sm) var(--consul-r-sm) 0;
        font-size: 14px;
        margin: 4px 0;
    }
    .consul-flag.error { border-left-color: var(--consul-danger); background: var(--consul-danger-soft); }
    .consul-flag.ok { border-left-color: var(--consul-success); background: var(--consul-success-soft); }

    /* ---- Jobs ---------------------------------------------------------- */
    .consul-job-title { font-weight: 500; font-size: 17px; line-height: 1.3; margin: 0; }
    .consul-job-meta {
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: 12px;
        margin-top: 4px;
        line-height: 1.5;
    }
    .consul-score {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-width: 64px;
        padding: 8px;
        border-radius: var(--consul-r);
        background: var(--consul-surface-alt);
        border: 1px solid var(--consul-border);
    }
    .consul-score b {
        font-family: var(--consul-mono);
        font-weight: 500;
        font-size: 22px;
        line-height: 1.1;
        color: var(--consul-text);
        font-variant-numeric: tabular-nums;
    }
    .consul-score span { font-family: var(--consul-mono); font-size: 11px; color: var(--consul-muted); }

    /* ---- Buttons / inputs ---------------------------------------------- */
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
        border-radius: var(--consul-r);
        border: 1px solid var(--consul-border-strong);
        background: var(--consul-surface-alt);
        color: var(--consul-text);
        font-family: var(--consul-sans);
        font-size: 14px;
        font-weight: 500;
        min-height: 40px;
        padding: 8px 16px;
        box-shadow: $highlight;
        transition: background-color .15s var(--consul-ease), border-color .15s var(--consul-ease),
                    color .15s var(--consul-ease), transform .15s var(--consul-ease);
    }
    .stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
        border-color: var(--consul-muted);
        color: var(--consul-text);
        background: var(--consul-surface-alt);
    }
    .stButton > button:active, .stDownloadButton > button:active,
    .stFormSubmitButton > button:active { transform: scale(.98); }
    .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
        background: var(--consul-accent);
        border-color: var(--consul-accent);
        color: var(--consul-on-accent);
    }
    .stButton > button[kind="primary"] p, .stFormSubmitButton > button[kind="primary"] p { color: var(--consul-on-accent); }
    .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
        background: $accent_hover;
        border-color: $accent_hover;
        color: var(--consul-on-accent);
    }
    .stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible,
    .stDownloadButton > button:focus-visible, a:focus-visible, input:focus-visible,
    textarea:focus-visible {
        outline: 2px solid var(--consul-accent);
        outline-offset: 2px;
        box-shadow: none;
    }
    [data-testid="stWidgetLabel"] label, [data-testid="stWidgetLabel"] p {
        color: var(--consul-secondary) !important;
        font-size: 14px !important;
    }
    [data-baseweb="input"] input, [data-baseweb="textarea"] textarea, [data-baseweb="select"] > div {
        background: var(--consul-surface) !important;
        border-color: var(--consul-border-strong) !important;
        color: var(--consul-text) !important;
        border-radius: var(--consul-r) !important;
    }
    [data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within,
    [data-baseweb="select"] > div:focus-within {
        border-color: var(--consul-accent) !important;
        box-shadow: 0 0 0 1px var(--consul-accent) !important;
    }
    [data-testid="stSliderThumbValue"], [data-testid="stSliderTickBarMin"],
    [data-testid="stSliderTickBarMax"] { font-family: var(--consul-mono) !important; }

    /* ---- Tabs / expanders / tables ------------------------------------- */
    .stTabs [data-baseweb="tab-list"] { gap: 24px; border-bottom: 1px solid var(--consul-border); }
    .stTabs [data-baseweb="tab"] {
        font-size: 14px;
        color: var(--consul-secondary);
        padding-left: 0;
        padding-right: 0;
    }
    .stTabs [aria-selected="true"] { color: var(--consul-text) !important; }
    .stTabs [data-baseweb="tab-highlight"] { background-color: var(--consul-text); height: 2px; }
    [data-testid="stExpander"] {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border) !important;
        border-radius: var(--consul-r-card) !important;
        box-shadow: none;
        margin-bottom: 12px;
    }
    [data-testid="stExpander"] summary { font-size: 15px; font-weight: 500; color: var(--consul-text); }
    [data-testid="stDataFrame"] {
        border-radius: var(--consul-r-card);
        overflow: hidden;
        border: 1px solid var(--consul-border);
    }
    [data-testid="stDataFrame"] * { font-family: var(--consul-sans); }

    /* ---- Feedback ------------------------------------------------------ */
    .stAlert, [data-testid="stAlert"] { border-radius: var(--consul-r); }
    .stProgress > div > div > div > div { background-color: var(--consul-accent); }
    .stSpinner > div { border-top-color: var(--consul-accent) !important; }

    /* ---- Empty state --------------------------------------------------- */
    .consul-empty {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-r-card);
        padding: 40px 24px;
        text-align: center;
    }
    .consul-empty .consul-empty-mark { display: none; }
    .consul-empty h3 { margin: 0 0 8px 0; font-size: 18px; font-weight: 500; }
    .consul-empty p { color: var(--consul-secondary); margin: 0 auto; max-width: 52ch; font-size: 14px; line-height: 1.55; }

    /* ---- Key/value and divider ----------------------------------------- */
    .consul-kv {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        min-height: 36px;
        align-items: center;
        border-bottom: 1px solid var(--consul-border);
        font-size: 14px;
    }
    .consul-kv:last-child { border-bottom: 0; }
    .consul-kv span:first-child { color: var(--consul-secondary); }
    .consul-kv span:last-child { font-family: var(--consul-mono); font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; }
    .consul-divider { height: 1px; background: var(--consul-border); margin: 24px 0; }

    /* ---- CV preview: the paper moment ---------------------------------- */
    .consul-cv {
        background: $paper;
        color: $paper_text;
        border: 1px solid var(--consul-border);
        border-radius: 4px;
        padding: 36px 40px;
        max-width: 820px;
        font-size: 14px;
        line-height: 1.45;
        box-shadow: 0 8px 24px rgba(0,0,0,0.18);
    }
    .consul-cv, .consul-cv p, .consul-cv span, .consul-cv li, .consul-cv div, .consul-cv b { color: $paper_text; }
    .consul-cv h1 { color: $paper_text; font-size: 26px; margin: 0 0 2px 0; }
    .consul-cv .cv-title { color: #3c4a5a; font-weight: 600; margin-bottom: 4px; }
    .consul-cv .cv-contact { color: #526171; font-size: 13px; margin-bottom: 16px; }
    .consul-cv h2 {
        color: $paper_text;
        font-size: 13px;
        letter-spacing: .08em;
        text-transform: uppercase;
        border-bottom: 1px solid #d7dde5;
        padding-bottom: 4px;
        margin: 16px 0 8px 0;
    }
    .consul-cv .cv-entry { margin-bottom: 8px; }
    .consul-cv .cv-entry-head { display: flex; justify-content: space-between; gap: 16px; }
    .consul-cv .cv-dates { color: #667085; font-size: 12px; white-space: nowrap; }
    .consul-cv ul { margin: 4px 0 4px 16px; padding: 0; }
    .consul-cv li { margin-bottom: 2px; }
    .consul-cv .cv-skills { color: #26323f; }

    /* ---- Footer -------------------------------------------------------- */
    .consul-app-footer {
        margin-top: 48px;
        border-top: 1px solid var(--consul-border);
        padding-top: 12px;
        color: var(--consul-muted);
        font-size: 12px;
        text-align: center;
    }

    #MainMenu, footer { visibility: hidden; }
    [data-testid="stSidebarNav"] { display: none; }

    /* ---- Motion: one entrance, nothing loops --------------------------- */
    @media (prefers-reduced-motion: no-preference) {
        .consul-page-head, .consul-hero { animation: consulRise .4s var(--consul-ease) both; }
        @keyframes consulRise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    }

    @media (max-width: 820px) {
        .block-container { padding: 24px 16px 48px 16px; }
        .consul-page-title { font-size: 28px; }
        .consul-hero { padding: 24px; }
        .consul-hero h1 { font-size: 32px !important; }
        .consul-cv { padding: 20px; }
        .consul-pipeline-row { grid-template-columns: 96px 1fr 40px; }
    }
    /* ==== Workspace components (redesign patch, unslop treatment) ===== */
    [data-testid="stSidebar"] .stButton > button { gap: 10px; }
    [data-testid="stSidebar"] .stButton > button [data-testid="stIconMaterial"] {
        font-size: 18px; color: var(--consul-muted);
        transition: color .15s var(--consul-ease);
    }
    [data-testid="stSidebar"] .stButton > button:hover [data-testid="stIconMaterial"],
    [data-testid="stSidebar"] .stButton > button[kind="primary"] [data-testid="stIconMaterial"] { color: var(--consul-text); }

    /* Page header with icon */
    .consul-page-head-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
    .consul-page-icon {
        width: 40px; height: 40px; flex: 0 0 40px; border-radius: var(--consul-r);
        display: grid; place-items: center; color: var(--consul-secondary);
        background: var(--consul-surface-alt); border: 1px solid var(--consul-border);
    }
    .consul-page-head .consul-eyebrow { margin-bottom: 4px; }
    .consul-page-head .consul-page-title { margin: 0; }

    /* Hero with readiness dial */
    .consul-hero { display: grid; grid-template-columns: minmax(0, 1fr) 184px; gap: 32px; align-items: center; }
    .consul-hero h1 { margin: 0 0 12px 0 !important; }
    .consul-hero p { font-size: 17px; line-height: 1.55; margin: 0 !important; }
    .consul-hero-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px; }
    .consul-hero-chips span {
        font-family: var(--consul-mono); font-size: 12px; color: var(--consul-secondary);
        padding: 4px 10px; border-radius: var(--consul-r-sm);
        background: var(--consul-surface-alt); border: 1px solid var(--consul-border);
        font-variant-numeric: tabular-nums;
    }
    .consul-hero-chips b { color: var(--consul-text); font-weight: 500; margin-right: 4px; }
    .consul-dial { position: relative; width: 184px; height: 184px; justify-self: end; }
    .consul-dial svg { width: 100%; height: 100%; transform: rotate(-90deg); overflow: visible; }
    .consul-dial-ticks line { stroke: var(--consul-text); stroke-opacity: .1; stroke-width: 1; }
    .consul-dial-track { fill: none; stroke: var(--consul-border-strong); stroke-width: 8; }
    .consul-dial-fill { fill: none; stroke: var(--consul-accent); stroke-width: 8; stroke-linecap: round; }
    .consul-dial-center { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
    .consul-dial-center b { font-family: var(--consul-mono); font-size: 40px; font-weight: 500; line-height: 1; color: var(--consul-text); font-variant-numeric: tabular-nums; }
    .consul-dial-center b small { font-size: 16px; color: var(--consul-muted); margin-left: 2px; }
    .consul-dial-center span { font-family: var(--consul-mono); font-size: 12px; color: var(--consul-muted); margin-top: 6px; }

    /* Stat tiles: numbers only */
    .consul-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
    .consul-stat {
        padding: 20px; border-radius: var(--consul-r-card);
        background: var(--consul-surface); border: 1px solid var(--consul-border);
    }
    .consul-stat-top { color: var(--consul-secondary); font-size: 14px; }
    .consul-stat-value { font-family: var(--consul-mono); font-size: 30px; font-weight: 500; line-height: 1; margin: 12px 0 8px; color: var(--consul-text); font-variant-numeric: tabular-nums; }
    .consul-stat-hint { font-family: var(--consul-mono); font-size: 12px; color: var(--consul-muted); }

    /* Section heads */
    .consul-section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin: 8px 0 12px; }
    .consul-section-head .t { font-size: 20px; font-weight: 500; color: var(--consul-text); }
    .consul-section-head .n { font-family: var(--consul-mono); font-size: 12px; color: var(--consul-muted); }

    /* Stepper */
    .consul-stepper { list-style: none; margin: 0 0 16px; padding: 0; position: relative; }
    .consul-stepper::before {
        content: ""; position: absolute; left: 17px; top: 20px; bottom: 20px; width: 1px;
        background: var(--consul-border-strong);
    }
    .consul-step {
        position: relative; display: grid; grid-template-columns: 36px 1fr auto; gap: 12px; align-items: center;
        padding: 8px 12px 8px 0; margin: 0 0 4px; border-radius: var(--consul-r);
    }
    .consul-step-mark {
        width: 36px; height: 36px; border-radius: var(--consul-r); display: grid; place-items: center;
        position: relative; z-index: 1;
        font-family: var(--consul-mono); font-size: 12px; color: var(--consul-muted);
        background: var(--consul-surface); border: 1px solid var(--consul-border-strong);
    }
    .consul-step-body b { display: block; font-size: 15px; font-weight: 500; color: var(--consul-text); }
    .consul-step-body span { display: block; font-size: 13px; color: var(--consul-muted); margin-top: 2px; }
    .consul-step-tag { font-family: var(--consul-mono); font-size: 12px; color: var(--consul-muted); padding: 2px 8px; border-radius: var(--consul-r-sm); border: 1px solid var(--consul-border); }
    .consul-step.done .consul-step-mark { background: var(--consul-success-soft); border-color: var(--consul-border); color: var(--consul-success); }
    .consul-step.done .consul-step-body b { color: var(--consul-secondary); }
    .consul-step.done .consul-step-tag { color: var(--consul-success); }
    .consul-step.next { background: var(--consul-surface-alt); }
    .consul-step.next .consul-step-mark { background: var(--consul-accent); border-color: var(--consul-accent); color: var(--consul-on-accent); }
    .consul-step.next .consul-step-tag { color: var(--consul-text); border-color: var(--consul-border-strong); }

    /* Upcoming calendar */
    .consul-calendar-empty { display: flex; gap: 16px; align-items: center; }
    .consul-cal {
        flex: 0 0 48px; height: 56px; border-radius: var(--consul-r); overflow: hidden; text-align: center;
        border: 1px solid var(--consul-border-strong); background: var(--consul-surface-alt);
        display: flex; flex-direction: column;
    }
    .consul-cal span { order: -1; border-bottom: 1px solid var(--consul-border); color: var(--consul-muted); font-family: var(--consul-mono); font-size: 11px; padding: 2px 0; }
    .consul-cal b { font-family: var(--consul-mono); font-size: 22px; font-weight: 500; line-height: 32px; color: var(--consul-text); }

    /* Empty state with paper stack */
    .consul-empty { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 24px; align-items: center; text-align: left; padding: 24px 32px; margin-bottom: 16px; }
    .consul-empty-art { width: 160px; height: 110px; color: var(--consul-text); }
    .consul-empty h3 { margin: 0 0 8px !important; }
    .consul-empty p { margin: 0 !important; }

    @media (max-width: 1100px) {
        .consul-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .consul-hero { grid-template-columns: 1fr; }
        .consul-dial { justify-self: start; width: 144px; height: 144px; }
    }
    @media (max-width: 820px) {
        .consul-empty { grid-template-columns: 1fr; padding: 24px; }
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
    "Dashboard": "Overview",
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
    return DARK if st.session_state.get("dark_mode", True) else LIGHT


def inject_css() -> None:
    st.markdown(
        _CSS.substitute(**palette(), fonts=font_css(), font_sans=FONT_SANS, font_mono=FONT_MONO),
        unsafe_allow_html=True,
    )


def apply_branding() -> None:
    st.sidebar.markdown(
        """
        <div class="consul-brandmark">
            <div class="mark">c</div>
            <div>
                <div class="name">consul</div>
                <div class="tag">Evidence-checked job search</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
