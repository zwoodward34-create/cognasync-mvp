"""
Build the three printable PDFs for the Graham/Cohen meeting.

Outputs (relative to this script's directory):
  - 1-cognasync-executive-summary.pdf
  - 2-cognasync-mode-c-sample.pdf
  - 3-cognasync-safety-architecture.pdf

Run from anywhere:  python3 _build_meeting_pdfs.py
"""

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# -----------------------------------------------------------------------------
# Design tokens
# -----------------------------------------------------------------------------

INK = HexColor("#1A1A1A")
INK_SOFT = HexColor("#3A3A3A")
INK_MUTED = HexColor("#6B6B6B")
ACCENT = HexColor("#1B4D5A")        # deep teal
ACCENT_TINT = HexColor("#EEF3F4")   # very pale teal
RULE = HexColor("#CFCFCF")
FLAG_TINT = HexColor("#FBF3EE")     # very pale warm tint for flagged sections
FLAG_BORDER = HexColor("#C97A53")

PAGE_W, PAGE_H = letter
MARGIN_L = 0.75 * inch
MARGIN_R = 0.75 * inch
MARGIN_T = 0.65 * inch
MARGIN_B = 0.6 * inch
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

# Single-page documents use tighter margins to keep the content on one sheet
TIGHT_MARGIN_T = 0.55 * inch
TIGHT_MARGIN_B = 0.5 * inch

OUT_DIR = Path(__file__).resolve().parent


# -----------------------------------------------------------------------------
# Reusable flowables
# -----------------------------------------------------------------------------

class HRule(Flowable):
    """A thin horizontal rule."""

    def __init__(self, width=CONTENT_W, thickness=0.5, color=RULE, space_before=0, space_after=0):
        super().__init__()
        self.width = width
        self.thickness = thickness
        self.color = color
        self.space_before = space_before
        self.space_after = space_after

    def wrap(self, availWidth, availHeight):
        return availWidth, self.thickness + self.space_before + self.space_after

    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        y = self.space_after
        self.canv.line(0, y, self.width, y)


class AccentBar(Flowable):
    """A short colored bar used as a visual stamp at the top of a section."""

    def __init__(self, width=36, thickness=2.5, color=ACCENT):
        super().__init__()
        self.width = width
        self.thickness = thickness
        self.color = color

    def wrap(self, availWidth, availHeight):
        return self.width, self.thickness

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.thickness, stroke=0, fill=1)


# -----------------------------------------------------------------------------
# Styles
# -----------------------------------------------------------------------------

def make_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["wordmark"] = ParagraphStyle(
        "wordmark",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=22,
        textColor=INK,
        spaceAfter=1,
    )

    styles["tagline"] = ParagraphStyle(
        "tagline",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=12,
        textColor=INK_MUTED,
        spaceAfter=6,
    )

    styles["doctitle"] = ParagraphStyle(
        "doctitle",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=12.5,
        textColor=ACCENT,
        spaceAfter=3,
    )

    styles["meta"] = ParagraphStyle(
        "meta",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=INK_MUTED,
        spaceAfter=10,
    )

    styles["section"] = ParagraphStyle(
        "section",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10,
        textColor=ACCENT,
        spaceBefore=8,
        spaceAfter=3,
        textTransform="uppercase",
    )

    styles["body"] = ParagraphStyle(
        "body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9.8,
        leading=13,
        textColor=INK,
        spaceAfter=4,
        alignment=TA_LEFT,
    )

    styles["body_tight"] = ParagraphStyle(
        "body_tight",
        parent=styles["body"],
        spaceAfter=2,
    )

    styles["lead"] = ParagraphStyle(
        "lead",
        parent=styles["body"],
        fontSize=10.2,
        leading=13.6,
        textColor=INK,
        spaceAfter=5,
    )

    styles["small"] = ParagraphStyle(
        "small",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=INK_MUTED,
        spaceAfter=4,
    )

    styles["small_italic"] = ParagraphStyle(
        "small_italic",
        parent=styles["small"],
        fontName="Helvetica-Oblique",
    )

    styles["rule_number"] = ParagraphStyle(
        "rule_number",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=20,
        textColor=ACCENT,
    )

    styles["rule_title"] = ParagraphStyle(
        "rule_title",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=INK,
        spaceAfter=2,
    )

    styles["rule_body"] = ParagraphStyle(
        "rule_body",
        parent=styles["body"],
        fontSize=9.8,
        leading=13.5,
        spaceAfter=0,
    )

    styles["mono_label"] = ParagraphStyle(
        "mono_label",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=INK_SOFT,
    )

    styles["mono_value"] = ParagraphStyle(
        "mono_value",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=12.5,
        textColor=INK,
    )

    styles["footer"] = ParagraphStyle(
        "footer",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=INK_MUTED,
    )

    return styles


STYLES = make_styles()


# -----------------------------------------------------------------------------
# Page chrome (header bar, footer)
# -----------------------------------------------------------------------------

def draw_chrome(canvas, doc, page_label, tight: bool = False):
    canvas.saveState()
    top_y = PAGE_H - (0.4 * inch if tight else 0.45 * inch)
    foot_y = 0.35 * inch if tight else 0.4 * inch
    rule_y = foot_y + 0.1 * inch

    # Top accent rule
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.2)
    canvas.line(MARGIN_L, top_y, MARGIN_L + 40, top_y)

    # Top-right wordmark
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(INK)
    canvas.drawRightString(PAGE_W - MARGIN_R, top_y - 2, "CognaSync")

    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(INK_MUTED)
    canvas.drawString(MARGIN_L, foot_y, page_label)
    canvas.drawRightString(
        PAGE_W - MARGIN_R, foot_y,
        f"Page {doc.page}",
    )
    # Thin footer rule
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.3)
    canvas.line(MARGIN_L, rule_y, PAGE_W - MARGIN_R, rule_y)
    canvas.restoreState()


def build_doc(out_path: Path, page_label: str, tight: bool = False):
    top_m = TIGHT_MARGIN_T if tight else MARGIN_T
    bot_m = TIGHT_MARGIN_B if tight else MARGIN_B
    doc = BaseDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=top_m,
        bottomMargin=bot_m,
        title=page_label,
        author="CognaSync",
    )
    frame = Frame(
        MARGIN_L, bot_m,
        CONTENT_W, PAGE_H - top_m - bot_m,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        showBoundary=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="main", frames=[frame],
                     onPage=lambda c, d: draw_chrome(c, d, page_label, tight=tight)),
    ])
    return doc


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def section_header(label: str):
    """Section label with small accent bar above."""
    return [
        AccentBar(),
        Spacer(1, 4),
        Paragraph(label, STYLES["section"]),
    ]


def kv_row(label, value):
    return Paragraph(
        f'<font color="#6B6B6B"><b>{label}</b></font>&nbsp;&nbsp;{value}',
        STYLES["body_tight"],
    )


def callout_paragraph(text, style=None, tint=ACCENT_TINT, border=ACCENT, padding=8):
    """Render a paragraph inside a tinted single-cell table for a callout look."""
    style = style or STYLES["body"]
    inner = Paragraph(text, style)
    tbl = Table([[inner]], colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), tint),
        ("LEFTPADDING", (0, 0), (-1, -1), padding + 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ("LINEBEFORE", (0, 0), (0, -1), 2, border),
    ]))
    return tbl


# =============================================================================
# DOCUMENT 1 — Executive Summary
# =============================================================================

def doc1_executive_summary():
    out = OUT_DIR / "1-cognasync-executive-summary.pdf"
    doc = build_doc(out, "CognaSync — Executive Summary", tight=True)
    story = []

    story.append(Paragraph("CognaSync", STYLES["wordmark"]))
    story.append(Paragraph(
        "Behavioral pattern recognition for outpatient mental health care",
        STYLES["tagline"],
    ))
    story.append(HRule(thickness=0.6, color=RULE, space_after=6))
    story.append(Paragraph("Executive Summary", STYLES["doctitle"]))
    story.append(Paragraph(
        "Prepared for John Graham (Sunbelt Holdings) and Jonathan Cohen (Idealab Arizona) &nbsp;&middot;&nbsp; May 2026",
        STYLES["meta"],
    ))

    # What it is
    story.extend(section_header("What CognaSync is"))
    story.append(Paragraph(
        "CognaSync is a behavioral pattern-tracking platform that pairs a patient-facing "
        "daily check-in with a provider-facing clinical summary, so the clinician walks "
        "into the appointment already knowing what has actually been happening in the "
        "patient's life between visits. The product surfaces patterns in self-reported "
        "data — mood, sleep, stress, medication adherence, substance use, and behavioral "
        "signals — without ever crossing into diagnosis or medication recommendation.",
        STYLES["lead"],
    ))

    # Clinical safety architecture
    story.extend(section_header("Clinical safety architecture"))
    story.append(Paragraph(
        "Every AI output is governed by four non-negotiable rules baked into the system "
        "prompt and enforced programmatically: never diagnose, never advise medication "
        "changes, describe data rather than clinical meaning, and route to crisis resources "
        "rather than engage with self-harm content.",
        STYLES["body"],
    ))
    story.append(Paragraph(
        "All quantitative scores — stability, stim load, sleep disruption, crash risk, "
        "nervous system load — are computed deterministically in code before any AI call, "
        "so the model never invents or recomputes numbers; it only references values passed "
        "to it as structured data.",
        STYLES["body"],
    ))
    story.append(Paragraph(
        "Crisis language is intercepted before it ever reaches the model, and every "
        "generated output is post-processed against a forbidden-language list that catches "
        "diagnostic phrasing, medication recommendations, and certainty overclaims that the "
        "model might otherwise let slip.",
        STYLES["body"],
    ))

    # Stage
    story.extend(section_header("Where we are today"))
    story.append(Paragraph(
        "Platform built and operational: dual-interface web product with patient daily "
        "check-in (basic and advanced modes), provider dashboard with patient summaries and "
        "threshold alerts, four AI output modes, deterministic scoring engine, symptom-"
        "correlation detection across eleven tracked variables, substance-use pattern "
        "detection, and a provider-only interpersonal safety signal detector. Built on "
        "Flask, React, Supabase, and the Anthropic API. "
        "<font color='#6B6B6B'><i>[Customize: current pilot status, design partners under "
        "discussion, any provider conversations underway.]</i></font>",
        STYLES["body"],
    ))

    # 12-month plan
    story.extend(section_header("The next twelve months"))
    story.append(Paragraph(
        "<b>Months 1–3.</b> Sign first clinical design partner — an Arizona behavioral "
        "health practice or outpatient psychiatric group — and run a structured pilot to "
        "validate provider workflow integration and clinical utility.",
        STYLES["body_tight"],
    ))
    story.append(Paragraph(
        "<b>Months 4–6.</b> Refine the provider interface against real clinical feedback. "
        "Sign a second design partner. Formalize regulatory and security posture "
        "(HIPAA BAA infrastructure, SaMD positioning).",
        STYLES["body_tight"],
    ))
    story.append(Paragraph(
        "<b>Months 7–12.</b> Convert design partners to paying providers. Validate "
        "willingness to pay at the practice level. Begin structured conversations with "
        "Arizona health systems (Valleywise, Banner Health) about institutional pilots.",
        STYLES["body_tight"],
    ))

    # Specific ask
    story.extend(section_header("Specific ask from this conversation"))
    story.append(callout_paragraph(
        "<b>One introduction</b> from John Graham to behavioral health leadership at "
        "Valleywise Health Foundation, for an exploratory pilot conversation. "
        "<b>One structural conversation</b> with Jonathan Cohen and the Idealab Arizona "
        "team about whether and how the studio's resources — network, GTM, ASU connectivity "
        "— can engage with a built, non-ASU-affiliated company in the medical/AI vertical. "
        "Capital is welcome but secondary to network and clinical relationships.",
        style=STYLES["body"], tint=ACCENT_TINT, border=ACCENT, padding=6,
    ))

    doc.build(story)
    return out


# =============================================================================
# DOCUMENT 2 — Mode C Provider Summary (sample)
# =============================================================================

def doc2_mode_c_sample():
    out = OUT_DIR / "2-cognasync-mode-c-sample.pdf"
    doc = build_doc(out, "CognaSync — Mode C Provider Summary (Sample)")
    story = []

    # Header
    story.append(Paragraph("CognaSync", STYLES["wordmark"]))
    story.append(Paragraph(
        "Mode C — Provider Clinical Summary &nbsp;&middot;&nbsp; "
        "Sample output for review (hypothetical patient, redacted)",
        STYLES["tagline"],
    ))
    story.append(HRule(thickness=0.6, color=RULE, space_after=6))

    # Patient meta
    meta_data = [
        [Paragraph("Patient", STYLES["mono_label"]),
         Paragraph("P-2284 (redacted)", STYLES["mono_value"]),
         Paragraph("Reporting period", STYLES["mono_label"]),
         Paragraph("14 days ending May 15, 2026", STYLES["mono_value"])],
        [Paragraph("Check-ins logged", STYLES["mono_label"]),
         Paragraph("12 of 14 days", STYLES["mono_value"]),
         Paragraph("Most recent entry", STYLES["mono_label"]),
         Paragraph("May 14, 2026 (1 day ago)", STYLES["mono_value"])],
    ]
    meta_table = Table(meta_data, colWidths=[1.05 * inch, 2.1 * inch, 1.15 * inch, 2.5 * inch])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 4))
    story.append(HRule(thickness=0.3, color=RULE, space_after=4))

    # Trajectory
    story.extend(section_header("Trajectory"))
    story.append(Paragraph(
        "Stability scores trended modestly downward across the 14-day period, with "
        "sleep disruption and self-reported headaches emerging as the most consistent "
        "co-occurring signals.",
        STYLES["body"],
    ))

    # Quantitative summary
    story.extend(section_header("Quantitative summary"))
    quant_rows = [
        ["Mood", "5.1 / 10", "declining", "slope -0.18/day, R²=0.31, p=0.04", "range 3–7"],
        ["Stress / Anxiety", "6.4 / 10", "rising", "slope +0.15/day, R²=0.22, p=0.09", "range 4–8"],
        ["Sleep", "6.2 hrs", "—", "Sleep Disruption Score avg 5.8 / 10", "<6 hrs on 6 of 12 nights"],
        ["Energy", "4.7 / 10", "stable", "—", "range 3–6"],
        ["Stim Load", "5.3 / 10", "—", "high-load days (≥7): 4 of 12", "caffeine ≥250mg on 5 days"],
    ]
    header = ["Variable", "Average", "Trend", "Statistical detail", "Range / context"]
    table_data = [[Paragraph(f"<b>{h}</b>", STYLES["small"]) for h in header]] + [
        [Paragraph(c, STYLES["small"]) for c in row] for row in quant_rows
    ]
    qtable = Table(table_data, colWidths=[1.05 * inch, 0.75 * inch, 0.7 * inch, 1.95 * inch, 2.35 * inch])
    qtable.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT_TINT),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, ACCENT),
        ("LINEBELOW", (0, -1), (-1, -1), 0.3, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [None, HexColor("#F8F8F8")]),
    ]))
    story.append(qtable)

    # Medication signal
    story.extend(section_header("Medication signal"))
    story.append(Paragraph(
        "Escitalopram 10mg logged on 11 of 12 check-in days (one missed dose on day 7). "
        "Dose timing varied between 7:15 AM and 11:50 AM across logged days, with a "
        "standard deviation of 78 minutes — timing variability exceeds the 60-minute "
        "consistency threshold. No PRN or stimulant medications recorded for this period.",
        STYLES["body"],
    ))

    # Advanced data
    story.extend(section_header("Advanced data (12 of 14 days populated)"))
    story.append(Paragraph(
        "Exercise logged on 5 of 12 days (avg 28 min on logged days). Alcohol units "
        "averaged 1.4 across all days, 2.6 on drinking days (5 of 12). Social quality "
        "averaged 5.2 / 10. Workload friction averaged 7.1 / 10, with sustained scores "
        "above 7 across the first 8 days of the period. Hydration logged adequate on 6 of "
        "12 days. Coping activities (breathing, meditation, movement) logged on 5 of 12 days.",
        STYLES["body"],
    ))

    # Qualitative themes
    story.extend(section_header("Qualitative themes"))
    story.append(Paragraph(
        "Journal entries from 9 of 12 days reference work. Recurring subjects include a "
        "specific project deadline, two named colleagues, and language clustered around "
        "<i>behind</i>, <i>catching up</i>, and <i>too much</i>. Three entries reference "
        "difficulty falling asleep specifically on Sunday and Monday nights. No coping "
        "activities logged on 7 of 12 days.",
        STYLES["body"],
    ))

    # PAGE 2
    story.append(PageBreak())
    story.append(Paragraph("Mode C — P-2284 (continued)", STYLES["doctitle"]))
    story.append(Spacer(1, 6))

    # Symptom patterns
    story.extend(section_header("Symptom patterns"))
    story.append(Paragraph(
        "<b>Headache.</b> Reported on 5 of 12 days. Co-occurring signals on symptom days: "
        "sleep_disruption_score elevated (avg 7.4 vs. 4.6 on non-symptom days, "
        "Δ = 2.8, n = 5); Stim Load elevated (avg 6.6 vs. 4.4, Δ = 2.2, n = 5). "
        "No medication change events within ±14 days of first symptom entry.",
        STYLES["body"],
    ))
    story.append(Paragraph(
        "No other symptoms meet the ≥3-day reporting threshold for this period.",
        STYLES["small_italic"],
    ))

    # Flags
    story.extend(section_header("Flags"))
    flag_html = (
        "<b>Sleep Disruption</b> &nbsp;—&nbsp; period average 5.8 / 10 exceeds the "
        "5.0 flag threshold; six of twelve nights logged below 6 hours.<br/><br/>"
        "<b>Headache Symptom Pattern</b> &nbsp;—&nbsp; symptom meets reporting "
        "threshold (≥3 days) with quantitatively distinct co-occurring sleep and "
        "stim-load patterns on symptom days.<br/><br/>"
        "<b>Sustained Workload Friction</b> &nbsp;—&nbsp; scores ≥7 sustained "
        "for 8 consecutive days, coinciding temporally with the rising-stress trend."
    )
    story.append(callout_paragraph(flag_html, style=STYLES["body"], tint=FLAG_TINT, border=FLAG_BORDER))

    # Suggested discussion topics
    story.extend(section_header("Suggested discussion topics"))
    story.append(Paragraph(
        "<b>1.</b> The Sunday/Monday sleep difficulty pattern combined with the "
        "sustained workload friction — worth clarifying with the patient whether the "
        "sleep difficulty is anticipatory of the week ahead or carryover from the prior "
        "week.",
        STYLES["body"],
    ))
    story.append(Paragraph(
        "<b>2.</b> The headache pattern's co-occurrence with sleep disruption and "
        "elevated Stim Load on the same days — worth confirming the patient's "
        "caffeine intake pattern and whether anything has shifted in dose timing or "
        "amount within the window.",
        STYLES["body"],
    ))
    story.append(Paragraph(
        "<b>3.</b> Alcohol logged on 5 of 12 days at an average of 2.6 units on "
        "drinking days. Volume sits below clinical concern threshold and is being "
        "raised only because it co-occurs temporally with the disrupted-sleep pattern.",
        STYLES["body"],
    ))

    # Methodology footer
    story.append(Spacer(1, 12))
    story.append(HRule(thickness=0.3, color=RULE, space_after=4))
    story.append(Paragraph(
        "<b>Methodology note.</b> This summary was generated from 12 check-ins logged "
        "across a 14-day window. Pattern claims requiring ≥7 logged days are valid "
        "for this period. Statistical trend references are reported only where N ≥ 21 "
        "with p ≤ 0.05 and R² ≥ 0.25; where the period contains insufficient "
        "data for statistical claims, the system reports observed averages and ranges "
        "without inferring trend. All scores are computed deterministically in code prior "
        "to any AI-generated language. Output is post-processed against a forbidden-language "
        "list to prevent diagnostic phrasing, medication recommendations, and certainty "
        "overclaims.",
        STYLES["footer"],
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<i>This document is a sample of system output for a hypothetical patient. "
        "No real patient data has been used. Numbers, journal references, and dates "
        "have been fabricated for demonstration.</i>",
        STYLES["footer"],
    ))

    doc.build(story)
    return out


# =============================================================================
# DOCUMENT 3 — Safety Architecture One-Pager
# =============================================================================

def doc3_safety_architecture():
    out = OUT_DIR / "3-cognasync-safety-architecture.pdf"
    doc = build_doc(out, "CognaSync — Clinical Safety Architecture", tight=True)
    story = []

    story.append(Paragraph("CognaSync", STYLES["wordmark"]))
    story.append(Paragraph(
        "Clinical safety architecture — the four non-negotiable rules and the symptom-pattern logic",
        STYLES["tagline"],
    ))
    story.append(HRule(thickness=0.6, color=RULE, space_after=8))

    story.append(Paragraph(
        "The defining design constraint of CognaSync is that every AI output respects a "
        "clear boundary: the system describes patterns in patient data; the clinician "
        "interprets what those patterns mean. The four rules below are enforced in three "
        "places — the system prompt, the structured data passed to the model, and a "
        "post-generation sanitization pass.",
        STYLES["body"],
    ))

    # The Four Rules — rendered as a table of numbered cells
    rules = [
        ("01", "Never diagnose",
         "No identification, detection, suggestion, or implication of any medical "
         "condition, mental health disorder, or psychiatric diagnosis. The rule applies "
         "to indirect framings (\"this pattern is often associated with…\") as well as "
         "explicit ones."),
        ("02", "Never advise medication changes",
         "No suggestion to start, stop, adjust the dose of, adjust the timing of, or "
         "substitute any medication. Observations that bear on medication route to "
         "provider discussion topics, never to patient action prompts."),
        ("03", "Describe data, not clinical meaning",
         "Observations are expressed as what the numbers show, not what they mean. "
         "“Mood averaged 4.2/10 over 14 days, trending down” is permitted; "
         "“mood has been consistently low” is not. Specificity protects against "
         "both overclaiming and hallucination."),
        ("04", "Route, don't engage, in crisis",
         "Crisis signals — explicit statements of self-harm or suicidal ideation — "
         "interrupt all analysis. The system replaces output with static crisis resources "
         "(988, Crisis Text Line, 911). The model never processes, comments on, or "
         "acknowledges the content of the triggering statement."),
    ]

    for number, title, body in rules:
        cell_left = Paragraph(number, STYLES["rule_number"])
        cell_right_inner = [
            Paragraph(title, STYLES["rule_title"]),
            Paragraph(body, STYLES["rule_body"]),
        ]
        cell_right = Table([[c] for c in cell_right_inner], colWidths=[CONTENT_W - 0.55 * inch])
        cell_right.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        rule_table = Table(
            [[cell_left, cell_right]],
            colWidths=[0.55 * inch, CONTENT_W - 0.55 * inch],
        )
        rule_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEABOVE", (0, 0), (-1, 0), 0.4, RULE),
        ]))
        story.append(KeepTogether(rule_table))

    story.append(Spacer(1, 6))
    story.append(HRule(thickness=0.6, color=RULE, space_after=10))

    # Enforcement
    story.extend(section_header("How the rules are enforced"))
    story.append(Paragraph(
        "The system prompt instructs the model to follow all four rules at generation "
        "time. After generation, every output is post-processed against a forbidden-language "
        "list that catches diagnostic phrasing (“you have…,” “you suffer "
        "from”), medication recommendations (“stop taking,” “increase "
        "your dose”), and certainty overclaims (“this confirms,” “this "
        "indicates [disorder]”). All quantitative scores — stability, stim load, "
        "sleep disruption, crash risk, nervous system load — are computed deterministically "
        "in Python before any AI call, so the model never invents or recomputes numbers; it "
        "only references values it receives as structured input.",
        STYLES["body"],
    ))

    # Symptom pattern logic
    story.extend(section_header("Symptom pattern detection"))
    story.append(Paragraph(
        "Patients log symptoms (headache, fatigue, brain fog, nausea, dizziness, and others) "
        "inside the daily check-in. When a symptom appears on three or more days within a "
        "60-day window, the system computes its co-occurrence with eleven tracked variables: "
        "sleep disruption, stim load, crash risk, mood, stress, energy, exercise minutes, "
        "alcohol units, hydration, workload friction, and perceived stress. A co-occurrence "
        "is surfaced only when the absolute difference between symptom-day and non-symptom-day "
        "means exceeds 1.5 on the variable's scale, and only when at least three matched "
        "observations support the comparison.",
        STYLES["body"],
    ))
    story.append(Paragraph(
        "When a symptom meets reporting threshold, the system also queries medication events "
        "for any new prescription, dose change, or discontinuation within ±14 days of the "
        "symptom's first appearance. If a change is found, it is reported as <b>temporal "
        "context, never as cause</b> — phrased as “these entries began around the "
        "same time as a change in [medication name] — worth mentioning to your "
        "provider,” never as “this is consistent with [a withdrawal effect]” "
        "or “this is caused by [the medication change].”",
        STYLES["body"],
    ))
    story.append(callout_paragraph(
        "The line is deliberate: the system surfaces patterns, the provider draws "
        "conclusions. No symptom interpretation. No causal claim. No recommendation. "
        "The provider receives the pattern with the data anchors needed to evaluate it "
        "clinically.",
        style=STYLES["body"], tint=ACCENT_TINT, border=ACCENT, padding=6,
    ))

    doc.build(story)
    return out


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    out1 = doc1_executive_summary()
    out2 = doc2_mode_c_sample()
    out3 = doc3_safety_architecture()
    print(f"Wrote: {out1}")
    print(f"Wrote: {out2}")
    print(f"Wrote: {out3}")
