# config/ — central, git-ignored settings

All sensitive or machine-specific values for the apps in this repo live here in
one place. **Nothing real in this folder is committed.** The `.gitignore` here
ignores everything except `README.md`, `.gitignore`, and `*.example.json`
templates — so any file you create with real values is automatically excluded
from git.

## How to set up

For each app, copy the `*.example.json` template to the real filename (drop the
`.example`) and fill in your values:

```powershell
cd config
Copy-Item credentials.example.json            credentials.json
Copy-Item meeting-notes-overlay.example.json  meeting-notes-overlay.json
```

The apps locate this `config/` folder automatically (Python apps resolve it
relative to their script; the .NET app walks up from its executable to the repo
root). If a config file is missing, each app falls back to safe defaults.

## Files

| File | Used by | What to put in it |
|------|---------|-------------------|
| `credentials.json` | MeetingTracker | Google OAuth **Desktop app** client JSON. Either paste the file you download from Google Cloud Console, or fill in `client_id` / `client_secret` in the template. |
| `token.json` | MeetingTracker | **Auto-generated** on first successful login — do not create by hand. Holds your OAuth access/refresh token. |
| `meeting-notes-overlay.json` | meeting-notes-overlay | `notesDirectories`: folders to scan for `.txt`/`.md` notes. `%USERPROFILE%` and other env vars are expanded. |

**ClaudePanes** needs nothing here — its layout files live in
`~/.config/claude-panes/` on your machine, not in this repo.

## Getting Google credentials (MeetingTracker)

1. Go to <https://console.cloud.google.com/> and create/select a project.
2. Enable the **Google Calendar API** and **Gmail API**.
3. Credentials → Create Credentials → OAuth client ID → **Desktop app**.
4. Download the JSON, save it here as `credentials.json`.
5. Run MeetingTracker; a browser opens for consent and `token.json` is written here.

## ⚠️ If a real secret was ever committed

Git-ignoring a file does **not** remove it from past commits. If you ever
committed `credentials.json` / `token.json`, rotate the secret (regenerate the
OAuth client secret in Google Cloud Console, delete `token.json`) and scrub
history before pushing.
