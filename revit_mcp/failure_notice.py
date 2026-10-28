# -*- coding: UTF-8 -*-
"""Small non-modal Revit notice for agent errors that were rolled back.

Revit shows kept warnings itself, as its mini-warning. Errors roll back
silently, so this box shows the user what the agent hit. Entries collect,
newest first, until the user closes it. It never takes focus and never
raises into execution. IronPython 2.7; imports under CPython for tests.
"""
import datetime
import logging

logger = logging.getLogger(__name__)

MAX_ENTRIES = 20
_state = {"window": None, "box": None, "entries": [], "count": 0}


def notice_entries(failures, now=None):
    """One display entry per rolled-back error in a call's failures."""
    stamp = (now or datetime.datetime.now()).strftime("%H:%M:%S")
    entries = []
    for item in failures:
        if item.get("action") != "rolled_back" or item.get("severity") == "Warning":
            continue
        ids = item.get("element_ids") or []
        detail = item.get("description", "")
        if ids:
            shown = ", ".join(str(value) for value in ids[:5])
            detail += u"  (ids {0}{1})".format(shown, ", ..." if len(ids) > 5 else "")
        entries.append(u"{0}  {1}\n    {2}".format(stamp, item.get("transaction", ""), detail))
    return entries


def notify_rolled_back(failures, application=None):
    """Add a call's rolled-back errors to the notice; never raises."""
    try:
        entries = notice_entries(failures)
        if not entries:
            return
        _state["entries"][:0] = reversed(entries)
        del _state["entries"][MAX_ENTRIES:]
        _state["count"] += len(entries)
        count = _state["count"]
        title = u"Revit MCP: {0} agent error{1} rolled back".format(count, "" if count == 1 else "s")
        _display(title, u"\n".join(_state["entries"]), application)
    except BaseException as error:
        logger.warning("Failure notice could not be shown: %s", error)


def _closed(sender, args):
    _state.update(window=None, box=None, entries=[], count=0)


def _display(title, text, application):
    """Create or update the owned, non-activating WPF tool window."""
    window = _state["window"]
    if window is None:
        window = _create(application)
    window.Title = title
    _state["box"].Text = text
    _state["box"].ScrollToHome()


def _create(application):
    import clr
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    from System.Diagnostics import Process
    from System.Windows import Window, WindowStyle, ResizeMode, WindowStartupLocation, TextWrapping, Thickness
    from System.Windows.Controls import TextBox, ScrollBarVisibility
    from System.Windows.Interop import WindowInteropHelper
    from System.Windows.Media import SolidColorBrush, Color

    owner = Process.GetCurrentProcess().MainWindowHandle
    window = Window()
    window.WindowStyle = WindowStyle.ToolWindow
    window.ResizeMode = ResizeMode.NoResize
    window.ShowInTaskbar = False
    window.ShowActivated = False
    window.Width, window.Height = 435.0, 120.0  # Revit's mini-warning is 435 x 117
    box = TextBox()
    box.IsReadOnly = True
    box.TextWrapping = TextWrapping.Wrap
    box.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    box.BorderThickness = Thickness(0)
    box.Padding = Thickness(4)
    box.Background = SolidColorBrush(Color.FromRgb(255, 255, 225))
    window.Content = box
    try:
        _place_above_mini_warning(window, application, owner)
    except BaseException as error:
        logger.warning("Failure notice uses default placement: %s", error)
    WindowInteropHelper(window).Owner = owner
    window.Closed += _closed
    window.Show()
    _state.update(window=window, box=box)
    return window


def _place_above_mini_warning(window, application, owner):
    """Revit pins its mini-warning 5 px inside the main window's lower right."""
    from System.Windows import WindowStartupLocation
    from Autodesk.Revit.UI import UIApplication
    extents = UIApplication(application).MainWindowExtents
    scale = _scale(owner)
    window.WindowStartupLocation = WindowStartupLocation.Manual
    window.Left = (extents.Right - 5) / scale - window.Width
    window.Top = (extents.Bottom - 5) / scale - 117 - 6 - window.Height


def _scale(handle):
    import clr
    clr.AddReference("System.Drawing")
    from System.Drawing import Graphics
    graphics = Graphics.FromHwnd(handle)
    try:
        return graphics.DpiX / 96.0
    finally:
        graphics.Dispose()
