"""LinkedIn "Standardized Data" codes the app needs to read API responses.

Company size (staffCountRange) is a fixed LinkedIn enum. Geo, function, seniority and industry ids are resolved
through LinkedIn's lookup endpoints instead of being hard-coded.
"""



STAFF_RANGES = {
    "1": "SIZE_1", "2-10": "SIZE_2_TO_10", "11-50": "SIZE_11_TO_50", "51-200": "SIZE_51_TO_200",
    "201-500": "SIZE_201_TO_500", "501-1000": "SIZE_501_TO_1000", "1001-5000": "SIZE_1001_TO_5000",
    "5001-10000": "SIZE_5001_TO_10000", "10001+": "SIZE_10001_OR_MORE",
}

STAFF_LABELS = {v: k for k, v in STAFF_RANGES.items()}
