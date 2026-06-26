using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.Storage.Pickers;
using WinRT.Interop;

namespace MeetingNotesOverlay;

public sealed partial class MainWindow : Window
{
    // Folders scanned for .txt/.md notes. Override via config/meeting-notes-overlay.json
    // at the repo root (see config/README.md); falls back to these defaults otherwise.
    private static readonly string[] NotesDirectories = LoadNotesDirectories();

    private static string[] DefaultNotesDirectories() =>
    [
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "TODOs"),
        Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
    ];

    private static string[] LoadNotesDirectories()
    {
        try
        {
            var configPath = FindRepoConfigFile("meeting-notes-overlay.json");
            if (configPath is not null)
            {
                using var stream = File.OpenRead(configPath);
                using var doc = JsonDocument.Parse(stream);
                if (doc.RootElement.TryGetProperty("notesDirectories", out var arr) &&
                    arr.ValueKind == JsonValueKind.Array)
                {
                    var dirs = arr.EnumerateArray()
                        .Select(e => e.GetString())
                        .Where(s => !string.IsNullOrWhiteSpace(s))
                        .Select(s => Environment.ExpandEnvironmentVariables(s!))
                        .ToArray();
                    if (dirs.Length > 0)
                        return dirs;
                }
            }
        }
        catch
        {
            // Missing or malformed config — fall back to defaults below.
        }
        return DefaultNotesDirectories();
    }

    // Walks up from the running app's directory to find <repo-root>/config/<fileName>.
    private static string? FindRepoConfigFile(string fileName)
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "config", fileName);
            if (File.Exists(candidate))
                return candidate;
        }
        return null;
    }

    private readonly nint _hwnd;
    private readonly AppWindow _appWindow;

    private double _fontSize = 14;
    private double _opacity = 0.92;
    private bool _isCaptureHidden;
    private bool _isAlwaysOnTop = true;
    private string? _currentFilePath;
    private List<FileInfo> _allFiles = [];
    private List<string> _extraDirectories = [];

    public MainWindow()
    {
        InitializeComponent();

        // Get window handle and AppWindow
        _hwnd = WindowNative.GetWindowHandle(this);
        var windowId = Win32Interop.GetWindowIdFromWindow(_hwnd);
        _appWindow = AppWindow.GetFromWindowId(windowId);

        // Configure window
        Title = "Notes Overlay";
        _appWindow.Resize(new Windows.Graphics.SizeInt32(560, 700));

        // Always on top
        SetAlwaysOnTop(true);

        // Apply capture exclusion
        ApplyCaptureExclusion();

        // Set initial opacity
        SetWindowOpacity(_opacity);

        // Load files and show welcome
        PopulateFileList();
        ShowWelcome();
    }

    // ── Capture Exclusion ──────────────────────────────────────────

    private void ApplyCaptureExclusion()
    {
        _isCaptureHidden = NativeMethods.SetWindowDisplayAffinity(
            _hwnd, NativeMethods.WDA_EXCLUDEFROMCAPTURE);
        UpdateStatus();
    }

    private void ToggleCaptureExclusion()
    {
        var newAffinity = _isCaptureHidden
            ? NativeMethods.WDA_NONE
            : NativeMethods.WDA_EXCLUDEFROMCAPTURE;

        if (NativeMethods.SetWindowDisplayAffinity(_hwnd, newAffinity))
        {
            _isCaptureHidden = !_isCaptureHidden;
            CaptureIcon.Glyph = _isCaptureHidden ? "\uED1A" : "\uE7B3";
            UpdateStatus();
        }
    }

    // ── Always On Top ──────────────────────────────────────────────

    private void SetAlwaysOnTop(bool onTop)
    {
        _isAlwaysOnTop = onTop;
        if (_appWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.IsAlwaysOnTop = onTop;
        }
    }

    // ── Opacity ────────────────────────────────────────────────────

    private void SetWindowOpacity(double opacity)
    {
        _opacity = Math.Clamp(opacity, 0.2, 1.0);
        NativeMethods.SetWindowOpacity(_hwnd, (byte)(_opacity * 255));
        OpacityLabel.Text = $"{(int)(_opacity * 100)}%";
    }

    // ── File Management ────────────────────────────────────────────

    private void PopulateFileList()
    {
        _allFiles = NotesDirectories.Concat(_extraDirectories)
            .Where(Directory.Exists)
            .SelectMany(dir => new DirectoryInfo(dir).GetFiles())
            .Where(f => f.Extension.Equals(".txt", StringComparison.OrdinalIgnoreCase)
                     || f.Extension.Equals(".md", StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(f => f.LastWriteTime)
            .ToList();

        FilterFiles();
    }

    private void FilterFiles()
    {
        var filter = FilterBox?.Text?.ToLowerInvariant() ?? "";
        FileListView.Items.Clear();

        foreach (var file in _allFiles)
        {
            if (string.IsNullOrEmpty(filter) || file.Name.Contains(filter, StringComparison.OrdinalIgnoreCase))
            {
                FileListView.Items.Add(Path.GetFileNameWithoutExtension(file.Name));
            }
        }
    }

    private void LoadFile(string filePath)
    {
        try
        {
            var content = File.ReadAllText(filePath);
            _currentFilePath = filePath;

            var isMd = Path.GetExtension(filePath).Equals(".md", StringComparison.OrdinalIgnoreCase);
            var markdown = isMd ? content : ConvertPlainTextToMarkdown(content);

            MarkdownContent.Text = markdown;
            UpdateStatus();
        }
        catch (Exception ex)
        {
            UpdateStatus($"Error: {ex.Message}");
        }
    }

    private async void OpenFile()
    {
        var picker = new FileOpenPicker();
        InitializeWithWindow.Initialize(picker, _hwnd);

        picker.SuggestedStartLocation = PickerLocationId.DocumentsLibrary;
        picker.FileTypeFilter.Add(".txt");
        picker.FileTypeFilter.Add(".md");

        var file = await picker.PickSingleFileAsync();
        if (file != null)
        {
            LoadFile(file.Path);
        }
    }

    private async void OpenFolderAsync()
    {
        var picker = new FolderPicker();
        InitializeWithWindow.Initialize(picker, _hwnd);

        picker.SuggestedStartLocation = PickerLocationId.DocumentsLibrary;
        picker.FileTypeFilter.Add("*");

        var folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;

        if (!_extraDirectories.Contains(folder.Path, StringComparer.OrdinalIgnoreCase))
            _extraDirectories.Add(folder.Path);

        PopulateFileList();
        FileSplitView.IsPaneOpen = true;

        var count = _allFiles.Count(f =>
            string.Equals(f.DirectoryName, folder.Path, StringComparison.OrdinalIgnoreCase));
        UpdateStatus($"Added {folder.Path} ({count} notes)");
    }

    private void ReloadCurrentFile()
    {
        if (_currentFilePath != null)
            LoadFile(_currentFilePath);
    }

    // ── Plain Text → Markdown Conversion ───────────────────────────

    private static string ConvertPlainTextToMarkdown(string text)
    {
        var lines = text.Split('\n');
        var result = new StringBuilder();

        for (var i = 0; i < lines.Length; i++)
        {
            var line = lines[i].TrimEnd('\r');
            var trimmed = line.Trim();

            // Detect section headers: short standalone lines ending with ':'
            // that are not bullets, URLs, or timestamps
            if (trimmed.Length > 1
                && trimmed.EndsWith(':')
                && trimmed.Length < 60
                && !trimmed.StartsWith('-')
                && !trimmed.StartsWith('*')
                && !trimmed.StartsWith('+')
                && !Regex.IsMatch(trimmed, @"^(https?://|\d{1,2}[:/]\d{2})"))
            {
                result.AppendLine();
                result.AppendLine($"## {trimmed.TrimEnd(':')}");
            }
            // Convert * bullets to - bullets (Markdig prefers -)
            else if (trimmed.StartsWith("* "))
            {
                result.AppendLine($"- {trimmed[2..]}");
            }
            else
            {
                result.AppendLine(line);
            }
        }

        return result.ToString();
    }

    // ── Font Size ──────────────────────────────────────────────────

    private void ChangeFontSize(int delta)
    {
        var newSize = _fontSize + delta;
        if (newSize is >= 8 and <= 28)
        {
            _fontSize = newSize;
            MarkdownContent.FontSize = newSize;
            FontSizeLabel.Text = newSize.ToString();
        }
    }

    // ── Status Bar ─────────────────────────────────────────────────

    private void UpdateStatus(string? message = null)
    {
        if (message != null)
        {
            StatusBar.Text = message;
            StatusBar.Foreground = new SolidColorBrush(Colors.Gray);
            return;
        }

        var captureText = _isCaptureHidden ? "Hidden from capture" : "VISIBLE to capture";
        var fileText = _currentFilePath != null ? $" | {Path.GetFileName(_currentFilePath)}" : "";

        StatusBar.Text = $"{captureText}{fileText}";
        StatusBar.Foreground = new SolidColorBrush(
            _isCaptureHidden
                ? ColorHelper.FromArgb(255, 76, 175, 80)
                : ColorHelper.FromArgb(255, 244, 67, 54));
        StatusBar.Opacity = 1.0;
    }

    // ── Welcome Content ────────────────────────────────────────────

    private void ShowWelcome()
    {
        MarkdownContent.Text = """
            # Notes Overlay

            This window is **hidden from screen capture**.

            ## Quick Start
            - Click the **hamburger menu** or press **Ctrl+L** to open the file list
            - Click **Open** or press **Ctrl+O** to open a file
            - Click the **folder icon** or press **Ctrl+Shift+O** to browse notes in any folder
            - **Ctrl + / -** to change font size
            - Press **Ctrl+R** to reload the current file

            ## Toolbar Controls
            - **A- / A+** — adjust font size
            - **Opacity buttons** — adjust window transparency
            - **Pin** — toggle always-on-top
            - **Eye** — toggle capture exclusion on/off

            ## Status Bar
            The bottom bar shows whether the window is hidden from screen capture.
            Green = hidden, Red = visible.
            """;
    }

    // ── Event Handlers ─────────────────────────────────────────────

    private void ToggleFilePanel_Click(object sender, RoutedEventArgs e)
        => FileSplitView.IsPaneOpen = !FileSplitView.IsPaneOpen;

    private void OpenFile_Click(object sender, RoutedEventArgs e)
        => OpenFile();

    private void OpenFolder_Click(object sender, RoutedEventArgs e)
        => OpenFolderAsync();

    private void Reload_Click(object sender, RoutedEventArgs e)
        => ReloadCurrentFile();

    private void FontDecrease_Click(object sender, RoutedEventArgs e)
        => ChangeFontSize(-1);

    private void FontIncrease_Click(object sender, RoutedEventArgs e)
        => ChangeFontSize(1);

    private void OpacityDecrease_Click(object sender, RoutedEventArgs e)
        => SetWindowOpacity(_opacity - 0.05);

    private void OpacityIncrease_Click(object sender, RoutedEventArgs e)
        => SetWindowOpacity(_opacity + 0.05);

    private void TogglePin_Click(object sender, RoutedEventArgs e)
    {
        _isAlwaysOnTop = !_isAlwaysOnTop;
        SetAlwaysOnTop(_isAlwaysOnTop);

        if (PinButton.Content is Microsoft.UI.Xaml.Controls.FontIcon icon)
        {
            icon.Glyph = _isAlwaysOnTop ? "\uE718" : "\uE77A";
        }
    }

    private void ToggleCapture_Click(object sender, RoutedEventArgs e)
        => ToggleCaptureExclusion();

    private void FilterBox_TextChanged(object sender, Microsoft.UI.Xaml.Controls.TextChangedEventArgs e)
        => FilterFiles();

    private void FileListView_SelectionChanged(object sender, Microsoft.UI.Xaml.Controls.SelectionChangedEventArgs e)
    {
        if (FileListView.SelectedItem is not string selectedName) return;

        var file = _allFiles.FirstOrDefault(f =>
            Path.GetFileNameWithoutExtension(f.Name) == selectedName);

        if (file != null)
            LoadFile(file.FullName);
    }
}
