"""
The CCDashboard Textual app — a futuristic terminal console for ~/.claude.

Four tabs over the shared, UI-agnostic engine:
  * Config        — searchable inventory of skills/agents/memory/rules/settings.
  * Conversations — full-text search of past Claude Code chats; Enter resumes one
                    in an elevated PowerShell (``claude --resume`` in its cwd).
  * Memories      — search your per-project Claude auto-memories; Enter opens one
                    in VS Code. Reuses the Conversations search engine verbatim.
  * QuizMe (v2)   — spaced-repetition quiz over pre-generated flash-card decks;
                    a background build runs on every app open (incremental, cheap when
                    up-to-date); cards already on disk are quizzable immediately;
                    free practice continues after the daily card; Claude grades answers;
                    high-score stats + per-card attempt history.

Instance attributes are ``_ccd_*`` prefixed to avoid colliding with Textual's
internal ``App`` attributes.
"""
from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from ccdashboard import conversations, memory, quiz, scan
from ccdashboard.tui.config_view import ConfigView
from ccdashboard.tui.conversations_view import ConversationsView
from ccdashboard.tui.memory_view import MemoriesView
from ccdashboard.tui.quiz_view import QuizView

# flashcards.py is delivered by a concurrent agent; guard the import so the app
# is importable and testable even before that module exists on disk.
try:
    from ccdashboard import flashcards as _flashcards
except ImportError:  # pragma: no cover
    _flashcards = None  # type: ignore[assignment]

try:
    import pyfiglet
except ImportError:  # pragma: no cover — banner is optional
    pyfiglet = None


class CCDashboardApp(App):
    """Top-level TUI app."""

    CSS_PATH = "app.tcss"
    TITLE = "CC · Dashboard"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("1", "show('config')", "Config"),
        Binding("2", "show('conversations')", "Conversations"),
        Binding("3", "show('memories')", "Memories"),
        Binding("4", "show('quizme')", "QuizMe"),
        Binding("slash", "search", "Search"),
    ]

    def __init__(self, config_dir: Path) -> None:
        super().__init__()
        self._ccd_config_dir = config_dir

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        if pyfiglet is not None:
            yield Static(pyfiglet.figlet_format("CC  DASH", font="small"), classes="banner")
        with TabbedContent(initial="config", id="tabs"):
            with TabPane("◇ CONFIG", id="config"):
                yield ConfigView(id="config-view")
            with TabPane("◇ CONVERSATIONS", id="conversations"):
                yield ConversationsView(id="conversations-view")
            with TabPane("◇ MEMORIES", id="memories"):
                yield MemoriesView(id="memory-view")
            with TabPane("◇ QUIZME", id="quizme"):
                yield QuizView(id="quiz-view")
        yield Footer()

    def on_mount(self) -> None:
        self._load()

    @work(thread=True, exclusive=True)
    def _load(self) -> None:
        """Index config + conversations + quiz cards off the UI thread, then populate.

        flashcards.load_decks() is a pure filesystem read (no network, no Claude call)
        so it never regresses startup time. Background deck generation starts separately
        from _ccd_build_decks() after _populate() completes and QuizView is ready.
        """
        vm = scan.build_view_model(self._ccd_config_dir)
        convos = conversations.index_conversations()
        mems = memory.index_memories()
        # v2: cards come from pre-generated decks, not live extraction.
        # _flashcards may be None if flashcards.py hasn't landed yet; safe fallback = [].
        cards = _flashcards.load_decks() if _flashcards is not None else []
        state = quiz.load_state()
        self.call_from_thread(self._populate, vm, convos, mems, cards, state)

    def _populate(
        self,
        vm: dict,
        convos: list,
        mems: list,
        cards: list,
        state,
    ) -> None:
        self.query_one(ConfigView).load_items(vm)
        self.query_one(ConversationsView).load_conversations(convos)
        self.query_one(MemoriesView).load_memories(mems)
        self.query_one(QuizView).load_quiz(cards, state)
        self._ccd_active_view().focus_search()
        # Start background deck generation now that QuizView is initialised and
        # can receive progress callbacks via set_build_progress / on_build_done.
        self._ccd_build_decks()

    @work(thread=True, exclusive=False)
    def _ccd_build_decks(self) -> None:
        """Background incremental deck build that runs on every app open.

        Skipped silently when ANTHROPIC_API_KEY is unset or the SDK is missing.
        Progress marshals to QuizView.set_build_progress; completion to on_build_done.
        """
        if _flashcards is None or not _flashcards.is_available():
            return

        def _cb(done: int, total: int, source: str) -> None:
            try:
                self.call_from_thread(
                    self.query_one(QuizView).set_build_progress, done, total, source
                )
            except Exception:  # noqa: BLE001 — QuizView may not be mounted yet
                pass

        try:
            result = _flashcards.build_decks(quiz.load_notes_dirs(), progress_cb=_cb)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(
                self.notify,
                f"Deck build error: {exc}",
                severity="error",
                timeout=8,
            )
            return

        try:
            self.call_from_thread(self.query_one(QuizView).on_build_done, result)
        except Exception:  # noqa: BLE001
            pass

    def action_show(self, tab: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab

    def action_refresh(self) -> None:
        self.notify("Refreshing…")
        self._load()

    def action_search(self) -> None:
        """Focus the active tab's search box (also bound to ``/``)."""
        self._ccd_active_view().focus_search()

    def _ccd_active_view(self):
        """Return the view widget in the active tab (Config/Conversations/Memories/Quiz)."""
        active = self.query_one("#tabs", TabbedContent).active
        if active == "conversations":
            return self.query_one(ConversationsView)
        if active == "memories":
            return self.query_one(MemoriesView)
        if active == "quizme":
            return self.query_one(QuizView)
        return self.query_one(ConfigView)

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated  # noqa: ARG002
    ) -> None:
        # Landing on a tab drops focus into its content, not the tab bar.
        self._ccd_active_view().focus_search()


def run(config_dir: Path) -> None:
    """Entry point used by cc_dashboard.py."""
    CCDashboardApp(config_dir).run()
