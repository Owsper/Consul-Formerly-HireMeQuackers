"""Visual design system for the consul Streamlit workspace.

The direction is an editorial career desk rather than a generic dashboard:
warm paper, deep ink, serif display type, monospaced labels and a single
terracotta accent. Tokens are centralised here so every page shares one scale
for colour, type, spacing and state.
"""

from __future__ import annotations

from string import Template

import streamlit as st

LIGHT = {
    "bg": "#F2EFE7",
    "surface": "#FCFAF5",
    "surface_alt": "#E9E4D8",
    "text": "#15201B",
    "muted": "#667069",
    "border": "#D8D1C2",
    "brand": "#1E3D34",
    "brand_soft": "#DCE6DF",
    "on_brand": "#FBF8F1",
    "accent": "#B45A3C",
    "accent_soft": "#F3E1D8",
    "success": "#2C6049",
    "success_soft": "#DDEBE4",
    "warn": "#8A5A16",
    "warn_soft": "#F4E8CE",
    "danger": "#9E3B35",
    "danger_soft": "#F4DEDA",
    "rule": "#C9C0AF",
    "sidebar": "#14221D",
    "sidebar_alt": "#1B2C25",
    "sidebar_text": "#F4EFE4",
    "sidebar_muted": "#9FAEA6",
    "sidebar_active": "#2C4A3F",
    "hero": "#182C24",
    "hero_text": "#F8F3E8",
    "shadow": "none",
}

DARK = {
    "bg": "#0F1512",
    "surface": "#17201C",
    "surface_alt": "#202C26",
    "text": "#ECE8DD",
    "muted": "#A7B2AB",
    "border": "#2C3933",
    "brand": "#9CC9B4",
    "brand_soft": "#1D3028",
    "on_brand": "#0E1713",
    "accent": "#D68B6E",
    "accent_soft": "#37231C",
    "success": "#8BC7A8",
    "success_soft": "#193127",
    "warn": "#E2B86F",
    "warn_soft": "#332817",
    "danger": "#E49A92",
    "danger_soft": "#351E1B",
    "rule": "#334139",
    "sidebar": "#0A100D",
    "sidebar_alt": "#121B17",
    "sidebar_text": "#EEE9DD",
    "sidebar_muted": "#91A198",
    "sidebar_active": "#23382F",
    "hero": "#1B2E26",
    "hero_text": "#F8F3E8",
    "shadow": "none",
}

FONT_DISPLAY = "Georgia, 'Iowan Old Style', 'Times New Roman', serif"
FONT_SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
FONT_MONO = "'IBM Plex Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', monospace"

_CSS = Template(
    """
    <style>
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
        --consul-display: $font_display;
        --consul-sans: $font_sans;
        --consul-mono: $font_mono;
        --consul-radius: 10px;
        --consul-radius-sm: 6px;
        --consul-shadow: $shadow;
    }

    html, body, [class*="css"], .stApp {
        font-family: var(--consul-sans);
    }
    .stApp {
        background:
            radial-gradient(900px 420px at 84% -12%, $accent_soft 0%, transparent 58%),
            linear-gradient(180deg, $bg 0%, $bg 100%);
        color: var(--consul-text);
    }
    .block-container {
        max-width: 1240px;
        padding-top: 2.35rem;
        padding-bottom: 4.5rem;
    }
    h1, h2, h3 {
        font-family: var(--consul-display);
        color: var(--consul-text);
        letter-spacing: -.025em;
        font-weight: 600;
    }
    h4 {
        font-family: var(--consul-sans);
        color: var(--consul-text);
        letter-spacing: -.01em;
    }
    h5 {
        font-family: var(--consul-mono);
        color: var(--consul-muted);
        text-transform: uppercase;
        letter-spacing: .13em;
        font-size: .69rem !important;
        font-weight: 500 !important;
        margin-top: 1.7rem !important;
        padding-bottom: .35rem;
        border-bottom: 1px solid var(--consul-border);
    }
    p, span, label, li {
        color: var(--consul-text);
    }
    small, .consul-muted {
        color: var(--consul-muted) !important;
    }
    a { color: var(--consul-brand); text-underline-offset: 3px; }
    hr { border-color: var(--consul-border); }
    code, pre, kbd {
        font-family: var(--consul-mono) !important;
        font-size: .78rem !important;
    }

    /* ---- Sidebar ------------------------------------------------------- */
    [data-testid="stSidebar"] {
        background: var(--consul-sidebar);
        border-right: 1px solid var(--consul-sidebar-active);
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
        width: 100%;
        justify-content: flex-start;
        text-align: left;
        min-height: 2.2rem;
        padding: .48rem .65rem;
        border: 1px solid transparent;
        border-radius: var(--consul-radius-sm);
        background: transparent;
        color: var(--consul-sidebar-muted);
        font-family: var(--consul-sans);
        font-size: .85rem;
        font-weight: 500;
        letter-spacing: .005em;
        box-shadow: none;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: var(--consul-sidebar-alt);
        color: var(--consul-sidebar-text);
        border-color: transparent;
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"] {
        background: var(--consul-sidebar-active);
        color: var(--consul-sidebar-text);
        border-color: var(--consul-sidebar-active);
        font-weight: 600;
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
        background: var(--consul-sidebar-active);
        color: var(--consul-sidebar-text);
    }
    [data-testid="stSidebar"] [data-testid="stToggle"] label span {
        color: var(--consul-sidebar-muted) !important;
    }
    [data-testid="stSidebar"] .stAlert {
        background: var(--consul-sidebar-alt);
        border: 1px solid var(--consul-sidebar-active);
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
        border-radius: 10px;
        background: var(--consul-hero-text);
        color: var(--consul-hero);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: var(--consul-display);
        font-weight: 700;
        font-size: 1.18rem;
        line-height: 1;
    }
    .consul-brandmark .name {
        color: var(--consul-sidebar-text);
        font-family: var(--consul-display);
        font-size: 1.18rem;
        font-weight: 600;
        letter-spacing: -.015em;
        line-height: 1.05;
    }
    .consul-brandmark .tag {
        color: var(--consul-sidebar-muted);
        font-family: var(--consul-mono);
        font-size: .58rem;
        letter-spacing: .12em;
        text-transform: uppercase;
        margin-top: .22rem;
    }
    .consul-nav-label {
        color: var(--consul-sidebar-muted);
        font-family: var(--consul-mono);
        font-size: .58rem;
        letter-spacing: .16em;
        text-transform: uppercase;
        margin: 1.15rem 0 .35rem .65rem;
    }
    .consul-side-profile {
        display: flex;
        gap: .65rem;
        align-items: center;
        border-top: 1px solid var(--consul-sidebar-active);
        padding: .9rem .2rem .2rem .2rem;
        margin-top: .6rem;
    }
    .consul-avatar {
        width: 32px;
        height: 32px;
        flex: 0 0 32px;
        border-radius: 50%;
        border: 1px solid var(--consul-sidebar-active);
        background: var(--consul-sidebar-alt);
        color: var(--consul-sidebar-text);
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: var(--consul-mono);
        font-size: .7rem;
        letter-spacing: .03em;
    }
    .consul-side-name {
        color: var(--consul-sidebar-text);
        font-size: .82rem;
        font-weight: 600;
        line-height: 1.2;
    }
    .consul-side-muted {
        color: var(--consul-sidebar-muted);
        font-family: var(--consul-mono);
        font-size: .58rem;
        letter-spacing: .03em;
        line-height: 1.5;
    }
    [data-testid="stSidebar"] .consul-divider {
        background: var(--consul-sidebar-active);
        margin: 1rem 0;
    }
    .consul-side-footer {
        color: var(--consul-sidebar-muted);
        font-family: var(--consul-mono);
        font-size: .56rem;
        letter-spacing: .08em;
        text-transform: uppercase;
        border-top: 1px solid var(--consul-sidebar-active);
        margin-top: 1rem;
        padding-top: .8rem;
    }

    /* ---- Page header --------------------------------------------------- */
    .consul-page-head {
        border-bottom: 1px solid var(--consul-rule);
        padding-bottom: 1.1rem;
        margin-bottom: 1.45rem;
    }
    .consul-eyebrow {
        color: var(--consul-accent);
        font-family: var(--consul-mono);
        font-size: .62rem;
        font-weight: 500;
        letter-spacing: .17em;
        text-transform: uppercase;
        margin-bottom: .38rem;
    }
    .consul-page-title {
        font-family: var(--consul-display);
        font-size: clamp(2rem, 3.3vw, 2.75rem);
        font-weight: 600;
        letter-spacing: -.035em;
        line-height: 1.02;
        margin: 0 0 .42rem 0;
        color: var(--consul-text);
    }
    .consul-page-sub {
        color: var(--consul-muted);
        font-size: .93rem;
        line-height: 1.55;
        max-width: 68ch;
        margin: 0;
    }
    .consul-section-intro {
        color: var(--consul-muted);
        font-size: .86rem;
        margin: -.2rem 0 .8rem 0;
    }

    /* ---- Cards / hero -------------------------------------------------- */
    .consul-card {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 1rem 1.15rem;
        box-shadow: var(--consul-shadow);
    }
    .consul-card + .consul-card { margin-top: .75rem; }
    .consul-hero {
        position: relative;
        overflow: hidden;
        background:
            repeating-linear-gradient(115deg, transparent 0 22px, rgba(255,255,255,.026) 22px 23px),
            var(--consul-hero);
        color: var(--consul-hero-text);
        border-radius: 14px;
        border: 1px solid var(--consul-hero);
        padding: 2rem 2.1rem;
    }
    .consul-hero h1, .consul-hero p, .consul-hero span { color: var(--consul-hero-text) !important; }
    .consul-hero h1 {
        font-family: var(--consul-display);
        font-weight: 500 !important;
        letter-spacing: -.035em;
        line-height: 1.05;
    }
    .consul-hero .consul-eyebrow { color: var(--consul-accent) !important; }
    .consul-hero .consul-hero-note {
        color: rgba(248,243,232,.66) !important;
        font-family: var(--consul-mono);
        font-size: .62rem;
        letter-spacing: .06em;
        margin-top: 1.1rem;
    }

    /* ---- Metrics / pipeline -------------------------------------------- */
    [data-testid="stMetric"] {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-top: 2px solid var(--consul-brand);
        border-radius: var(--consul-radius-sm);
        padding: .8rem .9rem .7rem .9rem;
        box-shadow: var(--consul-shadow);
    }
    [data-testid="stMetricLabel"] p {
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: .62rem !important;
        letter-spacing: .1em;
        text-transform: uppercase;
    }
    [data-testid="stMetricValue"] {
        color: var(--consul-text);
        font-family: var(--consul-display);
        font-weight: 600;
        letter-spacing: -.03em;
    }
    .consul-pipeline {
        background: var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 1rem 1.15rem 1.1rem 1.15rem;
        margin-top: .8rem;
    }
    .consul-pipeline-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 1rem;
        margin-bottom: .75rem;
    }
    .consul-pipeline-head b {
        font-family: var(--consul-display);
        font-size: 1rem;
        font-weight: 600;
    }
    .consul-pipeline-head span {
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: .58rem;
        letter-spacing: .1em;
        text-transform: uppercase;
    }
    .consul-pipeline-row {
        display: grid;
        grid-template-columns: 6.6rem 1fr 2.2rem;
        align-items: center;
        gap: .7rem;
        margin: .38rem 0;
    }
    .consul-pipeline-label {
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: .6rem;
        letter-spacing: .05em;
        text-transform: uppercase;
    }
    .consul-pipeline-track {
        height: 6px;
        border-radius: 999px;
        background: var(--consul-surface-alt);
        overflow: hidden;
    }
    .consul-pipeline-fill {
        height: 100%;
        border-radius: 999px;
        background: var(--consul-brand);
    }
    .consul-pipeline-value {
        color: var(--consul-text);
        font-family: var(--consul-mono);
        font-size: .68rem;
        text-align: right;
    }

    /* ---- Badges / flags ------------------------------------------------ */
    .consul-badge {
        display: inline-flex;
        align-items: center;
        gap: .3rem;
        padding: .18rem .52rem;
        border-radius: 999px;
        font-family: var(--consul-mono);
        font-size: .6rem;
        font-weight: 500;
        letter-spacing: .05em;
        text-transform: uppercase;
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
        padding: .5rem .7rem;
        border-radius: 0 var(--consul-radius-sm) var(--consul-radius-sm) 0;
        font-size: .82rem;
        margin: .35rem 0;
    }
    .consul-flag.error { border-left-color: var(--consul-danger); background: var(--consul-danger-soft); }
    .consul-flag.ok { border-left-color: var(--consul-success); background: var(--consul-success-soft); }

    /* ---- Jobs ---------------------------------------------------------- */
    .consul-job-title {
        font-family: var(--consul-display);
        font-weight: 600;
        font-size: 1.12rem;
        line-height: 1.25;
        margin: 0;
        letter-spacing: -.015em;
    }
    .consul-job-meta {
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: .64rem;
        letter-spacing: .02em;
        margin-top: .28rem;
        line-height: 1.55;
    }
    .consul-score {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-width: 62px;
        padding: .35rem .5rem;
        border-radius: var(--consul-radius-sm);
        background: var(--consul-surface-alt);
        border: 1px solid var(--consul-border);
    }
    .consul-score b {
        font-family: var(--consul-display);
        font-size: 1.25rem;
        line-height: 1.05;
    }
    .consul-score span {
        font-family: var(--consul-mono);
        font-size: .52rem;
        text-transform: uppercase;
        letter-spacing: .09em;
        color: var(--consul-muted);
    }

    /* ---- Buttons / inputs ---------------------------------------------- */
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
        border-radius: var(--consul-radius-sm);
        border: 1px solid var(--consul-border);
        background: var(--consul-surface);
        color: var(--consul-text);
        font-family: var(--consul-sans);
        font-size: .82rem;
        font-weight: 600;
        min-height: 2.35rem;
        transition: background .14s ease, border-color .14s ease, color .14s ease;
        box-shadow: none;
    }
    .stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
        border-color: var(--consul-brand);
        color: var(--consul-brand);
        background: var(--consul-surface);
    }
    .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
        background: var(--consul-brand);
        border-color: var(--consul-brand);
        color: var(--consul-on-brand);
    }
    .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
        background: var(--consul-brand);
        border-color: var(--consul-brand);
        color: var(--consul-on-brand);
        filter: brightness(1.06);
    }
    .stButton > button:focus-visible,
    .stFormSubmitButton > button:focus-visible,
    .stDownloadButton > button:focus-visible,
    a:focus-visible, input:focus-visible, textarea:focus-visible {
        outline: 2px solid var(--consul-accent);
        outline-offset: 2px;
        box-shadow: none;
    }
    [data-testid="stWidgetLabel"] label,
    [data-testid="stWidgetLabel"] p {
        color: var(--consul-muted) !important;
        font-family: var(--consul-mono);
        font-size: .62rem !important;
        letter-spacing: .06em;
        text-transform: uppercase;
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

    /* ---- Tabs / expanders / tables ------------------------------------- */
    .stTabs [data-baseweb="tab-list"] {
        gap: 1.3rem;
        border-bottom: 1px solid var(--consul-border);
    }
    .stTabs [data-baseweb="tab"] {
        font-family: var(--consul-mono);
        font-size: .64rem;
        letter-spacing: .09em;
        text-transform: uppercase;
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
        font-size: .86rem;
        font-weight: 600;
        color: var(--consul-text);
    }
    [data-testid="stDataFrame"] {
        border-radius: var(--consul-radius-sm);
        overflow: hidden;
        border: 1px solid var(--consul-border);
    }
    [data-testid="stDataFrame"] * { font-family: var(--consul-sans); }

    /* ---- Feedback ------------------------------------------------------ */
    .stAlert {
        border-radius: var(--consul-radius-sm);
        border: 1px solid var(--consul-border);
        background: var(--consul-surface);
    }
    .stProgress > div > div > div > div { background-color: var(--consul-accent); }
    .stSpinner > div { border-top-color: var(--consul-accent) !important; }

    /* ---- Empty state --------------------------------------------------- */
    .consul-empty {
        background:
            repeating-linear-gradient(135deg, transparent 0 18px, rgba(0,0,0,.012) 18px 19px),
            var(--consul-surface);
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 2.7rem 1.5rem;
        text-align: center;
    }
    .consul-empty .consul-empty-mark {
        width: 46px;
        height: 46px;
        border-radius: 50%;
        margin: 0 auto .85rem auto;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--consul-accent-soft);
        color: var(--consul-accent);
        font-family: var(--consul-mono);
        font-size: .78rem;
        letter-spacing: .04em;
    }
    .consul-empty h3 {
        margin: 0 0 .4rem 0;
        font-family: var(--consul-display);
        font-size: 1.3rem;
        font-weight: 600;
    }
    .consul-empty p {
        color: var(--consul-muted);
        margin: 0 auto;
        max-width: 52ch;
        font-size: .88rem;
        line-height: 1.55;
    }

    /* ---- Key/value and divider ----------------------------------------- */
    .consul-kv {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        padding: .34rem 0;
        border-bottom: 1px solid var(--consul-border);
        font-size: .82rem;
    }
    .consul-kv:last-child { border-bottom: 0; }
    .consul-kv span:first-child {
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: .62rem;
        letter-spacing: .04em;
        text-transform: uppercase;
        padding-top: .08rem;
    }
    .consul-kv span:last-child { font-weight: 600; text-align: right; }
    .consul-divider {
        height: 1px;
        background: var(--consul-border);
        margin: 1.6rem 0;
    }

    /* ---- CV preview ---------------------------------------------------- */
    .consul-cv {
        background: #FFFEFA;
        color: #15201b;
        border: 1px solid var(--consul-border);
        border-radius: var(--consul-radius);
        padding: 2.2rem 2.4rem;
        max-width: 820px;
        font-size: .88rem;
        line-height: 1.45;
    }
    .consul-cv h1 { color: #15201b; font-size: 1.7rem; margin: 0 0 .1rem 0; }
    .consul-cv .cv-title { color: #3c4a5a; font-weight: 600; margin-bottom: .2rem; }
    .consul-cv .cv-contact { color: #526171; font-size: .8rem; margin-bottom: .9rem; }
    .consul-cv h2 {
        color: #15201b;
        font-size: .82rem;
        letter-spacing: .08em;
        text-transform: uppercase;
        border-bottom: 1px solid #d7dde5;
        padding-bottom: .2rem;
        margin: 1rem 0 .4rem 0;
    }
    .consul-cv .cv-entry { margin-bottom: .55rem; }
    .consul-cv .cv-entry-head { display: flex; justify-content: space-between; gap: 1rem; }
    .consul-cv .cv-entry-head b { color: #15201b; }
    .consul-cv .cv-dates { color: #667085; font-size: .78rem; white-space: nowrap; }
    .consul-cv ul { margin: .25rem 0 .2rem 1.05rem; padding: 0; }
    .consul-cv li { margin-bottom: .16rem; }
    .consul-cv .cv-skills { color: #26323f; }

    /* ---- Footer -------------------------------------------------------- */
    .consul-app-footer {
        margin-top: 3rem;
        border-top: 1px solid var(--consul-border);
        padding-top: .7rem;
        color: var(--consul-muted);
        font-family: var(--consul-mono);
        font-size: .56rem;
        letter-spacing: .09em;
        text-transform: uppercase;
        text-align: center;
    }

    #MainMenu, footer { visibility: hidden; }
    [data-testid="stSidebarNav"] { display: none; }

    @media (max-width: 820px) {
        .block-container { padding-top: 1.4rem; padding-left: 1rem; padding-right: 1rem; }
        .consul-page-title { font-size: 2rem; }
        .consul-hero { padding: 1.4rem; }
        .consul-cv { padding: 1.3rem; }
        .consul-pipeline-row { grid-template-columns: 5.3rem 1fr 1.8rem; }
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
    return DARK if st.session_state.get("dark_mode") else LIGHT


def inject_css() -> None:
    colors = palette()
    st.markdown(
        _CSS.substitute(
            **colors,
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
                <div class="name">consul</div>
                <div class="tag">Career intelligence</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
