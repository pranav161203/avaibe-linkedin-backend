"""Suggest a topic, industry and CTA for a post from its caption.

Used when importing LinkedIn exports, which carry the caption but no topic. These are SUGGESTIONS:
posts get topic_suggested=True until someone opens and saves them. Simple keyword scoring, so it is
predictable and free; the themes follow the assignment brief and AVAIBE's posting history.
"""

import re

# Topic -> patterns (regular expressions, lower-case text). Order breaks ties: more specific first.
TOPICS: list[tuple[str, list[str]]] = [
    ("AVAIBE Tech Debate", [r"tech debate", r"showdown", r"tech war", r"\bvs\.?\b", "🆚", r"head to head", r"which one (would you|comes out)"]),
    ("Cybersecurity", [r"cyber", r"phishing", r"deepfake", r"shadow ai", r"vulnerabilit", r"\battack", r"security gap", r"intrusion", r"fraud", r"sensitive (student )?data"]),
    ("Commodity trading", [r"commodit", r"trading desk", r"\btraders?\b", r"\blng\b", r"\bdmcc\b", r"\bmetals\b", r"trading firms?"]),
    ("Education & LMS", [r"\bschools?\b", r"\blms\b", r"\bstudents?\b", r"classroom", r"teachers?", r"educators?", r"\bspea\b", r"children", r"higher education", r"curriculum", r"learning outcomes"]),
    ("ERP & CRM", [r"\berp\b", r"\bcrm\b", r"enquir", r"follow-?ups?", r"spreadsheet", r"inventory", r"customer (records|details|relationships)", r"e-invoicing", r"corporate tax"]),
    ("Websites & digital marketing", [r"website", r"\bseo\b", r"\bbrand\b", r"digital marketing", r"digital presence", r"\bvisitors?\b", r"\bads\b"]),
    ("Mobile apps", [r"mobile app", r"\bapp idea", r"\bapps?\b.*built your way"]),
    ("UAE trade & economy", [r"hormuz", r"\bports?\b", r"logistics", r"etihad rail", r"trade corridors?", r"customs", r"competition forum", r"\beconomy\b"]),
    ("UAE AI & innovation", [r"\buae\b", r"dubai", r"sharjah", r"abu dhabi", r"emirati", r"arabic", r"falcon", r"\btii\b", r"saudi"]),
    ("AI infrastructure & compute", [r"data[- ]cent", r"\bcompute\b", r"\bgpus?\b", r"power grid", r"electricity", r"\btpus?\b", r"h100", r"infrastructure"]),
    ("AI models & tools", [r"\bgpt", r"chatgpt", r"claude", r"gemini", r"grok", r"qwen", r"\bmeta\b", r"\bmuse\b", r"genie", r"\bsiri\b", r"openai", r"deepmind", r"\bmodels?\b", r"altman", r"image generation", r"generative", r"\bastra\b", r"\bfable\b"]),
    ("AI for business", [r"business(es)?", r"productivity", r"workflows?", r"work smarter", r"future of work", r"automat", r"decisions?"]),
    # Not plain "avaibe": nearly every caption mentions the company in its sign-off
    ("AVAIBE services & brand", [r"at avaibe,? we", r"avaibe (helps|builds|works|is your)", r"partner", r"we build", r"co-?founder", r"coming soon", r"stay tuned", r"behind the scenes", r"contact us", r"digital solutions?", r"vision"]),
]

# Used when nothing more specific matches but the post is clearly about AI
FALLBACK_AI = ("AI trends (general)", r"\bai\b|artificial intelligence")

# Service lines: a caption naming three or more of these is a services overview, whatever else it says
SERVICE_TOPICS = {"ERP & CRM", "Education & LMS", "Websites & digital marketing", "Mobile apps"}

# Calls to action, strongest ask first. Boilerplate such as "Learn more: www.avaibe.com | sales@avaibe.com"
# is on nearly every post, so it does not count as a contact CTA.
CTAS: list[tuple[str, list[str]]] = [
    ("Vote / comment", [r"\bvote\b", r"\bpoll\b", r"in the comments?", r"comment below", r"drop your", r"tell us", r"share your (thoughts|perspective|choice)", r"what do you think", r"which (one|would you)"]),
    ("Subscribe to newsletter", [r"subscribe"]),
    ("Contact sales", [r"contact us", r"let[’']s talk", r"get in touch", r"book a", r"\bdm us\b", r"contact (our|the) team"]),
    ("Read / watch more", [r"read (the|more|our)", r"watch the full", r"swipe to", r"\bdiscover\b"]),
    ("Follow AVAIBE", [r"follow avaibe"]),
]

INDUSTRY = {"Education & LMS": "Education", "Commodity trading": "Commodity trading"}

_HASHTAG = re.compile(r"#(\w+)", re.UNICODE)
_NOISE = [
    re.compile(r"#\w+", re.UNICODE),  # hashtags are kept separately and would skew topics (#UAE on everything)
    re.compile(r"https?://\S+|www\.\S+|\S+@\S+"),
    re.compile(r"(learn more|follow avaibe)[^\n]*", re.IGNORECASE),
]


def hashtags(caption: str) -> list[str]:
    return [f"#{t}" for t in _HASHTAG.findall(caption or "")]


def _clean(caption: str) -> str:
    text = caption or ""
    for rx in _NOISE[:2]:
        text = rx.sub(" ", text)
    return " ".join(text.split()).lower()


def _score(text: str, patterns: list[str]) -> int:
    hook = text[:200]
    score = 0
    for p in patterns:
        if re.search(p, text):
            score += 1
            if re.search(p, hook):
                score += 1  # the opening line says what the post is really about
    return score


def suggest_topic(caption: str) -> str | None:
    text = _clean(caption)
    if not text:
        return None
    body = _NOISE[2].sub(" ", text)
    # A head-to-head in the opening line is AVAIBE's debate series, even though it names AI models
    debate_name, debate_pats = TOPICS[0]
    if any(re.search(p, body[:200]) for p in debate_pats):
        return debate_name
    scores = {name: _score(body, pats) for name, pats in TOPICS}
    if sum(1 for t in SERVICE_TOPICS if scores[t] > 0) >= 3:
        return "AVAIBE services & brand"
    best = max(scores.values())
    if best == 0:
        return FALLBACK_AI[0] if re.search(FALLBACK_AI[1], body) else None
    return next(name for name, _ in TOPICS if scores[name] == best)


def suggest_cta(caption: str) -> str | None:
    text = _clean(caption)
    for name, pats in CTAS:
        if any(re.search(p, text) for p in pats):
            return name
    return None


def suggest(caption: str) -> dict[str, str | None]:
    topic = suggest_topic(caption)
    return {"topic": topic, "industry": INDUSTRY.get(topic or ""), "cta": suggest_cta(caption)}
