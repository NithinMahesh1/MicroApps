"""
search.py — UI-agnostic conversation search engine for the CONVERSATIONS tab.

Pure functions over the preloaded ``Conversation`` index: parse a typed query
(with inline ``project:``/``branch:``/``after:``/``before:`` operators and quoted
phrases), merge in dropdown filters, then rank by **relevance blended with
recency** with stdlib-only fuzzy (typo) rescue via :mod:`difflib`. Also builds the
highlighted preview renderable and the highlighted table TITLE cell.

Per ``ARCHITECTURE.md`` this module knows nothing about Textual; it depends only on
``ccdashboard.conversations.Conversation``, the standard library, and ``rich.text``.
The view translates dropdown selections into a :class:`Query` and calls
:func:`rank` / :func:`highlight` / :func:`highlight_title`.

Scoring keeps title hits dominant (``_W_TITLE`` ≫ everything), lets project/branch/
body+frequency contribute, blends in a 30-day-half-life recency term so a much-newer
slightly-weaker chat can edge ahead, and never lets a fuzzy match beat an exact one.
A term that matches nothing (exactly or fuzzily) fails coverage and drops the convo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from difflib import SequenceMatcher

from rich.text import Text

from .conversations import Conversation

# --- Query parsing ----------------------------------------------------------

_PHRASE_RE = re.compile(r'"([^"]*)"')
_TOKEN_RE = re.compile(r"\S+")
_WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# Inline operator keys (case-insensitive on the key).
_PROJECT_KEYS = ("project", "dir")
_BRANCH_KEY = "branch"
_AFTER_KEY = "after"
_BEFORE_KEY = "before"

# --- Scoring constants (no magic numbers) -----------------------------------

_W_TITLE = 10.0
_W_PROJECT = 4.0
_W_BRANCH = 4.0
_W_BODY = 3.0
_W_WHOLEWORD = 2.0           # bonus when a term matches at a word boundary (title or body)
_W_PHRASE_TITLE = 15.0
_W_PHRASE_BODY = 8.0
_FREQ_CAP = 5                # max extra body occurrences counted
_FREQ_BONUS = 0.3            # per extra body occurrence
_FUZZY_THRESHOLD = 0.8       # difflib ratio required to count a fuzzy match
_FUZZY_FACTOR = 0.4          # fuzzy contribution = field_weight * factor * ratio
_W_RECENCY = 4.0             # max recency contribution (newest)
_RECENCY_HALF_LIFE_DAYS = 30.0

# --- Highlight styling (cyan/teal theme) ------------------------------------

_STYLE_EXACT = "bold #00e5ff"
_STYLE_FUZZY = "#7ab8cc"
_SNIPPET_ELLIPSIS = "…"

# A far-future "age" stand-in for convos with no parsed last_date, so they sort
# last on recency without crashing the half-life math.
_NO_DATE_AGE_DAYS = 10_000


@dataclass(frozen=True)
class Query:
    """A parsed search query: AND terms + exact phrases + structured filters."""

    terms: tuple[str, ...] = ()      # lowercased AND terms
    phrases: tuple[str, ...] = ()    # lowercased quoted phrases (contiguous)
    project: str | None = None       # lc substring filter (from project:/dir: or dropdown)
    branch: str | None = None        # lc substring filter (from branch:)
    after: date | None = None        # last_date >= after
    before: date | None = None       # last_date <= before
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.terms and not self.phrases


def _parse_op_date(value: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` operator value, or None if unparseable."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_query(raw: str) -> Query:
    """Parse a raw search string into a :class:`Query`.

    Quoted ``"phrases"`` are extracted first (lowercased, inner whitespace kept).
    Remaining whitespace-split tokens are classified: ``project:``/``dir:`` →
    project filter, ``branch:`` → branch filter, ``after:``/``before:`` → date
    bounds (token ignored if the value is not a valid ``YYYY-MM-DD``). Any other
    token — including an unknown ``foo:bar`` or a bare ``:`` — becomes a literal
    lowercased AND term. Operator keys are case-insensitive.
    """
    phrases: list[str] = []

    def _capture_phrase(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner:
            phrases.append(inner.lower())
        return " "

    remainder = _PHRASE_RE.sub(_capture_phrase, raw)

    terms: list[str] = []
    project: str | None = None
    branch: str | None = None
    after: date | None = None
    before: date | None = None

    for token in _TOKEN_RE.findall(remainder):
        key, sep, value = token.partition(":")
        key_lc = key.lower()
        if sep and value:
            if key_lc in _PROJECT_KEYS:
                project = value.lower()
                continue
            if key_lc == _BRANCH_KEY:
                branch = value.lower()
                continue
            if key_lc == _AFTER_KEY:
                parsed = _parse_op_date(value)
                if parsed is not None:
                    after = parsed
                continue
            if key_lc == _BEFORE_KEY:
                parsed = _parse_op_date(value)
                if parsed is not None:
                    before = parsed
                continue
        # Anything else (including unknown foo:bar or bare ":") is a literal term.
        terms.append(token.lower())

    return Query(
        terms=tuple(terms),
        phrases=tuple(phrases),
        project=project,
        branch=branch,
        after=after,
        before=before,
        raw=raw,
    )


def merge_ui_filters(
    query: Query,
    *,
    project: str | None = None,     # full cwd from the project dropdown (None = All)
    since_days: int | None = None,  # from the date dropdown (None/0 = Any time)
    now: date | None = None,
) -> Query:
    """Return a new Query with dropdown filters applied where the query left them unset.

    Operators already present in the typed query win for the same field. Always
    returns a NEW :class:`Query` (immutability) — the input is never mutated.
    """
    new_project = query.project
    if query.project is None and project:
        new_project = project.lower()

    new_after = query.after
    if query.after is None and since_days:
        base = now or date.today()
        new_after = base - timedelta(days=since_days)

    return replace(query, project=new_project, after=new_after)


def _passes_hard_filters(c: Conversation, query: Query) -> bool:
    """Return whether ``c`` satisfies every structured filter on ``query``."""
    if query.project is not None and query.project not in c.project_lc:
        return False
    if query.branch is not None and query.branch not in c.branch_lc:
        return False
    if query.after is not None and (c.last_date is None or c.last_date < query.after):
        return False
    if query.before is not None and (c.last_date is None or c.last_date > query.before):
        return False
    return True


def _recency(c: Conversation, now: date) -> float:
    """Recency contribution ∈ [0, _W_RECENCY] from a 30-day half-life decay."""
    if c.last_date is None:
        return 0.0
    age_days = max((now - c.last_date).days, 0)
    return _W_RECENCY * (0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS))


def _tokens(*fields: str) -> list[str]:
    """Distinct alphanumeric tokens across the given lowercased short fields."""
    seen: list[str] = []
    for field in fields:
        for tok in _WORD_SPLIT_RE.split(field):
            if tok and tok not in seen:
                seen.append(tok)
    return seen


def _term_score(c: Conversation, term: str) -> float | None:
    """Exact-then-fuzzy contribution of a single ``term``, or None if it covers nothing."""
    score = 0.0
    hit = False

    if term in c.title_lc:
        score += _W_TITLE
        hit = True
    if term in c.project_lc:
        score += _W_PROJECT
        hit = True
    if term in c.branch_lc:
        score += _W_BRANCH
        hit = True
    if term in c.body_lc:
        count = c.body_lc.count(term)
        score += _W_BODY + min(count - 1, _FREQ_CAP) * _FREQ_BONUS
        hit = True

    if hit:
        boundary = re.compile(r"\b" + re.escape(term) + r"\b")
        if boundary.search(c.title_lc) or boundary.search(c.body_lc):
            score += _W_WHOLEWORD
        return score

    # Fuzzy rescue: best ratio against short-field tokens only (never body).
    best_ratio = 0.0
    best_weight = 0.0
    matcher = SequenceMatcher(a=term)
    fuzzy_fields = (
        (c.title_lc, _W_TITLE),
        (c.project_lc, _W_PROJECT),
        (c.branch_lc, _W_BRANCH),
    )
    for field, weight in fuzzy_fields:
        for tok in _tokens(field):
            matcher.set_seq2(tok)
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_weight = weight
    if best_ratio >= _FUZZY_THRESHOLD:
        return best_weight * _FUZZY_FACTOR * best_ratio
    return None


def _phrase_score(c: Conversation, phrase: str) -> float | None:
    """Exact phrase contribution (title + body), or None if it appears in neither."""
    score = 0.0
    matched = False
    if phrase in c.title_lc:
        score += _W_PHRASE_TITLE
        matched = True
    if phrase in c.body_lc:
        score += _W_PHRASE_BODY
        matched = True
    return score if matched else None


def _score(c: Conversation, query: Query, *, now: date) -> float | None:
    """Blended relevance+recency score, or None if any term/phrase fails coverage.

    Relevance ``R`` sums every term and phrase contribution (title hits dominate,
    project/branch/body+frequency add on, whole-word adds a small boundary bonus,
    fuzzy rescue is always weaker than an exact hit). The final score adds a 30-day
    half-life recency term so a newer chat can edge a slightly-weaker older one. Any
    term that hits nothing — exactly or fuzzily — or any phrase absent from both
    title and body, returns None so the caller drops the convo (coverage).
    """
    relevance = 0.0

    for term in query.terms:
        contribution = _term_score(c, term)
        if contribution is None:
            return None
        relevance += contribution

    for phrase in query.phrases:
        contribution = _phrase_score(c, phrase)
        if contribution is None:
            return None
        relevance += contribution

    return relevance + _recency(c, now)


def rank(
    convos: list[Conversation], query: Query, *, now: date | None = None
) -> list[Conversation]:
    """Filter, then order by blended relevance+recency (best first).

    Applies the structured hard filters, then: for an empty query returns the
    filtered set in pure newest-first browse order (``last_at`` desc); otherwise
    scores each survivor, drops any that fails coverage, and sorts by score desc,
    tie-breaking on ``last_at`` desc then ``session_id`` (stable + deterministic).
    """
    filtered = [c for c in convos if _passes_hard_filters(c, query)]

    if query.is_empty:
        return sorted(filtered, key=lambda c: c.last_at, reverse=True)

    effective_now = now or date.today()
    scored: list[tuple[float, Conversation]] = []
    for c in filtered:
        s = _score(c, query, now=effective_now)
        if s is not None:
            scored.append((s, c))

    # Stable, deterministic ordering via successive stable sorts (innermost key
    # first): session_id asc → last_at desc → score desc, so equal scores break on
    # newest activity then session id.
    scored.sort(key=lambda pair: pair[1].session_id)
    scored.sort(key=lambda pair: pair[1].last_at, reverse=True)
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored]


# --- Highlighting / preview content -----------------------------------------


def _match_spans(haystack_lc: str, needles: list[str]) -> list[tuple[int, int]]:
    """All (start, end) offsets in ``haystack_lc`` where any needle occurs (sorted)."""
    spans: list[tuple[int, int]] = []
    for needle in needles:
        if not needle:
            continue
        start = haystack_lc.find(needle)
        while start != -1:
            spans.append((start, start + len(needle)))
            start = haystack_lc.find(needle, start + 1)
    spans.sort()
    return spans


def _header_line(convo: Conversation) -> str:
    """The single metadata header line shown atop the preview pane."""
    return (
        f"{convo.title} — {convo.project_name} · {convo.git_branch} · "
        f"{convo.last_at[:16]} · {convo.message_count} msgs · {convo.session_id[:8]}"
    )


def highlight_title(convo: Conversation, query: Query) -> Text:
    """Return the table TITLE cell with matched query terms/phrases styled.

    Searches the original-case title case-insensitively for each term and phrase,
    styling exact spans with the bright cyan style. An empty query yields the plain
    title text.
    """
    title = convo.title
    text = Text(title)
    if query is None or query.is_empty:
        return text
    needles = [n for n in (*query.phrases, *query.terms) if n]
    title_lc = title.lower()
    for start, end in _match_spans(title_lc, needles):
        text.stylize(_STYLE_EXACT, start, end)
    return text


def _collapse(snippet: str) -> str:
    """Collapse whitespace/newlines in a snippet to single spaces."""
    return " ".join(snippet.split())


def _build_snippet(text_src: str, center: int, width: int) -> tuple[str, tuple[int, int]]:
    """Build one raw context window around ``center`` in ``text_src``.

    Returns the raw window substring plus its (start, end) offsets in source
    coordinates (used for de-duplicating overlapping windows and deciding the
    leading/trailing ``…`` markers).
    """
    half = width // 2
    start = max(0, center - half)
    end = min(len(text_src), center + half)
    return text_src[start:end], (start, end)


def highlight(
    convo: Conversation, query: Query, *, max_snippets: int = 3, width: int = 160
) -> Text:
    """Build the preview-pane renderable for ``convo`` under ``query``.

    A metadata header line, then up to ``max_snippets`` context windows of ``width``
    chars around the best matches in the original-case body ``text`` (newlines
    collapsed; ``…`` prepended/appended when truncated; overlapping windows
    de-duplicated), with matched spans styled in bright cyan. For an empty query the
    header is followed by a plain opening snippet of the transcript (no highlights).
    """
    header = _header_line(convo)
    body = convo.text
    body_lc = convo.body_lc or body.lower()

    if query is None or query.is_empty:
        opening = _collapse(body[: width * max_snippets])
        result = Text(header, style="bold")
        if opening:
            result.append("\n")
            result.append(opening)
        return result

    needles = [n for n in (*query.phrases, *query.terms) if n]
    spans = _match_spans(body_lc, needles)

    result = Text(header, style="bold")

    used_windows: list[tuple[int, int]] = []
    rendered = 0
    for span_start, _span_end in spans:
        if rendered >= max_snippets:
            break
        if any(w_start <= span_start < w_end for w_start, w_end in used_windows):
            continue  # already covered by a prior window — de-duplicate

        raw, (w_start, w_end) = _build_snippet(body, span_start, width)
        used_windows.append((w_start, w_end))

        prefix = _SNIPPET_ELLIPSIS if w_start > 0 else ""
        suffix = _SNIPPET_ELLIPSIS if w_end < len(body) else ""

        snippet_text = Text()
        if prefix:
            snippet_text.append(prefix)
        cursor = 0
        # Re-find every needle within this raw window, then collapse for display.
        for ls, le in _match_spans(raw.lower(), needles):
            if ls < cursor:
                continue
            snippet_text.append(_collapse_keep(raw[cursor:ls]))
            snippet_text.append(_collapse_keep(raw[ls:le]), style=_STYLE_EXACT)
            cursor = le
        snippet_text.append(_collapse_keep(raw[cursor:]))
        if suffix:
            snippet_text.append(suffix)

        result.append("\n")
        result.append(snippet_text)
        rendered += 1

    return result


def _collapse_keep(fragment: str) -> str:
    """Collapse internal newlines/runs of whitespace to single spaces, keeping content.

    Unlike :func:`_collapse` this preserves a single leading/trailing space so
    adjacent styled and unstyled fragments don't run together.
    """
    if not fragment:
        return ""
    lead = " " if fragment[:1].isspace() else ""
    trail = " " if fragment[-1:].isspace() else ""
    core = " ".join(fragment.split())
    return lead + core + trail if core else (lead or trail)


if __name__ == "__main__":  # pragma: no cover - tiny manual smoke
    import sys

    from .conversations import index_conversations

    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    idx = index_conversations()
    q = parse_query(" ".join(sys.argv[1:]) or "dashboard")
    ranked = rank(idx, q)
    print(f"query={q!r}")
    print(f"{len(ranked)} matches; top 5:")
    for c in ranked[:5]:
        print(f"  {c.last_at[:16]}  {c.project_name:<18.18}  {c.title[:50]}")
