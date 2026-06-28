"""
The CCDashboard Textual app — a futuristic terminal console for ~/.claude.

Three tabs over the shared, UI-agnostic engine:
  * Config        — searchable inventory of skills/agents/memory/rules/settings.
  * Conversations — full-text search of past Claude Code chats; Enter resumes one
                    in an elevated PowerShell (``claude --resume`` in its cwd).
  * QuizMe        — daily spaced-repetition quiz over your study notes; Claude
                    generates a question and grades your answer.

Instance attributes are ``_ccd_*`` prefixed to avoid colliding with Textual's
internal ``App`` attributes.
"""
from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from ccdashboard import conversations, quiz, scan
from ccdashboard.tui.config_view import ConfigView
from ccdashboard.tui.conversations_view import ConversationsView
from ccdashboard.tui.quiz_view import QuizView

try:
    import pyfiglet
except ImportError:  # pragma: no cover - banner is optional
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
        Binding("3", "show('quizme')", "QuizMe"),
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
            with TabPane("◇ QUIZME", id="quizme"):
                yield QuizView(id="quiz-view")
        yield Footer()

    def on_mount(self) -> None:
        self._load()

    @work(thread=True, exclusive=True)
    def _load(self) -> None:
        """Index config + conversations + quiz cards off the UI thread, then populate.

        ``quiz.load_cards`` / ``quiz.load_state`` are pure stdlib + filesystem
        reads (no network, no Claude call), so they don't regress startup. The
        only Claude work happens later, from inside QuizView's own worker.
        """
        vm = scan.build_view_model(self._ccd_config_dir)
        convos = conversations.index_conversations()
        cards = quiz.load_all_cards()
        state = quiz.load_state()
        self.call_from_thread(self._populate, vm, convos, cards, state)

    def _populate(self, vm: dict, convos: list, cards: list, state) -> None:
        self.query_one(ConfigView).load_items(vm)
        self.query_one(ConversationsView).load_conversations(convos)
        self.query_one(QuizView).load_quiz(cards, state)
        self._ccd_active_view().focus_search()

    def action_show(self, tab: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab

    def action_refresh(self) -> None:
        self.notify("Refreshing…")
        self._load()

    def action_search(self) -> None:
        """Focus the active tab's search box (also bound to ``/``)."""
        self._ccd_active_view().focus_search()

    def _ccd_active_view(self):
        """Return the view widget in the active tab (Config/Conversations/Quiz)."""
        active = self.query_one("#tabs", TabbedContent).active
        if active == "conversations":
            return self.query_one(ConversationsView)
        if active == "quizme":
            return self.query_one(QuizView)
        return self.query_one(ConfigView)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        # Landing on a tab should drop focus into its content, not the tab bar.
        self._ccd_active_view().focus_search()


def run(config_dir: Path) -> None:
    """Entry point used by cc_dashboard.py."""
    CCDashboardApp(config_dir).run()
