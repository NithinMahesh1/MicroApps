"""Todo TUI — a simple terminal to-do manager with tabbed Todo/Completed views.

Built with Textual. Tasks persist to ``~/.local/share/todo-tui/tasks.json``
(with a ``.bak`` fallback and atomic writes). Run directly with
``python todo_tui.py`` or via the MicroApps Launcher.
"""
import json
import tempfile
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
)

DATA_DIR = Path.home() / ".local" / "share" / "todo-tui"
DATA_FILE = DATA_DIR / "tasks.json"
BACKUP_FILE = DATA_DIR / "tasks.json.bak"


def load_tasks() -> dict:
    for path in (DATA_FILE, BACKUP_FILE):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return {"todo": [], "completed": []}


def save_tasks(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Keep a backup of the previous save
    if DATA_FILE.exists():
        try:
            BACKUP_FILE.write_bytes(DATA_FILE.read_bytes())
        except OSError:
            pass
    # Atomic write: write to temp file then rename
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with open(fd, "w") as f:
            json.dump(data, f, indent=2)
        Path(tmp_path).replace(DATA_FILE)
    except OSError:
        Path(tmp_path).unlink(missing_ok=True)
        raise


class AddTaskScreen(ModalScreen[str]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    AddTaskScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        max-height: 12;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #dialog Label {
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }
    #task-input {
        width: 100%;
        margin-bottom: 1;
    }
    #btn-row {
        width: 100%;
        align: center middle;
        height: 3;
    }
    #btn-row Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Add New Task")
            yield Input(placeholder="Enter task description...", id="task-input")
            with Horizontal(id="btn-row"):
                yield Button("Add", variant="success", id="btn-add")
                yield Button("Cancel", variant="error", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#task-input", Input).focus()

    @on(Button.Pressed, "#btn-add")
    def on_add(self) -> None:
        value = self.query_one("#task-input", Input).value.strip()
        if value:
            self.dismiss(value)

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel_btn(self) -> None:
        self.dismiss("")

    @on(Input.Submitted)
    def on_submit(self) -> None:
        value = self.query_one("#task-input", Input).value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss("")


class TaskItem(ListItem):
    def __init__(self, task_text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.task_text = task_text

    def compose(self) -> ComposeResult:
        yield Static(self.task_text)


class TodoApp(App):
    CSS = """
    Screen {
        background: transparent;
    }
    TabbedContent {
        height: 1fr;
        background: transparent;
    }
    TabPane {
        padding: 1;
        background: transparent;
    }
    ContentSwitcher {
        background: transparent;
    }
    ListView {
        height: 1fr;
        border: round $primary;
        background: transparent;
    }
    .empty-msg {
        width: 100%;
        height: 3;
        content-align: center middle;
        color: $text-muted;
    }
    #bottom-bar {
        dock: bottom;
        height: 3;
        align: center middle;
        padding: 0 1;
    }
    #bottom-bar Button {
        margin: 0 1;
        min-width: 8;
        max-width: 16;
    }
    """

    TITLE = "Todo TUI"
    BINDINGS = [
        Binding("a", "add_task", "Add Task"),
        Binding("d", "delete_task", "Delete"),
        Binding("enter", "toggle_task", "Complete/Undo"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.data = load_tasks()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent("Todo", "Completed"):
            with TabPane("Todo", id="tab-todo"):
                yield ListView(id="todo-list")
            with TabPane("Completed", id="tab-completed"):
                yield ListView(id="completed-list")
        with Horizontal(id="bottom-bar"):
            yield Button("Add", variant="success", id="btn-add-task")
            yield Button("Done/Undo", variant="primary", id="btn-toggle")
            yield Button("Delete", variant="error", id="btn-delete")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#todo-list", ListView).border_title = "Tasks"
        self.query_one("#completed-list", ListView).border_title = "Done"
        self._refresh_lists()

    def _refresh_lists(self) -> None:
        todo_list = self.query_one("#todo-list", ListView)
        completed_list = self.query_one("#completed-list", ListView)

        todo_list.clear()
        completed_list.clear()

        for task in self.data["todo"]:
            todo_list.append(TaskItem(f"[ ] {task}"))

        for task in self.data["completed"]:
            completed_list.append(TaskItem(f"[x] {task}"))

        if not self.data["todo"]:
            todo_list.append(TaskItem("  No tasks yet. Press 'a' to add one."))
        if not self.data["completed"]:
            completed_list.append(TaskItem("  No completed tasks yet."))

    def _get_active_tab(self) -> str:
        tabbed = self.query_one(TabbedContent)
        if tabbed.active == "tab-completed":
            return "completed"
        return "todo"

    def _get_selected_index(self, list_id: str) -> int | None:
        lv = self.query_one(f"#{list_id}", ListView)
        if lv.index is not None and lv.index >= 0:
            return lv.index
        return None

    def action_add_task(self) -> None:
        def on_result(result: str) -> None:
            if result:
                self.data["todo"].append(result)
                save_tasks(self.data)
                self._refresh_lists()

        self.push_screen(AddTaskScreen(), callback=on_result)

    @on(Button.Pressed, "#btn-add-task")
    def on_add_btn(self) -> None:
        self.action_add_task()

    def action_toggle_task(self) -> None:
        tab = self._get_active_tab()
        if tab == "todo":
            idx = self._get_selected_index("todo-list")
            if idx is not None and idx < len(self.data["todo"]):
                task = self.data["todo"].pop(idx)
                self.data["completed"].append(task)
                save_tasks(self.data)
                self._refresh_lists()
        else:
            idx = self._get_selected_index("completed-list")
            if idx is not None and idx < len(self.data["completed"]):
                task = self.data["completed"].pop(idx)
                self.data["todo"].append(task)
                save_tasks(self.data)
                self._refresh_lists()

    @on(Button.Pressed, "#btn-toggle")
    def on_toggle_btn(self) -> None:
        self.action_toggle_task()

    def action_delete_task(self) -> None:
        tab = self._get_active_tab()
        if tab == "todo":
            idx = self._get_selected_index("todo-list")
            if idx is not None and idx < len(self.data["todo"]):
                self.data["todo"].pop(idx)
                save_tasks(self.data)
                self._refresh_lists()
        else:
            idx = self._get_selected_index("completed-list")
            if idx is not None and idx < len(self.data["completed"]):
                self.data["completed"].pop(idx)
                save_tasks(self.data)
                self._refresh_lists()

    @on(Button.Pressed, "#btn-delete")
    def on_delete_btn(self) -> None:
        self.action_delete_task()


def main():
    app = TodoApp()
    app.run()


if __name__ == "__main__":
    main()
