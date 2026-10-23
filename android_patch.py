#!/usr/bin/env python3
"""Android patch for UABEA Next. Run from the repo root (the CI workflow does this).

It adds an in-app file picker, in-app dialogs, Android storage permission,
and packs classdata.tpk into the APK. It stops with an error if any spot it
needs to change is not found exactly once, so it can never half-apply silently.
"""
import os
import sys


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def replace_once(path, old, new):
    text = read(path)
    count = text.count(old)
    if count != 1:
        sys.exit(f"PATCH ERROR: expected 1 match in {path}, found {count} for:\n{old}")
    write(path, text.replace(old, new))


def replace_all(path, old, new, expected):
    text = read(path)
    count = text.count(old)
    if count != expected:
        sys.exit(f"PATCH ERROR: expected {expected} matches in {path}, found {count} for:\n{old}")
    write(path, text.replace(old, new))


# ---------------------------------------------------------------- new shared files

write("UABEANext4/AppPaths.cs", r'''using System;

namespace UABEANext4;

public static class AppPaths
{
    // folder where classdata.tpk, config.json and plugins live
    // desktop: next to the exe. android: the app's private files folder (set in MainActivity)
    public static string BaseDir { get; set; } = AppDomain.CurrentDomain.BaseDirectory;
}
''')

write("UABEANext4/Util/OverlayHost.cs", r'''using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Styling;

namespace UABEANext4.Util;

// a layer on top of the main view where dialogs and the file picker
// are shown on platforms that have no real windows (android)
public static class OverlayHost
{
    private static Panel? _layer;

    public static bool IsAvailable => _layer != null;

    public static void Init(Panel layer)
    {
        _layer = layer;
        layer.IsVisible = false;
        layer.Background = new SolidColorBrush(Color.FromArgb(160, 0, 0, 0));
    }

    public static void Show(Control content)
    {
        if (_layer == null)
            return;

        _layer.Children.Add(content);
        _layer.IsVisible = true;
    }

    public static void Hide(Control content)
    {
        if (_layer == null)
            return;

        _layer.Children.Remove(content);
        if (_layer.Children.Count == 0)
            _layer.IsVisible = false;
    }

    public static TopLevel? GetTopLevel()
    {
        return _layer == null ? null : TopLevel.GetTopLevel(_layer);
    }

    public static bool IsDark()
    {
        return Application.Current?.ActualThemeVariant == ThemeVariant.Dark;
    }
}
''')

write("UABEANext4/Util/FileDialogUtils.cs", r'''using Avalonia.Platform.Storage;
using System.Collections.Generic;
using System.Linq;

namespace UABEANext4.Util;

public static class FileDialogUtils
{
    public static string[] GetOpenFileDialogFiles(IReadOnlyList<IStorageFile> files)
    {
        return files.Select(sf => sf.TryGetLocalPath()).Where(p => p != null).ToArray()!;
    }

    public static string[] GetOpenFileDialogFiles(string[] files)
    {
        return files;
    }

    public static string[] GetOpenFolderDialogFolders(IReadOnlyList<IStorageFolder> folders)
    {
        return folders.Select(sf => sf.TryGetLocalPath()).Where(p => p != null).ToArray()!;
    }

    public static string[] GetOpenFolderDialogFolders(string[] folders)
    {
        return folders;
    }

    public static string? GetSaveFileDialogFile(IStorageFile? file)
    {
        return file?.TryGetLocalPath();
    }

    public static string? GetSaveFileDialogFile(PickedSaveFile? file)
    {
        return file?.FullPath;
    }
}
''')

write("UABEANext4/Util/AppPicker.cs", r'''using Avalonia.Platform.Storage;
using System;
using System.IO;
using System.Threading.Tasks;

namespace UABEANext4.Util;

public sealed class PickedSaveFile
{
    public string FullPath { get; }

    public PickedSaveFile(string fullPath)
    {
        FullPath = fullPath;
    }

    public Task<Stream> OpenWriteAsync()
    {
        Stream stream = new FileStream(FullPath, FileMode.Create, FileAccess.Write, FileShare.None);
        return Task.FromResult(stream);
    }
}

// one place for all "pick a file / folder / save location" calls.
// desktop: uses the normal system dialogs. android: uses our own in-app browser,
// because the app needs real file paths (bundles sit next to .resS files, etc.)
public sealed class AppPicker
{
    private static bool UseInApp => OperatingSystem.IsAndroid() && OverlayHost.IsAvailable;

    public async Task<string[]> OpenFilePickerAsync(FilePickerOpenOptions options)
    {
        if (UseInApp)
        {
            var picked = await InAppFilePicker.ShowAsync(
                InAppFilePicker.PickMode.Files, options.Title ?? "Open file", options.AllowMultiple, "");
            return picked ?? Array.Empty<string>();
        }

        var provider = StorageService.GetRealStorageProvider();
        if (provider is null)
            return Array.Empty<string>();

        var result = await provider.OpenFilePickerAsync(options);
        return FileDialogUtils.GetOpenFileDialogFiles(result);
    }

    public async Task<string[]> OpenFolderPickerAsync(FolderPickerOpenOptions options)
    {
        if (UseInApp)
        {
            var picked = await InAppFilePicker.ShowAsync(
                InAppFilePicker.PickMode.Folder, options.Title ?? "Choose folder", false, "");
            return picked ?? Array.Empty<string>();
        }

        var provider = StorageService.GetRealStorageProvider();
        if (provider is null)
            return Array.Empty<string>();

        var result = await provider.OpenFolderPickerAsync(options);
        return FileDialogUtils.GetOpenFolderDialogFolders(result);
    }

    public async Task<PickedSaveFile?> SaveFilePickerAsync(FilePickerSaveOptions options)
    {
        if (UseInApp)
        {
            var picked = await InAppFilePicker.ShowAsync(
                InAppFilePicker.PickMode.Save, options.Title ?? "Save file", false, options.SuggestedFileName ?? "");
            if (picked == null || picked.Length == 0)
                return null;

            return new PickedSaveFile(picked[0]);
        }

        var provider = StorageService.GetRealStorageProvider();
        if (provider is null)
            return null;

        var file = await provider.SaveFilePickerAsync(options);
        var path = FileDialogUtils.GetSaveFileDialogFile(file);
        return path == null ? null : new PickedSaveFile(path);
    }
}
''')

write("UABEANext4/Util/InAppFilePicker.cs", r'''using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace UABEANext4.Util;

// a simple touch friendly file browser that works with real file paths
public sealed class InAppFilePicker
{
    public enum PickMode
    {
        Files,
        Folder,
        Save
    }

    private sealed class Entry
    {
        public string Name = "";
        public string FullPath = "";
        public bool IsDir;
        public long Size;

        public override string ToString()
        {
            if (IsDir)
                return "\U0001F4C1  " + Name;

            return "\U0001F4C4  " + Name + "   (" + FormatSize(Size) + ")";
        }
    }

    private static string _lastDir = "";

    private readonly PickMode _mode;
    private readonly bool _multiple;
    private readonly TaskCompletionSource<string[]?> _tcs = new();
    private readonly Border _frame;
    private readonly TextBlock _pathText;
    private readonly ListBox _list;
    private readonly TextBox _nameBox;
    private readonly Button _okButton;
    private string _currentDir = "/";
    private bool _updating;

    public static async Task<string[]?> ShowAsync(PickMode mode, string title, bool multiple, string suggestedName)
    {
        var picker = new InAppFilePicker(mode, title, multiple, suggestedName);
        OverlayHost.Show(picker._frame);
        try
        {
            return await picker._tcs.Task;
        }
        finally
        {
            OverlayHost.Hide(picker._frame);
        }
    }

    private InAppFilePicker(PickMode mode, string title, bool multiple, string suggestedName)
    {
        _mode = mode;
        _multiple = multiple && mode == PickMode.Files;

        var titleText = new TextBlock
        {
            Text = title,
            FontWeight = FontWeight.Bold,
            FontSize = 18,
            VerticalAlignment = VerticalAlignment.Center
        };
        var closeButton = new Button { Content = "✕", Padding = new Thickness(14, 8) };
        closeButton.Click += (_, _) => Complete(null);

        var header = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Grid.SetColumn(closeButton, 1);
        header.Children.Add(titleText);
        header.Children.Add(closeButton);

        var shortcuts = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
        AddShortcut(shortcuts, "⬆ Up", GoUp);
        foreach (var (label, path) in GetShortcuts())
        {
            var target = path;
            AddShortcut(shortcuts, label, () => NavigateTo(target));
        }

        _pathText = new TextBlock
        {
            Margin = new Thickness(0, 8),
            TextWrapping = TextWrapping.Wrap,
            FontSize = 13,
            Opacity = 0.85
        };

        _list = new ListBox
        {
            SelectionMode = _multiple
                ? (SelectionMode.Multiple | SelectionMode.Toggle)
                : SelectionMode.Single
        };
        _list.SelectionChanged += OnSelectionChanged;
        var listBorder = new Border
        {
            BorderBrush = Brushes.Gray,
            BorderThickness = new Thickness(1),
            Child = _list
        };

        _nameBox = new TextBox
        {
            Text = suggestedName,
            Watermark = "File name",
            Margin = new Thickness(0, 8, 0, 0),
            IsVisible = mode == PickMode.Save
        };

        var cancelButton = new Button
        {
            Content = "Cancel",
            Padding = new Thickness(18, 10),
            Margin = new Thickness(0, 0, 8, 0)
        };
        cancelButton.Click += (_, _) => Complete(null);

        _okButton = new Button { Padding = new Thickness(18, 10) };
        _okButton.Click += (_, _) => OnOk();

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 8, 0, 0)
        };
        buttons.Children.Add(cancelButton);
        buttons.Children.Add(_okButton);

        var grid = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,*,Auto,Auto") };
        void Place(Control control, int row)
        {
            Grid.SetRow(control, row);
            grid.Children.Add(control);
        }
        Place(header, 0);
        Place(shortcuts, 1);
        Place(_pathText, 2);
        Place(listBorder, 3);
        Place(_nameBox, 4);
        Place(buttons, 5);

        var dark = OverlayHost.IsDark();
        _frame = new Border
        {
            Background = new SolidColorBrush(dark ? Color.Parse("#1E1E1E") : Color.Parse("#F3F3F3")),
            BorderBrush = Brushes.Gray,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(12),
            Margin = new Thickness(16),
            Child = grid
        };

        var start = _lastDir;
        if (string.IsNullOrEmpty(start) || !Directory.Exists(start))
            start = FindStartDir();

        NavigateTo(start);
        UpdateOk();
    }

    private static void AddShortcut(Panel panel, string label, Action action)
    {
        var button = new Button
        {
            Content = label,
            Padding = new Thickness(12, 8),
            Margin = new Thickness(0, 0, 6, 6)
        };
        button.Click += (_, _) => action();
        panel.Children.Add(button);
    }

    private static string FindStartDir()
    {
        foreach (var candidate in new[] { "/storage/emulated/0", "/sdcard", "/storage" })
        {
            if (Directory.Exists(candidate))
                return candidate;
        }

        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return !string.IsNullOrEmpty(home) && Directory.Exists(home) ? home : "/";
    }

    private static List<(string Label, string Path)> GetShortcuts()
    {
        var list = new List<(string Label, string Path)>();
        if (Directory.Exists("/storage/emulated/0"))
            list.Add(("Storage", "/storage/emulated/0"));
        if (Directory.Exists("/storage/emulated/0/Download"))
            list.Add(("Download", "/storage/emulated/0/Download"));

        try
        {
            if (Directory.Exists("/storage"))
            {
                foreach (var dir in Directory.GetDirectories("/storage"))
                {
                    var name = System.IO.Path.GetFileName(dir);
                    if (name is "emulated" or "self")
                        continue;

                    list.Add(("SD " + name, dir));
                }
            }
        }
        catch
        {
            // ignore, just no sd card shortcuts
        }

        if (list.Count == 0)
            list.Add(("Root", "/"));

        return list;
    }

    private void GoUp()
    {
        var parent = Directory.GetParent(_currentDir);
        if (parent != null)
            NavigateTo(parent.FullName);
    }

    private void NavigateTo(string dir)
    {
        var entries = new List<Entry>();
        try
        {
            var info = new DirectoryInfo(dir);
            foreach (var d in info.EnumerateDirectories().OrderBy(x => x.Name, StringComparer.OrdinalIgnoreCase))
            {
                entries.Add(new Entry { Name = d.Name, FullPath = d.FullName, IsDir = true });
            }
            foreach (var f in info.EnumerateFiles().OrderBy(x => x.Name, StringComparer.OrdinalIgnoreCase))
            {
                long size = 0;
                try
                {
                    size = f.Length;
                }
                catch
                {
                    // ignore
                }
                entries.Add(new Entry { Name = f.Name, FullPath = f.FullName, IsDir = false, Size = size });
            }
        }
        catch (Exception ex)
        {
            _pathText.Text = dir + "\n" + ex.Message +
                "\nIf this says access denied: open Android Settings > Apps > UABEA Next > " +
                "Permissions > Files and media (or 'All files access') and allow it.";
            return;
        }

        _currentDir = dir;
        _lastDir = dir;
        _pathText.Text = dir;

        _updating = true;
        _list.ItemsSource = entries;
        _updating = false;
        UpdateOk();
    }

    private void OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (_updating)
            return;

        foreach (var added in e.AddedItems)
        {
            if (added is Entry entry && entry.IsDir)
            {
                var target = entry.FullPath;
                Dispatcher.UIThread.Post(() => NavigateTo(target));
                return;
            }
        }

        if (_mode == PickMode.Save && _list.SelectedItem is Entry file && !file.IsDir)
            _nameBox.Text = file.Name;

        UpdateOk();
    }

    private int CountSelectedFiles()
    {
        var items = _list.SelectedItems;
        if (items == null)
            return 0;

        return items.OfType<Entry>().Count(x => !x.IsDir);
    }

    private void UpdateOk()
    {
        if (_mode == PickMode.Folder)
        {
            _okButton.Content = "Use this folder";
            _okButton.IsEnabled = true;
        }
        else if (_mode == PickMode.Save)
        {
            _okButton.Content = "Save here";
            _okButton.IsEnabled = true;
        }
        else
        {
            var count = CountSelectedFiles();
            _okButton.Content = "Open (" + count + ")";
            _okButton.IsEnabled = count > 0;
        }
    }

    private void OnOk()
    {
        if (_mode == PickMode.Folder)
        {
            Complete(new[] { _currentDir });
        }
        else if (_mode == PickMode.Save)
        {
            var name = _nameBox.Text?.Trim();
            if (string.IsNullOrEmpty(name))
                return;

            Complete(new[] { System.IO.Path.Combine(_currentDir, name) });
        }
        else
        {
            var files = _list.SelectedItems?.OfType<Entry>()
                .Where(x => !x.IsDir)
                .Select(x => x.FullPath)
                .ToArray();

            if (files == null || files.Length == 0)
                return;

            Complete(files);
        }
    }

    private void Complete(string[]? result)
    {
        _tcs.TrySetResult(result);
    }

    private static string FormatSize(long bytes)
    {
        string[] units = { "B", "KB", "MB", "GB" };
        double size = bytes;
        var unit = 0;
        while (size >= 1024 && unit < units.Length - 1)
        {
            size /= 1024;
            unit++;
        }
        return size.ToString(unit == 0 ? "0" : "0.#") + " " + units[unit];
    }
}
''')

write("UABEANext4/Services/OverlayDialogService.cs", r'''using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using System;
using System.Threading.Tasks;
using UABEANext4.Interfaces;
using UABEANext4.Util;

namespace UABEANext4.Services;

// dialog service for platforms without real windows (android):
// dialogs are shown on top of the main view instead
public class OverlayDialogService(ViewLocator viewLocator) : IDialogService
{
    public async Task ShowDialog(IDialogAware viewModel)
    {
        var tcs = new TaskCompletionSource<bool>();
        var frame = BuildFrame(viewModel, () => tcs.TrySetResult(true));
        OverlayHost.Show(frame);
        try
        {
            await tcs.Task;
        }
        finally
        {
            OverlayHost.Hide(frame);
        }
    }

    public void Show(IDialogAware viewModel)
    {
        _ = ShowDialog(viewModel);
    }

    public void Show<TResult>(IDialogAware<TResult> viewModel)
    {
        _ = ShowDialog<TResult>(viewModel);
    }

    public async Task<TResult?> ShowDialog<TResult>(IDialogAware<TResult> viewModel)
    {
        var tcs = new TaskCompletionSource<TResult?>();
        void handler(TResult? result) => tcs.TrySetResult(result);

        viewModel.RequestClose += handler;
        var frame = BuildFrame(viewModel, () => tcs.TrySetResult(default));
        OverlayHost.Show(frame);
        try
        {
            return await tcs.Task;
        }
        finally
        {
            viewModel.RequestClose -= handler;
            OverlayHost.Hide(frame);
        }
    }

    private Control BuildFrame(IDialogAware viewModel, Action onClose)
    {
        var view = viewLocator.Build(viewModel);
        view.DataContext = viewModel;

        var titleText = new TextBlock
        {
            Text = viewModel.Title,
            FontWeight = FontWeight.Bold,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(4, 0)
        };
        var closeButton = new Button { Content = "✕", Padding = new Thickness(14, 8) };
        closeButton.Click += (_, _) => onClose();

        var header = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("*,Auto"),
            Margin = new Thickness(0, 0, 0, 6)
        };
        Grid.SetColumn(closeButton, 1);
        header.Children.Add(titleText);
        header.Children.Add(closeButton);

        var panel = new DockPanel();
        DockPanel.SetDock(header, Avalonia.Controls.Dock.Top);
        panel.Children.Add(header);
        panel.Children.Add(view);

        var dark = OverlayHost.IsDark();
        var frame = new Border
        {
            Background = new SolidColorBrush(dark ? Color.Parse("#1E1E1E") : Color.Parse("#F3F3F3")),
            BorderBrush = Brushes.Gray,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(10),
            Margin = new Thickness(16),
            Child = panel
        };

        if (viewModel.Width <= 500)
        {
            frame.Width = viewModel.Width + 30;
            frame.HorizontalAlignment = HorizontalAlignment.Center;
        }
        else
        {
            frame.HorizontalAlignment = HorizontalAlignment.Stretch;
        }

        if (viewModel.Height <= 300)
        {
            frame.Height = viewModel.Height + 70;
            frame.VerticalAlignment = VerticalAlignment.Center;
        }
        else
        {
            frame.VerticalAlignment = VerticalAlignment.Stretch;
        }

        return frame;
    }
}
''')

# ---------------------------------------------------------------- edits to existing shared files

# real storage provider is kept for desktop, new GetStorageProvider returns our picker
replace_once(
    "UABEANext4/Util/StorageService.cs",
    "    public static IStorageProvider? GetStorageProvider()",
    "    public static AppPicker? GetStorageProvider()\n"
    "    {\n"
    "        return new AppPicker();\n"
    "    }\n"
    "\n"
    "    public static IStorageProvider? GetRealStorageProvider()",
)

# save-as helper now uses our picker types
replace_once(
    "UABEANext4/AssetWorkspace/Workspace.Saving.cs",
    "private static async Task<IStorageFile?> ShowSaveAsDialog(IStorageProvider storageProvider, string suggestedFileName)",
    "private static async Task<PickedSaveFile?> ShowSaveAsDialog(AppPicker storageProvider, string suggestedFileName)",
)

replace_once(
    "UABEANext4/Plugins/UavPluginFunctions.cs",
    "private readonly IStorageProvider _storageProvider;",
    "private readonly AppPicker _storageProvider;",
)

# base folder (classdata.tpk, config.json, plugins) can be moved by the platform
replace_all("UABEANext4/AssetWorkspace/Workspace.cs",
            "AppDomain.CurrentDomain.BaseDirectory", "AppPaths.BaseDir", 2)
replace_all("UABEANext4/Logic/Configuration/ConfigurationManager.cs",
            "AppDomain.CurrentDomain.BaseDirectory", "AppPaths.BaseDir", 2)

# clipboard on android has no main window
replace_once(
    "UABEANext4/Util/ApplicationExtensions.cs",
    "        var mainWindow = WindowUtils.GetMainWindow();\n",
    "        var topLevel = OverlayHost.GetTopLevel();\n"
    "        if (topLevel?.Clipboard != null)\n"
    "        {\n"
    "            await topLevel.Clipboard.SetTextAsync(text);\n"
    "            return;\n"
    "        }\n"
    "\n"
    "        var mainWindow = WindowUtils.GetMainWindow();\n",
)

# app startup: on android build a root with an overlay layer and use the overlay dialog service
replace_once(
    "UABEANext4/App.axaml.cs",
    "            singleViewPlatform.MainView = new MainView\n"
    "            {\n"
    "                DataContext = new MainViewModel()\n"
    "            };\n",
    "            var mainVm = new MainViewModel();\n"
    "            Control mainContent;\n"
    "            try\n"
    "            {\n"
    "                mainContent = new AndroidShellView(mainVm);\n"
    "            }\n"
    "            catch (Exception)\n"
    "            {\n"
    "                mainContent = new MainView { DataContext = mainVm };\n"
    "            }\n"
    "            var rootGrid = new Grid();\n"
    "            rootGrid.Children.Add(mainContent);\n"
    "            var overlayLayer = new Grid();\n"
    "            rootGrid.Children.Add(overlayLayer);\n"
    "            OverlayHost.Init(overlayLayer);\n"
    "            singleViewPlatform.MainView = rootGrid;\n",
)
replace_once(
    "UABEANext4/App.axaml.cs",
    "            services.AddSingleton<IDialogService, DummyDialogService>();",
    "            services.AddSingleton<IDialogService>(new OverlayDialogService(viewLocator));",
)
replace_once(
    "UABEANext4/App.axaml.cs",
    "using UABEANext4.Services;\n",
    "using UABEANext4.Services;\nusing UABEANext4.Util;\n",
)

# bigger touch targets for lists, trees, menus and buttons (android only)
replace_once(
    "UABEANext4/App.axaml.cs",
    "            singleViewPlatform.MainView = rootGrid;\n",
    "            singleViewPlatform.MainView = rootGrid;\n            ApplyTouchStyles();\n",
)
replace_once(
    "UABEANext4/App.axaml.cs",
    "    private IServiceProvider ConfigureServices(Window? mainWindow)",
    """    private void ApplyTouchStyles()
    {
        void AddMinHeight(Avalonia.Styling.Style style, double height)
        {
            style.Setters.Add(new Avalonia.Styling.Setter(Avalonia.Layout.Layoutable.MinHeightProperty, height));
            Styles.Add(style);
        }

        AddMinHeight(new Avalonia.Styling.Style(x => x.OfType<Avalonia.Controls.ListBoxItem>()), 40d);
        AddMinHeight(new Avalonia.Styling.Style(x => x.OfType<Avalonia.Controls.TreeViewItem>()), 38d);
        AddMinHeight(new Avalonia.Styling.Style(x => x.OfType<Avalonia.Controls.MenuItem>()), 40d);
        AddMinHeight(new Avalonia.Styling.Style(x => x.OfType<Avalonia.Controls.Button>()), 38d);
        AddMinHeight(new Avalonia.Styling.Style(x => x.OfType<Avalonia.Controls.DataGridRow>()), 40d);
        AddMinHeight(new Avalonia.Styling.Style(x => x.OfType<Avalonia.Controls.TabItem>()), 44d);
    }

    private IServiceProvider ConfigureServices(Window? mainWindow)""",
)
replace_once(
    "UABEANext4/App.axaml.cs",
    "using Avalonia.Markup.Xaml;\n",
    "using Avalonia.Markup.Xaml;\nusing Avalonia.Styling;\n",
)

write("UABEANext4/Plugins/PluginLoader.cs", r'''using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using UABEANext4.AssetWorkspace;
using UABEANext4.Util;

namespace UABEANext4.Plugins;
public class PluginLoader
{
    // plugin assemblies that are already part of the app (android can't load plugin dlls at runtime)
    public static List<Assembly> BuiltInAssemblies { get; } = [];

    private readonly List<IUavPluginOption> _pluginOptions = [];
    private readonly List<IUavPluginPreviewer> _pluginPreviewers = [];
    private readonly HashSet<string> _loadedPaths = new(StringComparer.OrdinalIgnoreCase);

    public bool LoadPlugin(string path)
    {
        try
        {
            var fullPath = Path.GetFullPath(path);

            if (_loadedPaths.Contains(fullPath))
                return true;

            if (!File.Exists(fullPath))
                return false;

            var plugLoadCtx = new PluginLoadContext(fullPath);
            var asm = plugLoadCtx.LoadAssemblyByPath(fullPath);

            var anyAdded = RegisterAssembly(asm);
            if (anyAdded)
            {
                _loadedPaths.Add(fullPath);
            }

            return anyAdded;
        }
        catch
        {
            return false;
        }

    }

    public void LoadBuiltInPlugins()
    {
        foreach (var asm in BuiltInAssemblies)
        {
            try
            {
                RegisterAssembly(asm);
            }
            catch
            {
                // skip a plugin that fails to register rather than crash the app
            }
        }
    }

    private bool RegisterAssembly(Assembly asm)
    {
        bool anyAdded = false;

        foreach (Type type in asm.GetTypes())
        {
            if (type.IsAbstract || type.IsInterface)
                continue;

            if (typeof(IUavPluginOption).IsAssignableFrom(type))
            {
                if (_pluginOptions.Any(o => o.GetType() == type))
                {
                    continue;
                }

                if (Activator.CreateInstance(type) is IUavPluginOption plugInst)
                {
                    _pluginOptions.Add(plugInst);
                    anyAdded = true;
                }
            }
            else if (typeof(IUavPluginPreviewer).IsAssignableFrom(type))
            {
                if (_pluginPreviewers.Any(p => p.GetType() == type))
                {
                    continue;
                }

                if (Activator.CreateInstance(type) is IUavPluginPreviewer plugInst)
                {
                    _pluginPreviewers.Add(plugInst);
                    anyAdded = true;
                }
            }
        }

        return anyAdded;
    }

    public void LoadPluginsInDirectory(string directory)
    {
        if (!Directory.Exists(directory))
        {
            Directory.CreateDirectory(directory);
            return;
        }

        foreach (string file in Directory.EnumerateFiles(directory, "*.dll"))
        {
            LoadPlugin(file);
        }
    }

    public List<PluginOptionModePair> GetOptionsThatSupport(Workspace workspace, List<AssetInst> assets, UavPluginMode mode)
    {
        var options = new List<PluginOptionModePair>();
        foreach (var option in _pluginOptions)
        {
            var bothOpt = mode & option.Options;
            foreach (var flag in bothOpt.GetUniqueFlags())
            {
                if (flag == UavPluginMode.All)
                    continue;

                var supported = option.SupportsSelection(workspace, flag, assets);
                if (supported)
                    options.Add(new PluginOptionModePair(option, flag));
            }
        }

        return options;
    }

    public List<PluginPreviewerTypePair> GetPreviewersThatSupport(Workspace workspace, AssetInst asset)
    {
        var previewers = new List<PluginPreviewerTypePair>();
        foreach (var previewer in _pluginPreviewers)
        {
            var previewType = previewer.SupportsPreview(workspace, asset);
            if (previewType != UavPluginPreviewerType.None)
                previewers.Add(new PluginPreviewerTypePair(previewer, previewType));
        }

        return previewers;
    }
}
''')

replace_once(
    "UABEANext4/AssetWorkspace/Workspace.cs",
    "        Plugins.LoadPluginsInDirectory(pluginsPath);\n",
    "        Plugins.LoadPluginsInDirectory(pluginsPath);\n        Plugins.LoadBuiltInPlugins();\n",
)

# ================================================================ v3: texture crash fix, speed, tablet layout

# ---- TextureLoader: smaller cache, size guard, downscaled preview
replace_once(
    "TexturePlugin/Helpers/TextureLoader.cs",
    "public const int DEFAULT_MAX_SPRITE_IMAGE_CACHE_SIZE = 10;",
    "public const int DEFAULT_MAX_SPRITE_IMAGE_CACHE_SIZE = 2;\n"
    "    public const long MAX_DECODE_PIXELS = 4096L * 4096L;\n"
    "    public const int PREVIEW_MAX_SIDE = 2048;",
)
replace_once(
    "TexturePlugin/Helpers/TextureLoader.cs",
    "public class TextureLoader\n{",
    "public class TexturePreviewTooLargeException : System.Exception\n"
    "{\n"
    "    public TexturePreviewTooLargeException(int width, int height)\n"
    "        : base($\"This texture is {width} x {height} px. Preview was skipped because it is too big for this device and would crash the app.\")\n"
    "    {\n"
    "    }\n"
    "}\n"
    "\n"
    "public class TextureLoader\n{",
)
replace_once(
    "TexturePlugin/Helpers/TextureLoader.cs",
    "            var encTextureData = texture.FillPictureData(textureAsset.FileInstance);\n",
    "            if ((long)texture.m_Width * texture.m_Height > MAX_DECODE_PIXELS)\n"
    "            {\n"
    "                return null;\n"
    "            }\n"
    "\n"
    "            var encTextureData = texture.FillPictureData(textureAsset.FileInstance);\n",
)
replace_once(
    "TexturePlugin/Helpers/TextureLoader.cs",
    "    public static Bitmap? GetTexture2DBitmap(Workspace workspace, AssetInst asset, out TextureFormat format)\n    {\n",
    r'''    private static byte[] DownscaleBgra(byte[] src, int w, int h, int step, out int outW, out int outH)
    {
        outW = System.Math.Max(1, w / step);
        outH = System.Math.Max(1, h / step);
        var dst = new byte[outW * outH * 4];
        int area = step * step;
        for (int y = 0; y < outH; y++)
        {
            for (int x = 0; x < outW; x++)
            {
                int b = 0, g = 0, r = 0, a = 0;
                for (int dy = 0; dy < step; dy++)
                {
                    int i = ((y * step + dy) * w + x * step) * 4;
                    for (int dx = 0; dx < step; dx++)
                    {
                        b += src[i];
                        g += src[i + 1];
                        r += src[i + 2];
                        a += src[i + 3];
                        i += 4;
                    }
                }
                int o = (y * outW + x) * 4;
                dst[o] = (byte)(b / area);
                dst[o + 1] = (byte)(g / area);
                dst[o + 2] = (byte)(r / area);
                dst[o + 3] = (byte)(a / area);
            }
        }
        return dst;
    }

    public static Bitmap? GetTexture2DBitmap(Workspace workspace, AssetInst asset, out TextureFormat format)
    {
        var textureEditBf = TextureHelper.GetByteArrayTexture(workspace, asset);
        var texture = TextureFile.ReadTextureFile(textureEditBf);
        format = (TextureFormat)texture.m_TextureFormat;

        int width = texture.m_Width;
        int height = texture.m_Height;
        if (width <= 0 || height <= 0)
        {
            return null;
        }
        if ((long)width * height > MAX_DECODE_PIXELS)
        {
            throw new TexturePreviewTooLargeException(width, height);
        }

        if (texture.m_PlatformBlob.Length != 0)
        {
            TextureHelper.SwizzleOptIn(texture, asset.FileInstance.file);
        }

        var encTextureData = texture.FillPictureData(asset.FileInstance);
        if (encTextureData is null || encTextureData.Length == 0)
        {
            return null;
        }

        var data = texture.DecodeTextureRaw(encTextureData);
        encTextureData = null;
        if (data == null || data.Length < (long)width * height * 4)
        {
            return null;
        }

        int outW = width;
        int outH = height;
        int step = System.Math.Max(1, (System.Math.Max(width, height) + PREVIEW_MAX_SIDE - 1) / PREVIEW_MAX_SIDE);
        if (step > 1)
        {
            data = DownscaleBgra(data, width, height, step, out outW, out outH);
        }

        var bmp = new WriteableBitmap(new PixelSize(outW, outH), new Vector(96, 96), PixelFormat.Bgra8888, AlphaFormat.Unpremul);
        using (var fb = bmp.Lock())
        {
            int rowBytes = outW * 4;
            if (fb.RowBytes == rowBytes)
            {
                Marshal.Copy(data, 0, fb.Address, rowBytes * outH);
            }
            else
            {
                for (int y = 0; y < outH; y++)
                {
                    Marshal.Copy(data, y * rowBytes, fb.Address + y * fb.RowBytes, rowBytes);
                }
            }
        }

        return bmp;
    }

    public static Bitmap? GetTexture2DBitmapOld(Workspace workspace, AssetInst asset, out TextureFormat format)
    {
''',
)

write("TexturePlugin/TexturePreviewer.cs", r'''using AssetsTools.NET.Extra;
using AssetsTools.NET.Texture;
using Avalonia.Media.Imaging;
using TexturePlugin.Helpers;
using UABEANext4.AssetWorkspace;
using UABEANext4.Logic.Mesh;
using UABEANext4.Plugins;

namespace TexturePlugin;
public class TexturePreviewer : IUavPluginPreviewer
{
    public string Name => "Preview Texture2D";
    public string Description => "Preview Texture2Ds";

    public UavPluginPreviewerType SupportsPreview(Workspace workspace, AssetInst selection)
    {
        var previewType = selection.Type == AssetClassID.Texture2D
            ? UavPluginPreviewerType.Image
            : UavPluginPreviewerType.None;

        return previewType;
    }

    public (Bitmap?, int) ExecuteImage(Workspace workspace, IUavPluginFunctions funcs, AssetInst selection, out string? error)
    {
        try
        {
            var image = TextureLoader.GetTexture2DBitmap(workspace, selection, out TextureFormat format);
            if (image != null)
            {
                error = null;
                return (image, (int)format);
            }
            else
            {
                error = $"This texture could not be previewed. The format may not be supported, or it has no data. ({format})";
                return (null, (int)format);
            }
        }
        catch (TexturePreviewTooLargeException ex)
        {
            error = ex.Message;
            return (null, -1);
        }
        catch (OutOfMemoryException)
        {
            GC.Collect();
            error = "Not enough memory to preview this texture.";
            return (null, -1);
        }
        catch (Exception ex)
        {
            error = $"Texture preview failed: {ex.Message}";
            return (null, -1);
        }
    }

    public MeshObj? ExecuteMesh(Workspace workspace, IUavPluginFunctions funcs, AssetInst selection, out string? error)
        => throw new InvalidOperationException();

    public string? ExecuteText(Workspace workspace, IUavPluginFunctions funcs, AssetInst selection, out string? error)
        => throw new InvalidOperationException();

    public void Cleanup() { }
}
''')

# ---- Previewer view model: decode in the background, drop stale requests
write("UABEANext4/ViewModels/Tools/PreviewerToolViewModel.cs", r'''using AvaloniaEdit.Document;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Messaging;
using Dock.Model.Mvvm.Controls;
using System;
using System.Threading;
using System.Threading.Tasks;
using UABEANext4.AssetWorkspace;
using UABEANext4.Logic;
using UABEANext4.Logic.Mesh;
using UABEANext4.Plugins;

namespace UABEANext4.ViewModels.Tools;

public partial class PreviewerToolViewModel : Tool
{
    const string TOOL_TITLE = "Previewer";
    private const int MAX_TEXT_CHARS = 200_000;

    public Workspace Workspace { get; }

    [ObservableProperty]
    public TextDocument? _activeDocument;
    [ObservableProperty]
    public MeshObj? _activeMesh;
    [ObservableProperty]
    public PreviewerToolPreviewType _activePreviewType = PreviewerToolPreviewType.Text;

    [ObservableProperty]
    public ImagePreviewViewModel _imagePreview = new();

    // defer this to first preview since dialogs won't exist until after initial load
    private readonly Lazy<UavPluginFunctions> _uavPluginFuncs = new(() => new UavPluginFunctions());

    private CancellationTokenSource? _cts;
    private readonly SemaphoreSlim _gate = new(1, 1);

    [Obsolete("This constructor is for the designer only and should not be used directly.", true)]
    public PreviewerToolViewModel()
    {
        Workspace = new();

        Id = TOOL_TITLE.Replace(" ", "");
        Title = TOOL_TITLE;

        _activeDocument = new TextDocument();
        _activeMesh = new MeshObj();
    }

    public PreviewerToolViewModel(Workspace workspace)
    {
        Workspace = workspace;

        Id = TOOL_TITLE.Replace(" ", "");
        Title = TOOL_TITLE;

        _activeDocument = new TextDocument("Tap an asset to preview it.");

        WeakReferenceMessenger.Default.Register<AssetsSelectedMessage>(this, OnAssetsSelected);
        WeakReferenceMessenger.Default.Register<WorkspaceClosingMessage>(this, OnWorkspaceClosing);
    }

    private void OnAssetsSelected(object recipient, AssetsSelectedMessage message)
    {
        var assets = message.Value;
        if (assets.Count == 0)
        {
            return;
        }

        _ = PreviewAsync(assets[0]);
    }

    private void OnWorkspaceClosing(object recipient, WorkspaceClosingMessage message)
    {
        _cts?.Cancel();
        ImagePreview.UpdateImage(null, null);
        SetDisplayText(string.Empty);
    }

    private async Task PreviewAsync(AssetInst asset)
    {
        _cts?.Cancel();
        var cts = new CancellationTokenSource();
        _cts = cts;
        var token = cts.Token;

        try
        {
            // wait a moment so fast scrolling / tapping does not start many decodes
            await Task.Delay(150, token);

            var funcs = _uavPluginFuncs.Value;
            var pluginsList = Workspace.Plugins.GetPreviewersThatSupport(Workspace, asset);
            if (pluginsList == null || pluginsList.Count == 0)
            {
                SetDisplayText("No preview available.");
                return;
            }

            var firstPrevPair = pluginsList[0];
            var prevType = firstPrevPair.PreviewType;
            var prev = firstPrevPair.Previewer;

            if (prevType == UavPluginPreviewerType.Mesh && OperatingSystem.IsAndroid())
            {
                SetDisplayText("3D mesh preview is not available on Android yet.");
                return;
            }

            if (prevType == UavPluginPreviewerType.Image)
            {
                ImagePreview.ImageInfo = "Loading...";
            }

            await _gate.WaitAsync(token);
            try
            {
                token.ThrowIfCancellationRequested();

                switch (prevType)
                {
                    case UavPluginPreviewerType.Image:
                    {
                        var result = await Task.Run(() =>
                        {
                            var (img, fmt) = prev.ExecuteImage(Workspace, funcs, asset, out string? err);
                            return (img, fmt, err);
                        });

                        if (token.IsCancellationRequested)
                        {
                            result.img?.Dispose();
                            return;
                        }

                        if (result.img != null)
                        {
                            ActivePreviewType = PreviewerToolPreviewType.Image;
                            ImagePreview.UpdateImage(result.img, (AssetsTools.NET.Texture.TextureFormat?)result.fmt);
                        }
                        else
                        {
                            SetDisplayText(result.err ?? "No preview available.");
                        }
                        break;
                    }
                    case UavPluginPreviewerType.Text:
                    {
                        var result = await Task.Run(() =>
                        {
                            var text = prev.ExecuteText(Workspace, funcs, asset, out string? err);
                            if (text != null && text.Length > MAX_TEXT_CHARS)
                            {
                                text = text.Substring(0, MAX_TEXT_CHARS) + "\n\n[... cut off to keep the app fast ...]";
                            }
                            return (text, err);
                        });

                        if (token.IsCancellationRequested)
                        {
                            return;
                        }

                        if (result.text != null)
                        {
                            ActivePreviewType = PreviewerToolPreviewType.Text;
                            ActiveDocument = new TextDocument(result.text);
                        }
                        else
                        {
                            SetDisplayText(result.err ?? "No preview available.");
                        }
                        break;
                    }
                    case UavPluginPreviewerType.Mesh:
                    {
                        var result = await Task.Run(() =>
                        {
                            var mesh = prev.ExecuteMesh(Workspace, funcs, asset, out string? err);
                            return (mesh, err);
                        });

                        if (token.IsCancellationRequested)
                        {
                            return;
                        }

                        if (result.mesh != null)
                        {
                            ActivePreviewType = PreviewerToolPreviewType.Mesh;
                            ActiveMesh = result.mesh;
                        }
                        else
                        {
                            SetDisplayText(result.err ?? "No preview available.");
                        }
                        break;
                    }
                    default:
                    {
                        SetDisplayText($"Preview type {prevType} not supported.");
                        break;
                    }
                }
            }
            finally
            {
                _gate.Release();
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            if (!token.IsCancellationRequested)
            {
                SetDisplayText($"Preview failed: {ex.Message}");
            }
        }
    }

    private void SetDisplayText(string text)
    {
        ImagePreview.UpdateImage(null, null);
        ActivePreviewType = PreviewerToolPreviewType.Text;
        ActiveDocument = new TextDocument(text);
    }
}

public enum PreviewerToolPreviewType
{
    Image,
    Text,
    Mesh,
}
''')

# ---- image preview: no use-after-dispose, no event leak
replace_once(
    "UABEANext4/ViewModels/Tools/ImagePreviewViewModel.cs",
    "        if (Image != null) {\n            Image.Dispose();\n        }\n\n        Image = bitmap;\n",
    "        var oldImage = Image;\n\n"
    "        Image = bitmap;\n"
    "        if (oldImage != null && !ReferenceEquals(oldImage, bitmap))\n"
    "        {\n"
    "            // give the renderer time to stop using the old picture before freeing it\n"
    "            System.Threading.Tasks.Task.Delay(2000).ContinueWith(_ =>\n"
    "                Avalonia.Threading.Dispatcher.UIThread.Post(() => oldImage.Dispose()));\n"
    "        }\n",
)
replace_once(
    "UABEANext4/Views/Tools/ImagePreviewView.axaml.cs",
    "        DataContextChanged += (s, e) =>\n"
    "        {\n"
    "            if (DataContext is PreviewerToolViewModel vm)\n"
    "            {\n"
    "                vm.ImagePreview.PropertyChanged += OnImagePreviewPropertyChanged;\n"
    "            }\n"
    "        };\n"
    "    }\n",
    "        DataContextChanged += (s, e) => Rehook();\n"
    "    }\n"
    "\n"
    "    private ImagePreviewViewModel? _hooked;\n"
    "    private bool _attached;\n"
    "\n"
    "    private void Rehook()\n"
    "    {\n"
    "        ImagePreviewViewModel? target = null;\n"
    "        if (_attached && DataContext is PreviewerToolViewModel vm)\n"
    "        {\n"
    "            target = vm.ImagePreview;\n"
    "        }\n"
    "        if (ReferenceEquals(target, _hooked))\n"
    "        {\n"
    "            return;\n"
    "        }\n"
    "        if (_hooked != null)\n"
    "        {\n"
    "            _hooked.PropertyChanged -= OnImagePreviewPropertyChanged;\n"
    "        }\n"
    "        _hooked = target;\n"
    "        if (_hooked != null)\n"
    "        {\n"
    "            _hooked.PropertyChanged += OnImagePreviewPropertyChanged;\n"
    "            TriggerFit();\n"
    "        }\n"
    "    }\n"
    "\n"
    "    protected override void OnAttachedToVisualTree(VisualTreeAttachmentEventArgs e)\n"
    "    {\n"
    "        base.OnAttachedToVisualTree(e);\n"
    "        _attached = true;\n"
    "        Rehook();\n"
    "    }\n"
    "\n"
    "    protected override void OnDetachedFromVisualTree(VisualTreeAttachmentEventArgs e)\n"
    "    {\n"
    "        base.OnDetachedFromVisualTree(e);\n"
    "        _attached = false;\n"
    "        Rehook();\n"
    "    }\n",
)

# ---- expose tool view models + document-opened event for the tablet shell
replace_once(
    "UABEANext4/ViewModels/MainDockFactory.cs",
    "    public DocumentManager DocMan;\n",
    "    public DocumentManager DocMan;\n"
    "    public WorkspaceExplorerToolViewModel? ExplorerTool => _workspaceExplorerTool;\n"
    "    public InspectorToolViewModel? InspectorTool => _inspectorToolViewModel;\n"
    "    public PreviewerToolViewModel? PreviewerTool => _previewerToolViewModel;\n",
)
replace_once(
    "UABEANext4/ViewModels/MainViewModel.cs",
    "    private readonly MainDockFactory _factory;\n",
    "    private readonly MainDockFactory _factory;\n\n"
    "    public WorkspaceExplorerToolViewModel? ExplorerToolVm => _factory.ExplorerTool;\n"
    "    public InspectorToolViewModel? InspectorToolVm => _factory.InspectorTool;\n"
    "    public PreviewerToolViewModel? PreviewerToolVm => _factory.PreviewerTool;\n"
    "    public event Action<AssetDocumentViewModel>? AssetDocumentOpened;\n",
)
replace_once(
    "UABEANext4/ViewModels/MainViewModel.cs",
    "            _factory.DocMan.Documents.Add(document);\n",
    "            _factory.DocMan.Documents.Add(document);\n"
    "            AssetDocumentOpened?.Invoke(document);\n",
)

write("UABEANext4/Views/AndroidShellView.cs", r'''using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.Messaging;
using System;
using System.Threading.Tasks;
using UABEANext4.Logic;
using UABEANext4.ViewModels;

namespace UABEANext4.Views;

/// <summary>
/// Touch friendly layout for Android: top bar, one page at a time (Files / Assets / Preview / Data),
/// and on wide screens the asset list and preview/data sit side by side.
/// </summary>
public class AndroidShellView : UserControl
{
    private const double WideBreakpoint = 820;

    private static readonly IBrush BarBrush = new SolidColorBrush(Color.Parse("#1F2937"));
    private static readonly IBrush ButtonBrush = new SolidColorBrush(Color.Parse("#374151"));
    private static readonly IBrush AccentBrush = new SolidColorBrush(Color.Parse("#2563EB"));

    private readonly MainViewModel _vm;
    private readonly Grid _content = new();
    private readonly ContentControl _filesPage = new();
    private readonly ContentControl _assetsPage = new();
    private readonly ContentControl _previewPage = new();
    private readonly ContentControl _dataPage = new();
    private readonly Button[] _tabButtons = new Button[4];
    private readonly ProgressBar _progress = new();
    private readonly TextBlock _status = new();
    private int _tab = 0;
    private bool _wide = false;

    public AndroidShellView(MainViewModel vm)
    {
        _vm = vm;

        _filesPage.Content = vm.ExplorerToolVm;
        _previewPage.Content = vm.PreviewerToolVm;
        _dataPage.Content = vm.InspectorToolVm;
        _assetsPage.Content = new TextBlock
        {
            Text = "Open a file in the Files tab, then tap a file to see its assets here.",
            Margin = new Thickness(16),
            TextWrapping = TextWrapping.Wrap
        };

        _content.Children.Add(_filesPage);
        _content.Children.Add(_assetsPage);
        _content.Children.Add(_previewPage);
        _content.Children.Add(_dataPage);

        var root = new Grid
        {
            RowDefinitions = new RowDefinitions("Auto,Auto,*,Auto")
        };

        var topBar = BuildTopBar();
        Grid.SetRow(topBar, 0);
        root.Children.Add(topBar);

        var statusGrid = new Grid();
        _progress.Minimum = 0;
        _progress.Maximum = 1;
        _progress.Height = 4;
        _progress.VerticalAlignment = VerticalAlignment.Top;
        _status.FontSize = 11;
        _status.Margin = new Thickness(8, 4, 8, 2);
        _status.IsVisible = false;
        statusGrid.Children.Add(_progress);
        statusGrid.Children.Add(_status);
        Grid.SetRow(statusGrid, 1);
        root.Children.Add(statusGrid);

        Grid.SetRow(_content, 2);
        root.Children.Add(_content);

        var nav = BuildNavBar();
        Grid.SetRow(nav, 3);
        root.Children.Add(nav);

        Content = root;

        vm.Workspace.PropertyChanged += (s, e) =>
        {
            if (e.PropertyName == "ProgressValue" || e.PropertyName == "ProgressText")
            {
                Dispatcher.UIThread.Post(UpdateProgress);
            }
        };

        vm.AssetDocumentOpened += doc =>
        {
            _assetsPage.Content = doc;
            SetTab(1);
        };

        WeakReferenceMessenger.Default.Register<AndroidShellView, AssetsSelectedMessage>(this, (r, m) =>
        {
            Dispatcher.UIThread.Post(r.OnAssetSelected);
        });
        WeakReferenceMessenger.Default.Register<AndroidShellView, WorkspaceClosingMessage>(this, (r, m) =>
        {
            Dispatcher.UIThread.Post(r.OnWorkspaceClosed);
        });

        Relayout();
        UpdateTabButtons();
    }

    private void OnAssetSelected()
    {
        // on a narrow screen jump to the preview when an asset is tapped
        if (!_wide && _tab == 1)
        {
            SetTab(2);
        }
    }

    private void OnWorkspaceClosed()
    {
        _assetsPage.Content = new TextBlock
        {
            Text = "Open a file in the Files tab, then tap a file to see its assets here.",
            Margin = new Thickness(16),
            TextWrapping = TextWrapping.Wrap
        };
        SetTab(0);
    }

    private void UpdateProgress()
    {
        var value = _vm.Workspace.ProgressValue;
        _progress.Value = value;
        var busy = value > 0f && value < 1f;
        _progress.IsVisible = busy;
        _status.IsVisible = busy;
        _status.Text = _vm.Workspace.ProgressText;
    }

    private Control BuildTopBar()
    {
        var panel = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(6, 4) };
        panel.Children.Add(MakeBarButton("Open", () => _vm.FileOpen()));
        panel.Children.Add(MakeBarButton("Folder", () => _vm.FileOpenFolder()));
        panel.Children.Add(MakeBarButton("Save", () => _ = _vm.FileSave()));

        var menuPanel = new StackPanel { Orientation = Orientation.Vertical, MinWidth = 200 };
        var flyout = new Flyout { Content = menuPanel };
        void AddMenu(string text, Action action)
        {
            var item = new Button
            {
                Content = text,
                MinHeight = 44,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Left,
                Margin = new Thickness(0, 2)
            };
            item.Click += (s, e) =>
            {
                flyout.Hide();
                try { action(); } catch (Exception) { }
            };
            menuPanel.Children.Add(item);
        }
        AddMenu("Save as...", () => _ = _vm.FileSaveAs());
        AddMenu("Save all", () => _ = _vm.FileSaveAll());
        AddMenu("Asset info", () => _vm.ShowAssetInfoDialog());
        AddMenu("Search bytes", () => _vm.ShowSearchBytesDialog());
        AddMenu("Options", () => _vm.ShowOptionsDialog());
        AddMenu("Close all files", () => _vm.FileCloseAll());

        var more = MakeBarButton("More", () => { });
        more.Flyout = flyout;
        panel.Children.Add(more);

        return new Border { Background = BarBrush, Child = panel };
    }

    private static Button MakeBarButton(string text, Action onClick)
    {
        var button = new Button
        {
            Content = text,
            MinHeight = 42,
            MinWidth = 64,
            Padding = new Thickness(14, 6),
            Margin = new Thickness(3),
            Background = ButtonBrush,
            Foreground = Brushes.White,
            VerticalAlignment = VerticalAlignment.Center
        };
        button.Click += (s, e) =>
        {
            try { onClick(); } catch (Exception) { }
        };
        return button;
    }

    private Control BuildNavBar()
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,*,*,*"), Background = BarBrush };
        string[] names = { "Files", "Assets", "Preview", "Data" };
        for (int i = 0; i < 4; i++)
        {
            int index = i;
            var button = new Button
            {
                Content = names[i],
                MinHeight = 52,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Center,
                VerticalContentAlignment = VerticalAlignment.Center,
                Margin = new Thickness(2),
                Foreground = Brushes.White
            };
            button.Click += (s, e) => SetTab(index);
            Grid.SetColumn(button, i);
            grid.Children.Add(button);
            _tabButtons[i] = button;
        }
        return grid;
    }

    private void SetTab(int tab)
    {
        _tab = tab;
        Relayout();
        UpdateTabButtons();
    }

    private void UpdateTabButtons()
    {
        for (int i = 0; i < _tabButtons.Length; i++)
        {
            _tabButtons[i].Background = i == _tab ? AccentBrush : Brushes.Transparent;
        }
    }

    protected override void OnSizeChanged(SizeChangedEventArgs e)
    {
        base.OnSizeChanged(e);
        var wide = e.NewSize.Width >= WideBreakpoint;
        if (wide != _wide)
        {
            _wide = wide;
            Relayout();
        }
    }

    private static void Place(Control control, int column, int span, bool visible)
    {
        Grid.SetColumn(control, column);
        Grid.SetColumnSpan(control, span);
        control.IsVisible = visible;
    }

    private void Relayout()
    {
        _content.ColumnDefinitions.Clear();
        if (_wide && _tab != 0)
        {
            _content.ColumnDefinitions.Add(new ColumnDefinition(1.2, GridUnitType.Star));
            _content.ColumnDefinitions.Add(new ColumnDefinition(1, GridUnitType.Star));
            Place(_filesPage, 0, 1, false);
            Place(_assetsPage, 0, 1, true);
            Place(_previewPage, 1, 1, _tab != 3);
            Place(_dataPage, 1, 1, _tab == 3);
        }
        else
        {
            _content.ColumnDefinitions.Add(new ColumnDefinition(1, GridUnitType.Star));
            Place(_filesPage, 0, 1, _tab == 0);
            Place(_assetsPage, 0, 1, _tab == 1);
            Place(_previewPage, 0, 1, _tab == 2);
            Place(_dataPage, 0, 1, _tab == 3);
        }
    }
}
''')

# ---------------------------------------------------------------- android project files

write("UABEANext4.Android/UABEANext4.Android.csproj", r'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0-android</TargetFramework>
    <SupportedOSPlatformVersion>23.0</SupportedOSPlatformVersion>
    <OutputType>Exe</OutputType>
    <Nullable>enable</Nullable>
    <ApplicationId>com.uabea.next</ApplicationId>
    <ApplicationVersion>1</ApplicationVersion>
    <ApplicationDisplayVersion>0.1</ApplicationDisplayVersion>
    <AndroidPackageFormat>apk</AndroidPackageFormat>
    <RuntimeIdentifiers>android-arm64</RuntimeIdentifiers>
    <PublishTrimmed>false</PublishTrimmed>
    <AndroidLinkMode>None</AndroidLinkMode>
    <RunAOTCompilation>false</RunAOTCompilation>
    <EmbedAssembliesIntoApk>true</EmbedAssembliesIntoApk>
    <AllowUnsafeBlocks>true</AllowUnsafeBlocks>
    <AvaloniaUseCompiledBindingsByDefault>true</AvaloniaUseCompiledBindingsByDefault>
    <ConcurrentGarbageCollection>false</ConcurrentGarbageCollection>
    <TieredPGO>false</TieredPGO>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Avalonia.Android" Version="11.3.8" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\UABEANext4\UABEANext4.csproj" />
    <!-- plugins are built into the app on android (dynamic plugin loading is not supported there) -->
    <ProjectReference Include="..\TexturePlugin\TexturePlugin.csproj" />
    <ProjectReference Include="..\AudioPlugin\AudioPlugin.csproj" />
    <ProjectReference Include="..\TextAssetPlugin\TextAssetPlugin.csproj" />
    <ProjectReference Include="..\MeshPlugin\MeshPlugin.csproj" />
    <ProjectReference Include="..\FontPlugin\FontPlugin.csproj" />
  </ItemGroup>

  <ItemGroup>
    <!-- the class database the app needs to read game assets -->
    <AndroidAsset Include="..\ReleaseFiles\classdata.tpk" Link="Assets\classdata.tpk" />
  </ItemGroup>
</Project>
''')

write("UABEANext4.Android/Properties/AndroidManifest.xml", r'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
	<uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE" />
	<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" />
	<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" />
	<application android:label="UABEA Next" android:largeHeap="true" android:requestLegacyExternalStorage="true"></application>
</manifest>
''')

write("UABEANext4.Android/MainActivity.cs", r'''using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.OS;
using Avalonia;
using Avalonia.Android;
using UABEANext4.Plugins;
using AndroidUri = Android.Net.Uri;

namespace UABEANext4.Android;

[Activity(
    Label = "UABEA Next",
    Theme = "@style/MyTheme.NoActionBar",
    MainLauncher = true,
    ConfigurationChanges = ConfigChanges.Orientation | ConfigChanges.ScreenSize | ConfigChanges.UiMode | ConfigChanges.ScreenLayout | ConfigChanges.SmallestScreenSize)]
public class MainActivity : AvaloniaMainActivity<App>
{
    protected override void OnCreate(Bundle? savedInstanceState)
    {
        System.AppDomain.CurrentDomain.UnhandledException += (s, e) => WriteCrashLog(e.ExceptionObject?.ToString());

        PrepareAppFiles();
        RegisterBuiltInPlugins();
        base.OnCreate(savedInstanceState);
        AskForAllFilesAccess();
    }

    protected override AppBuilder CustomizeAppBuilder(AppBuilder builder)
    {
        return base.CustomizeAppBuilder(builder)
            .WithInterFont();
    }

    // base folder = the app's private files folder (the install folder is read only)
    // classdata.tpk is packed in the apk, copy it there so the app can load it
    private void PrepareAppFiles()
    {
        try
        {
            var dir = FilesDir?.AbsolutePath ?? System.IO.Path.GetTempPath();
            AppPaths.BaseDir = dir;

            var dest = System.IO.Path.Combine(dir, "classdata.tpk");
            using var src = Assets!.Open("classdata.tpk");
            using var dst = System.IO.File.Create(dest);
            src.CopyTo(dst);
        }
        catch (System.Exception ex)
        {
            WriteCrashLog("PrepareAppFiles failed: " + ex);
        }
    }

    // plugins can't be loaded from dll files on android, so they are compiled into the app
    private static void RegisterBuiltInPlugins()
    {
        PluginLoader.BuiltInAssemblies.Add(typeof(TexturePlugin.TexturePreviewer).Assembly);
        PluginLoader.BuiltInAssemblies.Add(typeof(AudioPlugin.ExportAudioOption).Assembly);
        PluginLoader.BuiltInAssemblies.Add(typeof(TextAssetPlugin.TextAssetPreviewer).Assembly);
        PluginLoader.BuiltInAssemblies.Add(typeof(MeshPlugin.MeshPreviewer).Assembly);
        PluginLoader.BuiltInAssemblies.Add(typeof(FontPlugin.ExportFontOption).Assembly);
    }

    private void AskForAllFilesAccess()
    {
        try
        {
            if (Build.VERSION.SdkInt >= BuildVersionCodes.R)
            {
                if (!Environment.IsExternalStorageManager)
                {
                    var intent = new Intent(
                        "android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION",
                        AndroidUri.Parse("package:" + PackageName));
                    StartActivity(intent);
                }
            }
            else
            {
                RequestPermissions(new[]
                {
                    "android.permission.READ_EXTERNAL_STORAGE",
                    "android.permission.WRITE_EXTERNAL_STORAGE"
                }, 1);
            }
        }
        catch (System.Exception ex)
        {
            WriteCrashLog("AskForAllFilesAccess failed: " + ex);
        }
    }

    private void WriteCrashLog(string? text)
    {
        if (text == null)
            return;

        try
        {
            var dir = FilesDir?.AbsolutePath ?? System.IO.Path.GetTempPath();
            System.IO.File.AppendAllText(System.IO.Path.Combine(dir, "uabea_crash.log"), text + "\n\n");
        }
        catch
        {
            // nothing else we can do
        }

        try
        {
            System.IO.File.AppendAllText("/storage/emulated/0/Download/uabea_crash.log", text + "\n\n");
        }
        catch
        {
            // no permission yet, fine
        }
    }
}
''')

# ---------------------------------------------------------------- done
print("UABEA android patch applied")
