"""In-app PDF preview that cannot be blocked by the browser.

The previous preview embedded the PDF as a ``data:application/pdf;base64,…``
iframe. Chrome, Edge, Opera, Brave and Safari refuse to navigate a frame to a
``data:`` URL for security reasons, so the panel rendered an error such as
"Opera can't open this file" instead of the document — and Firefox blocks the
same thing when opened as a top-level link.

Rendering the pages to images with PyMuPDF sidesteps the whole class of problem:
no data URL, no PDF plugin, no viewer preference, no download prompt. What you
see is exactly what was exported.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.logging_config import get_logger

logger = get_logger("pdf_preview")

PREVIEW_DPI = 120
MAX_PREVIEW_PAGES = 8


def page_images(path: str | Path, *, dpi: int = PREVIEW_DPI,
                max_pages: int = MAX_PREVIEW_PAGES) -> tuple[list[bytes], int]:
    """Render each page of a PDF to PNG. Returns (images, total page count)."""
    import pymupdf

    with pymupdf.open(str(path)) as document:
        total = document.page_count
        images = [
            page.get_pixmap(dpi=dpi).tobytes("png")
            for index, page in enumerate(document)
            if index < max_pages
        ]
    return images, total


def show_pdf_preview(path: str | Path, *, caption: str = "") -> bool:
    """Show every page of the PDF inline. False when it cannot be rendered."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        images, total = page_images(path)
    except Exception as exc:  # a corrupt export must not break the page
        logger.warning("PDF preview failed for %s: %s", path.name, exc)
        return False
    if not images:
        return False

    for index, image in enumerate(images, start=1):
        st.image(image, caption=f"Page {index} of {total}", width="stretch")
    if total > len(images):
        st.caption(f"Showing the first {len(images)} of {total} pages. Download the PDF to see all of them.")
    if caption:
        st.caption(caption)
    return True
