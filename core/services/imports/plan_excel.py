"""Plan posts in bulk from an Excel file (or the same columns saved as CSV): the template, reading and checking
rows, and saving the ready ones as drafts. The HTTP side (permissions, upload, response) is in
core/api/views/plan_import.py.

Rows with problems and posts already planned are skipped, never half-saved.
"""

import csv
import io
from datetime import date, datetime, time, timedelta

from django.db import transaction
from pydantic import ValidationError

from core.common.timeutil import as_utc, from_uae_local, now_utc
from core.models import PlannedPost
from core.schemas.planner import PlannedPostIn


class PlanFileError(ValueError):
    """The file can't be read as a plan (wrong type, empty, missing columns, too many rows). Shown to the user."""


MAX_ROWS = 200

MAX_BYTES = 5 * 1024 * 1024

# (key, heading in the template, required, what to put, example)
COLUMNS = [
    ("date", "Date (UAE)", "For scheduling", "The day to post, e.g. 2026-12-02. Leave Date and Time empty to keep it unscheduled.", "2026-12-02"),
    ("time", "Time (UAE)", "For scheduling", "24-hour UAE time, e.g. 10:30. Needed whenever a date is given.", "10:30"),
    ("format", "Format", "Yes", "Pick from the list: Text, Image, Carousel, Video, Article or Poll.", "Text"),
    ("goal", "Goal", "Yes", "Pick from the list: Brand awareness, Sales or Engagement.", "Sales"),
    ("caption", "Post text", "Yes", "The full post as it should appear on LinkedIn (up to 3,000 characters). Hashtags go at the end of the text.", "Is your ERP doing the work, or are you?"),
    ("topic", "Topic", "No", "What the post is about, e.g. ERP & CRM. Used in Data to compare topics.", "ERP & CRM"),
    ("industry", "Industry", "No", "The industry it speaks to, e.g. Education.", "Trading"),
    ("cta", "Call to action", "No", "What you ask readers to do, e.g. Comment ERP for the checklist.", "Comment ERP for the checklist"),
    ("visibility", "Visibility", "No", "Public (default) or Connections only.", "Public"),
    ("article_title", "Article title", "Article only", "The article's headline.", ""),
    ("article_link", "Article link", "Article only", "Full link starting with https://", ""),
    ("poll_question", "Poll question", "Poll only", "Up to 140 characters.", ""),
    ("poll_options", "Poll options", "Poll only", "2 to 4 options separated by ; (each up to 30 characters), e.g. Yes; No; Not sure", ""),
    ("poll_duration", "Poll duration", "Poll only", "1 day, 3 days, 1 week or 2 weeks (default 1 week).", ""),
    ("carousel_title", "Carousel title", "Carousel only", "The document title LinkedIn shows on the carousel.", ""),
]

KEYS = [c[0] for c in COLUMNS]

HEADINGS = {c[1].lower(): c[0] for c in COLUMNS} | {c[0]: c[0] for c in COLUMNS}

FORMATS = {"text": "text", "image": "image", "carousel": "carousel", "video": "video", "article": "article", "poll": "poll", "newsletter": "article"}

GOALS = {"brand awareness": "brand", "brand": "brand", "sales": "sales", "leads": "sales", "engagement": "engagement"}

VISIBILITY = {"public": "PUBLIC", "": "PUBLIC", "connections only": "CONNECTIONS", "connections": "CONNECTIONS"}

DURATIONS = {"1 day": "1d", "3 days": "3d", "1 week": "1w", "2 weeks": "2w", "1d": "1d", "3d": "3d", "1w": "1w", "2w": "2w", "": None}

LIST_COLUMNS = {
    "format": ["Text", "Image", "Carousel", "Video", "Article", "Poll"],
    "goal": ["Brand awareness", "Sales", "Engagement"],
    "visibility": ["Public", "Connections only"],
    "poll_duration": ["1 day", "3 days", "1 week", "2 weeks"],
}

EXAMPLES = [
    {"date": "2026-12-02", "time": "10:30", "format": "Text", "goal": "Sales", "caption": "VAT season again. Is your ERP doing the work, or are you?\n\nComment ERP and we'll send our year-end checklist.\n\n#ERP #UAE", "topic": "ERP & CRM", "industry": "Trading", "cta": "Comment ERP for the checklist", "visibility": "Public"},
    {"date": "2026-12-03", "time": "13:00", "format": "Poll", "goal": "Engagement", "caption": "Quick one for school leaders in the UAE 👇\n\n#EdTech #UAE", "topic": "Education & LMS", "industry": "Education", "visibility": "Public", "poll_question": "What slows your LMS rollout most?", "poll_options": "Teacher training; Content; Parent apps; Budget", "poll_duration": "1 week"},
    {"date": "", "time": "", "format": "Article", "goal": "Brand awareness", "caption": "Our take on AI in UAE SMEs: where it pays off first.", "topic": "AI for business", "article_title": "AI in UAE SMEs: where it pays off first", "article_link": "https://avaibe.com/blog/ai-smes"},
]

def _read_rows(upload) -> list[tuple[int, dict]]:
    """(row number as the user sees it, {key: value}) for every non-empty row."""
    name = (upload.name or "").lower()
    raw = upload.read()
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception:
            raise PlanFileError("That Excel file couldn't be opened. Save it as .xlsx and try again.")
        ws = wb["Posts"] if "Posts" in wb.sheetnames else wb.worksheets[0]
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
    elif name.endswith(".csv"):
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        grid = [list(r) for r in csv.reader(io.StringIO(text))]
    else:
        raise PlanFileError("Upload the Excel template (.xlsx) or the same columns saved as .csv.")
    if not grid:
        raise PlanFileError("The file is empty.")
    header = [HEADINGS.get(str(h or "").strip().lower()) for h in grid[0]]
    missing = [c[1] for c in COLUMNS if c[2] == "Yes" and c[0] not in header]
    if missing:
        raise PlanFileError(f"Missing column{'s' if len(missing) > 1 else ''}: {', '.join(missing)}. Use the template and keep its headings.")
    rows = []
    for i, values in enumerate(grid[1:], start=2):
        row = {k: v for k, v in zip(header, values) if k}
        if all(v is None or str(v).strip() == "" for v in row.values()):
            continue
        rows.append((i, row))
    if len(rows) > MAX_ROWS:
        raise PlanFileError(f"The file has {len(rows)} posts; the limit is {MAX_ROWS} per file. Split it into smaller files.")
    return rows

def _text(v) -> str:
    return "" if v is None else str(v).strip()

def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _text(v)
    if not s:
        return None
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise ValueError(f'Date "{s}" isn\'t a date like 2026-12-02')

def _time(v) -> time | None:
    if isinstance(v, datetime):
        return v.time()
    if isinstance(v, time):
        return v
    if isinstance(v, (int, float)) and 0 <= v < 1:  # Excel stores times as a fraction of a day
        return (datetime.min + timedelta(days=float(v))).time().replace(second=0, microsecond=0)
    s = _text(v).upper()
    if not s:
        return None
    for f in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            return datetime.strptime(s, f).time()
        except ValueError:
            pass
    raise ValueError(f'Time "{_text(v)}" isn\'t a time like 10:30')

def _pick(v, choices: dict, what: str):
    s = _text(v).lower()
    if s not in choices:
        raise ValueError(f'{what} "{_text(v)}" isn\'t one of the choices')
    return choices[s]

def _check(row: dict) -> tuple[dict | None, list[str]]:
    """The planned-post body for this row, or the problems that stop it."""
    problems: list[str] = []
    body: dict = {}

    def get(fn):
        try:
            return fn()
        except ValueError as e:
            problems.append(str(e))
            return None

    d = get(lambda: _date(row.get("date")))
    t = get(lambda: _time(row.get("time")))
    if d and not t and not any("Time" in p for p in problems):
        problems.append("Add a time for the date (or leave both empty)")
    if t and not d and not any("Date" in p for p in problems):
        problems.append("Add a date for the time (or leave both empty)")
    if d and t:
        when = datetime.combine(d, t)
        if as_utc(from_uae_local(when)) <= now_utc():
            problems.append(f"{d:%d %b %Y} {t:%H:%M} is already in the past")
        body["scheduled_at"] = when.isoformat()

    fmt = get(lambda: _pick(row.get("format") or "Text", FORMATS, "Format"))
    if not _text(row.get("goal")):
        problems.append("Goal is empty: pick Brand awareness, Sales or Engagement")
    else:
        body["goal"] = get(lambda: _pick(row.get("goal"), GOALS, "Goal"))
    vis = get(lambda: _pick(row.get("visibility"), VISIBILITY, "Visibility"))
    caption = _text(row.get("caption"))
    if not caption:
        problems.append("Post text is empty")
    elif len(caption) > 3000:
        problems.append(f"Post text is {len(caption):,} characters; LinkedIn allows 3,000")

    details: dict = {}
    if fmt == "article":
        details = {"title": _text(row.get("article_title")) or None, "link": _text(row.get("article_link")) or None}
        if details["link"] and not details["link"].startswith(("http://", "https://")):
            problems.append("Article link must start with https://")
    elif fmt == "poll":
        raw = _text(row.get("poll_options")).replace("|", ";").replace("\n", ";")
        options = [o.strip() for o in raw.split(";") if o.strip()]
        details = {"question": _text(row.get("poll_question")) or None, "options": options or None, "duration": get(lambda: _pick(row.get("poll_duration"), DURATIONS, "Poll duration")) or "1w"}
        if not details["question"]:
            problems.append("A poll needs a Poll question")
        if not 2 <= len(options) <= 4:
            problems.append(f"A poll needs 2 to 4 Poll options separated by ; (found {len(options)})")
        elif any(len(o) > 30 for o in options):
            problems.append("Each poll option can be up to 30 characters")
        if details["question"] and len(details["question"]) > 140:
            problems.append("Poll question can be up to 140 characters")
    elif fmt == "carousel":
        details = {"document_title": _text(row.get("carousel_title")) or None}

    if problems:
        return None, problems
    body |= {
        "format": fmt,
        "caption": caption,
        "visibility": vis,
        "topic": _text(row.get("topic")) or None,
        "industry": _text(row.get("industry")) or None,
        "cta": _text(row.get("cta")) or None,
        "details": {k: v for k, v in details.items() if v is not None},
    }
    return body, []

def _friendly(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        where = ".".join(str(x) for x in err.get("loc", ()) if x != "details")
        out.append(f"{where.replace('_', ' ').capitalize()}: {err.get('msg', 'not valid')}" if where else err.get("msg", "Not valid"))
    return out


def build_template() -> bytes:
    """The Excel template: Posts sheet with dropdowns, a How to fill sheet, an Example sheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="C4482A")
    wrap = Alignment(wrap_text=True, vertical="top")
    widths = {"date": 13, "time": 11, "format": 12, "goal": 17, "caption": 60, "topic": 20, "industry": 16, "cta": 30, "visibility": 17}

    def posts_sheet(ws, rows):
        ws.append([c[1] for c in COLUMNS])
        for i, key in enumerate(KEYS, start=1):
            cell = ws.cell(row=1, column=i)
            cell.font, cell.fill = head_font, head_fill
            ws.column_dimensions[cell.column_letter].width = widths.get(key, 20)
        ws.freeze_panes = "A2"
        for r in rows:
            ws.append([r.get(k, "") for k in KEYS])
        for row in ws.iter_rows(min_row=2, max_row=max(2, ws.max_row)):
            for cell in row:
                cell.alignment = wrap
                cell.number_format = "@"  # text: Excel keeps 2026-12-02 and 10:30 exactly as typed

    ws = wb.active
    ws.title = "Posts"
    posts_sheet(ws, [])
    for row in ws.iter_rows(min_row=2, max_row=MAX_ROWS + 1, max_col=len(KEYS)):
        for cell in row:
            cell.number_format = "@"
            cell.alignment = wrap
    for key, values in LIST_COLUMNS.items():
        col = ws.cell(row=1, column=KEYS.index(key) + 1).column_letter
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True, showErrorMessage=True)
        dv.error, dv.errorTitle = "Pick a value from the list.", "Not in the list"
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{MAX_ROWS + 1}")

    how = wb.create_sheet("How to fill")
    how.append(["Column", "Required", "What to put", "Example"])
    for c in COLUMNS:
        how.append([c[1], c[2], c[3], c[4]])
    for cell in how[1]:
        cell.font, cell.fill = head_font, head_fill
    for col, w in zip("ABCD", (18, 16, 80, 40)):
        how.column_dimensions[col].width = w
    for row in how.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    how.append([])
    for line in (
        "Fill one row per post on the Posts sheet. Don't rename or move the column headings.",
        "Each post is added as Unpublished. Review it in the app, add any image, PDF or video, then schedule or publish it.",
        f"Up to {MAX_ROWS} posts per file. Importing the same file twice won't add the same post twice.",
        "Hashtags: write them at the end of the post text.",
    ):
        how.append([line])

    ex = wb.create_sheet("Example")
    posts_sheet(ex, EXAMPLES)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def review_rows(upload, account_id: int) -> tuple[list[dict], list]:
    """Check every row. Returns (one result per row for the screen, the rows ready to save as PlannedPostIn)."""
    existing = {(p.caption.strip(), as_utc(p.scheduled_at).isoformat() if p.scheduled_at else None) for p in PlannedPost.objects.filter(account_id=account_id).only("caption", "scheduled_at")}
    seen: set = set()
    results, ready = [], []
    for row_no, row in _read_rows(upload):
        body, problems = _check(row)
        parsed = None
        if body:
            try:
                parsed = PlannedPostIn.model_validate({**body, "account_id": account_id})
            except ValidationError as e:
                problems = _friendly(e)
        status = "error" if problems else "ready"
        if parsed:
            key = (parsed.caption.strip(), as_utc(parsed.scheduled_at).isoformat() if parsed.scheduled_at else None)
            if key in existing:
                status, problems = "duplicate", ["Already planned in the app (same text and time), so it's skipped"]
            elif key in seen:
                status, problems = "duplicate", ["Same text and time as an earlier row in this file, so it's skipped"]
            else:
                seen.add(key)
                ready.append(parsed)
        results.append(
            {
                "row": row_no,
                "status": status,
                "problems": problems,
                "format": parsed.format if parsed else _text(row.get("format")).lower() or None,
                "goal": parsed.goal if parsed else None,
                "scheduled_at": as_utc(parsed.scheduled_at).isoformat() if parsed and parsed.scheduled_at else None,
                "caption": (parsed.caption if parsed else _text(row.get("caption")))[:120],
            }
        )
    return results, ready


def save_drafts(ready: list) -> list[PlannedPost]:
    """Save the ready rows as drafts, all or nothing."""
    created = []
    if ready:
        with transaction.atomic():
            for body in ready:
                data = body.model_dump(exclude={"details"})
                data["details"] = body.stored_details()
                created.append(PlannedPost.objects.create(**data, status="draft"))
    return created
