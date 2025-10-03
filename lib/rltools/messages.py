# -*- coding: utf-8 -*-
"""
RL Tools messages.py

This module centralizes the startup message and helpers.  Both your
`doc-opened.py` hook and the ribbon button call into `show_start_message`
to present the onboarding reminder.  It also optionally opens the native
Revit Worksets dialog after the alert.

Engine notes:
  * In Rocket Mode (CPython), `pyrevit.forms` is unavailable.  We therefore
    build a small WPF dialog ourselves to render true bold.  If WPF fails
    for any reason, we fall back to Revit's `TaskDialog` with plain text.

Usage:
    from rltools.messages import show_start_message
    show_start_message(doc=doc, force=False, open_worksets_after=True)

Parameters:
    title (str): Title for the dialog window (default "RL Tools").
    force (bool): If True, always show the dialog (useful for the ribbon
        button).  Otherwise we filter out families and linked documents.
    doc (Document or None): The active Revit document; the helper uses it
        to decide if the message should display.  If None, the message
        will show when force is True.
    open_worksets_after (bool): When True, the native Worksets dialog will
        open automatically after the user closes the alert.
"""

# =============================
#  Public API (what others call)
# =============================

START_MESSAGE = (
    "Please Check Your Current **<<Workset>>**.\n\n"
    "For New Users, please read the **<<Starting View>>** (Available in only new projects) "
    "for GB Standards & Best Practices."
)


def show_start_message(title="RL Tools", force=False, doc=None, open_worksets_after=False):
    """Show the onboarding dialog; optionally open Worksets afterwards.

    We keep this function name and signature stable so your hook and button do
    not need to change other than toggling `open_worksets_after`.
    """
    # 1) Decide if we should show (unless the caller explicitly forces it)
    if not (force or _should_show_for_doc(doc)):
        return

    # 2) Try the rich WPF dialog first (it renders true bold); track success
    shown = _alert_wpf_with_bold(title, START_MESSAGE)

    # 3) If WPF failed for any reason, fall back to Revit TaskDialog (plain text)
    if not shown:
        try:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show(title, START_MESSAGE.replace("**", ""))
            shown = True
        except Exception:
            # Last resort: write to console so at least something is visible in logs
            print("[RL Tools] {}: {}".format(title, START_MESSAGE.replace("**", "")))

    # 4) Optionally open the native Worksets UI after user closes our dialog
    if shown and open_worksets_after:
        _open_worksets_dialog_safely()


# =============================
#  Internals (helpers)
# =============================

def _should_show_for_doc(doc):
    """Filter out contexts where showing the popup would be noisy.
    - Skip families and linked docs by default.
    - We no longer require worksharing; both non-workshared and workshared projects will see it.
    """
    if doc is None:
        # If the hook couldn't fetch a Document at this instant, we still show.
        return True
    if getattr(doc, "IsFamilyDocument", False):
        return False
    if hasattr(doc, "IsLinked") and doc.IsLinked:
        return False
    return True


def _alert_wpf_with_bold(title, message):
    """Render a simple modal WPF dialog and interpret **bold** markers visually.
    Returns True if the dialog was shown successfully, False if any error occurs.
    """
    try:
        # (1) Ensure WPF assemblies are loaded for CPython/IronPython
        import clr
        clr.AddReference("PresentationFramework")
        clr.AddReference("PresentationCore")
        clr.AddReference("WindowsBase")

        # (2) Import the WPF types we need
        from System.Windows import Window, WindowStartupLocation, SizeToContent, HorizontalAlignment, Thickness
        from System.Windows.Controls import StackPanel, TextBlock, Button
        from System.Windows.Documents import Run, Bold, LineBreak

        # (3) Helper to add a text chunk that may contain single \n line breaks
        def _add_text_chunk(tb, text, make_bold=False):
            parts = text.split("\n")
            for idx, chunk in enumerate(parts):
                run = Run(chunk)
                tb.Inlines.Add(Bold(run) if make_bold else run)
                if idx < len(parts) - 1:
                    tb.Inlines.Add(LineBreak())

        # (4) Build a small window
        win = Window()
        win.Title = title
        win.SizeToContent = SizeToContent.WidthAndHeight
        win.WindowStartupLocation = WindowStartupLocation.CenterScreen
        win.MinWidth = 440
        win.Topmost = True

        root = StackPanel()
        root.Margin = Thickness(20)

        # (5) Convert our mini-markdown ("**bold**") into WPF inlines
        for para in message.split("\n\n"):
            tb = TextBlock()
            tb.TextWrapping = True
            segments = para.split("**")
            for i, seg in enumerate(segments):
                _add_text_chunk(tb, seg, make_bold=(i % 2 == 1))
            if root.Children.Count > 0:
                tb.Margin = Thickness(0, 8, 0, 0)
            root.Children.Add(tb)

        # (6) OK button to close the dialog
        ok = Button()
        ok.Content = "OK"
        ok.MinWidth = 90
        ok.Margin = Thickness(0, 16, 0, 0)
        ok.HorizontalAlignment = HorizontalAlignment.Right

        def _close(sender, args):
            try:
                win.DialogResult = True
            except Exception:
                pass
            win.Close()

        ok.Click += _close

        root.Children.Add(ok)
        win.Content = root

        # (7) Show dialog modally; returns after user clicks OK
        win.ShowDialog()
        return True

    except Exception:
        return False


def _open_worksets_dialog_safely():
    """Open the native Revit Worksets dialog by posting the built-in command.
    We guard in a try/except so a missing command never crashes your script.
    """
    try:
        from Autodesk.Revit.UI import RevitCommandId, PostableCommand
        app = __revit__  # pyRevit provides UIApplication here
        cmd_id = RevitCommandId.LookupPostableCommandId(PostableCommand.Worksets)
        if cmd_id:
            app.PostCommand(cmd_id)
    except Exception:
        # If this ever fails (older Revit, custom environment), we simply skip.
        pass
