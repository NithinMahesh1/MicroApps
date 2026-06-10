import datetime
import re
import sys
import time
import webbrowser
from pathlib import Path

try:
    import msvcrt
except ImportError:
    msvcrt = None

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
import pyfiglet

# Robust local timezone that handles DST transitions on Windows
try:
    from dateutil import tz as _tz
    _LOCAL_TZ = _tz.tzlocal()
except ImportError:
    _LOCAL_TZ = None


def _local_now():
    """Get current local time as a timezone-aware datetime, DST-correct."""
    if _LOCAL_TZ is not None:
        return datetime.datetime.now(tz=_LOCAL_TZ)
    return datetime.datetime.now(datetime.timezone.utc).astimezone()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]
APP_DIR = Path(__file__).parent
# Sensitive files live in the repo-root `config/` folder (git-ignored). See config/README.md.
CONFIG_DIR = APP_DIR.parent / "config"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"
REFRESH_INTERVAL = 300  # re-fetch meetings every 5 minutes
ALERT_THRESHOLDS = [15, 10, 5]  # minutes before meeting


def authenticate(console):
    """Authenticate with Google Calendar and Gmail via OAuth 2.0."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        # Re-auth if token is missing the gmail scope
        if creds and not set(SCOPES).issubset(set(creds.scopes or [])):
            creds = None
            TOKEN_FILE.unlink()

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                console.print(
                    f"[bold red]Error:[/bold red] {CREDENTIALS_FILE.name} not found!\n"
                )
                console.print("[bold]To set up Google Calendar API access:[/bold]")
                console.print("  1. Go to https://console.cloud.google.com/")
                console.print("  2. Create a project (or select an existing one)")
                console.print(
                    "  3. Enable the [cyan]Google Calendar API[/cyan] and [cyan]Gmail API[/cyan]"
                )
                console.print(
                    "  4. Go to Credentials > Create Credentials > OAuth client ID"
                )
                console.print('  5. Choose [cyan]Desktop app[/cyan] as the type')
                console.print(
                    f"  6. Download the JSON and save it as [cyan]{CREDENTIALS_FILE.name}[/cyan] here:"
                )
                console.print(f"     [dim]{CONFIG_DIR}[/dim]")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    calendar_service = build("calendar", "v3", credentials=creds)
    gmail_service = build("gmail", "v1", credentials=creds)
    return calendar_service, gmail_service


def parse_dt(dt_string):
    """Parse a datetime string from the Google Calendar API."""
    if dt_string.endswith("Z"):
        dt_string = dt_string[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(dt_string)


def get_todays_meetings(service):
    """Fetch all of today's events from the primary calendar."""
    local_now = _local_now()
    start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + datetime.timedelta(days=1)

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return result.get("items", [])


def get_recent_emails(gmail_service, max_results=10):
    """Fetch recent unread emails from the primary inbox."""
    result = (
        gmail_service.users()
        .messages()
        .list(
            userId="me",
            labelIds=["INBOX", "UNREAD"],
            maxResults=max_results,
        )
        .execute()
    )

    messages = result.get("messages", [])
    emails = []
    for msg in messages:
        detail = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=msg["id"], format="metadata",
                 metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
        emails.append({
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", "(No subject)"),
            "snippet": detail.get("snippet", ""),
            "date": headers.get("Date", ""),
        })

    return emails


def format_countdown(total_minutes):
    """Format a minute count into a human-readable countdown string."""
    if total_minutes < 1:
        return "< 1m"
    if total_minutes < 60:
        return f"in {total_minutes}m"
    hours, mins = divmod(total_minutes, 60)
    return f"in {hours}h {mins}m"


_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def get_meeting_link(event):
    """Extract the best joinable meeting link from a calendar event."""
    # 1. Structured conference data (Google Meet, integrated Zoom, etc.)
    for entry in event.get("conferenceData", {}).get("entryPoints", []):
        uri = entry.get("uri", "")
        if uri.startswith("http"):
            return uri

    # 2. Legacy Google Hangouts / Meet link
    hangout = event.get("hangoutLink")
    if hangout:
        return hangout

    # 3. URL in the location field (manually pasted Zoom/Teams links)
    match = _URL_RE.search(event.get("location", ""))
    if match:
        return match.group(0)

    # 4. URL in the description (fallback)
    match = _URL_RE.search(event.get("description", ""))
    if match:
        return match.group(0)

    return None


def check_keypress():
    """Return the key pressed as a string, or None (non-blocking)."""
    if msvcrt is None:
        return None
    if msvcrt.kbhit():
        ch = msvcrt.getch()
        # Special / extended keys start with 0x00 or 0xE0
        if ch in (b"\x00", b"\xe0"):
            if msvcrt.kbhit():
                scan = msvcrt.getch()
                if scan == b"H":
                    return "UP"
                if scan == b"P":
                    return "DOWN"
            return None
        if ch == b"\t":
            return "TAB"
        try:
            return ch.decode("ascii")
        except UnicodeDecodeError:
            return None
    return None


def get_active_alert(meetings, acknowledged):
    """Return the first unacknowledged alert as (event, event_id, threshold, mins_until) or None."""
    now = _local_now()

    for event in meetings:
        start_raw = event.get("start", {})
        if "dateTime" not in start_raw:
            continue

        start_dt = parse_dt(start_raw["dateTime"])
        mins_until = (start_dt - now).total_seconds() / 60

        if mins_until <= 0:
            continue

        event_id = event.get("id", event.get("summary", ""))

        # Check thresholds in ascending order (5, 10, 15) so the tightest fires first
        for threshold in sorted(ALERT_THRESHOLDS):
            if mins_until <= threshold and (event_id, threshold) not in acknowledged:
                return (event, event_id, threshold, mins_until)

    return None


def build_display(meetings, active_alert=None, emails=None,
                  active_panel="meetings", cursor_meetings=0, cursor_emails=0,
                  console_height=40):
    """Build the full TUI layout with clock, meeting list, and emails."""
    now = _local_now()

    # When an alert is active the whole UI shifts to red
    alert_mode = active_alert is not None
    accent = "red" if alert_mode else "cyan"
    panel_border = "red" if alert_mode else "bright_blue"

    # --- Layout ---
    layout = Layout()
    sections = [Layout(name="clock", size=12)]
    if active_alert:
        sections.append(Layout(name="alert", size=7))
    sections.append(Layout(name="meetings"))
    if emails is not None:
        sections.append(Layout(name="emails"))
    layout.split_column(*sections)

    # Calculate visible rows for scrollable sections
    fixed_height = 12  # clock panel
    if active_alert:
        fixed_height += 7
    remaining = max(console_height - fixed_height, 10)
    if emails is not None:
        meetings_height = remaining // 2
        emails_height = remaining - meetings_height
    else:
        meetings_height = remaining
        emails_height = 0
    # With show_lines=True each meeting row uses ~2 terminal lines
    max_meeting_rows = max((meetings_height - 7) // 2, 3)
    max_email_rows = max(emails_height - 6, 3)

    # --- Clock panel ---
    time_str = now.strftime("%I:%M")
    am_pm = now.strftime("%p")
    big_time = pyfiglet.figlet_format(time_str, font="big").rstrip("\n")
    date_str = now.strftime("%A, %B %d, %Y")
    clock_text = Text(justify="center")
    clock_text.append(f"{big_time}  {am_pm}\n", style=f"bold bright_{accent}")
    clock_text.append(date_str, style="bold white")
    layout["clock"].update(
        Panel(
            clock_text,
            title="[bold]Current Time[/bold]",
            border_style=accent,
            padding=(1, 0),
        )
    )

    # --- Alert panel ---
    if active_alert:
        event, _event_id, threshold, mins_until = active_alert
        summary = event.get("summary", "(No title)")
        start_dt = parse_dt(event["start"]["dateTime"]).astimezone(now.tzinfo)
        start_str = start_dt.strftime("%I:%M %p")
        flash = int(time.time()) % 2 == 0

        if threshold <= 5:
            color = "red"
            header = "STARTING SOON"
        elif threshold <= 10:
            color = "yellow"
            header = "STARTING SOON"
        else:
            color = "cyan"
            header = "HEADS UP"

        border = f"bold {color}" if flash else color
        alert_text = Text(justify="center")
        alert_text.append(f"{summary}", style=f"bold {color}")
        alert_text.append(f"  |  {start_str}", style=color)
        alert_text.append(f"  |  {int(mins_until)} min away\n", style=f"bold {color}")
        if flash:
            alert_text.append("Press [ENTER] to acknowledge", style=f"bold {color}")
        else:
            alert_text.append("Press [ENTER] to acknowledge", style=f"dim {color}")

        layout["alert"].update(
            Panel(
                alert_text,
                title=f"[bold {color}]⚠  {header}  ⚠[/bold {color}]",
                border_style=border,
                padding=(1, 0),
            )
        )

    # --- Meetings table ---
    # Derive scroll offset to keep cursor visible
    if not meetings or len(meetings) <= max_meeting_rows:
        scroll_offset_m = 0
        cursor_meetings = min(cursor_meetings, max(0, len(meetings) - 1))
    else:
        cursor_meetings = min(cursor_meetings, len(meetings) - 1)
        scroll_offset_m = max(0, min(cursor_meetings - max_meeting_rows // 2,
                                    len(meetings) - max_meeting_rows))

    table = Table(expand=True, show_lines=True, border_style=panel_border)
    table.add_column("#", justify="center", width=4)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Time", style="cyan", width=24)
    table.add_column("Meeting", min_width=20)
    table.add_column("Countdown", justify="right", width=14)

    if not meetings:
        table.add_row(
            "[dim]--[/dim]",
            "[dim]--[/dim]",
            "[dim]--[/dim]",
            "[dim italic]No meetings scheduled for today[/dim italic]",
            "[dim]--[/dim]",
        )
    else:
        # Pre-compute all row data so scroll slicing preserves statuses
        meeting_rows = []
        next_found = False

        for idx, event in enumerate(meetings, start=1):
            start_raw = event.get("start", {})
            end_raw = event.get("end", {})
            summary = event.get("summary", "(No title)")
            is_all_day = "date" in start_raw and "dateTime" not in start_raw
            has_link = get_meeting_link(event) is not None

            if is_all_day:
                time_range = "All Day"
                status = "[blue]All Day[/blue]"
                countdown = "--"
                style = "blue"
            else:
                start_dt = parse_dt(start_raw["dateTime"]).astimezone(now.tzinfo)
                end_dt = parse_dt(end_raw["dateTime"]).astimezone(now.tzinfo)
                time_range = (
                    f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')}"
                )

                if end_dt <= now:
                    status = "[dim]Done[/dim]"
                    countdown = "[dim]Passed[/dim]"
                    style = "dim"
                elif start_dt <= now <= end_dt:
                    mins_left = int((end_dt - now).total_seconds() / 60)
                    status = "[bold green]NOW[/bold green]"
                    countdown = f"[green]{mins_left}m left[/green]"
                    style = "bold green"
                else:
                    total_mins = int((start_dt - now).total_seconds() / 60)
                    cd_str = format_countdown(total_mins)

                    if not next_found:
                        status = "[bold yellow]>> Next[/bold yellow]"
                        countdown = f"[bold yellow]{cd_str}[/bold yellow]"
                        style = "bold yellow"
                        next_found = True
                    else:
                        status = "[dim]Upcoming[/dim]"
                        countdown = f"[dim]{cd_str}[/dim]"
                        style = ""

            if has_link and style != "dim":
                num_display = f"[bold bright_magenta]{idx}[/bold bright_magenta]"
            elif has_link:
                num_display = f"[dim]{idx}[/dim]"
            else:
                num_display = "[dim]-[/dim]"

            name_display = f"[{style}]{summary}[/{style}]" if style else summary
            meeting_rows.append((num_display, status, time_range, name_display, countdown))

        # Display visible window with cursor highlight
        visible = meeting_rows[scroll_offset_m:scroll_offset_m + max_meeting_rows]
        for i, row in enumerate(visible):
            actual_idx = scroll_offset_m + i
            is_cursor = actual_idx == cursor_meetings and active_panel == "meetings"
            if is_cursor:
                ptr_num = f"[bold bright_white]►[/bold bright_white]{row[0]}"
                table.add_row(ptr_num, *row[1:], style="on grey23")
            else:
                table.add_row(*row)

    # Subtitle showing progress and scroll info
    timed = [e for e in meetings if "dateTime" in e.get("start", {})]
    done = sum(1 for e in timed if parse_dt(e["end"]["dateTime"]) <= now)
    subtitle_parts = [f"{done}/{len(timed)} completed", "# to join"]
    if meetings and len(meetings) > max_meeting_rows:
        scroll_info = []
        if scroll_offset_m > 0:
            scroll_info.append(f"↑{scroll_offset_m}")
        below = len(meetings) - scroll_offset_m - max_meeting_rows
        if below > 0:
            scroll_info.append(f"↓{below}")
        if scroll_info:
            subtitle_parts.append(" ".join(scroll_info))
    if emails is not None:
        subtitle_parts.append("Tab/↑↓: scroll")
    elif meetings and len(meetings) > max_meeting_rows:
        subtitle_parts.append("↑↓: scroll")
    subtitle = "  |  ".join(subtitle_parts)

    meetings_border = f"bold {panel_border}" if active_panel == "meetings" and emails is not None else panel_border

    layout["meetings"].update(
        Panel(
            table,
            title=f"[bold]Today's Schedule — {date_str}[/bold]",
            subtitle=subtitle,
            border_style=meetings_border,
        )
    )

    # --- Emails panel ---
    if emails is not None:
        # Derive scroll offset to keep cursor visible
        if not emails or len(emails) <= max_email_rows:
            scroll_offset_e = 0
            cursor_emails = min(cursor_emails, max(0, len(emails) - 1))
        else:
            cursor_emails = min(cursor_emails, len(emails) - 1)
            scroll_offset_e = max(0, min(cursor_emails - max_email_rows // 2,
                                        len(emails) - max_email_rows))

        email_table = Table(expand=True, show_lines=False, border_style=panel_border)
        email_table.add_column("", width=2)
        email_table.add_column("From", width=30, no_wrap=True)
        email_table.add_column("Subject", min_width=20, no_wrap=True)
        email_table.add_column("Preview", style="dim", no_wrap=True)

        if not emails:
            email_table.add_row(
                "",
                "[dim]--[/dim]",
                "[dim italic]No unread emails[/dim italic]",
                "[dim]--[/dim]",
            )
        else:
            visible_emails = emails[scroll_offset_e:scroll_offset_e + max_email_rows]
            for i, email in enumerate(visible_emails):
                actual_idx = scroll_offset_e + i
                is_cursor = actual_idx == cursor_emails and active_panel == "emails"
                sender = email["from"]
                # Show just the name portion if available
                if "<" in sender:
                    sender = sender.split("<")[0].strip().strip('"')
                if is_cursor:
                    email_table.add_row(
                        "[bold bright_white]►[/bold bright_white]",
                        f"[bold]{sender}[/bold]",
                        email["subject"],
                        email["snippet"][:80],
                        style="on grey23",
                    )
                else:
                    email_table.add_row(
                        "",
                        f"[bold]{sender}[/bold]",
                        email["subject"],
                        email["snippet"][:80],
                    )

        # Build subtitle with scroll indicators
        sub_parts = [f"{len(emails)} unread"]
        if emails and len(emails) > max_email_rows:
            scroll_info = []
            if scroll_offset_e > 0:
                scroll_info.append(f"↑{scroll_offset_e}")
            below = len(emails) - scroll_offset_e - max_email_rows
            if below > 0:
                scroll_info.append(f"↓{below}")
            if scroll_info:
                sub_parts.append(" ".join(scroll_info))
        sub_parts.append("Tab/↑↓: scroll")
        email_subtitle = "  |  ".join(sub_parts)

        emails_border = f"bold {panel_border}" if active_panel == "emails" else panel_border

        layout["emails"].update(
            Panel(
                email_table,
                title="[bold]Recent Emails[/bold]",
                subtitle=email_subtitle,
                border_style=emails_border,
            )
        )

    return layout


def main():
    console = Console()
    console.print(
        "[bold magenta]Meeting Tracker[/bold magenta] - Connecting to Google Calendar...\n"
    )

    try:
        calendar_service, gmail_service = authenticate(console)
    except Exception as e:
        console.print(f"[bold red]Authentication failed:[/bold red] {e}")
        sys.exit(1)

    console.print("[green]Connected![/green] Loading meetings...\n")

    try:
        last_fetch = None
        meetings = []
        emails = []
        acknowledged = set()
        active_panel = "meetings"
        cursor_meetings = 0
        cursor_emails = 0
        last_rendered_minute = None

        with Live(console=console, auto_refresh=False, screen=True) as live:
            while True:
                now_ts = time.time()

                def fetch_data():
                    nonlocal meetings, emails, last_fetch
                    try:
                        meetings = get_todays_meetings(calendar_service)
                    except Exception:
                        if not meetings:
                            raise
                    try:
                        emails = get_recent_emails(gmail_service)
                    except Exception:
                        pass  # keep previous emails on failure
                    last_fetch = time.time()

                def handle_key(key):
                    """Handle a keypress. Returns True to force a redraw."""
                    nonlocal active_alert, active_panel, cursor_meetings, cursor_emails
                    if key == "\x12":  # Ctrl+R
                        fetch_data()
                        return True
                    if key in ("\r", "\n", " ") and active_alert is not None:
                        _event, event_id, threshold, _mins = active_alert
                        acknowledged.add((event_id, threshold))
                        active_alert = get_active_alert(meetings, acknowledged)
                    elif key == "TAB":
                        if emails is not None:
                            active_panel = "emails" if active_panel == "meetings" else "meetings"
                        return True
                    elif key == "UP":
                        if active_panel == "meetings":
                            cursor_meetings = max(0, cursor_meetings - 1)
                        else:
                            cursor_emails = max(0, cursor_emails - 1)
                        return True
                    elif key == "DOWN":
                        if active_panel == "meetings":
                            cursor_meetings = min(cursor_meetings + 1, max(0, len(meetings) - 1))
                        else:
                            cursor_emails = min(cursor_emails + 1, max(0, len(emails) - 1))
                        return True
                    elif key and key.isdigit() and key != "0":
                        idx = int(key) - 1
                        if 0 <= idx < len(meetings):
                            link = get_meeting_link(meetings[idx])
                            if link:
                                webbrowser.open(link)
                    return False

                if last_fetch is None or (now_ts - last_fetch) > REFRESH_INTERVAL:
                    fetch_data()

                active_alert = get_active_alert(meetings, acknowledged)

                # Poll for keypresses and redraw smartly:
                # - Alert active: redraw every 1s (flashing)
                # - No alert: poll keys in 0.5s ticks, redraw only when minute changes
                if active_alert:
                    key = check_keypress()
                    if key:
                        handle_key(key)

                    live.update(
                        build_display(meetings, active_alert, emails,
                                      active_panel, cursor_meetings, cursor_emails,
                                      console.size.height),
                        refresh=True
                    )
                    time.sleep(1)
                else:
                    # Sleep until the next minute boundary, polling keys every 0.5s
                    current_minute = datetime.datetime.now().minute
                    secs_to_next_min = 60 - datetime.datetime.now().second

                    if last_rendered_minute != current_minute:
                        live.update(
                            build_display(meetings, active_alert, emails,
                                          active_panel, cursor_meetings, cursor_emails,
                                          console.size.height),
                            refresh=True
                        )
                        last_rendered_minute = current_minute

                    deadline = time.time() + min(secs_to_next_min, 30)
                    while time.time() < deadline:
                        key = check_keypress()
                        if key:
                            refreshed = handle_key(key)
                            if refreshed:
                                last_rendered_minute = None  # force redraw
                                break
                            if get_active_alert(meetings, acknowledged):
                                break
                        # Break early if we've crossed into a new minute
                        if datetime.datetime.now().minute != current_minute:
                            break
                        # Break early if an alert should now fire
                        if get_active_alert(meetings, acknowledged):
                            break
                        time.sleep(0.5)

    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")


if __name__ == "__main__":
    main()
