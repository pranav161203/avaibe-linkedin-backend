"""Parsing LinkedIn's Rest.li 2.0 query syntax, e.g.

    shares=List(urn:li:share:1,urn:li:share:2)
    timeIntervals=(timeRange:(start:1551398400000,end:1552003200000),timeGranularityType:DAY)
    dateRange=(start:(day:4,month:5,year:2024),end:(day:6,month:5,year:2024))
    entity=(share:urn:li:share:7325786486870552578)

URNs contain colons and (for comments/reactions) parentheses, so values are read with bracket depth in mind.
"""


def _split_top(s: str, sep: str = ",") -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts


def parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    v = value.strip()
    if v.startswith("List(") and v.endswith(")"):
        v = v[5:-1]
    return [x.strip() for x in _split_top(v) if x.strip()]


def parse_obj(value: str | None):
    """(a:1,b:(c:2)) -> {"a": "1", "b": {"c": "2"}}. A plain value is returned as-is."""
    if value is None:
        return None
    v = value.strip()
    if not (v.startswith("(") and v.endswith(")")):
        return v
    out = {}
    for part in _split_top(v[1:-1]):
        key, _, rest = part.partition(":")
        rest = rest.strip()
        # A URN value ("share:urn:li:share:1") is not a nested object
        out[key.strip()] = parse_obj(rest) if rest.startswith("(") and not rest.startswith("(urn") else rest
    return out


def time_intervals(params) -> dict | None:
    """Both Rest.li 2.0 (timeIntervals=(…)) and 1.0 (timeIntervals.timeRange.start=…) forms."""
    raw = params.get("timeIntervals")
    if raw:
        o = parse_obj(raw)
        tr = o.get("timeRange", {})
        return {"start": int(tr.get("start")), "end": int(tr.get("end")), "granularity": o.get("timeGranularityType", "DAY")}
    if params.get("timeIntervals.timeRange.start"):
        return {
            "start": int(params["timeIntervals.timeRange.start"]),
            "end": int(params["timeIntervals.timeRange.end"]),
            "granularity": params.get("timeIntervals.timeGranularityType", "DAY"),
        }
    return None


def date_range(params, key: str = "dateRange"):
    """dateRange=(start:(day:4,month:5,year:2024),end:(…)) -> (date, date) with end exclusive; None if absent."""
    from datetime import date

    raw = params.get(key)
    if not raw:
        return None
    o = parse_obj(raw)

    def d(x):
        return date(int(x["year"]), int(x["month"]), int(x["day"]))

    return d(o["start"]), (d(o["end"]) if "end" in o else None)
