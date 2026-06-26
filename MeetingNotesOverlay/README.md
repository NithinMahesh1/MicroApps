# Meeting Notes Overlay

A WinUI 3 desktop app that displays your notes as an always-on-top overlay that is **invisible to screen sharing**. Built for presenting demos in Microsoft Teams, Slack, Google Meet, Zoom, etc. while keeping your talking points visible only to you.

## How It Works

The app uses the Windows API [`SetWindowDisplayAffinity`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity) with the `WDA_EXCLUDEFROMCAPTURE` flag (`0x00000011`). This tells the Desktop Window Manager (DWM) to:

- **Render the window normally** on your physical display
- **Exclude the window entirely** from the capture buffer that screen sharing apps read

All screen sharing apps (Teams, Slack, Google Meet, Zoom, Discord, OBS) use standard Windows capture APIs (DXGI Desktop Duplication, BitBlt, PrintWindow). Since `WDA_EXCLUDEFROMCAPTURE` operates at the OS level, the overlay is invisible to **all** of them — not just one specific app.

### Key Technical Details

| File | Purpose |
|------|---------|
| `NativeMethods.cs` | P/Invoke declarations for `SetWindowDisplayAffinity` (capture exclusion), `SetLayeredWindowAttributes` (opacity), and `SetWindowLongW` (layered window style) |
| `MainWindow.xaml` | WinUI 3 UI — toolbar, SplitView file browser, `MarkdownTextBlock` content viewer, status bar |
| `MainWindow.xaml.cs` | Window logic — capture exclusion, always-on-top via `OverlappedPresenter`, file loading, plain-text-to-markdown conversion |
| `App.xaml` | Application entry point with WinUI dark theme (`XamlControlsResources`) |

### Plain Text Intelligence

`.txt` files are automatically converted to markdown before rendering:
- Lines ending with `:` that are short and standalone (e.g., `Swagger:`, `SQL:`) become `## headers`
- `* bullet` items are normalized to `- bullet` for consistent rendering
- Everything else passes through as-is

This means your existing notes from `%USERPROFILE%\TODOs` render with proper formatting without any changes.

## Prerequisites

- Windows 10 version 2004+ or Windows 11
- .NET 10 SDK
- Windows App SDK (pulled via NuGet automatically)

## How to Run

```bash
cd MeetingNotesOverlay
dotnet run
```

Or build and run the exe directly:

```bash
dotnet build -c Release
.\bin\Release\net10.0-windows10.0.22621.0\MeetingNotesOverlay.exe
```

## Controls

| Control | Shortcut | Description |
|---------|----------|-------------|
| Hamburger menu | `Ctrl+L` | Toggle the file browser panel |
| Open | `Ctrl+O` | Pick a folder; its `.md`/`.txt` notes are added to the file browser |
| Reload | `Ctrl+R` | Reload the current file |
| A- / A+ | `Ctrl+-` / `Ctrl++` | Decrease / increase font size (range: 8–28) |
| Opacity buttons | — | Adjust window transparency (20%–100%) |
| Pin | — | Toggle always-on-top |
| Eye | — | Toggle capture exclusion on/off |

## How to Test That Capture Exclusion Works

### Quick Test (Solo)

1. Run the app — confirm the status bar shows **green "Hidden from capture"**
2. Open **Snipping Tool** (Win+Shift+S) and take a screenshot of your full screen
3. The overlay window should be **completely invisible** in the screenshot
4. Everything behind the overlay (desktop, other windows) should show through as if the overlay isn't there

### Test with Screen Recording

1. Open **Xbox Game Bar** (Win+G) or **OBS** and start a screen recording
2. Position the overlay over some content (e.g., a browser window)
3. Stop the recording and watch the playback
4. The overlay should be invisible in the recording

### Test with Teams/Slack/Meet

1. Start a meeting with a coworker or yourself (Teams lets you join from two devices)
2. Share your **entire desktop** (not a specific window)
3. Have the overlay open with notes visible on your screen
4. On the other device/participant view — the overlay should not appear
5. Toggle capture exclusion off (eye button) — the overlay should now appear to the other participant

### If the Status Bar Shows Red "VISIBLE to capture"

This means `SetWindowDisplayAffinity` failed. Possible causes:
- Windows version too old (need 10 version 2004 / build 19041+)
- Another process has a conflicting display affinity on the window
- Remote desktop session (some RDP implementations don't support this flag)

## Tech Stack

- .NET 10 / C#
- WinUI 3 (Windows App SDK 1.8)
- CommunityToolkit.WinUI `MarkdownTextBlock` for markdown rendering
- Win32 P/Invoke for `SetWindowDisplayAffinity` and window opacity
