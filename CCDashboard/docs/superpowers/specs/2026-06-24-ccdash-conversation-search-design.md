# CCDash Conversation Search Upgrade — Design Spec

**Date:** 2026-06-24
**App:** `CCDashboard` (Textual TUI), CONVERSATIONS tab
**Status:** Approved design — this document is the **shared contract**. Parallel
implementation agents MUST follow the field names, signatures, IDs, and constants
here EXACTLY so independently-built files integrate without rework.

---

## 1. Goal

Make finding an old conversation easy. Today the CONVERSATIONS search does a plain
substring AND over `title + body`, then shows results in **pure newest-first order**
with no way to tell why each row matched. A common keyword like `grep` returns dozens
of recency-sorted rows and the right one gets buried.

Upgrade search to:

1. **Relevance ranking blended with recency** (replace pure newest-first).
2. **Filters** — project/folder and date range — via **both** inline query operators
   **and** a visible filter row.
3. **Preview pane** for the highlighted row showing the matching context with
   **highlighted** terms.
4. **Fuzzy matching** (typo tolerance) using **stdlib `difflib`** only (no new
   dependency — safest supply-chain posture, ships inside Python).
5. **Highlighting** of matched terms in the preview and the table TITLE cell.

Branch filtering is **operator-only** (`branch:`); no branch dropdown.

---

## 2. Architecture overview

```
conversations.py   indexing + Conversation model + elevated-resume (existing concern)
search.py   (NEW)  query parsing + filtering + relevance/recency ranking + fuzzy + highlight
tui/conversations_view.py   filter row + search box + table + preview pane + wiring
tui/app.tcss       styles for filter row + preview pane
tests/ (NEW)       first pytest suite for CCDashboard (pure engine + light view smoke)
```

The engine stays **UI-agnostic** (per `ARCHITECTURE.md`): `search.py` knows nothing
about Textual; the view translates dropdown selections into a `Query` and calls the
engine.

---

## 3. Data model changes — `ccdashboard/conversations.py`

### 3.1 `Conversation` dataclass (replace `search_blob` with structured fields)

```python
from datetime import date

@dataclass(frozen=True)
class Conversation:
    session_id: str
    cwd: str
    git_branch: str
    title: str
    started_at: str
    last_at: str
    message_count: int
    project_dir: str
    file_path: str
    text: str = ""              # original-case concatenated body, used for snippets
    # NEW precomputed search fields (built once at index time):
    title_lc: str = ""          # title.lower()
    body_lc: str = ""           # text.lower()
    project_lc: str = ""        # cwd.lower()  (full path, so project:smart-gift-card works)
    branch_lc: str = ""         # git_branch.lower()
    project_name: str = ""      # Path(cwd).name (leaf folder, for display + dropdown)
    last_date: date | None = None   # parsed date(last_at), for range filters + recency
```

- **Remove** the `search_blob` field entirely.
- `to_dict()` is unchanged in shape (it never serialized `search_blob`); it does NOT
  serialize the new fields either.

### 3.2 `_parse_session` builds the new fields

After computing `title`, `cwd`, `branch`, `body_text`:

```python
return Conversation(
    ...,
    text=body_text,
    title_lc=title.lower(),
    body_lc=body_text.lower(),
    project_lc=cwd.lower(),
    branch_lc=(branch or "—").lower(),
    project_name=Path(cwd).name,
    last_date=_parse_date(last),
)
```

Add a helper:

```python
def _parse_date(ts: str) -> date | None:
    """Parse an ISO-8601 timestamp's date (or None)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return None
```

(Add `from datetime import date, datetime` to imports.)

### 3.3 Raise the truncation cap

```python
_MAX_TEXT_PER_CONVO = 1_000_000  # was 500_000; captures nearly all transcripts
```

### 3.4 Remove the old search functions

Delete `search()`, `filter_conversations()`, and `_snippet()` from `conversations.py`
— their responsibilities move to `search.py`. Update the `__main__` smoke test at the
bottom to import and call `search.rank(...)` instead of `search(...)`.

---

## 4. Search engine — NEW `ccdashboard/search.py`

UI-agnostic. Depends only on `conversations.Conversation`, stdlib, and `rich.text`.

### 4.1 `Query` model + parser

```python
@dataclass(frozen=True)
class Query:
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
```

```python
def parse_query(raw: str) -> Query:
    ...
```

Parsing rules (apply in this order on `raw`):

1. Extract `"quoted phrases"` → `phrases` (lowercased, inner whitespace preserved).
2. From the remaining text, split on whitespace into tokens. For each token:
   - `project:VALUE` or `dir:VALUE` → set `project = VALUE.lower()`.
   - `branch:VALUE` → set `branch = VALUE.lower()`.
   - `after:YYYY-MM-DD` → set `after` (ignore token if unparseable).
   - `before:YYYY-MM-DD` → set `before` (ignore token if unparseable).
   - any other token (including an unknown `foo:bar`) → append to `terms` lowercased.
3. `raw` retains the original string.

Operators are case-insensitive on the key (`Project:` == `project:`). A bare `:` or
empty value is treated as a literal term.

### 4.2 Merge UI filters

The view passes dropdown selections; operators already in the typed query win for the
same field.

```python
def merge_ui_filters(
    query: Query,
    *,
    project: str | None = None,     # full cwd from the project dropdown (None = All)
    since_days: int | None = None,  # from the date dropdown (None/0 = Any time)
    now: date | None = None,
) -> Query:
    """Return a new Query with dropdown filters applied where the query left them unset."""
```

- If `query.project is None` and `project` given → set `project=project.lower()`.
- If `query.after is None` and `since_days` truthy → set `after = (now or date.today()) - timedelta(days=since_days)`.
- Always returns a NEW Query (immutability).

### 4.3 Ranking

```python
def rank(convos: list[Conversation], query: Query, *, now: date | None = None) -> list[Conversation]:
    """Filter, then order by blended relevance+recency (best first)."""
```

Algorithm:

1. **Hard filters** — drop a convo unless ALL hold:
   - `query.project` is None OR `query.project in c.project_lc`.
   - `query.branch` is None OR `query.branch in c.branch_lc`.
   - `query.after` is None OR (`c.last_date` is not None AND `c.last_date >= query.after`).
   - `query.before` is None OR (`c.last_date` is not None AND `c.last_date <= query.before`).
2. **Empty query** (`query.is_empty`): skip scoring; return the filtered list sorted by
   `last_at` descending (today's browse behavior, now optionally filtered).
3. **Score** each remaining convo with `_score(c, query, now=now or date.today())`.
   A convo is **dropped** if any term/phrase fails coverage (see below → score returns
   `None`).
4. **Sort** by score descending, tie-break by `last_at` descending, then `session_id`
   (stable + deterministic).

### 4.4 Scoring (`_score`) — relevance blended with recency

Named module constants (no magic numbers):

```python
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
```

`_score(c, query, *, now) -> float | None`:

- **Per term** `t` in `query.terms`, contribution is the SUM of:
  - `_W_TITLE` if `t in c.title_lc`.
  - `_W_PROJECT` if `t in c.project_lc`.
  - `_W_BRANCH` if `t in c.branch_lc`.
  - `_W_BODY + min(count-1, _FREQ_CAP) * _FREQ_BONUS` if `t in c.body_lc`
    (`count = c.body_lc.count(t)`).
  - `_W_WHOLEWORD` if `t` matches at a word boundary in `title_lc` or `body_lc`
    (regex `\b{re.escape(t)}\b`).
  - If `t` hit **no** field exactly → **fuzzy rescue**: best `difflib.SequenceMatcher`
    ratio of `t` against tokens of `title_lc`/`project_lc`/`branch_lc` (NOT body — too
    costly/noisy). If best ratio ≥ `_FUZZY_THRESHOLD`, contribution =
    `field_weight_of_best * _FUZZY_FACTOR * ratio`; else this term contributes 0 and the
    convo **fails coverage** (return `None`).
- **Per phrase** `p` in `query.phrases`:
  - `_W_PHRASE_TITLE` if `p in c.title_lc`; plus `_W_PHRASE_BODY` if `p in c.body_lc`.
  - If `p` is in neither → **fails coverage** (return `None`). (Phrases are exact; no
    fuzzy.)
- **Relevance** `R` = sum of all term + phrase contributions.
- **Recency**: `age = (now - c.last_date).days` if `c.last_date` else a large number;
  `rec = 0.5 ** (max(age, 0) / _RECENCY_HALF_LIFE_DAYS)` (∈ (0, 1]); recency
  contribution = `_W_RECENCY * rec` (0 if `last_date` is None).
- **Final** = `R + _W_RECENCY * rec`. Return it.

This makes title hits dominate, lets project/branch/body+frequency contribute, allows a
slightly-weaker but much-newer chat to edge ahead (the blend), and never lets fuzzy beat
an exact match. Adding a second term that hits the title rockets that chat to the top.

### 4.5 Highlight / preview content

```python
def highlight(convo: Conversation, query: Query, *, max_snippets: int = 3, width: int = 160) -> "rich.text.Text":
    """Build the preview-pane renderable: a metadata header line + up to `max_snippets`
    context windows around the best matches, with matched terms styled."""
```

- Header line (one line): `{title} — {project_name} · {git_branch} · {last_at[:16]} · {message_count} msgs · {session_id[:8]}`.
- Determine match positions in the **original-case** `title`/`text` (search
  case-insensitively for each term/phrase). Build up to `max_snippets` windows of
  `width` chars around distinct match offsets in `text`; collapse newlines; prepend/append
  `…` when truncated. De-duplicate overlapping windows.
- Style matched spans with a bright/bold style; fuzzy-only matches dimmer. Use
  `rich.text.Text` with `.stylize(style, start, end)` or `Text.assemble`. Suggested
  styles: exact = `"bold #00e5ff"`, fuzzy = `"#7ab8cc"`.
- If `query.is_empty`: header line + a plain snippet of the opening message
  (first ~`width*max_snippets` chars of `text`), no highlights.

A small helper `highlight_title(convo, query) -> Text` returns the table TITLE cell with
matched terms styled (used by the view when adding rows).

### 4.6 Performance

In-memory over the preloaded index (~98 convos). Per keystroke is bounded by the 180 ms
debounce; scoring is `str.count`/`in`/one `\b` regex per term per short field plus body.
Fuzzy runs only on short-field tokens and only when a term misses exactly. Lowercased
fields are precomputed at index time. No per-keystroke file I/O.

---

## 5. UI — `ccdashboard/tui/conversations_view.py`

### 5.1 Layout (`compose`)

Order, with IDs the rest of the code/tests rely on:

```
Horizontal(id="conv-filters", classes="filter-row")
    Select(options=<projects>, prompt="All projects", id="conv-project", allow_blank=True)
    Select(options=<date presets>, prompt="Any time", id="conv-date", allow_blank=True)
Input(id="conv-search", placeholder="search…  project:foo  branch:bar  after:2026-06-01  \"exact phrase\"")
DataTable(id="conv-table", zebra_stripes=True, cursor_type="row")   # columns unchanged
Static(id="conv-preview", classes="preview")
Static("loading…", id="conv-status", classes="status")
```

- **Date preset options** (label, since_days): `("Any time", 0)`, `("Last 24 hours", 1)`,
  `("Last 7 days", 7)`, `("Last 30 days", 30)`, `("Last year", 365)`.
- **Project options**: built in `load_conversations` from the distinct `cwd`s in the
  index, label = `project_name` (leaf), value = full `cwd`. Sorted by label. Populated via
  `Select.set_options(...)` after load.

### 5.2 Wiring

- Keep `__init__` state (`_ccd_convos`, `_ccd_rows`, `_ccd_search_timer`).
- `load_conversations(convos)`: store, populate the project Select options, render all,
  update status.
- `_ccd_render(convos, query=None)`: render rows; TITLE cell uses
  `search.highlight_title(c, query)` when `query` is non-empty, else plain text.
- `on_input_changed` (id `conv-search`): existing 180 ms debounce → `_ccd_run_search`.
- `on_select_changed` (ids `conv-project`, `conv-date`): re-run search immediately
  (no debounce needed).
- `_ccd_run_search()`: build the effective query —
  `q = search.parse_query(text)`, then
  `q = search.merge_ui_filters(q, project=<project select value or None>, since_days=<date select value or None>)`,
  then `ranked = search.rank(self._ccd_convos, q)`. Render, update status
  (`"{n} matches for …"`), and refresh the preview for the first row.
- `on_data_table_row_highlighted` (id `conv-table`): update `#conv-preview` via
  `search.highlight(self._ccd_rows[cursor_row], <current query>)`. Store the current
  `Query` on `self` (`self._ccd_query`) so the highlight handler can reuse it.
- Preserve existing behavior: `/` + `↓` focus flow (`focus_search`, `on_key`),
  Enter-to-resume (`on_data_table_row_selected` → `_resume`).

### 5.3 Notes

- `Select.value` is the sentinel `Select.BLANK` when nothing is chosen → treat as None.
- `RowHighlighted` fires as the cursor moves; keep the handler cheap (it calls
  `search.highlight`, which is bounded by `max_snippets`).

---

## 6. Styling — `ccdashboard/tui/app.tcss`

Add (matching the cyan/teal theme):

```css
.filter-row { height: 3; margin: 1 2 0 2; }
.filter-row Select { width: 1fr; margin: 0 1 0 0; }

#conv-preview {
    height: 9;
    margin: 0 2;
    padding: 0 1;
    background: #070b12;
    color: #cfeffd;
    border: round #103040;
}
```

`DataTable` keeps `height: 1fr`; the fixed-height filter row and preview pane bracket it.

---

## 7. Tests — NEW `CCDashboard/tests/`

First pytest suite for the app. The engine is pure functions, so most coverage is unit
tests with no Textual involved.

- `tests/conftest.py` — a `make_convo(**overrides)` factory building `Conversation`
  records with sensible defaults (and computing the `*_lc`/`last_date` fields the way
  `_parse_session` does), plus a `freeze_now` date fixture for deterministic recency.
- `tests/test_search.py`:
  - `parse_query`: bare terms (AND), quoted phrase, `project:`/`dir:`, `branch:`,
    `after:`/`before:` (valid + invalid), unknown `foo:bar` as a literal term, mixed.
  - `merge_ui_filters`: dropdown applied only when operator absent; `since_days` →
    `after`; immutability.
  - `rank`: title hit outranks body-only hit; term frequency raises score;
    whole-word bonus; **fuzzy rescue** (typo finds the chat, ranked below an exact hit);
    **recency blend** (equal relevance → newer first; a much-newer slightly-weaker chat
    can edge an older stronger one within the bound, but a title hit (≫) is not overtaken
    by recency); coverage drop (a term matching nothing excludes the convo); empty query →
    pure `last_at` desc; project/branch/date filters cut the set.
  - `highlight`: returns a `Text` whose styled spans cover the matched substrings; empty
    query → header + plain opening snippet.
- `tests/test_conversations.py`: write a tiny JSONL transcript to a tmp dir, run
  `index_conversations(tmp)` / `_parse_session`, assert `project_name`, `last_date`,
  `title_lc`/`body_lc`, cap behavior, and newest-first index order.
- One light `tests/test_view.py` (`@pytest.mark.integration`) using Textual `Pilot`:
  mount the app with an injected index, type a query, assert the table reorders and the
  preview updates. Keep minimal.

Add `CCDashboard/requirements-dev.txt` with `pytest` (a pip-audit-clean pinned version)
and a `pytest.ini`/`[tool.pytest.ini_options]` registering the `unit`/`integration`
markers. Tests run with `python -m pytest CCDashboard/tests`.

---

## 8. Out of scope (documented follow-ups)

- Persistent, mtime-keyed on-disk index cache (so launch/`Ctrl+R` doesn't re-parse
  ~300 MB). Biggest future scalability win; separate effort.
- Fully uncapped / streaming body search (we only raised the cap to 1 MB here).
- Boolean `OR`, negation (`-term`), saved searches, branch dropdown.
- **Fuzzy-vs-exact tie-break (Low):** a fuzzy *title* match (ratio ≥ ~0.83) can
  outscore an exact *body-only, non-word-boundary* substring hit (e.g. fuzzy title
  "permission settings" at 7.81 beats exact body "superpermissionsx" at 7.0). It only
  bites when the exact hit is a mid-word body substring AND the fuzzy hit lands in a
  higher-weighted field; normal use ranks correctly. Fix later by capping fuzzy
  contribution below the weakest exact-field weight (would re-tune ranking tests).

---

## 9. Acceptance

- Searching `grep` ranks the relevant chat far higher than pure recency would; adding
  `permissions` (a title word) floats the target to the top.
- A typo (`permisions`) still finds it via fuzzy rescue.
- Project dropdown + `after:`/date dropdown narrow results; `branch:` operator works.
- Highlighted preview pane updates as the row cursor moves.
- `python -m pytest CCDashboard/tests` passes; the app launches and the CONVERSATIONS
  tab behaves as described.
