"""Test data builders shared by the test modules (LinkedIn export workbooks)."""

import io
from datetime import date

import openpyxl

EXPORTED = date(2026, 11, 16)

def _xlsx(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

POST_HEADER = [
    "Post title", "Post link", "Post type", "Campaign name", "Posted by", "Created date", "Campaign start date",
    "Campaign end date", "Audience", "Impressions", "Views", "Offsite Views", "Clicks", "Click through rate (CTR)",
    "Likes", "Comments", "Reposts", "Follows", "Engagement rate", "Content Type",
]

def _post(link: str, created: str, ctype: str, caption: str, impressions: int = 100, views="") -> list:
    return [caption, link, "Organic", "", "Someone", created, "", "", "All followers", impressions, views, "",
            5, 0.05, 8, 2, 1, "", 0.16, ctype]

def content_file(posts: list[list]) -> bytes:
    return _xlsx({
        "Metrics": [
            ["Aggregated engagement metrics ... All dates and times are in UTC."],
            ["Date", "Impressions (organic)", "Impressions (sponsored)", "Impressions (total)", "Unique impressions (organic)",
             "Clicks (organic)", "Clicks (sponsored)", "Clicks (total)", "Reactions (organic)", "Reactions (sponsored)",
             "Reactions (total)", "Comments (organic)", "Comments (sponsored)", "Comments (total)", "Reposts (organic)",
             "Reposts (sponsored)", "Reposts (total)"],
            ["11/14/2026", 22, 0, 22, 11, 2, 0, 2, 1, 0, 1, 0, 0, 0, 0, 0, 0],
        ],
        "All posts": [["Engagement metrics for individual posts."], POST_HEADER, *posts],
    })
