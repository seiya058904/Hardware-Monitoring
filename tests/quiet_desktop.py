"""Real Tk widgets without mapping test windows or taking desktop focus."""
from contextlib import ExitStack, contextmanager
import tkinter as tk
from unittest.mock import patch


@contextmanager
def quiet_desktop(root):
    root.withdraw()
    original_toplevel = tk.Toplevel

    def hidden_toplevel(*args, **kwargs):
        window = original_toplevel(*args, **kwargs)
        window.withdraw()
        return window

    with ExitStack() as stack:
        stack.enter_context(patch('app.tk.Toplevel', side_effect=hidden_toplevel))
        # Restore paths are asserted through this spy; native visibility is
        # checked in a separate sustained acceptance session.
        stack.enter_context(patch.object(root, 'deiconify'))
        stack.enter_context(patch.object(tk.Misc, 'focus_force'))
        stack.enter_context(patch.object(tk.Misc, 'focus_set'))
        stack.enter_context(patch.object(tk.Misc, 'lift'))
        yield
