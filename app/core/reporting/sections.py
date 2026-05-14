"""Platypus flowables for each report section (cover, TOC, tables, charts)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from reportlab.lib import colors as rl_colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from .. import models
from ..plotting import assign_note_letters
from ..summaries import get_ais_summary, get_ais_summary_stats
from . import charts
from .styling import (
    A4_PORTRAIT,
    COLOR_RULE,
    COLOR_ZEBRA,
    DataPeriodBanner,
    KPI,
    LANDSCAPE_CONTENT_HEIGHT_PT,
    LANDSCAPE_CONTENT_WIDTH_PT,
    MARGIN_SIDE,
    NoteCard,
    PORTRAIT_CONTENT_HEIGHT_PT,
    SectionHeader,
    _escape_xml_text,
    build_paragraph_styles,
    build_toc_flowable,
    cover_page_flowables,
    kpi_row_table,
    severity_pill_cell,
    styled_data_table,
)


def _pw() -> float:
    return A4_PORTRAIT[0] - 2 * MARGIN_SIDE


def _landscape_chart_max_height_pt() -> float:
    """Room under Heading1 + DataPeriodBanner + spacers on a landscape page."""
    return max(120.0, LANDSCAPE_CONTENT_HEIGHT_PT - 100.0)


def _telemetry_chart_max_height_pt() -> float:
    """Room under optional section chrome inside the portrait frame."""
    return max(200.0, PORTRAIT_CONTENT_HEIGHT_PT - 140.0)


def build_cover(
    *,
    title_for_pdf: str,
    platform_name: str,
    mission_id: str,
    mission_title: str,
    date_range_str: str,
    generated_utc: str,
    logo_path: Any,
) -> List[Any]:
    styles = build_paragraph_styles()
    return cover_page_flowables(
        title=title_for_pdf,
        platform=platform_name,
        mission_id=mission_id,
        mission_title=mission_title,
        date_range=date_range_str,
        generated_utc=generated_utc,
        logo_path=logo_path,
        styles=styles,
    )


def build_toc_intro() -> List[Any]:
    styles = build_paragraph_styles()
    return [
        Paragraph("Table of Contents", styles["TOCHeading"]),
        Spacer(1, 6),
        Paragraph(
            "The outline below is bookmarked in this PDF for quick navigation.",
            styles["Caption"],
        ),
        Spacer(1, 10),
        build_toc_flowable(styles),
    ]


def build_mission_details_sections(
    sections: Sequence[Tuple[str, Sequence[Tuple[str, str]]]],
) -> List[Any]:
    """sections: (heading, [(label, value), ...]) — skip blocks with no rows."""
    styles = build_paragraph_styles()
    out: List[Any] = []
    for heading, rows in sections:
        if not rows:
            continue
        out.append(Paragraph(heading.replace("&", "&amp;"), styles["Heading2"]))
        data = [
            [
                Paragraph(f"<b>{k}</b>", styles["Caption"]),
                Paragraph(str(v).replace("&", "&amp;"), styles["Body"]),
            ]
            for k, v in rows
        ]
        t = Table(data, colWidths=[_pw() * 0.26, _pw() * 0.74])
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.25, COLOR_RULE),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [rl_colors.white, COLOR_ZEBRA]),
                    ("LEFTPADDING", (0, 0), (0, -1), 3),
                    ("RIGHTPADDING", (0, 0), (0, -1), 2),
                    ("TOPPADDING", (0, 0), (0, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (0, -1), 2),
                    ("LEFTPADDING", (1, 0), (1, -1), 6),
                    ("RIGHTPADDING", (1, 0), (1, -1), 6),
                ]
            )
        )
        out.append(t)
        out.append(Spacer(1, 10))
    return out


def _instrument_lines_to_value_paragraph(lines: Sequence[str], styles: dict[str, ParagraphStyle]) -> Paragraph:
    """Turn ITEM:/SUB: lines from builder into HTML bullets (no raw Unicode box-drawing)."""
    if not lines or (len(lines) == 1 and lines[0] == "(None)"):
        return Paragraph("—", styles["Body"])
    parts: List[str] = []
    for raw in lines:
        s = str(raw).strip()
        if s == "(None)":
            return Paragraph("—", styles["Body"])
        if s.startswith("SUB:"):
            inner = _escape_xml_text(s[4:].strip())
            parts.append(f"&nbsp;&nbsp;&nbsp;&nbsp;&#8211; {inner}")
        elif s.startswith("ITEM:"):
            inner = _escape_xml_text(s[5:].strip())
            parts.append(f"&#8226; {inner}")
        else:
            parts.append(f"&#8226; {_escape_xml_text(s)}")
    return Paragraph("<br/>".join(parts), styles["Body"])


def build_instruments_page(
    instrument_blocks: Sequence[Tuple[str, Sequence[str]]],
) -> List[Any]:
    """Mission-details style: Heading2 + two-column label/value table per instrument group."""
    if not instrument_blocks:
        return []
    styles = build_paragraph_styles()
    out: List[Any] = []
    for heading, lines in instrument_blocks[:3]:
        out.append(Paragraph(heading.replace("&", "&amp;"), styles["Heading2"]))
        value_p = _instrument_lines_to_value_paragraph(lines, styles)
        data = [
            [
                Paragraph("<b>Instruments</b>", styles["Caption"]),
                value_p,
            ]
        ]
        t = Table(data, colWidths=[_pw() * 0.26, _pw() * 0.74])
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.25, COLOR_RULE),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [rl_colors.white, COLOR_ZEBRA]),
                    ("LEFTPADDING", (0, 0), (0, -1), 3),
                    ("RIGHTPADDING", (0, 0), (0, -1), 2),
                    ("TOPPADDING", (0, 0), (0, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (0, -1), 2),
                    ("LEFTPADDING", (1, 0), (1, -1), 6),
                    ("RIGHTPADDING", (1, 0), (1, -1), 6),
                ]
            )
        )
        out.append(t)
        out.append(Spacer(1, 10))
    return out


def build_summary(
    *,
    mission_telemetry_summary: dict,
    report_period_telemetry_summary: dict,
    report_period_power_summary: dict,
    report_period_ctd_summary: dict,
    report_period_weather_summary: dict,
    report_period_wave_summary: dict,
    report_period_error_summary: dict,
    mission_goals: Optional[Sequence[models.MissionGoal]],
    period_label: str,
) -> List[Any]:
    styles = build_paragraph_styles()
    out: List[Any] = []
    out.append(DataPeriodBanner(period_label, styles))
    out.append(Spacer(1, 8))

    out.append(Paragraph("Navigation and Power", styles["Heading2"]))
    kpis: List[KPI] = [
        KPI("Distance (period)", f"{report_period_telemetry_summary.get('total_distance_km', 0.0):.2f}", "km"),
        KPI("Avg SOG (period)", f"{report_period_telemetry_summary.get('avg_speed_knots', 0.0):.2f}", "kt"),
        KPI("Distance (mission)", f"{mission_telemetry_summary.get('total_distance_km', 0.0):.2f}", "km"),
        KPI("Power in (avg)", f"{report_period_power_summary.get('avg_total_input_W', 0.0):.2f}", "W"),
        KPI("Power out (avg)", f"{report_period_power_summary.get('avg_total_output_W', 0.0):.2f}", "W"),
        KPI("Errors (count)", str(report_period_error_summary.get("total_errors", 0)), ""),
    ]
    solar = report_period_power_summary.get("avg_solar_panel_W") or {}
    if solar:
        for name, w in list(solar.items())[:3]:
            kpis.append(KPI(name, f"{w:.2f}", "W"))
    out.append(kpi_row_table(kpis[:12], styles))
    out.append(Spacer(1, 12))

    def _stat_block(title: str, d: dict, unit: str) -> List[KPI]:
        items: List[KPI] = []
        if "avg" in d:
            items.append(KPI(f"{title} avg", f"{d['avg']:.2f}", unit))
        if "min" in d:
            items.append(KPI(f"{title} min", f"{d['min']:.2f}", unit))
        if "max" in d:
            items.append(KPI(f"{title} max", f"{d['max']:.2f}", unit))
        return items

    ocean: List[KPI] = []
    wt = report_period_ctd_summary.get("WaterTemperature")
    if wt:
        ocean.extend(_stat_block("Water temp", wt, "°C"))
    sal = report_period_ctd_summary.get("Salinity")
    if sal:
        ocean.extend(_stat_block("Salinity", sal, "PSU"))
    if ocean:
        out.append(Paragraph("Oceanographic (CTD)", styles["Heading2"]))
        out.append(kpi_row_table(ocean, styles))
        out.append(Spacer(1, 8))

    wx: List[KPI] = []
    at = report_period_weather_summary.get("AirTemperature")
    if at:
        wx.extend(_stat_block("Air temp", at, "°C"))
    ws = report_period_weather_summary.get("WindSpeed")
    if ws:
        wx.extend(_stat_block("Wind", ws, "kt"))
    wg = report_period_weather_summary.get("WindGust")
    if wg and "max" in wg:
        wx.append(KPI("Wind gust max", f"{wg['max']:.2f}", "kt"))
    bp = report_period_weather_summary.get("BarometricPressure")
    if bp:
        wx.extend(_stat_block("Pressure", bp, "mbar"))
    if wx:
        out.append(Paragraph("Meteorological", styles["Heading2"]))
        out.append(kpi_row_table(wx, styles))
        out.append(Spacer(1, 8))

    sea: List[KPI] = []
    hs = report_period_wave_summary.get("SignificantWaveHeight")
    if hs:
        sea.extend(_stat_block("Sig. wave hgt", hs, "m"))
    tp = report_period_wave_summary.get("WavePeriod")
    if tp:
        sea.extend(_stat_block("Peak period", tp, "s"))
    if sea:
        out.append(Paragraph("Sea state", styles["Heading2"]))
        out.append(kpi_row_table(sea, styles))

    sev = report_period_error_summary.get("by_severity") or {}
    if sev:
        out.append(Spacer(1, 8))
        out.append(Paragraph("Errors by severity", styles["Heading2"]))
        sev_kpis = [KPI(str(k), str(v), "") for k, v in list(sev.items())[:8]]
        out.append(kpi_row_table(sev_kpis, styles))

    if mission_goals:
        out.append(Spacer(1, 8))
        out.append(Paragraph("Mission goals", styles["Heading2"]))
        for g in mission_goals:
            mark = "[x]" if g.is_completed else "[ ]"
            out.append(
                Paragraph(
                    f"{mark} {g.description.replace('&', '&amp;')}",
                    styles["Body"],
                )
            )

    return out


def build_telemetry_section(
    telemetry_df: pd.DataFrame,
    note_annotations: List[Dict[str, Any]],
    *,
    report_distance_km: float,
) -> List[Any]:
    if telemetry_df.empty or "lastLocationFix" not in telemetry_df.columns:
        return []
    styles = build_paragraph_styles()
    out: List[Any] = []
    df = telemetry_df.dropna(subset=["latitude", "longitude"]).sort_values("lastLocationFix")
    if df.empty:
        return []
    start = df["lastLocationFix"].min()
    end = df["lastLocationFix"].max()
    lat0, lon0 = float(df.iloc[0]["latitude"]), float(df.iloc[0]["longitude"])
    lat1, lon1 = float(df.iloc[-1]["latitude"]), float(df.iloc[-1]["longitude"])
    banner = (
        f"Start {start} UTC @ {lat0:.4f}°N, {abs(lon0):.4f}°{'W' if lon0 < 0 else 'E'} · "
        f"Latest {end} UTC @ {lat1:.4f}°N, {abs(lon1):.4f}°{'W' if lon1 < 0 else 'E'} · "
        f"Report-period track distance ~{report_distance_km:.2f} km (from telemetry fixes)."
    )
    out.append(DataPeriodBanner(banner, styles))
    out.append(
        Paragraph(
            "Speed over ground is shown on a 0–4 kt scale (cmocean · speed).",
            styles["Caption"],
        )
    )
    out.append(Spacer(1, 6))
    # Shallow-copy dicts so matplotlib's assign_note_letters does not mutate the
    # builder's list before build_mission_notes_section runs assign again for PDF.
    chart_annotations = [dict(a) for a in note_annotations] if note_annotations else []
    img = charts.chart_telemetry_image(
        telemetry_df,
        chart_annotations,
        max_width_pt=_pw(),
        max_height_pt=_telemetry_chart_max_height_pt(),
    )
    out.append(img)
    return out


def build_mission_notes_section(note_annotations: List[Dict[str, Any]]) -> List[Any]:
    if not note_annotations:
        return []
    styles = build_paragraph_styles()
    out: List[Any] = []
    out.append(Paragraph("Mission notes", styles["Heading1"]))
    out.append(
        Paragraph(
            "Notes are keyed to letters on the telemetry map.",
            styles["Caption"],
        )
    )
    out.append(Spacer(1, 8))
    ann = assign_note_letters(list(note_annotations))
    ann_sorted = sorted(
        ann,
        key=lambda n: (str(n.get("cluster_letter") or n.get("letter") or "?"), int(n.get("cluster_sub_idx", 0))),
    )
    for note in ann_sorted:
        letter = str(note.get("letter") or "?").strip()
        ev = note.get("event_time")
        if isinstance(ev, datetime):
            et = ev.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            et = "unknown time"
        author = str(note.get("created_by_username") or "").strip()
        body = str(note.get("full_note_text") or "").strip()
        out.append(NoteCard(letter, et, author, body, styles))
        out.append(Spacer(1, 10))
    return out


def build_power_section(power_df: pd.DataFrame, period_label: str) -> List[Any]:
    if power_df.empty:
        return []
    styles = build_paragraph_styles()
    out: List[Any] = [
        Paragraph("Power subsystem", styles["Heading1"]),
        DataPeriodBanner(period_label, styles),
        Spacer(1, 6),
        charts.chart_power_image(
            power_df,
            max_width_pt=LANDSCAPE_CONTENT_WIDTH_PT,
            max_height_pt=_landscape_chart_max_height_pt(),
        ),
    ]
    return out


def build_ctd_section(ctd_df: pd.DataFrame, period_label: str) -> List[Any]:
    if ctd_df.empty:
        return []
    styles = build_paragraph_styles()
    return [
        Paragraph("CTD summary", styles["Heading1"]),
        DataPeriodBanner(period_label, styles),
        Spacer(1, 6),
        charts.chart_ctd_image(
            ctd_df,
            max_width_pt=LANDSCAPE_CONTENT_WIDTH_PT,
            max_height_pt=_landscape_chart_max_height_pt(),
        ),
    ]


def build_weather_section(weather_df: pd.DataFrame, period_label: str) -> List[Any]:
    if weather_df.empty:
        return []
    styles = build_paragraph_styles()
    return [
        Paragraph("Weather summary", styles["Heading1"]),
        DataPeriodBanner(period_label, styles),
        Spacer(1, 6),
        charts.chart_weather_image(
            weather_df,
            max_width_pt=LANDSCAPE_CONTENT_WIDTH_PT,
            max_height_pt=_landscape_chart_max_height_pt(),
        ),
    ]


def build_waves_section(wave_df: pd.DataFrame, period_label: str) -> List[Any]:
    if wave_df.empty:
        return []
    styles = build_paragraph_styles()
    return [
        Paragraph("Wave summary", styles["Heading1"]),
        DataPeriodBanner(period_label, styles),
        Spacer(1, 6),
        charts.chart_wave_image(
            wave_df,
            max_width_pt=LANDSCAPE_CONTENT_WIDTH_PT,
            max_height_pt=_landscape_chart_max_height_pt(),
        ),
    ]


def build_c3_section(fluorometer_df: pd.DataFrame, period_label: str) -> List[Any]:
    if fluorometer_df.empty:
        return []
    styles = build_paragraph_styles()
    return [
        Paragraph("C3 fluorometer summary", styles["Heading1"]),
        DataPeriodBanner(period_label, styles),
        Spacer(1, 6),
        charts.chart_c3_image(
            fluorometer_df,
            max_width_pt=LANDSCAPE_CONTENT_WIDTH_PT,
            max_height_pt=_landscape_chart_max_height_pt(),
        ),
    ]


def build_errors_section(error_df: pd.DataFrame, period_label: str) -> List[Any]:
    if error_df.empty:
        return []
    styles = build_paragraph_styles()
    out: List[Any] = [
        Paragraph("Vehicle errors", styles["Heading1"]),
        DataPeriodBanner(period_label, styles),
        Spacer(1, 8),
    ]
    df = error_df.tail(50).copy()
    ts_col = "Timestamp" if "Timestamp" in df.columns else "timeStamp"
    veh = "VehicleName" if "VehicleName" in df.columns else "vehicleName"
    msg = "ErrorMessage" if "ErrorMessage" in df.columns else "error_Message"
    headers = ["Time (UTC)", "Severity", "Source", "Code", "Vehicle", "Detail"]
    pw = _pw()
    t_w, sev_w, src_w, code_w, v_w = 118.0, 54.0, 68.0, 78.0, 56.0
    detail_w = max(80.0, pw - t_w - sev_w - src_w - code_w - v_w)
    rows: List[List[Any]] = []
    for _, row in df.iterrows():
        ts_raw = row.get(ts_col)
        try:
            ts_txt = pd.to_datetime(ts_raw, utc=True).strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ts_raw) else ""
        except Exception:  # noqa: BLE001
            ts_txt = str(ts_raw) if pd.notna(ts_raw) else ""
        sev = row.get("parsed_severity")
        if pd.isna(sev) or sev is None:
            sev = row.get("errorSeverity")
        src = row.get("parsed_source")
        code = row.get("parsed_code")
        detail = row.get("parsed_detail")
        if pd.isna(detail) or detail is None:
            detail = row.get(msg, "")
        detail_str = str(detail) if pd.notna(detail) else ""
        if len(detail_str) > 8000:
            detail_str = detail_str[:8000] + "…"
        rows.append(
            [
                Paragraph(_escape_xml_text(ts_txt), styles["TableCell"]),
                severity_pill_cell(str(sev) if pd.notna(sev) else None, styles, col_width_pt=sev_w - 4),
                Paragraph(_escape_xml_text(str(src) if pd.notna(src) else ""), styles["TableCell"]),
                Paragraph(_escape_xml_text(str(code) if pd.notna(code) else ""), styles["TableCell"]),
                Paragraph(_escape_xml_text(str(row.get(veh, "")) if pd.notna(row.get(veh)) else ""), styles["TableCell"]),
                Paragraph(_escape_xml_text(detail_str), styles["TableCell"]),
            ]
        )
    t = styled_data_table(
        headers,
        rows,
        styles=styles,
        col_widths=[t_w, sev_w, src_w, code_w, v_w, detail_w],
    )
    out.append(t)
    return out


def build_ais_section(
    ais_df: pd.DataFrame,
    *,
    start_date: Optional[Any],
    end_date: Optional[Any],
) -> List[Any]:
    if ais_df.empty:
        return []
    styles = build_paragraph_styles()
    ais_stats = get_ais_summary_stats(ais_df, max_age_hours=24 * 365)
    targets = get_ais_summary(ais_df, max_age_hours=24 * 365)[:25]
    generated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    dr = (
        f"{start_date} to {end_date}"
        if start_date and end_date
        else "mission window (see report dates)"
    )
    out: List[Any] = [
        Paragraph("AIS report", styles["Heading1"]),
        DataPeriodBanner(f"{dr} · generated {generated_at_utc}", styles),
        Spacer(1, 8),
    ]
    kpi_block = kpi_row_table(
        [
            KPI("Total vessels", str(ais_stats.get("total_vessels", 0)), ""),
            KPI("Class A", str(ais_stats.get("class_a_count", 0)), ""),
            KPI("Class B", str(ais_stats.get("class_b_count", 0)), ""),
            KPI("Hazardous", str(ais_stats.get("hazardous_count", 0)), ""),
        ],
        styles,
    )
    out.append(kpi_block)
    out.append(Spacer(1, 10))
    headers = ["Last seen (UTC)", "Vessel", "MMSI", "Category", "Destination"]
    pw = _pw()
    t_w, mmsi_w, cat_w = 120.0, 52.0, 78.0
    rest = max(60.0, pw - t_w - mmsi_w - cat_w)
    v_w = rest * 0.52
    d_w = rest - v_w
    rows: List[List[str]] = []
    for row in targets:
        seen = row.get("LastSeenTimestamp")
        if seen is not None and pd.notna(seen):
            st = pd.to_datetime(seen, utc=True).strftime("%Y-%m-%d %H:%M:%S")
        else:
            st = "N/A"
        cat = str(row.get("Category", "N/A"))
        rows.append(
            [
                st,
                str(row.get("ShipName", "Unknown")),
                str(row.get("MMSI", "N/A")),
                cat,
                str(row.get("Destination", "N/A")),
            ]
        )
    out.append(
        styled_data_table(
            headers,
            rows,
            styles=styles,
            col_widths=[t_w, v_w, mmsi_w, cat_w, d_w],
            hazard_col_index=3,
        )
    )
    return out
