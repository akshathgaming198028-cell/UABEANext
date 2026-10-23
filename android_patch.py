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
    "            var rootGrid = new Grid();\n"
    "            rootGrid.Children.Add(new MainView\n"
    "            {\n"
    "                DataContext = new MainViewModel()\n"
    "            });\n"
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
