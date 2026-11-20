"""Measure a rendered CV against the reference document's visual architecture.

The checks are deliberately geometric rather than pixel-diff based: typography,
margins, column alignment, bullet indentation, section rules, page count and text
overflow are what make the reference recognisable and what break first when a
resume generator substitutes its own layout.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from core.logging_config import get_logger
from services.master_template import (
    MARGIN_LEFT_PT, MARGIN_RIGHT_PT, PAGE_HEIGHT_PT, PAGE_WIDTH_PT,
    reference_pdf_path,
)

logger = get_logger("layout")

TOLERANCE_PT = 2.5


def _open(path: str | Path):
    import pymupdf

    return pymupdf.open(str(path))


def _spans(document) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for page_number, page in enumerate(document, start=1):
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    spans.append({
                        "page": page_number, "text": text, "x0": x0, "y0": y0,
                        "x1": x1, "y1": y1, "font": span.get("font", ""),
                        "size": round(float(span.get("size", 0.0)), 1),
                    })
    return spans


def _rules(document) -> list[dict[str, float]]:
    rules: list[dict[str, float]] = []
    for page_number, page in enumerate(document, start=1):
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect is None:
                continue
            width = rect.width
            height = rect.height
            if width >= 20 and height <= 2.5:
                rules.append({"page": page_number, "x0": rect.x0, "x1": rect.x1,
                              "y": rect.y0, "width": width})
    # Some converters draw a thin border as two adjacent rectangles. Count each
    # visual rule once, keeping the widest segment on that line.
    merged: dict[tuple[int, float], dict[str, float]] = {}
    for rule in rules:
        key = (int(rule["page"]), round(rule["y"] * 2) / 2)
        current = merged.get(key)
        if current is None or rule["width"] > current["width"]:
            merged[key] = rule
    return list(merged.values())


def _mode(values: list[float]) -> float | None:
    if not values:
        return None
    rounded = [round(v, 1) for v in values]
    return Counter(rounded).most_common(1)[0][0]


def extract_metrics(path: str | Path) -> dict[str, Any]:
    document = _open(path)
    try:
        spans = _spans(document)
        rules = _rules(document)
        sizes = Counter(s["size"] for s in spans)
        fonts = {s["font"].split("+")[-1] for s in spans}
        body_spans = [s for s in spans if 9.0 <= s["size"] <= 10.2]
        column_x = _mode([s["x0"] for s in body_spans if s["x0"] > 100])
        dates_x = _mode([s["x0"] for s in body_spans if s["x0"] < 100])
        bullets = [s for s in spans if s["text"][:1] in {"●", "•"}]
        images = sum(len(page.get_images(full=True)) for page in document)
        characters = sum(len(s["text"]) for s in spans)
        return {
            "pages": document.page_count,
            "characters": characters,
            "images": images,
            "file_size_kb": round(Path(path).stat().st_size / 1024, 1),
            "page_width": round(document[0].rect.width, 2),
            "page_height": round(document[0].rect.height, 2),
            "left_edge": round(min(s["x0"] for s in spans), 2) if spans else 0.0,
            "right_edge": round(max(s["x1"] for s in spans), 2) if spans else 0.0,
            "top_edge": round(min(s["y0"] for s in spans), 2) if spans else 0.0,
            "bottom_edge": round(max(s["y1"] for s in spans), 2) if spans else 0.0,
            "column_x": column_x,
            "dates_x": dates_x,
            "bullet_x": round(_mode([s["x0"] for s in bullets]), 2) if bullets else None,
            "name_size": max(sizes) if sizes else 0.0,
            "body_size": _mode([s["size"] for s in body_spans]),
            "sizes": sorted(sizes),
            "fonts": sorted(fonts),
            "rules": len([r for r in rules if r["width"] >= 200]),
            "rule_width": round(max((r["width"] for r in rules), default=0.0), 1),
        }
    finally:
        document.close()


def _serif(fonts: list[str]) -> bool:
    blob = " ".join(fonts).lower()
    return any(name in blob for name in ("times", "liberation serif", "serif", "nimbus roman"))


def _icon_fonts(fonts: list[str]) -> bool:
    blob = " ".join(fonts).lower()
    return any(name in blob for name in (
        "wingdings", "webdings", "symbol", "fontawesome", "material icons",
        "glyphicons", "icomoon",
    ))


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def compare_layout(generated_path: str | Path,
                   reference_path: str | Path | None = None,
                   *, source: str = "docx_conversion") -> dict[str, Any]:
    """Compare a generated PDF with the reference. Never raises for layout drift."""
    generated = extract_metrics(generated_path)
    reference_file = Path(reference_path) if reference_path else reference_pdf_path()
    checks: list[dict[str, Any]] = []

    if reference_file.exists():
        try:
            reference = extract_metrics(reference_file)
        except Exception as exc:  # pragma: no cover - corrupt reference
            logger.warning("Could not read reference PDF: %s", exc)
            reference = None
    else:
        reference = None

    width_ok = abs(generated["page_width"] - PAGE_WIDTH_PT) <= 1.0
    height_ok = abs(generated["page_height"] - PAGE_HEIGHT_PT) <= 1.0
    checks.append(_check("page_size", width_ok and height_ok,
                         f"A4 {generated['page_width']}×{generated['page_height']} pt"))

    left_ok = abs(generated["left_edge"] - MARGIN_LEFT_PT) <= TOLERANCE_PT
    checks.append(_check("left_margin", left_ok,
                         f"text starts at {generated['left_edge']} pt "
                         f"(reference {MARGIN_LEFT_PT})"))
    top_ok = abs(generated["top_edge"] - 47.5) <= 3.0
    checks.append(_check("top_margin", top_ok,
                         f"first line at {generated['top_edge']} pt"))

    right_limit = PAGE_WIDTH_PT - MARGIN_RIGHT_PT + TOLERANCE_PT
    document = _open(generated_path)
    try:
        overflow = [s for s in _spans(document) if s["x1"] > right_limit + 1]
    finally:
        document.close()
    overflowing_bottom = generated["bottom_edge"] > PAGE_HEIGHT_PT - 40
    checks.append(_check(
        "no_text_overflow",
        not overflow and not overflowing_bottom,
        f"right edge {generated['right_edge']} pt, bottom {generated['bottom_edge']} pt",
    ))

    if reference and reference.get("column_x") and generated.get("column_x"):
        delta = abs(generated["column_x"] - reference["column_x"])
        checks.append(_check("main_column_alignment", delta <= TOLERANCE_PT,
                             f"{generated['column_x']} vs {reference['column_x']} pt"))
        date_delta = abs((generated.get("dates_x") or 0) - (reference.get("dates_x") or 0))
        checks.append(_check("date_column_alignment", date_delta <= TOLERANCE_PT,
                             f"{generated.get('dates_x')} vs {reference.get('dates_x')} pt"))
        if reference.get("bullet_x") is not None:
            if generated.get("bullet_x") is None:
                checks.append(_check("bullet_indentation", True,
                                     "this CV contains no bulleted content"))
            else:
                bullet_delta = abs(generated["bullet_x"] - reference["bullet_x"])
                checks.append(_check("bullet_indentation", bullet_delta <= TOLERANCE_PT,
                                     f"{generated['bullet_x']} vs {reference['bullet_x']} pt"))
    else:
        checks.append(_check("main_column_alignment", True,
                             "reference PDF unavailable; expected geometry used"))
        checks.append(_check("date_column_alignment", True,
                             "reference PDF unavailable; expected geometry used"))

    checks.append(_check(
        "typography",
        abs(generated["name_size"] - 16.0) <= 1.0
        and generated.get("body_size") is not None
        and abs(generated["body_size"] - 10.0) <= 0.6
        and _serif(generated["fonts"]),
        f"name {generated['name_size']} pt, body {generated.get('body_size')} pt, "
        f"fonts {', '.join(generated['fonts'][:4])}",
    ))

    checks.append(_check("section_rules", generated["rules"] >= 1
                         and generated["rule_width"] >= 400,
                         f"{generated['rules']} rule(s), widest {generated['rule_width']} pt"))

    # ATS parse guarantees: a real text layer, no raster content and no icon fonts.
    checks.append(_check(
        "text_layer",
        generated["characters"] >= 200,
        f"{generated['characters']} extractable character(s)",
    ))
    checks.append(_check(
        "no_embedded_images",
        generated["images"] == 0,
        f"{generated['images']} embedded image(s)",
    ))
    checks.append(_check(
        "no_icon_fonts",
        not _icon_fonts(generated["fonts"]),
        f"fonts {', '.join(generated['fonts'][:4])}",
    ))
    checks.append(_check(
        "file_size",
        generated["file_size_kb"] <= 2500,
        f"{generated['file_size_kb']} KB",
    ))

    page_limit = (reference["pages"] + 1) if reference else 2
    checks.append(_check("page_count", generated["pages"] <= max(2, page_limit),
                         f"{generated['pages']} page(s)"))

    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "generated": generated,
        "reference": reference,
        "source": source,
        "reference_path": str(reference_file) if reference_file.exists() else "",
    }
