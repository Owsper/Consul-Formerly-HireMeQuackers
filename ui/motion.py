"""Motion layer for the consul workspace.

Everything that moves lives here so the visual theme in ``theme.py`` stays
readable. The catalogue below is numbered: each entry is one distinct
animation or transition, and the same number appears next to its CSS rule or
JS handler. Rules of the road:

- only ``transform``, ``opacity``, ``filter``, ``clip-path`` and colour are
  animated, so everything stays on the compositor;
- one easing family: ``--m-out`` for entrances, ``--m-spring`` for things
  that should overshoot a touch, ``--m-io`` for loops;
- loops are slow (2.5 s+) and quiet, nothing blinks for attention except the
  "up next" step and the caret;
- ``prefers-reduced-motion: reduce`` switches the whole layer off, and the JS
  checks it before attaching any pointer effect.

Catalogue
---------
Page transitions and loading
  1  page exit: content dims, blurs and sinks when a nav item is clicked
  2  page enter: content rises out of a blur
  3  route curtain: ember beam sweeps across the top on every page change
  4  route veil: a translucent panel wipes off the content area
  5  rerun progress bar while a script run is in flight
  6  rerun progress glow trailing the bar
  7  stale-content dim while Streamlit reruns
  8  staggered block entrance, one delay step per block
  9  scroll reveal for blocks below the fold
 10  sidebar items cascade in on first load

Ambient
 11  aurora drift of the ember background glow
 12  dot grid slow drift
 13  grain jitter so the noise never looks frozen
 14  cursor light: soft ember light follows the pointer with easing
 15  hero conic border slowly rotates
 16  hero grid lines drift
 17  hero glow follows the pointer inside the hero
 18  page index numeral parallax on scroll
 19  page index numeral outline draws in

Typography
 20  page title letters rise one by one
 21  eyebrow types itself out
 22  eyebrow caret blinks, then fades away
 23  eyebrow slashes spin in
 24  hero headline words lift in sequence
 25  hero "prove" gradient pans
 26  hero paragraph blur-in
 27  section heading underline draws
 28  h5 underline draws
 29  link underline grows on hover
 30  numbers count up to their value

Dashboard pieces
 31  readiness dial fills
 32  dial tick ring slowly rotates
 33  dial orbiting spark
 34  dial number glow breathes
 35  dial pops in with a spring
 36  hero chips stagger in
 37  hero chip hover lift
 38  stat tile entrance stagger
 39  stat tile 3D tilt toward the pointer
 40  stat tile spotlight follows the pointer
 41  stat tile top line ignites on hover
 42  stat icon wiggles on hover
 43  stat value rises in
 44  pipeline rows stagger in
 45  pipeline fill grows
 46  pipeline shimmer sweep
 47  pipeline value ticks in
 48  pipeline row hover highlight
 49  stepper rows stagger in
 50  stepper hover nudge
 51  "up next" marker pulse ring
 52  done marker check pops
 53  step marker rotates on hover
 54  stepper rail draws down
 55  calendar tile flips in
 56  key/value rows slide on hover
 57  card spotlight follows the pointer
 58  card 3D tilt
 59  card hover lift

Empty states and documents
 60  empty state sheets float
 61  sheets fan out on hover
 62  stamp slams in
 63  stamp wobbles on hover
 64  empty state art lines draw in
 65  empty state dashed border marches on hover
 66  CV paper rises in
 67  CV paper tilts toward the pointer

Navigation
 68  sidebar nav icon slides on hover
 69  active nav bar grows in
 70  active nav background sweeps in
 71  nav group dash extends on hover of the group
 72  brand mark breathes
 73  brand mark spins on hover
 74  avatar ring rotates
 75  sidebar collapse chevron rotates on hover
 76  page icon tile floats in
 77  page icon glyph bounces on hover

Buttons and controls
 78  click ripple from the pointer position
 79  magnetic primary button
 80  primary button sheen sweep on hover
 81  button press squish
 82  secondary button border glow on hover
 83  button icon nudges on hover
 84  download button arrow drops on hover
 85  input focus ring glows in
 86  input label lifts when focused
 87  select dropdown menu scales in
 88  dropdown options cascade
 89  slider thumb grows on hover
 90  slider thumb press
 91  checkbox tick pops
 92  radio dot pops
 93  toggle thumb squish
 94  multiselect tag pops in
 95  number input steppers press
 96  file uploader dashed border marches
 97  file uploader icon bobs on hover

Disclosure and data
 98  tab underline glides
 99  tab hover lift
100  tab panel content fades in
101  expander hover lift
102  expander chevron rotates
103  expander content slides down
104  dataframe fades in
105  progress bar stripes travel
106  custom spinner rotation

Feedback
107  alerts slide in from the left
108  error alert shakes once
109  success alert icon pops
110  toast slides in
111  badge hover lift
112  evidenced stamp pops
113  popover and tooltip scale in
114  caption fades in
115  divider draws
116  footer fades up
117  scrollbar thumb lights up on hover
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

MOTION_CSS = r"""
<style>
:root {
  --m-out: cubic-bezier(0.16, 1, 0.3, 1);
  --m-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --m-io: cubic-bezier(0.65, 0, 0.35, 1);
  --m-fast: 160ms;
  --m-mid: 320ms;
  --m-slow: 640ms;
}

@media (prefers-reduced-motion: no-preference) {

/* ===== Page transitions and loading ================================= */
/* 1 */ .block-container.consul-exit { opacity: .35; filter: blur(6px); transform: translateY(10px) scale(.995);
          transition: opacity 180ms var(--m-io), filter 180ms var(--m-io), transform 180ms var(--m-io); }
/* 2 */ .block-container.consul-enter { animation: mPageIn 700ms var(--m-out) backwards; }
        @keyframes mPageIn { from { opacity: 0; filter: blur(10px); transform: translateY(18px) scale(.99); } to { opacity: 1; filter: none; transform: none; } }
/* 3 */ .consul-curtain { position: fixed; top: 0; left: 0; right: 0; height: 2px; z-index: 99990; pointer-events: none;
          background: linear-gradient(90deg, transparent, var(--consul-accent) 40%, #FFD3B8 50%, var(--consul-accent) 60%, transparent);
          transform: translateX(-100%); filter: drop-shadow(0 0 8px var(--consul-accent)); }
        .consul-curtain.run { animation: mCurtain 900ms var(--m-io) forwards; }
        @keyframes mCurtain { to { transform: translateX(100%); } }
/* 4 */ .consul-veil { position: fixed; inset: 0; z-index: 99980; pointer-events: none;
          background: linear-gradient(100deg, color-mix(in srgb, var(--consul-accent) 10%, var(--consul-bg)) 0%, var(--consul-bg) 60%);
          clip-path: inset(0 0 0 100%); }
        .consul-veil.run { animation: mVeil 760ms var(--m-io) forwards; }
        @keyframes mVeil { 0% { clip-path: inset(0 0 0 0); opacity: .55; } 100% { clip-path: inset(0 0 0 100%); opacity: 0; } }
/* 5 */ .stApp[data-test-script-state="running"]::before { content: ""; position: fixed; top: 0; left: 0; height: 2px; width: 100%;
          z-index: 99995; background: var(--consul-accent); transform-origin: left;
          animation: mRunBar 1.6s var(--m-out) forwards; }
        @keyframes mRunBar { from { transform: scaleX(0); } to { transform: scaleX(.85); } }
/* 6 */ .stApp[data-test-script-state="running"] header[data-testid="stHeader"]::after { content: ""; position: fixed; top: 0; left: 0;
          width: 120px; height: 3px; z-index: 99996; border-radius: 2px;
          background: radial-gradient(closest-side, #FFD3B8, transparent); animation: mRunGlow 1.2s var(--m-io) infinite; }
        @keyframes mRunGlow { from { transform: translateX(-120px); } to { transform: translateX(100vw); } }
/* 7 */ [data-stale="true"] { opacity: .55 !important; transition: opacity var(--m-mid) var(--m-io) !important; }
/* 8 */ .block-container > div > [data-testid="stVerticalBlock"] > div { animation: mRise .6s var(--m-out) backwards; }
        .block-container > div > [data-testid="stVerticalBlock"] > div:nth-child(2) { animation-delay: 60ms; }
        .block-container > div > [data-testid="stVerticalBlock"] > div:nth-child(3) { animation-delay: 120ms; }
        .block-container > div > [data-testid="stVerticalBlock"] > div:nth-child(4) { animation-delay: 180ms; }
        .block-container > div > [data-testid="stVerticalBlock"] > div:nth-child(5) { animation-delay: 240ms; }
        .block-container > div > [data-testid="stVerticalBlock"] > div:nth-child(6) { animation-delay: 300ms; }
        .block-container > div > [data-testid="stVerticalBlock"] > div:nth-child(n+7) { animation-delay: 360ms; }
/* 9 */ html.consul-js .m-reveal { opacity: 0; transform: translateY(28px); filter: blur(4px);
          transition: opacity .8s var(--m-out), transform .8s var(--m-out), filter .8s var(--m-out); }
        html.consul-js .m-reveal.m-in { opacity: 1; transform: none; filter: none; }
/* 10 */ [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"] { animation: mSlideR .5s var(--m-out) backwards; }
        [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:nth-child(-n+4) { animation-delay: 40ms; }
        [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:nth-child(n+5):nth-child(-n+8) { animation-delay: 110ms; }
        [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:nth-child(n+9):nth-child(-n+12) { animation-delay: 180ms; }
        [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:nth-child(n+13) { animation-delay: 250ms; }

/* ===== Ambient ====================================================== */
/* 11 */ .stApp { animation: mAurora 28s var(--m-io) infinite alternate; background-size: 120% 120%, 120% 120%, 22px 22px, auto; }
        @keyframes mAurora { 0% { background-position: 0% 0%, 0% 0%, 0 0, 0 0; } 100% { background-position: 8% 6%, -6% -4%, 66px 44px, 0 0; } }
/* 12 */ /* dot grid drifts as the third background layer, see mAurora */
/* 13 */ .stApp::after { inset: -6%; animation: mGrain 1.2s steps(6) infinite; }
        @keyframes mGrain { 0% { transform: translate(0,0); } 20% { transform: translate(-2%,1%); } 40% { transform: translate(1%,-2%); }
          60% { transform: translate(-1%,2%); } 80% { transform: translate(2%,1%); } 100% { transform: translate(0,0); } }
/* 14 */ .consul-cursor-light { position: fixed; left: 0; top: 0; width: 520px; height: 520px; margin: -260px 0 0 -260px;
          border-radius: 50%; pointer-events: none; z-index: 1; opacity: 0;
          background: radial-gradient(closest-side, color-mix(in srgb, var(--consul-accent) 9%, transparent), transparent);
          transition: opacity .6s var(--m-io); will-change: transform; }
        .consul-cursor-light.on { opacity: 1; }
/* 15 */ .consul-hero { isolation: isolate; }
        .consul-hero > .consul-hero-ring { position: absolute; inset: -1px; border-radius: inherit; padding: 1px; pointer-events: none; z-index: -1;
          background: conic-gradient(from var(--m-angle, 0deg), transparent 0 70%, var(--consul-accent) 80%, transparent 90%);
          -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor; mask-composite: exclude;
          animation: mSpinAngle 9s linear infinite; opacity: .7; }
        @property --m-angle { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
        @keyframes mSpinAngle { to { --m-angle: 360deg; } }
/* 16 */ .consul-hero::before { animation: mHeroGrid 18s linear infinite; }
        @keyframes mHeroGrid { to { background-position: 64px 0; } }
/* 17 */ .consul-hero::after { content: ""; position: absolute; inset: 0; pointer-events: none; z-index: -1; opacity: 0;
          background: radial-gradient(360px circle at var(--mx, 50%) var(--my, 50%), color-mix(in srgb, var(--consul-accent) 14%, transparent), transparent 70%);
          transition: opacity var(--m-mid) var(--m-io); }
        .consul-hero:hover::after { opacity: 1; }
/* 18 */ .consul-page-index { transform: translateY(calc(var(--m-scroll, 0) * 0.25px)); transition: transform 80ms linear; }
/* 19 */ .consul-page-index { animation: mOutline 1.4s var(--m-out) .2s backwards; }
        @keyframes mOutline { from { opacity: 0; letter-spacing: .1em; -webkit-text-stroke-color: transparent; } to { opacity: 1; } }

/* ===== Typography =================================================== */
/* 20 */ .m-char { display: inline-block; white-space: pre; animation: mChar .7s var(--m-out) backwards; animation-delay: calc(var(--c) * 22ms + 120ms); }
        @keyframes mChar { from { opacity: 0; transform: translateY(0.45em) rotate(4deg); filter: blur(4px); } to { opacity: 1; transform: none; filter: none; } }
/* 21 */ .consul-eyebrow { animation: mType 900ms steps(28, end) backwards; }
        @keyframes mType { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
/* 22 */ .consul-page-head .consul-eyebrow::after, .consul-hero .consul-eyebrow::after { content: ""; display: inline-block; width: 7px; height: 12px;
          margin-left: 4px; vertical-align: -1px; background: var(--consul-accent); animation: mCaret 1s steps(1) 6 backwards, mFadeOut .4s 6s forwards; }
        @keyframes mCaret { 50% { opacity: 0; } }
        @keyframes mFadeOut { to { opacity: 0; } }
/* 23 */ .consul-eyebrow i { display: inline-block; animation: mSlash .6s var(--m-spring) both .5s; }
        @keyframes mSlash { from { transform: rotate(-90deg) scale(.4); opacity: 0; } }
/* 24 */ .m-word { display: inline-block; animation: mWord .8s var(--m-out) backwards; animation-delay: calc(var(--w) * 70ms + 150ms); }
        @keyframes mWord { from { opacity: 0; transform: translateY(40%) skewY(4deg); filter: blur(6px); } to { opacity: 1; transform: none; filter: none; } }
/* 25 */ .consul-hero h1 em { background-size: 200% 100%; animation: mPan 6s var(--m-io) infinite alternate; }
        @keyframes mPan { from { background-position: 0% 50%; } to { background-position: 100% 50%; } }
/* 26 */ .consul-hero p, .consul-page-sub { animation: mBlurIn .9s var(--m-out) .35s backwards; }
        @keyframes mBlurIn { from { opacity: 0; filter: blur(8px); } to { opacity: 1; filter: none; } }
/* 27 */ .consul-section-head { position: relative; }
        .consul-section-head::after { content: ""; position: absolute; left: 0; bottom: -6px; height: 1px; width: 100%;
          background: linear-gradient(90deg, var(--consul-border-strong), transparent); transform-origin: left; animation: mGrowX 1s var(--m-out) .2s backwards; }
/* 28 */ h5 { background: linear-gradient(var(--consul-accent), var(--consul-accent)) left bottom / 0 1px no-repeat; animation: mH5 1s var(--m-out) .2s forwards; }
        @keyframes mH5 { to { background-size: 48px 1px; } }
/* 29 */ .block-container a:not([data-testid]) { background: linear-gradient(currentColor, currentColor) left 100% / 0 1px no-repeat; text-decoration: none;
          transition: background-size var(--m-mid) var(--m-out); }
        .block-container a:not([data-testid]):hover { background-size: 100% 1px; }
/* 30 */ .m-count { display: inline-block; animation: mPop .5s var(--m-spring) backwards; }

/* ===== Dashboard pieces ============================================= */
/* 31 */ .consul-dial-fill { animation: mDial 1.6s var(--m-out) .3s backwards; }
        @keyframes mDial { from { stroke-dashoffset: var(--dial-from); } }
/* 32 */ .consul-dial-ticks { transform-origin: 90px 90px; animation: mSpin 60s linear infinite; }
/* 33 */ .consul-dial::after { content: ""; position: absolute; left: 50%; top: 50%; width: 6px; height: 6px; margin: -3px; border-radius: 50%;
          background: #FFD3B8; box-shadow: 0 0 10px 2px var(--consul-accent); animation: mOrbit 7s linear infinite; }
        @keyframes mOrbit { from { transform: rotate(0deg) translateY(-98px); } to { transform: rotate(360deg) translateY(-98px); } }
/* 34 */ .consul-dial-center b { animation: mGlow 3.2s var(--m-io) infinite; }
        @keyframes mGlow { 50% { text-shadow: 0 0 24px color-mix(in srgb, var(--consul-accent) 55%, transparent); } }
/* 35 */ .consul-dial { animation: mSpringIn .9s var(--m-spring) .15s backwards; }
        @keyframes mSpringIn { from { opacity: 0; transform: scale(.6) rotate(-30deg); } to { opacity: 1; transform: none; } }
/* 36 */ .consul-hero-chips span { animation: mRise .6s var(--m-out) backwards; }
        .consul-hero-chips span:nth-child(1) { animation-delay: .55s; } .consul-hero-chips span:nth-child(2) { animation-delay: .62s; }
        .consul-hero-chips span:nth-child(3) { animation-delay: .69s; }
/* 37 */ .consul-hero-chips span { transition: transform var(--m-mid) var(--m-spring), border-color var(--m-mid), color var(--m-mid); }
        .consul-hero-chips span:hover { transform: translateY(-3px); border-color: color-mix(in srgb, var(--consul-accent) 45%, transparent); color: var(--consul-text); }
/* 38 */ .consul-stat { animation: mRise .7s var(--m-out) backwards; animation-delay: calc(var(--i) * 80ms + 160ms); }
/* 39 */ .consul-stat, .consul-card, .consul-empty, .consul-cv {
          transform: perspective(900px) rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg)) translateY(var(--lift, 0px));
          transition: transform 420ms var(--m-out), border-color var(--m-mid), box-shadow var(--m-mid); }
        .consul-stat:hover { --lift: -4px; transform: perspective(900px) rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg)) translateY(var(--lift)); }
/* 40 */ .consul-stat::after, .consul-card::after, .consul-pipeline::after { content: ""; position: absolute; inset: 0; border-radius: inherit;
          pointer-events: none; opacity: 0; transition: opacity var(--m-mid) var(--m-io);
          background: radial-gradient(260px circle at var(--mx, 50%) var(--my, 50%), color-mix(in srgb, var(--consul-accent) 12%, transparent), transparent 70%); }
        .consul-stat:hover::after, .consul-card:hover::after, .consul-pipeline:hover::after { opacity: 1; }
        .consul-card, .consul-pipeline { position: relative; }
/* 41 */ .consul-stat::before { transform: scaleX(0); transition: transform .5s var(--m-out), opacity .3s; }
        .consul-stat:hover::before { transform: scaleX(1); opacity: 1; }
/* 42 */ .consul-stat:hover .consul-stat-top svg { animation: mWiggle .6s var(--m-io); }
        @keyframes mWiggle { 25% { transform: rotate(-14deg); } 50% { transform: rotate(10deg); } 75% { transform: rotate(-5deg); } }
/* 43 */ .consul-stat-value { animation: mValue .8s var(--m-out) backwards; animation-delay: calc(var(--i) * 80ms + 300ms); }
        @keyframes mValue { from { opacity: 0; transform: translateY(16px); clip-path: inset(100% 0 0 0); } to { opacity: 1; transform: none; clip-path: inset(0); } }
/* 44 */ .consul-pipeline-row { animation: mSlideR .55s var(--m-out) backwards; animation-delay: calc(var(--i) * 70ms + 300ms); }
/* 45 */ .consul-pipeline-fill { animation: mGrowX 1.1s var(--m-out) backwards; animation-delay: calc(var(--i) * 90ms + 450ms); }
/* 46 */ .consul-pipeline-fill::after { animation: mShimmer 2.8s var(--m-io) 1.8s infinite; }
        @keyframes mShimmer { 0% { transform: translateX(-100%); } 60%, 100% { transform: translateX(100%); } }
/* 47 */ .consul-pipeline-value { animation: mPop .5s var(--m-spring) backwards; animation-delay: calc(var(--i) * 90ms + 700ms); }
/* 48 */ .consul-pipeline-row { border-radius: 8px; transition: background-color var(--m-fast), transform var(--m-mid) var(--m-out); }
        .consul-pipeline-row:hover { background: color-mix(in srgb, var(--consul-text) 3%, transparent); transform: translateX(4px); }
/* 49 */ .consul-step { animation: mSlideR .55s var(--m-out) backwards; }
        .consul-step:nth-child(1) { animation-delay: .25s; } .consul-step:nth-child(2) { animation-delay: .32s; }
        .consul-step:nth-child(3) { animation-delay: .39s; } .consul-step:nth-child(4) { animation-delay: .46s; }
        .consul-step:nth-child(5) { animation-delay: .53s; }
/* 50 */ .consul-step { transition: background-color var(--m-mid), transform var(--m-mid) var(--m-out); }
        .consul-step:hover { transform: translateX(5px); }
/* 51 */ .consul-step.next .consul-step-mark { animation: mRing 2.4s var(--m-io) infinite; }
        @keyframes mRing { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--consul-accent) 55%, transparent); } 70%, 100% { box-shadow: 0 0 0 14px transparent; } }
/* 52 */ .consul-step.done .consul-step-mark { animation: mPop .6s var(--m-spring) .6s backwards; }
/* 53 */ .consul-step-mark { transition: transform var(--m-mid) var(--m-spring); }
        .consul-step:hover .consul-step-mark { transform: rotate(-8deg) scale(1.06); }
/* 54 */ .consul-stepper::before { transform-origin: top; animation: mGrowY 1.2s var(--m-out) .2s backwards; }
/* 55 */ .consul-cal { transform-origin: top; animation: mFlip .8s var(--m-spring) .4s backwards; }
        @keyframes mFlip { from { opacity: 0; transform: perspective(300px) rotateX(-80deg); } to { opacity: 1; transform: none; } }
/* 56 */ .consul-kv { transition: padding var(--m-mid) var(--m-out), background-color var(--m-fast); }
        .consul-kv:hover { padding-left: 6px; padding-right: 6px; background: color-mix(in srgb, var(--consul-text) 3%, transparent); }
/* 57  spotlight shared with 40 */
/* 58  tilt shared with 39, driven by JS for .consul-card */
/* 59 */ .consul-card:hover { --lift: -3px; }

/* ===== Empty states and documents =================================== */
/* 59b */ .consul-empty { animation: mRise .6s var(--m-out) .1s backwards; }
/* 60 */ .consul-empty-art .s1 { animation: mFloat 6s var(--m-io) infinite; }
        .consul-empty-art .s2 { animation: mFloat 6s var(--m-io) -2s infinite; }
        @keyframes mFloat { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
/* 61 */ .consul-empty:hover .s2 { animation: none; transform: translate(8px, -3px) rotate(3deg); }
        .consul-empty:hover .s3 { transform: translate(16px, -5px) rotate(6deg); }
/* 62 */ .consul-empty-art .stamp { animation: mStamp .7s var(--m-spring) .6s backwards; }
        @keyframes mStamp { from { opacity: 0; transform: scale(2.2) rotate(14deg); } 60% { opacity: 1; } to { opacity: 1; transform: none; } }
/* 63 */ .consul-empty:hover .stamp { animation: mWobble .7s var(--m-io); }
        @keyframes mWobble { 25% { transform: rotate(-6deg); } 50% { transform: rotate(4deg); } 75% { transform: rotate(-2deg); } }
/* 64 */ .consul-empty-art .s1 rect + rect { transform-origin: left; transform-box: fill-box; animation: mGrowX .7s var(--m-out) backwards; }
        .consul-empty-art .s1 rect:nth-child(3) { animation-delay: .35s; } .consul-empty-art .s1 rect:nth-child(4) { animation-delay: .42s; }
        .consul-empty-art .s1 rect:nth-child(5) { animation-delay: .49s; } .consul-empty-art .s1 rect:nth-child(6) { animation-delay: .56s; }
        .consul-empty-art .s1 rect:nth-child(7) { animation-delay: .63s; }
/* 65 */ .consul-empty { background-clip: padding-box; }
        .consul-empty:hover { border-color: color-mix(in srgb, var(--consul-accent) 45%, transparent); }
        .consul-empty::before { content: ""; position: absolute; inset: -1px; border-radius: inherit; pointer-events: none; opacity: 0;
          background: repeating-linear-gradient(90deg, var(--consul-accent) 0 6px, transparent 6px 12px) top / 200% 1px no-repeat,
                      repeating-linear-gradient(90deg, var(--consul-accent) 0 6px, transparent 6px 12px) bottom / 200% 1px no-repeat;
          transition: opacity var(--m-mid); }
        .consul-empty:hover::before { opacity: .7; animation: mMarch 1.2s linear infinite; }
        @keyframes mMarch { to { background-position: 12px 0, -12px 100%; } }
/* 66 */ .consul-cv { animation: mPaper .9s var(--m-out) backwards; }
        @keyframes mPaper { from { opacity: 0; transform: translateY(30px) rotate(-1deg); box-shadow: 0 0 0 rgba(0,0,0,0); } to { opacity: 1; } }
/* 67  CV tilt driven by JS via 39 */

/* ===== Navigation =================================================== */
/* 68 */ [data-testid="stSidebar"] .stButton > button [data-testid="stIconMaterial"] { transition: transform var(--m-mid) var(--m-spring), color var(--m-fast); }
        [data-testid="stSidebar"] .stButton > button:hover [data-testid="stIconMaterial"] { transform: translateX(3px) scale(1.08); }
/* 69 */ [data-testid="stSidebar"] .stButton > button[kind="primary"]::before { transform-origin: center; animation: mGrowY .5s var(--m-spring) backwards; }
/* 70 */ [data-testid="stSidebar"] .stButton > button[kind="primary"] { background-size: 200% 100% !important; animation: mSweep .6s var(--m-out) backwards; }
        @keyframes mSweep { from { background-position: 100% 0; } to { background-position: 0 0; } }
/* 71 */ .consul-nav-label::before { display: inline-block; margin-right: 4px; transition: transform var(--m-mid) var(--m-out); transform-origin: left; }
        [data-testid="stSidebarUserContent"]:hover .consul-nav-label::before { transform: scaleX(1.8); }
/* 72 */ .consul-brandmark .mark { animation: mBreath 4s var(--m-io) infinite; }
        @keyframes mBreath { 50% { box-shadow: 0 6px 26px -2px color-mix(in srgb, var(--consul-accent) 80%, transparent), inset 0 1px 0 rgba(255,255,255,.35); } }
/* 73 */ .consul-brandmark .mark { transition: transform .6s var(--m-spring); }
        .consul-brandmark:hover .mark { transform: rotate(354deg) scale(1.08); }
/* 74 */ .consul-avatar { position: relative; }
        .consul-avatar::after { content: ""; position: absolute; inset: -3px; border-radius: 50%; border: 1px dashed color-mix(in srgb, var(--consul-accent) 55%, transparent);
          animation: mSpin 14s linear infinite; }
/* 75 */ [data-testid="stSidebarCollapseButton"] button { transition: transform var(--m-mid) var(--m-spring); }
        [data-testid="stSidebarCollapseButton"] button:hover { transform: translateX(-3px) scale(1.1); }
/* 76 */ .consul-page-icon { animation: mSpringIn .8s var(--m-spring) .1s backwards; }
/* 77 */ .consul-page-icon svg { transition: transform .5s var(--m-spring); }
        .consul-page-head:hover .consul-page-icon svg { transform: translateY(-3px) rotate(-8deg) scale(1.1); }

/* ===== Buttons and controls ========================================= */
/* 78 */ .consul-ripple { position: absolute; border-radius: 50%; pointer-events: none; transform: scale(0); opacity: .45;
          background: currentColor; animation: mRipple .65s var(--m-out) forwards; }
        @keyframes mRipple { to { transform: scale(1); opacity: 0; } }
        .stButton > button, .stFormSubmitButton > button, .stDownloadButton > button { position: relative; overflow: hidden; }
/* 79 */ .block-container .stButton > button[kind="primary"] { transform: translate(var(--tx, 0px), var(--ty, 0px)); }
/* 80 */ .block-container .stButton > button[kind="primary"]::after, .stFormSubmitButton > button[kind="primary"]::after {
          content: ""; position: absolute; top: 0; bottom: 0; width: 40%; left: -60%; pointer-events: none;
          background: linear-gradient(100deg, transparent, rgba(255,255,255,.45), transparent); transform: skewX(-20deg); }
        .block-container .stButton > button[kind="primary"]:hover::after, .stFormSubmitButton > button[kind="primary"]:hover::after { animation: mSheen .8s var(--m-out); }
        @keyframes mSheen { to { left: 130%; } }
/* 81 */ .stButton > button:active, .stFormSubmitButton > button:active, .stDownloadButton > button:active { transform: scale(.96) !important; transition-duration: 80ms !important; }
/* 82 */ .block-container .stButton > button[kind="secondary"]:hover { border-color: color-mix(in srgb, var(--consul-accent) 50%, transparent);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--consul-accent) 12%, transparent), 0 8px 20px -12px var(--consul-accent); }
/* 83 */ .block-container .stButton > button p { transition: transform var(--m-mid) var(--m-spring); }
        .block-container .stButton > button:hover p { transform: translateX(2px); }
/* 84 */ .stDownloadButton > button:hover [data-testid="stIconMaterial"], .stDownloadButton > button:hover svg { animation: mDrop .7s var(--m-io) infinite; }
        @keyframes mDrop { 50% { transform: translateY(3px); } }
/* 85 */ [data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { transition: box-shadow var(--m-mid) var(--m-out), border-color var(--m-mid); }
        [data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within { box-shadow: 0 0 0 4px color-mix(in srgb, var(--consul-accent) 18%, transparent) !important; }
/* 86 */ [data-testid="stWidgetLabel"] { transition: transform var(--m-mid) var(--m-out), color var(--m-mid); transform-origin: left; }
        [data-testid="stTextInput"]:focus-within [data-testid="stWidgetLabel"], [data-testid="stTextArea"]:focus-within [data-testid="stWidgetLabel"],
        [data-testid="stNumberInput"]:focus-within [data-testid="stWidgetLabel"] { transform: translateY(-2px); }
        [data-testid="stTextInput"]:focus-within [data-testid="stWidgetLabel"] p, [data-testid="stTextArea"]:focus-within [data-testid="stWidgetLabel"] p { color: var(--consul-accent-ink) !important; }
/* 87 */ [data-baseweb="popover"] > div, [data-baseweb="menu"] { animation: mMenu .22s var(--m-out) backwards; transform-origin: top; }
        @keyframes mMenu { from { opacity: 0; transform: translateY(-6px) scale(.97); } to { opacity: 1; transform: none; } }
/* 88 */ [data-baseweb="menu"] li { animation: mRise .3s var(--m-out) backwards; }
        [data-baseweb="menu"] li:nth-child(2) { animation-delay: 25ms; } [data-baseweb="menu"] li:nth-child(3) { animation-delay: 50ms; }
        [data-baseweb="menu"] li:nth-child(4) { animation-delay: 75ms; } [data-baseweb="menu"] li:nth-child(n+5) { animation-delay: 100ms; }
/* 89 */ [data-baseweb="slider"] [role="slider"] { transition: transform var(--m-mid) var(--m-spring), box-shadow var(--m-mid); }
        [data-baseweb="slider"] [role="slider"]:hover { transform: scale(1.25); box-shadow: 0 0 0 6px color-mix(in srgb, var(--consul-accent) 18%, transparent); }
/* 90 */ [data-baseweb="slider"] [role="slider"]:active { transform: scale(.9); }
/* 91 */ [data-testid="stCheckbox"] input:checked + div, [data-baseweb="checkbox"] input:checked ~ span { animation: mPop .4s var(--m-spring); }
/* 92 */ [data-baseweb="radio"] input:checked + div { animation: mPop .4s var(--m-spring); }
/* 93 */ [data-testid="stCheckbox"] label:active [role="checkbox"] > div, [data-baseweb="checkbox"]:active > div > div { transform: scaleX(1.25); transition: transform .12s; }
/* 94 */ [data-baseweb="tag"] { animation: mPop .35s var(--m-spring) backwards; }
/* 95 */ [data-testid="stNumberInputStepDown"]:active, [data-testid="stNumberInputStepUp"]:active { transform: scale(.85); }
        [data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] { transition: transform .12s var(--m-out); }
/* 96 */ [data-testid="stFileUploaderDropzone"] { background-image: none !important; position: relative; }
        [data-testid="stFileUploaderDropzone"]:hover { animation: mDashPulse 1.6s var(--m-io) infinite; }
        @keyframes mDashPulse { 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--consul-accent) 14%, transparent); } }
/* 97 */ [data-testid="stFileUploaderDropzone"]:hover button [data-testid="stIconMaterial"], [data-testid="stFileUploaderDropzone"]:hover svg { animation: mBob 1s var(--m-io) infinite; }
        @keyframes mBob { 50% { transform: translateY(-3px); } }

/* ===== Disclosure and data ========================================== */
/* 98 */ .stTabs [data-baseweb="tab-highlight"] { transition: transform .45s var(--m-out), width .45s var(--m-out) !important; }
/* 99 */ .stTabs [data-baseweb="tab"] { transition: color var(--m-fast), transform var(--m-mid) var(--m-out); }
        .stTabs [data-baseweb="tab"]:hover { transform: translateY(-2px); color: var(--consul-text); }
/* 100 */ .stTabs [data-baseweb="tab-panel"] { animation: mBlurRise .5s var(--m-out) backwards; }
        @keyframes mBlurRise { from { opacity: 0; transform: translateY(10px); filter: blur(4px); } to { opacity: 1; transform: none; filter: none; } }
/* 101 */ [data-testid="stExpander"] { transition: transform var(--m-mid) var(--m-out), border-color var(--m-mid), box-shadow var(--m-mid); }
        [data-testid="stExpander"]:hover { transform: translateY(-2px); border-color: var(--consul-border-strong) !important; box-shadow: 0 14px 30px -22px rgba(0,0,0,.7); }
/* 102 */ [data-testid="stExpander"] summary svg, [data-testid="stExpander"] summary [data-testid="stIconMaterial"] { transition: transform var(--m-mid) var(--m-spring); }
        [data-testid="stExpander"] details[open] > summary [data-testid="stExpanderToggleIcon"] { transform: rotate(0deg); }
        [data-testid="stExpander"] summary:hover [data-testid="stIconMaterial"] { transform: scale(1.2); color: var(--consul-accent); }
/* 103 */ [data-testid="stExpander"] details[open] [data-testid="stExpanderDetails"] { animation: mDown .4s var(--m-out) backwards; }
        @keyframes mDown { from { opacity: 0; transform: translateY(-8px); clip-path: inset(0 0 100% 0); } to { opacity: 1; transform: none; clip-path: inset(0); } }
/* 104 */ [data-testid="stDataFrame"] { animation: mBlurRise .7s var(--m-out) .1s backwards; }
/* 105 */ .stProgress > div > div > div > div { background-image: repeating-linear-gradient(-45deg, rgba(255,255,255,.18) 0 8px, transparent 8px 16px) !important;
          background-size: 22px 22px !important; animation: mStripes .8s linear infinite; transition: width .5s var(--m-out); }
        @keyframes mStripes { to { background-position: 22px 0; } }
/* 106 */ [data-testid="stSpinner"] i, .stSpinner > div > i { animation: mSpin .8s var(--m-io) infinite !important; border-top-color: var(--consul-accent) !important; }

/* ===== Feedback ===================================================== */
/* 107 */ [data-testid="stAlert"] { animation: mSlideR .5s var(--m-out) backwards; }
/* 108 */ [data-testid="stAlert"]:has([data-testid="stAlertContentError"]) { animation: mSlideR .5s var(--m-out) backwards, mShake .5s var(--m-io) .5s; }
        @keyframes mShake { 20%, 60% { transform: translateX(-5px); } 40%, 80% { transform: translateX(5px); } }
/* 109 */ [data-testid="stAlertContentSuccess"] [data-testid="stIconMaterial"], [data-testid="stAlert"] svg { animation: mPop .5s var(--m-spring) .3s backwards; }
/* 110 */ [data-testid="stToast"] { animation: mToast .5s var(--m-spring) backwards; }
        @keyframes mToast { from { opacity: 0; transform: translateX(40px) scale(.95); } to { opacity: 1; transform: none; } }
/* 111 */ .consul-badge { transition: transform var(--m-mid) var(--m-spring), filter var(--m-mid); }
        .consul-badge:hover { transform: translateY(-2px); filter: brightness(1.15); }
/* 112 */ .consul-stamp { animation: mStampSmall .5s var(--m-spring) backwards; }
        @keyframes mStampSmall { from { opacity: 0; transform: scale(1.6) rotate(-8deg); } to { opacity: 1; transform: none; } }
/* 113 */ [data-testid="stTooltipContent"], [data-baseweb="tooltip"] { animation: mMenu .2s var(--m-out) backwards; }
/* 114 */ [data-testid="stCaptionContainer"] { animation: mBlurIn .7s var(--m-out) .2s backwards; }
/* 115 */ .consul-divider { transform-origin: left; animation: mGrowX .9s var(--m-out) backwards; }
/* 116 */ .consul-app-footer { animation: mRise .8s var(--m-out) .5s backwards; }
/* 117 */ * { scrollbar-width: thin; scrollbar-color: var(--consul-border-strong) transparent; }
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-thumb { background: var(--consul-border-strong); border-radius: 10px; border: 3px solid transparent; background-clip: padding-box;
          transition: background-color var(--m-mid); }
        ::-webkit-scrollbar-thumb:hover { background-color: var(--consul-accent); }

/* ===== Shared keyframes ============================================= */
@keyframes mRise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
@keyframes mSlideR { from { opacity: 0; transform: translateX(-14px); } to { opacity: 1; transform: none; } }
@keyframes mPop { from { opacity: 0; transform: scale(.5); } to { opacity: 1; transform: none; } }
@keyframes mGrowX { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes mGrowY { from { transform: scaleY(0); } to { transform: scaleY(1); } }
@keyframes mSpin { to { transform: rotate(360deg); } }
}

/* Hidden host for the motion script */
[data-testid="stElementContainer"]:has(iframe[height="0"]), [data-testid="stElementContainer"]:has(.consul-route),
[data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] style) { position: absolute !important; width: 0 !important; height: 0 !important; overflow: hidden; }

@media (prefers-reduced-motion: reduce) {
  .consul-cursor-light, .consul-curtain, .consul-veil { display: none !important; }
}
</style>
"""

MOTION_JS = r"""
<script>
(function () {
  const W = window.parent, D = W.document;
  const reduce = W.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = W.matchMedia('(pointer: fine)').matches;
  const routeOf = () => (D.querySelector('.consul-route') || {}).dataset?.page || '';
  const M = W.__consulMotion = W.__consulMotion || { route: routeOf() };
  // Streamlit can replace this iframe on rerun; only the newest generation acts.
  const gen = M.gen = (M.gen || 0) + 1;
  const live = () => M.gen === gen;
  D.documentElement.classList.add('consul-js');
  if (reduce) return;

  const one = (cls) => D.querySelector('.' + cls) || D.body.appendChild(Object.assign(D.createElement('div'), { className: cls }));
  const curtain = one('consul-curtain'), veil = one('consul-veil');                       // 3, 4

  function play() {                                                                      // 2, 3, 4
    [curtain, veil].forEach(el => { el.classList.remove('run'); void el.offsetWidth; el.classList.add('run'); });
    const bc = D.querySelector('.block-container');
    if (bc) { bc.classList.remove('consul-exit', 'consul-enter'); void bc.offsetWidth; bc.classList.add('consul-enter');
      setTimeout(() => bc.classList.remove('consul-enter'), 800); }
  }

  const on = (t, type, fn, opt) => t.addEventListener(type, e => { if (live()) fn(e); }, opt);

  on(D, 'click', e => {                                                                  // 1
    const btn = e.target.closest('[data-testid="stSidebar"] .stButton > button');
    if (btn && btn.getAttribute('kind') !== 'primary') {
      const bc = D.querySelector('.block-container'); if (!bc) return;
      bc.classList.add('consul-exit'); setTimeout(() => bc.classList.remove('consul-exit'), 1500);
    }
  }, true);

  on(D, 'pointerdown', e => {                                                            // 78
    const b = e.target.closest('.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button');
    if (!b) return;
    const r = b.getBoundingClientRect(), s = Math.max(r.width, r.height) * 2.2;
    const rp = D.createElement('span'); rp.className = 'consul-ripple';
    rp.style.cssText = `width:${s}px;height:${s}px;left:${e.clientX - r.left - s / 2}px;top:${e.clientY - r.top - s / 2}px`;
    b.appendChild(rp); setTimeout(() => rp.remove(), 700);
  });

  if (fine) {
    const light = one('consul-cursor-light');                                             // 14
    let tx = M.tx ?? -999, ty = M.ty ?? -999, x = tx, y = ty;
    on(D, 'pointermove', e => { M.tx = tx = e.clientX; M.ty = ty = e.clientY; light.classList.add('on'); });
    on(D.documentElement, 'pointerleave', () => light.classList.remove('on'));
    (function loop() { if (!live()) return; x += (tx - x) * .12; y += (ty - y) * .12;
      light.style.transform = `translate3d(${x}px,${y}px,0)`; W.requestAnimationFrame(loop); })();

    const TILT = '.consul-stat, .consul-card, .consul-empty, .consul-cv, .consul-hero, .consul-pipeline';
    on(D, 'pointermove', e => {                                                          // 17, 39, 40, 57, 58, 67
      const el = e.target.closest(TILT); if (!el) return;
      const r = el.getBoundingClientRect(), px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
      el.style.setProperty('--mx', (px * 100) + '%'); el.style.setProperty('--my', (py * 100) + '%');
      if (!el.matches('.consul-hero, .consul-pipeline')) {
        const k = el.matches('.consul-cv') ? 2 : (el.matches('.consul-empty') ? 3 : 6);
        el.style.setProperty('--rx', ((.5 - py) * k) + 'deg'); el.style.setProperty('--ry', ((px - .5) * k) + 'deg');
      }
    });
    on(D, 'pointerout', e => {
      const el = e.target.closest(TILT);
      if (el && !el.contains(e.relatedTarget)) { el.style.setProperty('--rx', '0deg'); el.style.setProperty('--ry', '0deg'); }
    });

    on(D, 'pointermove', e => {                                                          // 79
      D.querySelectorAll('.block-container .stButton > button[kind="primary"]').forEach(b => {
        const r = b.getBoundingClientRect(), dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
        const near = Math.hypot(dx, dy) < 120;
        b.style.setProperty('--tx', near ? (dx * .18) + 'px' : '0px'); b.style.setProperty('--ty', near ? (dy * .25) + 'px' : '0px');
      });
    });
  }

  const main = D.querySelector('[data-testid="stMain"]');                                // 18
  if (main) on(main, 'scroll', () => D.documentElement.style.setProperty('--m-scroll', main.scrollTop), { passive: true });

  const io = new W.IntersectionObserver(entries => entries.forEach(en => {               // 9
    if (en.isIntersecting) { en.target.classList.add('m-in'); io.unobserve(en.target); }
  }), { rootMargin: '0px 0px -8% 0px' });

  function countUp(el) {                                                                 // 30
    if (el.dataset.mCounted) return; el.dataset.mCounted = '1';
    const m = el.textContent.trim().match(/^(\d+)/); if (!m || +m[1] === 0) return;
    const target = +m[1], rest = el.innerHTML.slice(el.innerHTML.indexOf(m[1]) + m[1].length);
    const t0 = W.performance.now(), dur = 900 + Math.min(target, 200) * 3;
    (function step(t) { const p = Math.min(1, (t - t0) / dur), k = 1 - Math.pow(1 - p, 4);
      el.innerHTML = Math.round(target * k) + rest; if (p < 1) W.requestAnimationFrame(step); })(t0);
  }

  function splitText(el, cls, varName) {                                                 // 20, 24
    if (el.dataset.mSplit) return; el.dataset.mSplit = '1';
    let i = 0;
    const walk = (node) => [...node.childNodes].forEach(n => {
      if (n.nodeType === 3) {
        const frag = D.createDocumentFragment();
        const parts = cls === 'm-char' ? [...n.textContent] : n.textContent.split(/(\s+)/);
        parts.forEach(part => {
          if (!part) return;
          if (cls === 'm-word' && /^\s+$/.test(part)) { frag.appendChild(D.createTextNode(part)); return; }
          const s = D.createElement('span'); s.className = cls; s.style.setProperty(varName, i++); s.textContent = part; frag.appendChild(s);
        });
        n.replaceWith(frag);
      } else if (n.nodeType === 1 && n.tagName === 'EM' && cls === 'm-word') {
        n.classList.add('m-word'); n.style.setProperty(varName, i++);
      } else if (n.nodeType === 1 && !n.matches('a, svg, button')) walk(n);
    });
    walk(el);
  }

  function decorate() {
    if (!live()) return;
    D.querySelectorAll('.consul-page-title').forEach(el => splitText(el, 'm-char', '--c'));
    D.querySelectorAll('.consul-hero h1').forEach(el => splitText(el, 'm-word', '--w'));
    D.querySelectorAll('.consul-stat-value, .consul-dial-center b, .consul-pipeline-value, .consul-hero-chips b, [data-testid="stMetricValue"] div')
      .forEach(countUp);
    D.querySelectorAll('.consul-hero:not([data-m-ring])').forEach(h => {                  // 15
      h.dataset.mRing = '1'; h.prepend(Object.assign(D.createElement('div'), { className: 'consul-hero-ring' })); });
    const vh = W.innerHeight;
    D.querySelectorAll('.block-container [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:not([data-m-seen]), .block-container [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:not([data-m-seen])')
      .forEach(el => { el.dataset.mSeen = '1';
        if (el.getBoundingClientRect().top > vh * .92) { el.classList.add('m-reveal'); el.dataset.mGen = gen; io.observe(el); } });
    D.querySelectorAll('.m-reveal:not(.m-in):not([data-m-gen="' + gen + '"])').forEach(el => {
      el.dataset.mGen = gen; io.observe(el); });
    const r = routeOf();
    if (r && r !== M.route) { M.route = r; play(); }
  }

  let pending = false;
  const mo = new W.MutationObserver(() => {
    if (!live()) { mo.disconnect(); return; }
    if (pending) return; pending = true;
    W.requestAnimationFrame(() => { pending = false; decorate(); });
  });
  mo.observe(D.body, { childList: true, subtree: true });
  decorate();
})();
</script>
"""


def inject_motion(page: str) -> None:
    """Mount the motion CSS, the route marker and the pointer/transition script."""
    st.markdown(MOTION_CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="consul-route" data-page="{page}" hidden></div>', unsafe_allow_html=True)
    components.html(MOTION_JS, height=0)
