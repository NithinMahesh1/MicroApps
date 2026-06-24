"""Unit tests for the pure search engine (``ccdashboard.search``).

These follow Section 4 of the conversation-search design spec: the query parser,
the dropdown/operator merge, the blended relevance+recency ranking (including
fuzzy rescue and coverage drops), and the highlight/preview builder. The engine
is UI-agnostic, so nothing here touches Textual.
"""
from __future__ import annotations

from datetime import date

import pytest

from ccdashboard import search

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# parse_query
# ---------------------------------------------------------------------------


def test_parse_query_bare_terms_are_lowercased_and_anded() -> None:
    q = search.parse_query("Grep Permissions")
    assert q.terms == ("grep", "permissions")
    assert q.phrases == ()
    assert q.project is None and q.branch is None
    assert q.after is None and q.before is None
    assert q.raw == "Grep Permissions"
    assert not q.is_empty


def test_parse_query_extracts_quoted_phrase_lowercased_whitespace_preserved() -> None:
    q = search.parse_query('foo "Exact Phrase Here" bar')
    assert q.phrases == ("exact phrase here",)
    assert q.terms == ("foo", "bar")
    assert not q.is_empty


def test_parse_query_project_and_dir_operators_set_project_lc() -> None:
    assert search.parse_query("project:Smart-Gift-Card").project == "smart-gift-card"
    assert search.parse_query("dir:Smart-Gift-Card").project == "smart-gift-card"


def test_parse_query_branch_operator_sets_branch_lc() -> None:
    q = search.parse_query("branch:Feature/Login")
    assert q.branch == "feature/login"


def test_parse_query_after_before_valid() -> None:
    q = search.parse_query("after:2026-06-01 before:2026-06-30")
    assert q.after == date(2026, 6, 1)
    assert q.before == date(2026, 6, 30)


def test_parse_query_invalid_after_is_ignored_not_a_term() -> None:
    q = search.parse_query("after:nonsense grep")
    assert q.after is None
    # An unparseable date operator is dropped entirely (not kept as a literal term).
    assert q.terms == ("grep",)


def test_parse_query_invalid_before_is_ignored() -> None:
    q = search.parse_query("before:2026-13-99")
    assert q.before is None
    assert q.terms == ()
    assert q.is_empty


def test_parse_query_unknown_operator_is_a_literal_term() -> None:
    q = search.parse_query("foo:bar")
    assert q.terms == ("foo:bar",)
    assert q.project is None and q.branch is None


def test_parse_query_operator_key_is_case_insensitive() -> None:
    assert search.parse_query("Project:Web").project == "web"
    assert search.parse_query("BRANCH:Main").branch == "main"


def test_parse_query_bare_colon_or_empty_value_is_literal_term() -> None:
    # "project:" with an empty value is a literal token, not a project filter.
    q = search.parse_query("project:")
    assert q.project is None
    assert q.terms == ("project:",)


def test_parse_query_empty_string_is_empty() -> None:
    q = search.parse_query("")
    assert q.is_empty
    assert q.terms == () and q.phrases == ()


def test_parse_query_mixed_everything() -> None:
    q = search.parse_query(
        'grep "exact phrase" project:web branch:main after:2026-01-01 before:2026-12-31 extra'
    )
    assert q.terms == ("grep", "extra")
    assert q.phrases == ("exact phrase",)
    assert q.project == "web"
    assert q.branch == "main"
    assert q.after == date(2026, 1, 1)
    assert q.before == date(2026, 12, 31)


# ---------------------------------------------------------------------------
# merge_ui_filters
# ---------------------------------------------------------------------------


def test_merge_applies_project_dropdown_when_query_has_no_project() -> None:
    q = search.parse_query("grep")
    merged = search.merge_ui_filters(q, project="C:\\Repos\\Web")
    assert merged.project == "c:\\repos\\web"
    assert merged is not q  # immutability


def test_merge_operator_wins_over_project_dropdown() -> None:
    q = search.parse_query("grep project:typed")
    merged = search.merge_ui_filters(q, project="C:\\Repos\\Other")
    assert merged.project == "typed"  # the typed operator is preserved


def test_merge_since_days_becomes_after_relative_to_now() -> None:
    q = search.parse_query("grep")
    now = date(2026, 6, 24)
    merged = search.merge_ui_filters(q, since_days=7, now=now)
    assert merged.after == date(2026, 6, 17)


def test_merge_operator_after_wins_over_since_days() -> None:
    q = search.parse_query("after:2026-06-01")
    merged = search.merge_ui_filters(q, since_days=7, now=date(2026, 6, 24))
    assert merged.after == date(2026, 6, 1)


def test_merge_zero_since_days_is_any_time() -> None:
    q = search.parse_query("grep")
    merged = search.merge_ui_filters(q, since_days=0, now=date(2026, 6, 24))
    assert merged.after is None


def test_merge_none_inputs_return_equivalent_query() -> None:
    q = search.parse_query("grep project:web")
    merged = search.merge_ui_filters(q)
    assert merged is not q
    assert merged.project == "web"
    assert merged.terms == ("grep",)


def test_merge_does_not_mutate_original() -> None:
    q = search.parse_query("grep")
    search.merge_ui_filters(q, project="C:\\Repos\\Web", since_days=30, now=date(2026, 6, 24))
    # original is untouched
    assert q.project is None
    assert q.after is None


# ---------------------------------------------------------------------------
# rank — relevance + recency
# ---------------------------------------------------------------------------


def test_rank_title_hit_outranks_body_only_hit(make_convo, freeze_now) -> None:
    title_hit = make_convo(
        session_id="t",
        title="Debugging the grep pipeline",
        text="nothing relevant here",
        last_at="2026-06-24T10:00:00.000Z",
    )
    body_hit = make_convo(
        session_id="b",
        title="Unrelated topic",
        text="we used grep to find it",
        last_at="2026-06-24T10:00:00.000Z",
    )
    ranked = search.rank([body_hit, title_hit], search.parse_query("grep"), now=freeze_now)
    assert [c.session_id for c in ranked] == ["t", "b"]


def test_rank_term_frequency_raises_score(make_convo, freeze_now) -> None:
    many = make_convo(
        session_id="many",
        title="x",
        text="grep grep grep grep",
        last_at="2026-06-24T10:00:00.000Z",
    )
    once = make_convo(
        session_id="once",
        title="x",
        text="grep",
        last_at="2026-06-24T10:00:00.000Z",
    )
    ranked = search.rank([once, many], search.parse_query("grep"), now=freeze_now)
    assert [c.session_id for c in ranked] == ["many", "once"]


def test_rank_whole_word_bonus(make_convo, freeze_now) -> None:
    whole = make_convo(
        session_id="whole",
        title="x",
        text="we ran grep today",
        last_at="2026-06-24T10:00:00.000Z",
    )
    substring = make_convo(
        session_id="sub",
        title="x",
        text="the regrepper module",
        last_at="2026-06-24T10:00:00.000Z",
    )
    ranked = search.rank([substring, whole], search.parse_query("grep"), now=freeze_now)
    assert ranked[0].session_id == "whole"


def test_rank_fuzzy_rescue_finds_typo_but_ranks_below_exact(make_convo, freeze_now) -> None:
    # Query 'permisions' is a typo of 'permissions'. The "exact" convo contains the
    # typed string verbatim in its title (an exact hit); the "fuzzy" convo has the
    # correctly-spelled word, so the typo only matches it via difflib fuzzy rescue.
    # Fuzzy must never beat exact.
    exact = make_convo(
        session_id="exact",
        title="permisions hotfix",  # contains the (mis)typed query verbatim => exact
        text="body",
        last_at="2026-06-24T10:00:00.000Z",
    )
    fuzzy = make_convo(
        session_id="fuzzy",
        title="permissions hotfix",  # correctly spelled => only a fuzzy match for the typo
        text="body",
        last_at="2026-06-24T10:00:00.000Z",
    )
    ranked = search.rank([fuzzy, exact], search.parse_query("permisions"), now=freeze_now)
    assert [c.session_id for c in ranked] == ["exact", "fuzzy"]


def test_rank_fuzzy_rescue_actually_includes_typo_match(make_convo, freeze_now) -> None:
    convo = make_convo(
        session_id="only",
        title="permissions overhaul",
        text="body text",
        last_at="2026-06-24T10:00:00.000Z",
    )
    ranked = search.rank([convo], search.parse_query("permisions"), now=freeze_now)
    assert [c.session_id for c in ranked] == ["only"]


def test_rank_recency_breaks_ties_for_equal_relevance(make_convo, freeze_now) -> None:
    older = make_convo(
        session_id="older",
        title="grep notes",
        text="grep",
        last_at="2026-05-01T10:00:00.000Z",
    )
    newer = make_convo(
        session_id="newer",
        title="grep notes",
        text="grep",
        last_at="2026-06-24T10:00:00.000Z",
    )
    ranked = search.rank([older, newer], search.parse_query("grep"), now=freeze_now)
    assert [c.session_id for c in ranked] == ["newer", "older"]


def test_rank_title_hit_not_overtaken_by_a_much_newer_body_hit(make_convo, freeze_now) -> None:
    # A title hit (_W_TITLE=10) must dominate even a brand-new body-only hit
    # (recency contributes at most _W_RECENCY=4), per the spec's "title hits dominate".
    old_title = make_convo(
        session_id="title",
        title="grep deep dive",
        text="nothing",
        last_at="2025-01-01T10:00:00.000Z",  # very old
    )
    new_body = make_convo(
        session_id="body",
        title="unrelated",
        text="grep",
        last_at="2026-06-24T10:00:00.000Z",  # brand new
    )
    ranked = search.rank([new_body, old_title], search.parse_query("grep"), now=freeze_now)
    assert ranked[0].session_id == "title"


def test_rank_coverage_drop_excludes_convo_missing_a_term(make_convo, freeze_now) -> None:
    has_both = make_convo(
        session_id="both",
        title="grep and permissions",
        text="x",
        last_at="2026-06-24T10:00:00.000Z",
    )
    has_one = make_convo(
        session_id="one",
        title="grep only",
        text="zzzzz nothing about the second term",
        last_at="2026-06-24T10:00:00.000Z",
    )
    ranked = search.rank(
        [has_both, has_one], search.parse_query("grep permissions"), now=freeze_now
    )
    assert [c.session_id for c in ranked] == ["both"]


def test_rank_phrase_coverage_drop(make_convo, freeze_now) -> None:
    has_phrase = make_convo(
        session_id="has",
        title="x",
        text="this contains the exact phrase verbatim",
        last_at="2026-06-24T10:00:00.000Z",
    )
    no_phrase = make_convo(
        session_id="no",
        title="x",
        text="exact words but phrase not contiguous here",
        last_at="2026-06-24T10:00:00.000Z",
    )
    ranked = search.rank(
        [has_phrase, no_phrase], search.parse_query('"exact phrase"'), now=freeze_now
    )
    assert [c.session_id for c in ranked] == ["has"]


def test_rank_empty_query_is_pure_last_at_desc(make_convo, freeze_now) -> None:
    a = make_convo(session_id="a", last_at="2026-06-01T10:00:00.000Z")
    b = make_convo(session_id="b", last_at="2026-06-24T10:00:00.000Z")
    c = make_convo(session_id="c", last_at="2026-03-15T10:00:00.000Z")
    ranked = search.rank([a, b, c], search.parse_query(""), now=freeze_now)
    assert [x.session_id for x in ranked] == ["b", "a", "c"]


def test_rank_project_filter_cuts_the_set(make_convo, freeze_now) -> None:
    web = make_convo(session_id="web", cwd="C:\\Repos\\Web", text="grep")
    api = make_convo(session_id="api", cwd="C:\\Repos\\Api", text="grep")
    ranked = search.rank(
        [web, api], search.parse_query("grep project:web"), now=freeze_now
    )
    assert [c.session_id for c in ranked] == ["web"]


def test_rank_branch_filter_cuts_the_set(make_convo, freeze_now) -> None:
    main = make_convo(session_id="main", git_branch="main", text="grep")
    feat = make_convo(session_id="feat", git_branch="feature/login", text="grep")
    ranked = search.rank(
        [main, feat], search.parse_query("grep branch:feature"), now=freeze_now
    )
    assert [c.session_id for c in ranked] == ["feat"]


def test_rank_date_filters_cut_the_set(make_convo, freeze_now) -> None:
    inside = make_convo(session_id="in", last_at="2026-06-15T10:00:00.000Z", text="grep")
    too_old = make_convo(session_id="old", last_at="2026-05-01T10:00:00.000Z", text="grep")
    too_new = make_convo(session_id="new", last_at="2026-07-01T10:00:00.000Z", text="grep")
    q = search.parse_query("grep after:2026-06-01 before:2026-06-30")
    ranked = search.rank([inside, too_old, too_new], q, now=freeze_now)
    assert [c.session_id for c in ranked] == ["in"]


def test_rank_empty_query_with_project_filter(make_convo, freeze_now) -> None:
    web = make_convo(session_id="web", cwd="C:\\Repos\\Web", last_at="2026-06-24T10:00:00.000Z")
    api = make_convo(session_id="api", cwd="C:\\Repos\\Api", last_at="2026-06-24T11:00:00.000Z")
    ranked = search.rank([web, api], search.parse_query("project:web"), now=freeze_now)
    assert [c.session_id for c in ranked] == ["web"]


# ---------------------------------------------------------------------------
# highlight / preview
# ---------------------------------------------------------------------------


def test_highlight_styled_spans_cover_matched_substring(make_convo) -> None:
    # Use a body where the match term does NOT also appear in the title/header, so a
    # styled span over the body 'grep' is unambiguously a *match* highlight (the header
    # may carry its own base styling, which we don't assert against here).
    convo = make_convo(
        title="Pipeline notes",
        text="We ran grep against the logs to find the error quickly.",
    )
    rendered = search.highlight(convo, search.parse_query("grep"))
    plain = rendered.plain
    assert rendered.spans, "expected at least one styled span"
    # At least one styled span must land exactly on a matched 'grep' substring.
    covered = [
        plain[s.start : s.end]
        for s in rendered.spans
        if plain[s.start : s.end].lower() == "grep"
    ]
    assert covered, "expected a styled span covering the matched 'grep' substring"


def test_highlight_empty_query_is_header_plus_plain_snippet(make_convo) -> None:
    convo = make_convo(
        title="Opening Title",
        text="This is the opening message of the transcript body.",
        git_branch="main",
        last_at="2026-06-24T10:30:00.000Z",
        message_count=4,
        session_id="abcdef12-3456-7890-aaaa-bbbbbbbbbbbb",
    )
    rendered = search.highlight(convo, search.parse_query(""))
    plain = rendered.plain
    # Header carries the title and the opening snippet text appears, with no highlights.
    assert "Opening Title" in plain
    assert "opening message" in plain
    assert rendered.spans == [] or all(
        plain[s.start : s.end].strip() == "" for s in rendered.spans
    )


def test_highlight_header_contains_metadata(make_convo) -> None:
    convo = make_convo(
        title="Some Title",
        cwd="C:\\Repos\\smart-gift-card",
        git_branch="main",
        last_at="2026-06-24T10:30:00.000Z",
        message_count=7,
        session_id="deadbeef-0000-1111-2222-333344445555",
    )
    rendered = search.highlight(convo, search.parse_query("anything"))
    plain = rendered.plain
    assert "Some Title" in plain
    assert "smart-gift-card" in plain  # project_name (leaf)
    assert "main" in plain  # git_branch
    assert "deadbeef" in plain  # session_id[:8]


def test_highlight_title_styles_matched_term(make_convo) -> None:
    convo = make_convo(title="Grep Pipeline Debugging")
    rendered = search.highlight_title(convo, search.parse_query("grep"))
    assert rendered.plain == "Grep Pipeline Debugging"
    assert rendered.spans, "expected the matched title term to be styled"


def test_highlight_title_empty_query_is_plain(make_convo) -> None:
    convo = make_convo(title="Grep Pipeline Debugging")
    rendered = search.highlight_title(convo, search.parse_query(""))
    assert rendered.plain == "Grep Pipeline Debugging"
    assert rendered.spans == []
