"""Made-up audience proportions for the demo data (instead of proportions taken from a real page export).

Keeps LinkedIn's standard category names (locations, job functions, seniority, industries, company sizes) and
invents the counts: a seeded random long tail, with a UAE-heavy location mix so the demo shows the app's UAE
features. The numbers describe no real page.

    python manage.py shell -c "from core.mock_linkedin.synthetic_calibration import write; write()"
"""

import json
import random
from pathlib import Path

from dev_tools.mock_linkedin import MOCK_DIR

SEED = 2026
TOTALS = {"followers": 3850, "visitors": 560}
# Made-up share of each audience in the UAE (spread over the UAE locations in the list)
UAE_SHARE = {"followers": 0.21, "visitors": 0.34}
# A plausible (invented) lead order for a UAE software / ERP / edtech company; other names follow at random
LEADERS = {
    "job_function": ["Engineering", "Information Technology", "Business Development", "Operations", "Education", "Sales", "Entrepreneurship"],
    "industry": ["Software Development", "IT Services and IT Consulting", "Education Administration Programs", "Primary and Secondary Education",
                 "Financial Services", "Technology, Information and Internet", "Retail"],
    "seniority": ["Senior", "Entry", "Manager", "Director", "Owner", "CXO", "VP"],
    "company_size": ["11-50", "51-200", "2-10", "201-500", "1001-5000", "501-1000"],
}


def _counts(names: list[str], total: int, rng: random.Random, uae: float | None, leaders: list[str] = ()) -> list[list]:
    # Long tail: weights fall off with rank. The order is invented: leaders first, the rest shuffled
    rest = [n for n in names if n not in leaders]
    rng.shuffle(rest)
    order = [n for n in leaders if n in names] + rest
    weights = {n: rng.lognormvariate(0, 0.4) / (i + 1) ** 0.9 for i, n in enumerate(order)}
    if uae is not None:
        uae_names = [n for n in names if "United Arab Emirates" in n]
        if uae_names:
            rest = sum(w for n, w in weights.items() if n not in uae_names)
            # Give the UAE names `uae` of the weight, split unevenly (Dubai usually leads)
            split = sorted((rng.random() + (1.5 if "Dubai" in n else 0) for n in uae_names), reverse=True)
            uae_sorted = sorted(uae_names, key=lambda n: ("Dubai" not in n, "Abu Dhabi" not in n))
            s = sum(split)
            for n, part in zip(uae_sorted, split):
                weights[n] = rest * uae / (1 - uae) * part / s
    w_total = sum(weights.values())
    rows = [[n, max(1, round(total * w / w_total))] for n, w in weights.items()]
    rows.sort(key=lambda r: -r[1])
    return rows


def build(real_shape: dict) -> dict:
    rng = random.Random(SEED)
    out = {}
    for key, section in real_shape.items():
        audience, _, dim = key.partition("/")
        total = TOTALS.get(audience, section.get("total", 1000))
        names = [r[0] for r in section.get("rows", [])]
        uae = UAE_SHARE.get(audience) if dim == "location" else None
        out[key] = {"total": total, "rows": _counts(names, total, rng, uae, LEADERS.get(dim, []))}
    return out


def write(src: Path = MOCK_DIR / "calibration_demographics.json", dst: Path = MOCK_DIR / "calibration_synthetic.json") -> Path:
    """Read only the category names from `src`, write made-up counts to `dst`."""
    real = json.loads(src.read_text(encoding="utf-8"))
    dst.write_text(json.dumps(build(real), ensure_ascii=False, indent=1), encoding="utf-8")
    return dst
