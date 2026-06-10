# meeting-notes-overlay

**Stack:** .NET 10, WinUI 3, Windows App SDK 1.8, CommunityToolkit MarkdownTextBlock
**Purpose:** Always-on-top overlay hidden from screen capture (Teams/Slack/Zoom/Meet)
**Core API:** `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` via P/Invoke
**Features:** File browser (TODOs dir), .txt/.md support, font/opacity controls, always-on-top toggle
**Notes dir:** `%USERPROFILE%\TODOs` (Script Demo files + daily notes; configurable via `NotesDirectories` in `MainWindow.xaml.cs`)

Unpackaged WinUI 3 app (`WindowsPackageType=None`).
