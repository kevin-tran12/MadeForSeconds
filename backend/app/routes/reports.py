"""Admin-only expense report endpoints — summary, CSV export, PDF export."""

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..auth import require_admin
from ..firestore import get_db
from ..models_expense import EXPENSE_CATEGORIES

router = APIRouter(prefix="/api/admin/reports", dependencies=[Depends(require_admin)])


def _date_range(year: int, month: int | None):
    """Return (start, end) datetime objects for the given period."""
    if month:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    else:
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return start, end


def _fetch_expenses(db, year: int, month: int | None, status: str = "active") -> list[dict]:
    start, end = _date_range(year, month)
    query = db.collection("expenses")
    query = query.where("status", "==", status)
    query = query.where("date", ">=", start)
    query = query.where("date", "<", end)
    docs = list(query.stream())
    expenses = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        expenses.append(data)
    return expenses


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_summary(year: int, month: int | None = None):
    """Aggregate totals for a year or specific month."""
    db = get_db()
    expenses = _fetch_expenses(db, year, month)

    total_project = sum(e.get("project_total", 0) for e in expenses)
    total_tax = sum(e.get("project_tax", 0) for e in expenses)
    total_raw = sum(e.get("raw_total", 0) for e in expenses)

    # Category breakdown
    by_category: dict[str, dict] = {}
    for cat_value in EXPENSE_CATEGORIES:
        cat_expenses = [e for e in expenses if e.get("category") == cat_value]
        if cat_expenses:
            by_category[cat_value] = {
                "count": len(cat_expenses),
                "total": sum(e.get("project_total", 0) for e in cat_expenses),
                "tax": sum(e.get("project_tax", 0) for e in cat_expenses),
            }

    # Monthly breakdown for yearly queries
    by_month = []
    if not month:
        for m in range(1, 13):
            start = datetime(year, m, 1, tzinfo=timezone.utc)
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if m == 12 else datetime(year, m + 1, 1, tzinfo=timezone.utc)
            month_expenses = [
                e for e in expenses
                if start <= (e.get("date") if isinstance(e.get("date"), datetime) else datetime.fromisoformat(str(e.get("date"))).replace(tzinfo=timezone.utc)) < end
            ]
            by_month.append({
                "month": m,
                "total": sum(e.get("project_total", 0) for e in month_expenses),
                "tax": sum(e.get("project_tax", 0) for e in month_expenses),
                "count": len(month_expenses),
            })

    period = f"{year}-{month:02d}" if month else str(year)
    return {
        "period": period,
        "total_expenses": total_project,
        "total_tax": total_tax,
        "total_raw": total_raw,
        "expense_count": len(expenses),
        "by_category": by_category,
        "by_month": by_month if not month else [],
    }


# ── CSV Export ───────────────────────────────────────────────────────────────


@router.get("/export/csv")
async def export_csv(year: int, month: int | None = None):
    """Download expense data as a CSV file."""
    db = get_db()
    expenses = _fetch_expenses(db, year, month)
    expenses.sort(key=lambda e: str(e.get("date", "")))

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Date", "Vendor", "Category", "Purpose / Recipe", "Description",
        "Raw Subtotal", "Raw Tax", "Raw Total",
        "Project Subtotal", "Project Tax", "Project Total",
        "Item Count", "AI Parsed", "Status",
    ])

    for e in expenses:
        date = e.get("date")
        if isinstance(date, datetime):
            date_str = date.strftime("%Y-%m-%d")
        else:
            date_str = str(date)[:10]

        for_field = e.get("purpose") or e.get("recipe_id") or ""

        def cents(v: int) -> str:
            return f"${v / 100:.2f}"

        writer.writerow([
            date_str,
            e.get("vendor", ""),
            e.get("category", ""),
            for_field,
            e.get("description", ""),
            cents(e.get("raw_subtotal", 0)),
            cents(e.get("raw_tax", 0)),
            cents(e.get("raw_total", 0)),
            cents(e.get("project_subtotal", 0)),
            cents(e.get("project_tax", 0)),
            cents(e.get("project_total", 0)),
            len(e.get("items", [])),
            "Yes" if e.get("ai_parsed") else "No",
            e.get("status", "active"),
        ])

    # Summary row
    writer.writerow([])
    writer.writerow([
        "TOTAL", "", "", "", "",
        f"${sum(e.get('raw_subtotal', 0) for e in expenses) / 100:.2f}",
        f"${sum(e.get('raw_tax', 0) for e in expenses) / 100:.2f}",
        f"${sum(e.get('raw_total', 0) for e in expenses) / 100:.2f}",
        f"${sum(e.get('project_subtotal', 0) for e in expenses) / 100:.2f}",
        f"${sum(e.get('project_tax', 0) for e in expenses) / 100:.2f}",
        f"${sum(e.get('project_total', 0) for e in expenses) / 100:.2f}",
        len(expenses), "", "",
    ])

    period = f"{year}-{month:02d}" if month else str(year)
    filename = f"expenses-{period}.csv"
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── PDF Export ───────────────────────────────────────────────────────────────


@router.get("/export/pdf")
async def export_pdf(year: int, month: int | None = None):
    """Generate a PDF expense report using reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    )

    db = get_db()
    expenses = _fetch_expenses(db, year, month)
    expenses.sort(key=lambda e: str(e.get("date", "")))

    period = f"{year}-{month:02d}" if month else str(year)
    total_project = sum(e.get("project_total", 0) for e in expenses)
    total_tax = sum(e.get("project_tax", 0) for e in expenses)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=18, spaceAfter=4)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10, textColor=colors.grey)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=12, spaceBefore=16, spaceAfter=6)

    brand_color = colors.HexColor("#e85d04")

    story = []

    # Header
    story.append(Paragraph("MadeForSeconds", title_style))
    story.append(Paragraph(f"Expense Report — {period}", sub_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=brand_color, spaceAfter=12))

    # Summary
    story.append(Paragraph("Summary", section_style))
    summary_data = [
        ["Total Expenses", f"${total_project / 100:.2f}"],
        ["Total Tax Paid", f"${total_tax / 100:.2f}"],
        ["Number of Purchases", str(len(expenses))],
    ]
    summary_table = Table(summary_data, colWidths=[3 * inch, 2 * inch])
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.whitesmoke, colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(summary_table)

    # Category breakdown
    story.append(Paragraph("By Category", section_style))
    cat_by_value: dict[str, dict] = {}
    for cat in EXPENSE_CATEGORIES:
        cat_expenses = [e for e in expenses if e.get("category") == cat]
        if cat_expenses:
            cat_by_value[cat] = {
                "count": len(cat_expenses),
                "total": sum(e.get("project_total", 0) for e in cat_expenses),
            }

    cat_data = [["Category", "Count", "Total"]]
    for cat, data in cat_by_value.items():
        pct = (data["total"] / total_project * 100) if total_project > 0 else 0
        cat_data.append([cat.capitalize(), str(data["count"]), f"${data['total'] / 100:.2f} ({pct:.0f}%)"])
    if len(cat_data) > 1:
        cat_table = Table(cat_data, colWidths=[3 * inch, 1.5 * inch, 2.5 * inch])
        cat_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1, 0), brand_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(cat_table)

    # Detailed listing
    story.append(Paragraph("All Expenses", section_style))
    detail_data = [["Date", "Vendor", "Category", "Project Total", "Tax"]]
    for e in expenses:
        date = e.get("date")
        date_str = date.strftime("%Y-%m-%d") if isinstance(date, datetime) else str(date)[:10]
        detail_data.append([
            date_str,
            e.get("vendor", "")[:30],
            e.get("category", ""),
            f"${e.get('project_total', 0) / 100:.2f}",
            f"${e.get('project_tax', 0) / 100:.2f}",
        ])

    if len(detail_data) > 1:
        col_widths = [1 * inch, 2.5 * inch, 1.5 * inch, 1.25 * inch, 1 * inch]
        detail_table = Table(detail_data, colWidths=col_widths)
        detail_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), brand_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(detail_table)

    doc.build(story)
    buffer.seek(0)

    filename = f"expenses-{period}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
