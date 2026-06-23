"""ReportLab styles, palette, reusable flowables, and WeeklyReportDocTemplate.

Page margins (``MARGIN_*``) define the content frame. Running headers are drawn in the top margin
above that frame (``HEADER_TEXT_FROM_PAGE_TOP``, ``HEADER_RULE_FROM_PAGE_TOP``) — do not place
header text relative to ``MARGIN_TOP`` with a small offset or the rule will cross the text.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Literal, Optional, Sequence, Tuple

import matplotlib.font_manager as fm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.doctemplate import BaseDocTemplate, Frame, PageTemplate
from reportlab.platypus.tableofcontents import TableOfContents

from ..plotting import REPORT_PDF_FONT_STACK

logger = logging.getLogger(__name__)

# --- Palette (design system) ---
COLOR_PRIMARY = colors.HexColor("#0B3D62")
COLOR_ACCENT = colors.HexColor("#1F8FA8")
COLOR_BODY = colors.HexColor("#1F2937")
COLOR_MUTED = colors.HexColor("#6B7280")
COLOR_ZEBRA = colors.HexColor("#F3F4F6")
COLOR_RULE = colors.HexColor("#E5E7EB")
COLOR_SEV_CRITICAL = colors.HexColor("#B91C1C")
COLOR_SEV_WARNING = colors.HexColor("#B45309")
COLOR_SEV_INFO = colors.HexColor("#1D4ED8")
COLOR_SEV_OK = colors.HexColor("#15803D")

MARGIN_SIDE = 12 * mm
MARGIN_TOP = 14 * mm
MARGIN_BOTTOM = 10 * mm

# Running header sits in the top margin (above the content frame).
HEADER_TEXT_FROM_PAGE_TOP = 5 * mm
HEADER_RULE_FROM_PAGE_TOP = 8 * mm

A4_PORTRAIT = A4
A4_LANDSCAPE = landscape(A4)

# Usable inner dimensions (match Frame(...) in WeeklyReportDocTemplate).
PORTRAIT_CONTENT_WIDTH_PT = A4_PORTRAIT[0] - 2 * MARGIN_SIDE
PORTRAIT_CONTENT_HEIGHT_PT = A4_PORTRAIT[1] - MARGIN_TOP - MARGIN_BOTTOM
LANDSCAPE_CONTENT_WIDTH_PT = A4_LANDSCAPE[0] - 2 * MARGIN_SIDE
LANDSCAPE_CONTENT_HEIGHT_PT = A4_LANDSCAPE[1] - MARGIN_TOP - MARGIN_BOTTOM


def _register_body_font() -> str:
    """Register first resolvable font from REPORT_PDF_FONT_STACK; return ReportLab family name."""
    name = "ReportBody"
    for family in REPORT_PDF_FONT_STACK:
        try:
            path = fm.findfont(fm.FontProperties(family=family), fallback_to_default=False)
        except (ValueError, RuntimeError, OSError):
            continue
        if not path or path.endswith("DejaVuSans.ttf") and family != "DejaVu Sans":
            continue
        lower = path.lower()
        if not (lower.endswith(".ttf") or lower.endswith(".otf")):
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            pdfmetrics.registerFontFamily(name, normal=name, bold=name, italic=name, boldItalic=name)
            logger.debug("Report PDF font registered: %s from %s", family, path)
            return name
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not register font %s: %s", path, exc)
    return "Helvetica"


_REGISTERED_FONT = _register_body_font()


def build_paragraph_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    font = _REGISTERED_FONT
    styles: dict[str, ParagraphStyle] = {}

    styles["CoverTitle"] = ParagraphStyle(
        name="CoverTitle",
        parent=base["Title"],
        fontName=font,
        fontSize=24,
        leading=28,
        textColor=colors.white,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    styles["CoverMeta"] = ParagraphStyle(
        name="CoverMeta",
        parent=base["Normal"],
        fontName=font,
        fontSize=11,
        leading=14,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    styles["Heading1"] = ParagraphStyle(
        name="Heading1",
        parent=base["Heading1"],
        fontName=font,
        fontSize=16,
        leading=20,
        textColor=COLOR_PRIMARY,
        spaceBefore=6,
        spaceAfter=8,
    )
    styles["Heading2"] = ParagraphStyle(
        name="Heading2",
        parent=base["Heading2"],
        fontName=font,
        fontSize=12,
        leading=15,
        textColor=COLOR_BODY,
        spaceBefore=4,
        spaceAfter=4,
    )
    styles["Body"] = ParagraphStyle(
        name="Body",
        parent=base["Normal"],
        fontName=font,
        fontSize=10,
        leading=12.5,
        textColor=COLOR_BODY,
    )
    styles["Caption"] = ParagraphStyle(
        name="Caption",
        parent=base["Normal"],
        fontName=font,
        fontSize=8.5,
        leading=10,
        textColor=COLOR_MUTED,
    )
    styles["Muted"] = ParagraphStyle(
        name="Muted",
        parent=base["Normal"],
        fontName=font,
        fontSize=9,
        leading=11,
        textColor=COLOR_MUTED,
    )
    styles["TOCHeading"] = ParagraphStyle(
        name="TOCHeading",
        parent=styles["Heading1"],
        fontSize=18,
    )
    styles["CoverPrimaryField"] = ParagraphStyle(
        name="CoverPrimaryField",
        parent=styles["Body"],
        fontSize=11,
        leading=15,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    styles["CoverSecondaryMeta"] = ParagraphStyle(
        name="CoverSecondaryMeta",
        parent=styles["Body"],
        fontSize=11,
        leading=14,
        textColor=COLOR_MUTED,
        alignment=TA_CENTER,
        fontName=font,
    )
    styles["TableHeaderWhite"] = ParagraphStyle(
        name="TableHeaderWhite",
        parent=styles["Body"],
        fontSize=9,
        leading=11,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    styles["TableCell"] = ParagraphStyle(
        name="TableCell",
        parent=styles["Body"],
        fontSize=8,
        leading=10.5,
        textColor=COLOR_BODY,
        alignment=TA_LEFT,
    )
    styles["KPIValue"] = ParagraphStyle(
        name="KPIValue",
        parent=styles["Body"],
        fontSize=8.5,
        leading=10,
        textColor=COLOR_BODY,
        alignment=TA_CENTER,
    )
    styles["KPIValueDense"] = ParagraphStyle(
        name="KPIValueDense",
        parent=styles["KPIValue"],
        fontSize=7.5,
        leading=9,
    )
    styles["KPICaptionDense"] = ParagraphStyle(
        name="KPICaptionDense",
        parent=styles["Caption"],
        fontSize=7.5,
        leading=9,
    )
    return styles


class SectionHeader(Flowable):
    """Navy title + accent rule."""

    def __init__(self, title: str, styles: dict[str, ParagraphStyle]):
        self._title = title
        self._styles = styles
        self._p = Paragraph(title.replace("&", "&amp;"), styles["Heading1"])
        self.h = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        w, h = self._p.wrap(avail_width, avail_height)
        self.h = h + 6
        return avail_width, self.h

    def draw(self) -> None:
        self._p.drawOn(self.canv, 0, 6)
        self.canv.setStrokeColor(COLOR_ACCENT)
        self.canv.setLineWidth(1)
        self.canv.line(0, 2, self.width, 2)


class DataPeriodBanner(Flowable):
    """Small grey line (period / sample count)."""

    def __init__(self, text: str, styles: dict[str, ParagraphStyle]):
        self._p = Paragraph(text.replace("&", "&amp;"), styles["Muted"])
        self.h = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        w, h = self._p.wrap(avail_width, avail_height)
        self.h = h + 4
        return avail_width, self.h

    def draw(self) -> None:
        self._p.drawOn(self.canv, 0, 0)


class KPI:
    __slots__ = ("label", "value", "unit", "trend")

    def __init__(
        self,
        label: str,
        value: str,
        unit: str = "",
        trend: Optional[Literal["up", "down"]] = None,
    ):
        self.label = label
        self.value = value
        self.unit = unit
        self.trend = trend


def _format_kpi_value_html(
    value: str,
    unit: str = "",
    trend: Optional[Literal["up", "down"]] = None,
) -> str:
    esc_val = (value or "").replace("&", "&amp;").replace("<", "&lt;")
    parts = [esc_val]
    if unit:
        esc_unit = unit.replace("&", "&amp;").replace("<", "&lt;")
        parts.append(f' <font size="7">{esc_unit}</font>')
    if trend == "up":
        parts.append(f' <font color="#15803D" size="7">▲</font>')
    elif trend == "down":
        parts.append(f' <font color="#B91C1C" size="7">▼</font>')
    return f"<nobr>{''.join(parts)}</nobr>"


def kpi_row_table(kpis: Sequence[KPI], styles: dict[str, ParagraphStyle]) -> Table:
    if not kpis:
        return Table([[""]])
    dense = len(kpis) >= 8
    label_style = styles["KPICaptionDense"] if dense else styles["Caption"]
    value_style = styles["KPIValueDense"] if dense else styles["KPIValue"]
    row_labels: List[Paragraph] = []
    row_vals: List[Paragraph] = []
    for k in kpis:
        esc_label = (k.label or "").replace("&", "&amp;").replace("<", "&lt;")
        row_labels.append(Paragraph(f"<b>{esc_label}</b>", label_style))
        row_vals.append(
            Paragraph(_format_kpi_value_html(k.value, k.unit, k.trend), value_style)
        )
    inner_w = A4_PORTRAIT[0] - 2 * MARGIN_SIDE
    col_w = inner_w / len(kpis)
    t = Table([row_labels, row_vals], colWidths=[col_w] * len(kpis))
    t.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, 0), (-1, 0), COLOR_ZEBRA),
                ("BOX", (0, 0), (-1, -1), 0.4, COLOR_RULE),
            ]
        )
    )
    return t


class NoteCard(Flowable):
    """Letter badge + time + author + body."""

    def __init__(
        self,
        letter: str,
        event_time: str,
        author: str,
        body: str,
        styles: dict[str, ParagraphStyle],
    ):
        self.letter = letter
        self.event_time = event_time
        self.author = author
        esc = (body or "").replace("&", "&amp;").replace("<", "&lt;")
        meta = f"{event_time}" + (f" · {author}" if author else "")
        self._meta = Paragraph(meta.replace("&", "&amp;"), styles["Caption"])
        self._body = Paragraph(esc or "(no content)", styles["Body"])
        self.h = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        badge_w = 28
        inner_w = avail_width - badge_w - 8
        _, h1 = self._meta.wrap(inner_w, avail_height)
        _, h2 = self._body.wrap(inner_w, avail_height)
        self.h = max(32.0, h1 + h2 + 8)
        return avail_width, self.h

    def draw(self) -> None:
        self.canv.saveState()
        self.canv.setFillColor(COLOR_PRIMARY)
        self.canv.circle(14, self.h / 2, 12, fill=1, stroke=0)
        self.canv.setFillColor(colors.white)
        self.canv.setFont(_REGISTERED_FONT, 11)
        self.canv.drawCentredString(14, self.h / 2 - 4, self.letter[:3])
        self.canv.restoreState()
        self._meta.drawOn(self.canv, 36, self.h - 14)
        self._body.drawOn(self.canv, 36, 0)


class GoalCard(Flowable):
    """Completion badge + time/user meta + goal description (mirrors NoteCard layout)."""

    def __init__(
        self,
        *,
        is_completed: bool,
        meta_line: str,
        body: str,
        styles: dict[str, ParagraphStyle],
    ):
        self.is_completed = is_completed
        esc = (body or "").replace("&", "&amp;").replace("<", "&lt;")
        self._meta = Paragraph(meta_line.replace("&", "&amp;"), styles["Caption"])
        self._body = Paragraph(esc or "(no description)", styles["Body"])
        self.h = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        badge_w = 28
        inner_w = avail_width - badge_w - 8
        _, h1 = self._meta.wrap(inner_w, avail_height)
        _, h2 = self._body.wrap(inner_w, avail_height)
        self.h = max(32.0, h1 + h2 + 8)
        return avail_width, self.h

    def draw(self) -> None:
        cx, cy = 14.0, self.h / 2.0
        r = 11.0
        self.canv.saveState()
        if self.is_completed:
            self.canv.setFillColor(COLOR_SEV_OK)
            self.canv.circle(cx, cy, r, fill=1, stroke=0)
            self.canv.setStrokeColor(colors.white)
            self.canv.setLineWidth(2.2)
            self.canv.setLineCap(1)
            # Check mark
            self.canv.line(cx - 5.0, cy - 0.5, cx - 1.5, cy - 4.0)
            self.canv.line(cx - 1.5, cy - 4.0, cx + 6.5, cy + 5.0)
        else:
            self.canv.setFillColor(colors.white)
            self.canv.setStrokeColor(COLOR_RULE)
            self.canv.setLineWidth(1.2)
            self.canv.circle(cx, cy, r, fill=1, stroke=1)
            self.canv.setStrokeColor(COLOR_MUTED)
            self.canv.setLineWidth(1.6)
            self.canv.line(cx - 4.5, cy, cx + 4.5, cy)
        self.canv.restoreState()
        self._meta.drawOn(self.canv, 36, self.h - 14)
        self._body.drawOn(self.canv, 36, 0)


def severity_color(severity: Optional[str]) -> Any:
    if not severity:
        return COLOR_MUTED
    s = severity.upper()
    if "CRITICAL" in s or "ERROR" in s:
        return COLOR_SEV_CRITICAL
    if "WARN" in s:
        return COLOR_SEV_WARNING
    if "INFO" in s or "NOTICE" in s:
        return COLOR_SEV_INFO
    if "OK" in s or "SUCCESS" in s:
        return COLOR_SEV_OK
    return COLOR_MUTED


def _escape_xml_text(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;")


def severity_pill_cell(severity: Optional[str], styles: dict[str, ParagraphStyle], *, col_width_pt: float = 52) -> Table:
    label = (severity or "—").replace("&", "&amp;")
    color = severity_color(severity)
    st = ParagraphStyle(
        name="Pill",
        parent=styles["Caption"],
        fontSize=8,
        leading=10,
        textColor=colors.white,
        backColor=color,
        alignment=TA_CENTER,
        borderPadding=4,
    )
    inner = Paragraph(label, st)
    t = Table([[inner]], colWidths=[col_width_pt])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


def _cell_plain_for_hazard(cell: Any) -> str:
    if cell is None:
        return ""
    if isinstance(cell, Paragraph):
        try:
            return cell.getPlainText()
        except Exception:  # noqa: BLE001
            return str(cell)
    return str(cell)


def styled_data_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    styles: dict[str, ParagraphStyle],
    col_widths: Optional[Sequence[float]] = None,
    hazard_col_index: Optional[int] = None,
    header_style: Optional[ParagraphStyle] = None,
) -> Table:
    """Build a data table with wrapping cells (Paragraph or Flowable per cell)."""
    hdr_style = header_style or styles["TableHeaderWhite"]
    cell_style = styles["TableCell"]
    header_row: List[Any] = [Paragraph(_escape_xml_text(h), hdr_style) for h in headers]
    data: List[List[Any]] = [header_row]
    for row in rows:
        built: List[Any] = []
        for c in row:
            if isinstance(c, Flowable):
                built.append(c)
            else:
                built.append(Paragraph(_escape_xml_text(str(c)), cell_style))
        data.append(built)
    t = Table(data, colWidths=list(col_widths) if col_widths else None, repeatRows=1)
    style_cmds: List[Tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for r in range(1, len(data)):
        if r % 2 == 1:
            style_cmds.append(("BACKGROUND", (0, r), (-1, r), COLOR_ZEBRA))
        if hazard_col_index is not None:
            cell = data[r][hazard_col_index] if hazard_col_index < len(data[r]) else ""
            plain = _cell_plain_for_hazard(cell)
            if "Hazardous" in plain or "hazardous" in plain:
                style_cmds.append(("LINEAFTER", (0, r), (0, r), 3, COLOR_SEV_CRITICAL))
    t.setStyle(TableStyle(style_cmds))
    return t


class WeeklyReportDocTemplate(BaseDocTemplate):
    """Portrait + landscape page templates, header/footer, TOC notify + outline entries."""

    def __init__(
        self,
        filename: str,
        *,
        mission_header: str,
        report_title: str,
        generated_utc: str,
        styles: dict[str, ParagraphStyle],
    ):
        self._mission_header = mission_header
        self._report_title = report_title
        self._generated_utc = generated_utc
        self._styles = styles
        self._heading_count = 0

        pw, ph = A4_PORTRAIT
        frame_p = Frame(
            MARGIN_SIDE,
            MARGIN_BOTTOM,
            pw - 2 * MARGIN_SIDE,
            ph - MARGIN_TOP - MARGIN_BOTTOM,
            id="portrait_frame",
        )
        lw, lh = A4_LANDSCAPE
        frame_l = Frame(
            MARGIN_SIDE,
            MARGIN_BOTTOM,
            lw - 2 * MARGIN_SIDE,
            lh - MARGIN_TOP - MARGIN_BOTTOM,
            id="landscape_frame",
        )

        def on_cover(canvas: Any, doc: BaseDocTemplate) -> None:
            canvas.saveState()
            canvas.setFont(_REGISTERED_FONT, 8)
            canvas.setFillColor(COLOR_MUTED)
            canvas.drawRightString(pw - MARGIN_SIDE, MARGIN_BOTTOM - 6, f"Page {canvas.getPageNumber()}")
            canvas.restoreState()

        def _draw_running_header(canvas: Any, page_w: float, page_h: float, doc: BaseDocTemplate) -> None:
            """Mission title + rule in top margin; rule sits below text, above content frame."""
            y_text = page_h - HEADER_TEXT_FROM_PAGE_TOP
            y_rule = page_h - HEADER_RULE_FROM_PAGE_TOP
            canvas.setFont(_REGISTERED_FONT, 8.5)
            canvas.setFillColor(COLOR_BODY)
            canvas.drawString(MARGIN_SIDE, y_text, doc._mission_header[:120])  # type: ignore[attr-defined]
            canvas.setFillColor(COLOR_PRIMARY)
            canvas.drawRightString(page_w - MARGIN_SIDE, y_text, doc._report_title[:80])  # type: ignore[attr-defined]
            canvas.setStrokeColor(COLOR_ACCENT)
            canvas.setLineWidth(0.5)
            canvas.line(MARGIN_SIDE, y_rule, page_w - MARGIN_SIDE, y_rule)

        def on_portrait(canvas: Any, doc: BaseDocTemplate) -> None:
            canvas.saveState()
            _draw_running_header(canvas, pw, ph, doc)
            canvas.setFont(_REGISTERED_FONT, 8)
            canvas.setFillColor(COLOR_MUTED)
            footer = f"Page {canvas.getPageNumber()} · Generated {doc._generated_utc}"  # type: ignore[attr-defined]
            canvas.drawString(MARGIN_SIDE, 6, footer)
            canvas.restoreState()

        def on_landscape(canvas: Any, doc: BaseDocTemplate) -> None:
            canvas.saveState()
            _draw_running_header(canvas, lw, lh, doc)
            canvas.setFont(_REGISTERED_FONT, 8)
            canvas.setFillColor(COLOR_MUTED)
            footer = f"Page {canvas.getPageNumber()} · Generated {doc._generated_utc}"  # type: ignore[attr-defined]
            canvas.drawString(MARGIN_SIDE, 6, footer)
            canvas.restoreState()

        BaseDocTemplate.__init__(
            self,
            filename,
            pagesize=A4_PORTRAIT,
            pageTemplates=[
                PageTemplate(id="cover", frames=[frame_p], onPage=on_cover),
                PageTemplate(id="portrait", frames=[frame_p], onPage=on_portrait),
                PageTemplate(
                    id="landscape",
                    frames=[frame_l],
                    onPage=on_landscape,
                    pagesize=A4_LANDSCAPE,
                ),
            ],
            title=report_title,
        )
        self.firstPageTemplateName = "cover"

    def afterFlowable(self, flowable: Flowable) -> None:
        if isinstance(flowable, Paragraph):
            st_name = getattr(flowable.style, "name", "")
            if st_name not in ("Heading1", "Heading2"):
                return
            text = flowable.getPlainText()
            toc_level = 0 if st_name == "Heading1" else 1
            outline_level = toc_level
            try:
                self.notify("TOCEntry", (toc_level, text, self.page))
            except Exception:  # noqa: BLE001
                pass
            try:
                key = f"h-{self._heading_count}"
                self._heading_count += 1
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(
                    text,
                    key,
                    level=outline_level,
                    closed=(st_name == "Heading2"),
                )
            except Exception:  # noqa: BLE001
                pass


def build_toc_flowable(styles: dict[str, ParagraphStyle]) -> TableOfContents:
    # Heading1 -> TOCEntry level 0; Heading2 -> level 1 (nested under week headings in EOM).
    toc = TableOfContents(dotsMinLevel=0, rightColumnWidth=56)
    toc.levelStyles = [
        ParagraphStyle(
            name="TOC1",
            parent=styles["Body"],
            fontSize=10,
            leading=13,
            leftIndent=0,
            firstLineIndent=0,
            spaceBefore=2,
        ),
        ParagraphStyle(
            name="TOC2",
            parent=styles["Body"],
            fontSize=9,
            leading=12,
            leftIndent=18,
            firstLineIndent=0,
            spaceBefore=0,
        ),
    ]
    return toc


def cover_page_flowables(
    *,
    title: str,
    platform: str,
    mission_id: str,
    mission_title: str,
    date_range: str,
    generated_utc: str,
    logo_path: Optional[Any],
    styles: dict[str, ParagraphStyle],
) -> List[Flowable]:
    from reportlab.platypus import Image as RLImage

    out: List[Flowable] = []
    band_h = 52 * mm
    pw, _ph = A4_PORTRAIT
    inner_w = pw - 2 * MARGIN_SIDE

    has_logo = logo_path is not None and hasattr(logo_path, "exists") and logo_path.exists()
    est_fixed_pt = float(band_h) + float(12 * mm) + 88 * mm + (42 * mm if has_logo else 0)
    top_balance = (float(PORTRAIT_CONTENT_HEIGHT_PT) - est_fixed_pt) / 2.0
    top_spacer = max(float(8 * mm), min(float(52 * mm), top_balance))
    out.append(Spacer(1, top_spacer))

    title_p = Paragraph(title.replace("&", "&amp;"), styles["CoverTitle"])
    if has_logo:
        try:
            logo = RLImage(str(logo_path), width=42 * mm, height=20 * mm, kind="proportional")
            logo.hAlign = "CENTER"
            tbl_logo = Table([[logo]], colWidths=[inner_w])
            tbl_logo.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
            out.append(tbl_logo)
            out.append(Spacer(1, 10 * mm))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not embed logo: %s", exc)

    band_table = Table([[title_p]], colWidths=[inner_w], rowHeights=[band_h])
    band_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_PRIMARY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 16),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
            ]
        )
    )
    out.append(band_table)
    out.append(Spacer(1, 12 * mm))

    def _primary_block(label: str, value: str) -> Paragraph:
        esc = _escape_xml_text(value)
        return Paragraph(
            f'<b><font size="12">{_escape_xml_text(label)}</font></b><br/><font size="11">{esc}</font>',
            styles["CoverPrimaryField"],
        )

    def _secondary_block(label: str, value: str) -> Paragraph:
        esc = _escape_xml_text(value)
        return Paragraph(
            f'<i>{_escape_xml_text(label)}</i><br/><i>{esc}</i>',
            styles["CoverSecondaryMeta"],
        )

    meta_rows: List[List[Paragraph]] = [
        [_primary_block("Platform", platform)],
        [_primary_block("Mission ID", mission_id)],
        [_primary_block("Mission title", mission_title)],
        [_secondary_block("Report window", date_range)],
        [_secondary_block("Generated", generated_utc)],
    ]
    meta_inner_w = inner_w - 16 * mm
    meta_table = Table(meta_rows, colWidths=[meta_inner_w])
    meta_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    card = Table([[meta_table]], colWidths=[meta_inner_w])
    card.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, COLOR_RULE),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    out.append(Table([[card]], colWidths=[inner_w], style=TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")])))
    return out
