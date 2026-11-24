from typing import Literal

Format = Literal["image", "carousel", "video", "poll", "newsletter", "text", "untagged"]
Checkpoint = Literal["1h", "6h", "24h", "48h", "7d"]


def normalise_hashtags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = t.strip().lstrip("#").strip().lower()
        if t and f"#{t}" not in out:
            out.append(f"#{t}")
    return out


Dimension = Literal["location", "industry", "seniority", "job_title", "job_function", "company_size", "company"]


