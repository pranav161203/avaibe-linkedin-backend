"""Company knowledge base: read files, split text into chunks, find the chunks that match a question.

- Files: .txt, .md, .pdf (text PDFs; scanned images can't be read) and .docx, up to 5 MB.
- Chunking: split on headings (Markdown '#' lines, or Word heading styles), then on blank lines, packing paragraphs
  into chunks of about CHUNK_TARGET characters. A long paragraph is split at sentence ends. Each chunk keeps the
  heading of its section, so a passage still makes sense on its own.
- Search: PostgreSQL full-text search (ranked) on the server; a simple word-match score elsewhere (SQLite in tests).
- Applies to: a source with no accounts is company-wide; one with accounts is used only for those accounts. Search for
  an account sees the company-wide sources plus that account's own.
"""

import io
import re

from django.db import connection, transaction
from django.db.models import Q, QuerySet

from core.models import Account, KnowledgeChunk, KnowledgeSource

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 200_000
CHUNK_TARGET = 900  # characters; small enough to be specific, big enough to keep a thought together
CHUNK_MAX = 1400
FILE_TYPES = (".txt", ".md", ".pdf", ".docx")


class KnowledgeError(Exception):
    """Shown to the user as-is."""


# ------------------------------------------------------------------ reading files

def read_file(name: str, data: bytes) -> str:
    """The text of an uploaded file. Raises KnowledgeError with a message the team can act on."""
    lower = (name or "").lower()
    if len(data) > MAX_BYTES:
        raise KnowledgeError("Files must be 5 MB or smaller. Split the file or paste the relevant text.")
    if lower.endswith((".txt", ".md")):
        for enc in ("utf-8-sig", "cp1252"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        raise KnowledgeError("The text file could not be read. Save it as UTF-8 and try again.")
    if lower.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
        except Exception:
            raise KnowledgeError("The PDF could not be opened. Remove any password protection and try again.")
        if not text.strip():
            raise KnowledgeError("No text was found in this PDF. It may be a scanned document; paste the text instead.")
        return text
    if lower.endswith(".docx"):
        import docx

        try:
            doc = docx.Document(io.BytesIO(data))
        except Exception:
            raise KnowledgeError("The Word file could not be opened. Save it as .docx and try again.")
        lines = []
        for p in doc.paragraphs:
            t = p.text.strip()
            if not t:
                continue
            lines.append("")  # each Word paragraph stays its own paragraph
            style = (p.style.name or "").lower() if p.style is not None else ""
            m = re.match(r"heading (\d)", style)
            lines.append(f"{'#' * int(m.group(1))} {t}" if m else ("# " + t if style == "title" else t))
        for table in doc.tables:  # tables keep their rows, cells separated by " | "
            lines.append("")
            for row in table.rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(lines)
    raise KnowledgeError("Supported formats: .txt, .md, .pdf and .docx.")


# ------------------------------------------------------------------ chunking

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_long(paragraph: str) -> list[str]:
    if len(paragraph) <= CHUNK_MAX:
        return [paragraph]
    parts, cur = [], ""
    for sentence in _SENTENCE_END.split(paragraph):
        if cur and len(cur) + len(sentence) + 1 > CHUNK_TARGET:
            parts.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
        while len(cur) > CHUNK_MAX:  # one very long "sentence": cut at a space
            cut = cur.rfind(" ", 0, CHUNK_MAX)
            cut = cut if cut > CHUNK_TARGET // 2 else CHUNK_MAX
            parts.append(cur[:cut].strip())
            cur = cur[cut:].strip()
    if cur:
        parts.append(cur)
    return parts


def chunk_text(text: str) -> list[tuple[str, str]]:
    """[(section heading, chunk text)] in reading order."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    # A heading always starts its own block, even with no blank line around it (Word files, pasted text)
    text = re.sub(r"(?m)^(\s{0,3}#{1,6}\s+.+)$", r"\n\1\n", clean(text))
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        lines = block.split("\n")
        m = _HEADING.match(lines[0])
        if m:
            sections.append((m.group(2).strip()[:200], []))
            rest = "\n".join(lines[1:]).strip()
            if rest:
                sections[-1][1].append(rest)
        elif block.strip():
            sections[-1][1].append(block.strip())

    chunks: list[tuple[str, str]] = []
    for heading, paragraphs in sections:
        cur = ""
        for para in paragraphs:
            for piece in _split_long(para):
                if cur and len(cur) + len(piece) + 2 > CHUNK_TARGET:
                    chunks.append((heading, cur))
                    cur = piece
                else:
                    cur = f"{cur}\n\n{piece}" if cur else piece
        if cur:
            chunks.append((heading, cur))
    return chunks


def section_count(text: str) -> int:
    return sum(1 for line in clean(text).split("\n") if _HEADING.match(line))


# ------------------------------------------------------------------ saving

def _validate(title: str, content: str) -> tuple[str, str]:
    title, content = title.strip(), clean(content)
    if not title:
        raise KnowledgeError("Enter a title for the source.")
    if not content:
        raise KnowledgeError("Enter some text to add.")
    if len(content) > MAX_CHARS:
        raise KnowledgeError(f"That's {len(content):,} characters; the limit is {MAX_CHARS:,} per source. Split it into smaller sources.")
    return title[:200], content


def _rechunk(source: KnowledgeSource) -> None:
    source.chunk_items.all().delete()
    KnowledgeChunk.objects.bulk_create(
        KnowledgeChunk(source=source, index=i, heading=h, text=t) for i, (h, t) in enumerate(chunk_text(source.content))
    )


def for_account(account_id: int | None) -> QuerySet[KnowledgeSource]:
    """Sources that apply to this account: its company's company-wide ones plus the account's own.
    Never another company's, whatever their "applies to" says."""
    company_id = Account.objects.filter(id=account_id).values_list("company_id", flat=True).first() if account_id else None
    qs = KnowledgeSource.objects.filter(company_id=company_id)
    cond = Q(accounts__isnull=True) if account_id is None else Q(accounts__isnull=True) | Q(accounts__id=account_id)
    return qs.filter(cond).distinct()


def _same_company(company_id: int | None, account_ids: list[int] | None) -> None:
    if account_ids and Account.objects.filter(id__in=account_ids).exclude(company_id=company_id).exists():
        raise KnowledgeError("Sources can only apply to accounts within the same company")


def add_source(
    title: str, content: str, user_email: str | None, company_id: int | None,
    file_name: str | None = None, account_ids: list[int] | None = None,
) -> KnowledgeSource:
    title, content = _validate(title, content)
    _same_company(company_id, account_ids)
    with transaction.atomic():
        s = KnowledgeSource.objects.create(
            company_id=company_id, title=title, kind="file" if file_name else "text", file_name=file_name, content=content, chars=len(content),
            created_by=user_email, updated_by=user_email,
        )
        s.accounts.set(account_ids or [])
        _rechunk(s)
    return s


def update_source(source: KnowledgeSource, title: str, content: str, user_email: str | None, account_ids: list[int] | None = None) -> KnowledgeSource:
    title, content = _validate(title, content)
    _same_company(source.company_id, account_ids)
    with transaction.atomic():
        source.title, source.content, source.chars, source.updated_by = title, content, len(content), user_email
        source.save()
        source.accounts.set(account_ids or [])
        _rechunk(source)
    return source


# ------------------------------------------------------------------ search

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_STOP = set(
    "a an and are as at be but by can do does for from has have how i if in into is it its me my of on or our so "
    "than that the their them then there these they this to us was we what when where which who why will with you your".split()
)


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def search(query: str, limit: int = 5, account_id: int | None = None) -> list[dict]:
    """The chunks that best match `query` among the sources for `account_id`, best first:
    [{source_id, source_title, heading, text, score}]."""
    terms = _terms(query)
    if not terms:
        return []
    chunks = KnowledgeChunk.objects.select_related("source").filter(source__in=for_account(account_id))
    if connection.vendor == "postgresql":
        rows = _search_postgres(chunks, " ".join(terms), limit)
    else:
        rows = _search_simple(chunks, terms, limit)
    return [
        {"source_id": c.source_id, "source_title": c.source.title, "heading": c.heading, "text": c.text, "score": round(score, 4)}
        for c, score in rows
    ]


def _search_postgres(chunks: QuerySet[KnowledgeChunk], q: str, limit: int) -> list[tuple[KnowledgeChunk, float]]:
    from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

    # Any of the words may match ("websearch" syntax with OR); the heading counts more than the body
    query = SearchQuery(" OR ".join(q.split()), search_type="websearch", config="english")
    vector = SearchVector("heading", weight="A", config="english") + SearchVector("text", weight="B", config="english")
    qs = (
        chunks.annotate(rank=SearchRank(vector, query))
        .filter(rank__gt=0)
        .order_by("-rank")[:limit]
    )
    return [(c, float(c.rank)) for c in qs]


def _search_simple(chunks: QuerySet[KnowledgeChunk], terms: list[str], limit: int) -> list[tuple[KnowledgeChunk, float]]:
    scored = []
    for c in chunks:
        words = _terms(f"{c.heading} {c.heading} {c.text}")  # heading counts twice
        if not words:
            continue
        hits = sum(words.count(t) for t in set(terms))
        covered = sum(1 for t in set(terms) if t in words)
        if hits:
            scored.append((c, covered + hits / len(words)))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def context_block(query: str, account_id: int | None, limit: int = 5) -> str:
    """Company knowledge for a Claude prompt (for this account): the best-matching passages, each with its source.
    Empty if none."""
    hits = search(query, limit, account_id)
    if not hits:
        return ""
    parts = []
    for h in hits:
        section = f' section="{h["heading"]}"' if h["heading"] else ""
        parts.append(f'<passage source="{h["source_title"]}"{section}>\n{h["text"]}\n</passage>')
    return (
        "AVAIBE's own knowledge base (written by the team; use these facts, don't invent others):\n"
        "<untrusted_company_knowledge>\n" + "\n".join(parts) + "\n</untrusted_company_knowledge>"
    )
