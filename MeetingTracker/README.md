# Meeting Tracker

A Python TUI (Terminal User Interface) application that connects to your Google Calendar and displays today's meetings in a live, auto-refreshing terminal dashboard.

## What's Implemented

### Live Clock
- Real-time clock displayed at the top of the terminal, updating every second
- Shows both the current time (12-hour format) and the full date

### Today's Meeting Schedule
- Fetches all events from your primary Google Calendar for the current day
- Meetings are listed in chronological order with four columns:

| Column | Description |
|---|---|
| **Status** | `Done`, `NOW`, `>> Next`, `Upcoming`, or `All Day` |
| **Time** | Start and end time of the meeting |
| **Meeting** | The event title from your calendar |
| **Countdown** | Time remaining until start, time left in meeting, or `Passed` |

### Status Indicators
- **Done** (dimmed) -- meeting has already ended
- **NOW** (green) -- meeting is currently in progress, shows minutes remaining
- **>> Next** (yellow) -- the very next upcoming meeting, with countdown
- **Upcoming** (dimmed) -- future meetings later in the day
- **All Day** (blue) -- all-day events

### Auto-Refresh
- The meeting list automatically re-fetches from Google Calendar every 5 minutes
- The clock and countdown timers update every second

### Progress Tracking
- A subtitle at the bottom of the schedule shows how many timed meetings have been completed (e.g., `3/7 completed`)

## Prerequisites

- Python 3.7+
- A Google account with Google Calendar
- A Google Cloud project with the Calendar API enabled

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `google-api-python-client` -- Google Calendar API client
- `google-auth-oauthlib` -- OAuth 2.0 authentication flow
- `google-auth-httplib2` -- HTTP transport for authentication
- `rich` -- terminal UI rendering (clock, tables, panels, colors)

### 2. Set Up Google Calendar API Credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable the **Google Calendar API**:
   - Navigate to **APIs & Services > Library**
   - Search for "Google Calendar API" and click **Enable**
4. Create OAuth 2.0 credentials:
   - Go to **APIs & Services > Credentials**
   - Click **Create Credentials > OAuth client ID**
   - If prompted, configure the OAuth consent screen first (choose "External", fill in the app name, and add your email)
   - Select **Desktop app** as the application type
   - Click **Create**
5. Download the credentials JSON file
6. Rename it to `credentials.json` and place it in the `MeetingTracker` folder (same directory as `meeting_tracker.py`)

### 3. Run the Application

```bash
python meeting_tracker.py
```

On the **first run**, a browser window will open asking you to log in to your Google account and grant calendar read access. After authorizing, a `token.json` file is saved locally so you won't need to log in again.

### 4. Exit

Press `Ctrl+C` to quit the application.

## Project Structure

```
MeetingTracker/
  meeting_tracker.py   # Main application
  requirements.txt     # Python dependencies
  README.md            # This file
  credentials.json     # Your Google OAuth credentials (you provide this)
  token.json           # Auto-generated after first login (do not share)
```

## Notes

- The app only requests **read-only** access to your calendar (`calendar.readonly` scope)
- `credentials.json` and `token.json` contain sensitive data -- do not commit them to version control
- If your token expires or you revoke access, delete `token.json` and re-run the app to re-authenticate
