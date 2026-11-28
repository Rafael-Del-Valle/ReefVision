"""Deterministic SVG and CSV from saved research report specifications."""

import csv
from datetime import UTC, datetime
from io import StringIO
from xml.etree.ElementTree import Element, SubElement, tostring

from reefvision.schemas.research_reports import FigureSnapshot

_PALETTE = ("#006A9C", "#A74B08", "#007A5A", "#6C488B")
_DASHES = ("", "6 3", "2 3", "8 2 2 2")


def figure_svg(snapshot: FigureSnapshot) -> str:
    width, height = 900, 540
    left, right, top, bottom = 82, 850, 78, 438
    svg = Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
            "role": "img",
            "aria-labelledby": "figure-title figure-desc",
            "font-family": "sans-serif",
            "font-size": "13",
        },
    )
    SubElement(svg, "title", {"id": "figure-title"}).text = snapshot.configuration.title
    SubElement(svg, "desc", {"id": "figure-desc"}).text = (
        f"{snapshot.x_label}; {snapshot.y_label}. Source {snapshot.source_evidence}. "
        + (snapshot.uncertainty or "Descriptive observations.")
    )

    def element(kind: str, **attributes: str | float | int) -> Element:
        return SubElement(
            svg, kind, {key.replace("_", "-"): str(value) for key, value in attributes.items()}
        )

    def label(text: str, x: float, y: float, **attributes: str | float | int) -> None:
        element("text", x=x, y=y, **attributes).text = text

    def line(x1: float, y1: float, x2: float, y2: float, color: str, dash: str = "") -> None:
        element("line", x1=x1, y1=y1, x2=x2, y2=y2, stroke=color, stroke_dasharray=dash)

    points = [point for series in snapshot.series for point in series.points]
    xs = [point.x for point in points]
    ys = [point.y for point in points] + [value for _, value in snapshot.guidelines]
    ys.extend(
        bound for point in points for bound in (point.lower, point.upper) if bound is not None
    )
    if snapshot.zero_identity:
        xs.extend(ys)
        ys.extend(xs)
    if snapshot.geometry == "bars":
        ys.append(0)
    lo_x, hi_x, lo_y, hi_y = min(xs), max(xs), min(ys), max(ys)
    if snapshot.geometry == "bars":
        lo_x -= 0.6
        hi_x += 0.6
    if hi_x == lo_x:
        lo_x, hi_x = lo_x - 0.5, hi_x + 0.5
    if hi_y == lo_y:
        lo_y, hi_y = lo_y - 0.5, hi_y + 0.5

    def x(value: float) -> float:
        return left + (right - left) * (value - lo_x) / (hi_x - lo_x)

    def y(value: float) -> float:
        return bottom - (bottom - top) * (value - lo_y) / (hi_y - lo_y)

    element("rect", x=0, y=0, width=width, height=height, fill="white")
    label(snapshot.configuration.title, left, 35, font_size=21, font_weight="bold")
    if snapshot.uncertainty:
        label(snapshot.uncertainty, left, 58, font_size=11)
    for step in range(5):
        py = lo_y + (hi_y - lo_y) * step / 4
        line(left, y(py), right, y(py), "#d5d5d5")
        label(f"{py:.4g}", left - 8, y(py) + 4, text_anchor="end")
    line(left, top, left, bottom, "#161616")
    line(left, bottom, right, bottom, "#161616")
    if snapshot.geometry == "bars":
        labels = {point.x: point.label for point in points}
        stride = max(1, (len(labels) + 7) // 8)
        for index, (px, text) in enumerate(sorted(labels.items())):
            if index % stride == 0:
                shown = text if len(text) <= 29 else text[:26] + "…"
                label(shown, x(px), bottom + 16, text_anchor="middle", font_size=9)
    else:
        for step in range(5):
            px = lo_x + (hi_x - lo_x) * step / 4
            tick = (
                datetime.fromtimestamp(px * 86400, UTC).date().isoformat()
                if snapshot.x_scale == "utc_day"
                else f"{px:.5g}"
            )
            label(tick, x(px), bottom + 17, text_anchor="middle")
    label(snapshot.x_label, (left + right) / 2, bottom + 44, text_anchor="middle")
    label(
        snapshot.y_label,
        21,
        (top + bottom) / 2,
        text_anchor="middle",
        transform=f"rotate(-90 21 {(top + bottom) / 2})",
    )
    if snapshot.zero_identity:
        line(x(lo_x), y(lo_x), x(hi_x), y(hi_x), "#616161", "5 4")
    for name, value in snapshot.guidelines:
        line(left, y(value), right, y(value), "#767676", "4 3")
        label(name[:72], right - 4, y(value) - 4, text_anchor="end", font_size=9)
    for index, series in enumerate(snapshot.series):
        color = (
            _PALETTE[index % 4]
            if snapshot.configuration.style == "accessible_color"
            else ("#131313", "#626262", "#949494", "#404040")[index % 4]
        )
        dash = _DASHES[index % len(_DASHES)]
        if snapshot.geometry == "lines":
            element(
                "polyline",
                points=" ".join(f"{x(point.x):.2f},{y(point.y):.2f}" for point in series.points),
                fill="none",
                stroke=color,
                stroke_width=2,
                stroke_dasharray=dash,
            )
        for point in series.points:
            px, py = x(point.x), y(point.y)
            center = px
            if snapshot.geometry == "bars":
                size = min(46, (right - left) / max(3, len(set(xs))) * 0.7) / len(snapshot.series)
                center = px + (index - (len(snapshot.series) - 1) / 2) * size
                node = element(
                    "rect",
                    x=center - size / 2,
                    y=min(py, y(0)),
                    width=max(1, size - 1),
                    height=max(1, abs(py - y(0))),
                    fill=color,
                )
            elif index % 2 == 0:
                node = element(
                    "circle", cx=px, cy=py, r=4, fill="white", stroke=color, stroke_width=2
                )
            else:
                node = element("rect", x=px - 4, y=py - 4, width=8, height=8, fill=color)
            if point.lower is not None and point.upper is not None:
                line(center, y(point.lower), center, y(point.upper), "#161616")
                line(center - 3, y(point.lower), center + 3, y(point.lower), "#161616")
                line(center - 3, y(point.upper), center + 3, y(point.upper), "#161616")
                label(
                    f"n={point.denominator}",
                    center,
                    y(point.upper) - 5,
                    font_size=9,
                    text_anchor="middle",
                )
            SubElement(node, "title").text = f"{series.label}: {point.label} ({point.y:.8g})"
        if index < 5:
            gx = left + index * 151
            line(gx, bottom + 71, gx + 17, bottom + 71, color, dash)
            label(series.label[:21], gx + 22, bottom + 75, font_size=10)
    # XML serialization escapes user text. No external executable or assets.
    return tostring(svg, encoding="unicode")


def figure_csv(snapshot: FigureSnapshot) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")

    def text_cell(value: str) -> str:
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    writer.writerow(
        (
            "series",
            "label",
            "x",
            "y",
            "denominator",
            "lower",
            "upper",
            "x_unit_label",
            "y_unit_label",
            "uncertainty",
            "method",
            "source_sha256",
            "software_version",
        )
    )
    for series in snapshot.series:
        for point in series.points:
            writer.writerow(
                (
                    text_cell(series.label),
                    text_cell(point.label),
                    point.x,
                    point.y,
                    point.denominator,
                    point.lower,
                    point.upper,
                    text_cell(snapshot.x_label),
                    text_cell(snapshot.y_label),
                    snapshot.uncertainty,
                    snapshot.method,
                    snapshot.source_sha256,
                    snapshot.software_version,
                )
            )
    return output.getvalue()
