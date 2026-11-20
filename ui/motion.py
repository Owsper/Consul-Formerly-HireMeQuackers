"""Motion layer for the consul workspace.

A small, purposeful subset of consul-redesign-motion.patch, kept within the
unslop rules: motion only where it explains a change, one easing curve, short
durations, nothing that loops, nothing that follows the pointer.

1  readiness dial fills to its value once
2  pipeline bars grow to their value once
3  figures count up to their value (dial, stat tiles, pipeline)
4  dropdown menus and popovers fade and rise a few pixels
5  tab panels fade in when switched
6  expander content slides down when opened
7  alerts slide in once from the left
8  buttons press down slightly (already in theme.py)

``prefers-reduced-motion: reduce`` switches all of it off, including the
count-up script.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

MOTION_CSS = """
<style>
:root { --m-ease: cubic-bezier(0.22, 1, 0.36, 1); }

@media (prefers-reduced-motion: no-preference) {
  /* 1 */ .consul-dial-fill { animation: mDial 600ms var(--m-ease) 150ms backwards; }
          @keyframes mDial { from { stroke-dashoffset: var(--dial-from); } }
  /* 2 */ .consul-pipeline-fill { transform-origin: left; animation: mGrow 500ms var(--m-ease) 150ms backwards; }
          @keyframes mGrow { from { transform: scaleX(0); } }
  /* 4 */ [data-baseweb="popover"] > div { animation: mMenu 180ms var(--m-ease) backwards; }
          @keyframes mMenu { from { opacity: 0; transform: translateY(-4px); } }
  /* 5 */ .stTabs [data-baseweb="tab-panel"] { animation: mFade 200ms var(--m-ease) backwards; }
          @keyframes mFade { from { opacity: 0; } }
  /* 6 */ [data-testid="stExpander"] details[open] [data-testid="stExpanderDetails"] { animation: mDown 220ms var(--m-ease) backwards; }
          @keyframes mDown { from { opacity: 0; transform: translateY(-6px); } }
  /* 7 */ [data-testid="stAlert"] { animation: mSlide 300ms var(--m-ease) backwards; }
          @keyframes mSlide { from { opacity: 0; transform: translateX(-8px); } }
}

/* The count-up script mounts in a zero-height component; keep it out of the layout. */
[data-testid="stElementContainer"]:has(iframe.stIFrame),
[data-testid="stElementContainer"]:has(style) {
  position: absolute !important; width: 0 !important; height: 0 !important; overflow: hidden;
}
</style>
"""

# 3: tween each figure from 0 to its rendered value once.
COUNT_UP_JS = """
<script>
(function () {
  let W, D;
  try { W = window.parent; D = W.document; } catch (e) { return; }
  if (W.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  function run() {
    D.querySelectorAll('.consul-stat-value, .consul-dial-center b, .consul-pipeline-value').forEach(function (el) {
      if (el.dataset.mCounted) return;
      el.dataset.mCounted = '1';
      const node = el.firstChild;
      if (!node || node.nodeType !== 3 || !/^\\d+$/.test(node.textContent.trim())) return;
      const target = +node.textContent.trim();
      if (!target) return;
      const t0 = W.performance.now();
      (function step(t) {
        const p = Math.min(1, (t - t0) / 600), k = 1 - Math.pow(1 - p, 3);
        node.textContent = String(Math.round(target * k));
        if (p < 1) W.requestAnimationFrame(step);
      })(t0);
    });
  }
  run(); setTimeout(run, 300); setTimeout(run, 1000);
})();
</script>
"""


def inject_motion(page: str = "") -> None:
    """Mount the motion CSS and the count-up script. ``page`` is kept for call compatibility."""
    st.markdown(MOTION_CSS, unsafe_allow_html=True)
    components.html(COUNT_UP_JS, height=0)
