"""LinkedIn "Standardized Data": the codes the API returns instead of names.

Demographics come back as URNs (urn:li:geo:…, urn:li:function:…, urn:li:seniority:…, urn:li:industry:…) or enums
(staffCountRange SIZE_11_TO_50 …) that an app has to translate into names.

- Job functions (1-26) and seniorities (1-10) follow LinkedIn's published standard lists.
- Country ids: India 102713980 and United States 103644278 appear in LinkedIn's own doc samples; the others are
  LinkedIn's ids where known and otherwise illustrative.
- Region/city ids and industry ids below are ILLUSTRATIVE for the dummy data: stable numbers in a plausible range,
  not guaranteed to be LinkedIn's real ids. The real app resolves ids through LinkedIn's lookup endpoints, so
  nothing should depend on these exact numbers.
"""

import zlib

# Real LinkedIn enum, shared with the app (the mock serves the same codes the real API returns)
from core.integrations.linkedin.standardized import STAFF_LABELS, STAFF_RANGES  # noqa: F401

FUNCTIONS = {
    1: "Accounting", 2: "Administrative", 3: "Arts and Design", 4: "Business Development",
    5: "Community and Social Services", 6: "Consulting", 7: "Education", 8: "Engineering", 9: "Entrepreneurship",
    10: "Finance", 11: "Healthcare Services", 12: "Human Resources", 13: "Information Technology", 14: "Legal",
    15: "Marketing", 16: "Media and Communication", 17: "Military and Protective Services", 18: "Operations",
    19: "Product Management", 20: "Program and Project Management", 21: "Purchasing", 22: "Quality Assurance",
    23: "Real Estate", 24: "Research", 25: "Sales", 26: "Customer Success and Support",
}

SENIORITIES = {
    1: "Unpaid", 2: "Training", 3: "Entry", 4: "Senior", 5: "Manager", 6: "Director", 7: "VP", 8: "CXO",
    9: "Partner", 10: "Owner",
}


COUNTRIES = {
    "India": 102713980, "United States": 103644278, "United Arab Emirates": 104305776, "United Kingdom": 101165590,
    "Saudi Arabia": 100459316, "Qatar": 104170880, "Oman": 103619019, "Kuwait": 103239229, "Bahrain": 100425729,
    "Canada": 101174742, "Germany": 101282230, "Australia": 101452733, "Pakistan": 101022442, "Egypt": 106155005,
    "Philippines": 103121230, "Singapore": 102454443, "Sri Lanka": 100446352, "Nepal": 104630404,
    "Bangladesh": 106215326,
}


def stable_id(name: str, base: int, span: int) -> int:
    """A deterministic illustrative id for a name (same name -> same id on every run)."""
    return base + zlib.crc32(name.encode("utf-8")) % span


def geo_id(name: str) -> int:
    """Countries use the table above; regions/cities get an illustrative id in LinkedIn's market-area range."""
    return COUNTRIES.get(name) or stable_id(name, 90010000, 89999)


def industry_id(name: str) -> int:
    known = {
        "Software Development": 4, "Technology, Information and Internet": 6, "IT Services and IT Consulting": 96,
        "Advertising Services": 80, "Marketing Services": 1862, "Financial Services": 43, "Higher Education": 68,
        "Primary and Secondary Education": 1999, "Education Administration Programs": 69,
        "IT System Custom Software Development": 3102, "Staffing and Recruiting": 104,
    }
    return known.get(name) or stable_id(name, 3200, 2000)


def function_id(name: str) -> int | None:
    return next((k for k, v in FUNCTIONS.items() if v.lower() == name.lower()), None)


def seniority_id(name: str) -> int | None:
    return next((k for k, v in SENIORITIES.items() if v.lower() == name.lower()), None)
