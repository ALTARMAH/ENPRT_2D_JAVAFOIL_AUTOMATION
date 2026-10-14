"""
aero_ui.py - compact Tkinter shell around aero_auto: configure a wing, sanity-check it against
the FSUK/FSG rules, run single JavaFoil analyses or full campaigns, and browse the results.

This is a convenience UI; every feature here calls into aero_auto / aero_report / aero_targets.
Everything that touches JavaFoil runs in a worker thread so the window never freezes.
"""
import os
import io
import re
import sys
import time
import glob
import math
import shutil
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
import numpy as np
import pandas as pd
# Ensure streams are never None (e.g. in PyInstaller windowed mode)
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        sys.stdout = io.StringIO()
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        sys.stderr = io.StringIO()


def _crash_handler(exc_type, exc_value, exc_tb):
    import traceback
    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        crash_dir = os.path.join(os.path.expanduser("~"), ".aero_auto")
        os.makedirs(crash_dir, exist_ok=True)
        with open(os.path.join(crash_dir, "crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Application Error:\n{err_msg}\n")
    except Exception:
        pass
    try:
        messagebox.showerror(
            "Application Error",
            f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}\n\nDetails saved to ~/.aero_auto/crash.log"
        )
    except Exception:
        pass


sys.excepthook = _crash_handler

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aero_auto as A

try:
    import aero_targets as T
except Exception:
    T = None

try:
    import aero_report as R
except Exception:
    R = None

FW = "front wing"
RW = "rear wing"
CUSTOM = "custom"
ATTR = {
    "front wing": ("fw", 1400.0),
    "rear wing": ("rw", 950.0),
    "custom": ("custom", 1000.0)
}

THEMES = {
    'dark': {
        'label': 'Dark (default)',
        'BG': '#0f172a',
        'PANEL': '#1e293b',
        'PANEL2': '#101d36',
        'BAND': '#12234a',
        'TXT': '#e2e8f0',
        'MUTED': '#94a3b8',
        'ACCENT': '#f79e0b',
        'SKY': '#7dd3fc',
        'RULE': '#33415c',
        'SEL_BG': '#0b1220',
        'TIP_BG': '#fff7d6',
        'TIP_FG': '#0b1220',
        'TIP_BORDER': '#f79e0b'
    },
    'light': {
        'label': 'Light',
        'BG': '#f4f6fb',
        'PANEL': '#e6ebf3',
        'PANEL2': '#ffffff',
        'BAND': '#1f2b45',
        'TXT': '#1e293b',
        'MUTED': '#5b6b82',
        'ACCENT': '#b45309',
        'SKY': '#0369a1',
        'RULE': '#c3ccda',
        'SEL_BG': '#ffffff',
        'TIP_BG': '#1f2b45',
        'TIP_FG': '#f8fafc',
        'TIP_BORDER': '#b45309'
    },
    'contrast': {
        'label': 'High contrast',
        'BG': '#000000',
        'PANEL': '#141414',
        'PANEL2': '#0a0a0a',
        'BAND': '#000000',
        'TXT': '#ffffff',
        'MUTED': '#d0d0d0',
        'ACCENT': '#ffcc00',
        'SKY': '#66e0ff',
        'RULE': '#6b6b6b',
        'SEL_BG': '#000000',
        'TIP_BG': '#ffcc00',
        'TIP_FG': '#000000',
        'TIP_BORDER': '#ffffff'
    }
}
DEFAULT_THEME = 'dark'

BG = '#000000'
PANEL = '#000000'
PANEL2 = '#000000'
BAND = '#000000'
TXT = '#000000'
MUTED = '#000000'
ACCENT = '#000000'
SKY = '#000000'
RULE = '#000000'
SEL_BG = '#000000'
TIP_BG = '#000000'
TIP_FG = '#000000'
TIP_BORDER = '#000000'

def _apply_palette(name):
    """Install a theme by name, updating the module-level colour globals."""
    global BG, PANEL, PANEL2, BAND, TXT, MUTED, ACCENT, SKY, RULE, SEL_BG, TIP_BG, TIP_FG, TIP_BORDER
    p = THEMES.get(name) or THEMES[DEFAULT_THEME]
    BG, PANEL, PANEL2 = p['BG'], p['PANEL'], p['PANEL2']
    BAND, TXT, MUTED = p['BAND'], p['TXT'], p['MUTED']
    ACCENT, SKY, RULE = p['ACCENT'], p['SKY'], p['RULE']
    SEL_BG = p['SEL_BG']
    TIP_BG, TIP_FG, TIP_BORDER = p['TIP_BG'], p['TIP_FG'], p['TIP_BORDER']
    return p

_apply_palette(DEFAULT_THEME)

def subprocess_open(path):
    """Open a file/folder with the OS default handler. Never raises (fire-and-forget);
    returns True if a launcher was started, False otherwise."""
    import subprocess
    path = os.path.expanduser(str(path))
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
            return True
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        else:
            opener = shutil.which('xdg-open') or shutil.which('gio')
            if opener is None:
                return False
            if opener.endswith('gio'):
                cmd = [opener, 'open', path]
            else:
                cmd = [opener, path]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        return False

class ToolTip:
    """Single shared hover tooltip controller for the whole app.
    Using one controller means at most one description is on screen at a time,
    it is always dismissed on click / leave / Escape / tab change, and it is
    shown only after a short delay so it never flickers while the mouse moves.
    """
    def __init__(self):
        self.tip = None
        self.label = None
        self._pending = None
        self._after = None
        self.enabled = True
        self.delay = 350
        self.wraplength = 420
        self._last_xy = None

    def register(self, widget, text):
        if not text:
            return
        widget.bind('<Enter>', lambda e, w=widget, t=text: self.schedule(w, t, e), add='+')
        widget.bind('<Motion>', lambda e, w=widget, t=text: self._on_motion(w, t, e), add='+')
        widget.bind('<Leave>', lambda e: self.hide(), add='+')
        widget.bind('<ButtonPress>', lambda e: self.hide(), add='+')
        widget.bind('<Destroy>', lambda e, w=widget: self._on_destroy(w), add='+')

    def _on_motion(self, widget, text, ev):
        if ev:
            self._last_xy = (ev.x_root, ev.y_root)

    def _on_destroy(self, widget):
        if self._pending and self._pending[0] is widget:
            self._pending = None
            self._cancel()
        self.hide()

    def _cancel(self):
        if self._after is not None and self._pending:
            try:
                self._pending[0].after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def schedule(self, widget, text, ev=None):
        self._cancel()
        if not self.enabled or not text:
            return
        if ev:
            self._last_xy = (ev.x_root, ev.y_root)
        else:
            try:
                self._last_xy = (widget.winfo_rootx() + 16, widget.winfo_rooty() + widget.winfo_height() + 6)
            except Exception:
                self._last_xy = None
        self._pending = (widget, text)
        try:
            self._after = widget.after(int(self.delay), self._show)
        except Exception:
            self._after = None

    def _show(self):
        self._after = None
        if not self._pending:
            return
        widget, text = self._pending
        try:
            if not widget.winfo_exists():
                return
            if self.tip is not None:
                try:
                    self.tip.destroy()
                except Exception:
                    pass
                self.tip = None

            self.tip = tk.Toplevel(widget)
            self.tip.withdraw()
            self.tip.wm_overrideredirect(True)
            try:
                self.tip.attributes('-topmost', True)
            except Exception:
                pass
            self.label = tk.Label(
                self.tip, text=text, background=TIP_BG, foreground=TIP_FG,
                relief='solid', borderwidth=1, highlightthickness=1,
                highlightbackground=TIP_BORDER, font=('TkDefaultFont', 9),
                padx=8, pady=5, justify='left', wraplength=self.wraplength
            )
            self.label.pack()
            self._place(widget)
            self.tip.deiconify()
            self.tip.lift()
        except Exception:
            pass

    def _place(self, widget):
        try:
            self.tip.update_idletasks()
            tw = self.tip.winfo_reqwidth()
            th = self.tip.winfo_reqheight()
            sw = widget.winfo_screenwidth()
            sh = widget.winfo_screenheight()

            if self._last_xy:
                mx, my = self._last_xy
                x = mx + 12
                y = my + 18
            else:
                x = widget.winfo_rootx() + 16
                y = widget.winfo_rooty() + widget.winfo_height() + 6

            if x + tw > sw - 10:
                x = max(6, sw - tw - 10)
            if y + th > sh - 35:
                y = max(6, (self._last_xy[1] - th - 8) if self._last_xy else (widget.winfo_rooty() - th - 6))
            x = max(4, min(x, sw - tw - 4))
            y = max(4, min(y, sh - th - 4))
            self.tip.wm_geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass

    def hide(self, event=None):
        self._cancel()
        self._pending = None
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None
            self.label = None

    def set_options(self, enabled=None, delay=None, wraplength=None):
        if enabled is not None:
            self.enabled = bool(enabled)
        if delay is not None:
            self.delay = max(0, int(delay))
        if wraplength is not None:
            self.wraplength = max(160, int(wraplength))
        if not self.enabled:
            self.hide()

_TIP = ToolTip()

def add_tooltip(widget, text):
    """Helper to add a hover description to any widget."""
    _TIP.register(widget, text)

def tip_hide():
    """Dismiss any on-screen description (used on clicks, tab changes, Esc)."""
    _TIP.hide()

class _QueueWriter(io.TextIOBase):
    """File-like object that forwards writes to the UI queue as one line per message."""
    def __init__(self, q, kind='camp'):
        self.q = q
        self.kind = kind
        self._buf = ''

    def write(self, s):
        self._buf += str(s)
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            self.q.put((self.kind, line))
        return len(s)

    def flush(self):
        if self._buf:
            self.q.put((self.kind, self._buf))
            self._buf = ''

def bind_scrollable(canvas):
    """Enable cross-platform mouse wheel scrolling (Linux Button-4/5, Win/Mac MouseWheel)."""
    def _on_wheel(ev):
        if getattr(ev, 'num', None) == 4:
            canvas.yview_scroll(-1, 'units')
        elif getattr(ev, 'num', None) == 5:
            canvas.yview_scroll(1, 'units')
        elif hasattr(ev, 'delta') and ev.delta:
            canvas.yview_scroll(int(-1 * (ev.delta / 120)), 'units')

    def _on_enter(e=None):
        canvas.bind_all('<MouseWheel>', _on_wheel)
        canvas.bind_all('<Button-4>', _on_wheel)
        canvas.bind_all('<Button-5>', _on_wheel)

    def _on_leave(e=None):
        canvas.unbind_all('<MouseWheel>')
        canvas.unbind_all('<Button-4>')
        canvas.unbind_all('<Button-5>')

    canvas.bind('<Enter>', _on_enter)
    canvas.bind('<Leave>', _on_leave)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.report_callback_exception = _crash_handler
        self._state = self._read_state()
        s = self._state.get('settings', {}) if isinstance(self._state, dict) else {}
        self._settings = {
            'theme': s.get('theme', DEFAULT_THEME),
            'tips': bool(s.get('tips', True)),
            'tip_delay': int(float(s.get('tip_delay', 450) or 0)),
            'tip_wrap': int(float(s.get('tip_wrap', 420) or 420)),
        }
        if self._settings['theme'] not in THEMES:
            self._settings['theme'] = DEFAULT_THEME
        self._pal = _apply_palette(self._settings['theme'])
        self._pal_name = self._settings['theme']
        _TIP.set_options(
            enabled=self._settings['tips'],
            delay=self._settings['tip_delay'],
            wraplength=self._settings['tip_wrap']
        )
        self._setup_theme()
        self.title("aero_ui - multi-element wing campaign shell")
        self.geometry("1240x820")
        self._load_icon()

        A.seed_airfoil_store()
        for cand in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'airfoils'),
            getattr(sys, '_MEIPASS', '') and os.path.join(sys._MEIPASS, 'assets', 'airfoils'),
        ]:
            if cand and os.path.isdir(cand):
                A.AIRFOILS.update(A.load_all(cand))
        A.AIRFOILS.update(A.load_all(A.AIRFOIL_DIR))
        if os.path.isdir(A.AIRFOIL_STORE):
            A.AIRFOILS.update(A.load_all(A.AIRFOIL_STORE))

        from queue import Queue
        A.WORKER_DIRS = Queue()
        jf, mh = A.find_java_jars()
        if os.path.isabs(jf) and os.path.isfile(jf):
            A.JAVA_DIR = os.path.dirname(jf)
        w = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'workers')
        try:
            os.makedirs(w, exist_ok=True)
        except OSError:
            w = os.path.join(A.APP_DATA_DIR, 'workers')
            try:
                os.makedirs(w, exist_ok=True)
            except Exception:
                pass
        try:
            for j_path in (jf, mh):
                if j_path and os.path.isfile(j_path):
                    dst = os.path.join(w, os.path.basename(j_path))
                    if not os.path.exists(dst):
                        shutil.copy(j_path, dst)
        except Exception:
            pass
        A.WORKER_DIRS.put(w)

        self.names = sorted(A.AIRFOILS.keys())
        self.results = pd.DataFrame()
        self._tree_frame = pd.DataFrame()
        self.threads = []
        self.ui_q = queue.Queue()
        self._cli_lock = threading.Lock()
        self.cam_t0 = None
        self.cam_runs_base = 0
        self.cam_active = False
        self._gimg = None
        self._graph_paths = []
        self._cur_graph_path = None
        self.gr_selected_rid = ""
        self.gr_only_active_run = tk.BooleanVar(value=True)
        self._drain_timer_running = True

        self.gh_state = tk.StringVar(value='300')
        self.ge_state = tk.BooleanVar(value=True)
        self.custom_span_state = tk.StringVar(value='1000')
        self.gr_results = tk.StringVar(value=os.path.join(A.OUT_DIR, 'results.csv'))

        self.after(50, self._drain_ui)
        self._build_ui()

        self.bind('<ButtonPress>', lambda e: tip_hide(), add='+')
        self.bind('<Escape>', lambda e: tip_hide(), add='+')

        self._apply_state(self._state)
        self._refresh_runs()
        self.load_results_cache()
        self.refresh_graph_files()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _bundle_root(self):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return meipass
        return os.path.dirname(os.path.abspath(__file__))

    def _load_icon(self):
        root = self._bundle_root()
        candidates = [
            os.environ.get('AERO_ICON'),
            os.path.join(root, 'assets', 'icon.ico'),
            os.path.join(root, 'assets', 'icon.png'),
            os.path.join(root, 'assets', 'Logoertblanc.png'),
        ]
        for p in candidates:
            if not p or not os.path.exists(p):
                continue
            try:
                if p.lower().endswith('.ico'):
                    self.iconbitmap(p)
                else:
                    self._icon_img = tk.PhotoImage(file=p)
                    self.iconphoto(True, self._icon_img)
                return
            except Exception:
                pass

    def _lib_base(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs')

    def _new_run(self, kind, label, **meta):
        run = A.new_run_dir(kind, label, base=self._lib_base())
        path = os.path.join(run, 'results.csv')
        A.write_run_meta(run, kind=kind, label=label, results='results.csv', **meta)
        return run, path

    def _state_path(self):
        return os.path.join(os.path.expanduser('~'), '.aero_auto', 'ui_state.json')

    def _capture_state(self):
        def sel_names(lb):
            try:
                return [lb.get(i) for i in lb.curselection()]
            except Exception:
                return []

        fp = {}
        fp['cfg'] = dict(
            chord=self.vars['chord'].get() if 'chord' in self.vars else '',
            speed=self.vars['speed'].get() if 'speed' in self.vars else '',
            re=self.vars['re'].get() if 're' in self.vars else '',
            al0=self.vars['al0'].get() if 'al0' in self.vars else '',
            al1=self.vars['al1'].get() if 'al1' in self.vars else '',
            alst=self.vars['alst'].get() if 'alst' in self.vars else '',
            main=self.main_box.get() if hasattr(self, 'main_box') else '',
            role=self._role_state.get() if hasattr(self, '_role_state') else '',
            custom_span=self.custom_span_state.get(),
            gh=self.gh_state.get(),
            reg=self.reg_state.get() if hasattr(self, 'reg_state') else True,
            ge=self.ge_state.get(),
            flaps=[[v.get() for v in vals[:-1]] + [vals[-1].get()] for vals, _ in getattr(self, 'flap_rows', [])],
        )
        fp['cam'] = dict(
            hours=self.cam_hours.get() if hasattr(self, 'cam_hours') else '0.5',
            workers=self.cam_workers.get() if hasattr(self, 'cam_workers') else '4',
            out=self.cam_out.get() if hasattr(self, 'cam_out') else '',
            unb=self.cam_flow_unb.get() if hasattr(self, 'cam_flow_unb') else True,
            gnd=self.cam_flow_gnd.get() if hasattr(self, 'cam_flow_gnd') else False,
            heights=self.cam_heights.get() if hasattr(self, 'cam_heights') else '',
            role=self.cam_role.get() if hasattr(self, 'cam_role') else '',
            enforce=self.cam_enforce.get() if hasattr(self, 'cam_enforce') else True,
            resume=self.cam_resume.get() if hasattr(self, 'cam_resume') else True,
            check=self.cam_check.get() if hasattr(self, 'cam_check') else True,
            report=self.cam_report.get() if hasattr(self, 'cam_report') else True,
            open=self.cam_open.get() if hasattr(self, 'cam_open') else True,
            mains=sel_names(getattr(self, 'cam_mains', None)),
            flaps=sel_names(getattr(self, 'cam_flaps', None)),
        )
        fp['opt'] = dict(
            res_file=self.opt_res_file.get() if hasattr(self, 'opt_res_file') else '',
            main=self.opt_main_box.get() if hasattr(self, 'opt_main_box') else '',
            iters=self.opt_iters.get() if hasattr(self, 'opt_iters') else '',
            step=self.opt_step.get() if hasattr(self, 'opt_step') else '',
            perturb=self.opt_perturb.get() if hasattr(self, 'opt_perturb') else '',
            target_cl=self.opt_target_cl.get() if hasattr(self, 'opt_target_cl') else '',
            target_gap=self.opt_target_gap.get() if hasattr(self, 'opt_target_gap') else '',
            max_h=self.opt_max_height.get() if hasattr(self, 'opt_max_height') else '',
            max_l=self.opt_max_length.get() if hasattr(self, 'opt_max_length') else '',
            gh=self.opt_gh_state.get() if hasattr(self, 'opt_gh_state') else '',
            ge=self.opt_ge_v.get() if hasattr(self, 'opt_ge_v') else True,
            reg=self.opt_reg_v.get() if hasattr(self, 'opt_reg_v') else True,
            objs={k: v.get() for k, v in getattr(self, 'opt_objectives', {}).items()},
            flaps=[[v.get() for v in vals[:-1]] + [vals[-1].get()] for vals, _ in getattr(self, 'opt_flap_rows', [])],
        )
        fp['res'] = dict(
            file=self.res_file.get() if hasattr(self, 'res_file') else '',
            gr=self.gr_results.get(),
        )
        try:
            self._settings['theme'] = self.theme_var.get() if hasattr(self, 'theme_var') else self._settings['theme']
            self._settings['tips'] = bool(self.tips_var.get()) if hasattr(self, 'tips_var') else self._settings['tips']
            self._settings['tip_delay'] = int(float(self.tip_delay_var.get() or 0)) if hasattr(self, 'tip_delay_var') else self._settings['tip_delay']
            self._settings['tip_wrap'] = int(float(self.tip_wrap_var.get() or 420)) if hasattr(self, 'tip_wrap_var') else self._settings['tip_wrap']
        except Exception as e:
            self.log(f"(settings not saved: {e})")
        fp['settings'] = dict(self._settings)
        fp['geom'] = self.geometry()
        try:
            fp['tab'] = self.notebook.index(self.notebook.select())
        except Exception:
            fp['tab'] = 0
        fp['legacy_imported'] = bool(getattr(self, '_legacy_imported', False))
        return fp

    def _read_state(self):
        import json
        try:
            with open(self._state_path()) as f:
                s = json.load(f)
            return s if isinstance(s, dict) else {}
        except Exception:
            return {}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self._state_path()), exist_ok=True)
            with open(self._state_path(), 'w') as f:
                import json
                json.dump(self._capture_state(), f, indent=1)
        except Exception:
            pass

    def _load_state(self):
        self._apply_state(self._read_state())

    def _schedule_state_save(self):
        job = getattr(self, '_save_job', None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._save_job = self.after(500, self._save_state)

    def _apply_state(self, s):
        if not isinstance(s, dict):
            s = {}
        try:
            cfg = s.get('cfg', {})
            for k in ('chord', 'speed', 're', 'al0', 'al1', 'alst'):
                if cfg.get(k) and k in self.vars:
                    self.vars[k].set(str(cfg[k]))
            if cfg.get('main') and hasattr(self, 'main_box'):
                self.main_box.set(cfg['main'])
            role = cfg.get('role')
            if role in (FW, RW, CUSTOM) and hasattr(self, '_role_state'):
                self._role_state.set(role)
                self.on_role()
            if cfg.get('custom_span'):
                self.custom_span_state.set(str(cfg['custom_span']))
            if cfg.get('gh'):
                self.gh_state.set(str(cfg['gh']))
            if isinstance(cfg.get('reg'), bool) and hasattr(self, 'reg_state'):
                self.reg_state.set(cfg['reg'])
            if isinstance(cfg.get('ge'), bool):
                self.ge_state.set(cfg['ge'])
                self._toggle_ground_height()
            cfg_flaps = cfg.get('flaps')
            if isinstance(cfg_flaps, list) and hasattr(self, 'flap_rows'):
                for (vals, _cb), cf in zip(self.flap_rows, cfg_flaps):
                    if isinstance(cf, list) and len(cf) == 6:
                        for i, x in enumerate(cf):
                            vals[i].set(x)

            c = s.get('cam', {})
            for k, var in (
                ('hours', getattr(self, 'cam_hours', None)),
                ('workers', getattr(self, 'cam_workers', None)),
                ('out', getattr(self, 'cam_out', None)),
                ('heights', getattr(self, 'cam_heights', None))
            ):
                if var and c.get(k):
                    var.set(str(c[k]))
            for k, var in (
                ('unb', getattr(self, 'cam_flow_unb', None)),
                ('gnd', getattr(self, 'cam_flow_gnd', None)),
                ('enforce', getattr(self, 'cam_enforce', None)),
                ('resume', getattr(self, 'cam_resume', None)),
                ('check', getattr(self, 'cam_check', None)),
                ('report', getattr(self, 'cam_report', None)),
                ('open', getattr(self, 'cam_open', None))
            ):
                if var and isinstance(c.get(k), bool):
                    var.set(c[k])
            if c.get('role') and hasattr(self, 'cam_role'):
                self.cam_role.set(c['role'])
            for lb, names in ((getattr(self, 'cam_mains', None), c.get('mains')), (getattr(self, 'cam_flaps', None), c.get('flaps'))):
                if lb and isinstance(names, list):
                    lb.selection_clear(0, 'end')
                    for n in names:
                        if n in self.names:
                            lb.selection_set(self.names.index(n))

            o = s.get('opt', {})
            if o.get('res_file') and hasattr(self, 'opt_res_file'):
                self.opt_res_file.set(o['res_file'])
            if o.get('main') and hasattr(self, 'opt_main_box'):
                self.opt_main_box.set(o['main'])
            for k, var in (
                ('iters', getattr(self, 'opt_iters', None)),
                ('step', getattr(self, 'opt_step', None)),
                ('perturb', getattr(self, 'opt_perturb', None)),
                ('target_cl', getattr(self, 'opt_target_cl', None)),
                ('target_gap', getattr(self, 'opt_target_gap', None)),
                ('max_h', getattr(self, 'opt_max_height', None)),
                ('max_l', getattr(self, 'opt_max_length', None)),
                ('gh', getattr(self, 'opt_gh_state', None))
            ):
                if var and o.get(k):
                    var.set(str(o[k]))
            if isinstance(o.get('ge'), bool) and hasattr(self, 'opt_ge_v'):
                self.opt_ge_v.set(o['ge'])
            if isinstance(o.get('reg'), bool) and hasattr(self, 'opt_reg_v'):
                self.opt_reg_v.set(o['reg'])
            objs = o.get('objs')
            if isinstance(objs, dict) and hasattr(self, 'opt_objectives'):
                for k, v in objs.items():
                    if k in self.opt_objectives and isinstance(v, bool):
                        self.opt_objectives[k].set(v)
            opt_flaps = o.get('flaps')
            if isinstance(opt_flaps, list) and hasattr(self, 'opt_flap_rows'):
                for (vals, _cb), cf in zip(self.opt_flap_rows, opt_flaps):
                    if isinstance(cf, list) and len(cf) == 6:
                        for i, x in enumerate(cf):
                            vals[i].set(x)

            r = s.get('res', {})
            if r.get('file') and hasattr(self, 'res_file'):
                self.res_file.set(r['file'])
            if r.get('gr'):
                self.gr_results.set(r['gr'])

            st = s.get('settings', {})
            if st.get('theme') and st['theme'] in THEMES and hasattr(self, 'theme_var'):
                self.theme_var.set(st['theme'])
            if isinstance(st.get('tips'), bool) and hasattr(self, 'tips_var'):
                self.tips_var.set(st['tips'])
            if st.get('tip_delay') is not None and hasattr(self, 'tip_delay_var'):
                self.tip_delay_var.set(str(st['tip_delay']))
            if st.get('tip_wrap') is not None and hasattr(self, 'tip_wrap_var'):
                self.tip_wrap_var.set(str(st['tip_wrap']))

            if s.get('geom'):
                try:
                    self.geometry(s['geom'])
                except Exception:
                    pass
            if s.get('tab') is not None and hasattr(self, 'notebook'):
                try:
                    self.notebook.select(int(s['tab']))
                except Exception:
                    pass

            if not s.get('legacy_imported') and getattr(R, 'import_legacy_results', None):
                try:
                    added = R.import_legacy_results(base=os.path.expanduser(self._lib_base()))
                    if added:
                        self.log(f"imported {len(added)} existing result set(s) into the library")
                except Exception:
                    pass
                self._legacy_imported = True
        except Exception as e:
            self.log(f"(state restore warning: {e})")

    def _on_close(self):
        try:
            self._save_state()
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

    def log(self, text):
        self.ui_q.put(('log', text))

    def _append_log(self, widget, text, cap=2000, follow=True):
        if not widget:
            return
        widget.configure(state='normal')
        widget.insert('end', str(text) + '\n')
        try:
            lines = int(float(widget.index('end-1c').split('.')[0]))
            if lines > cap:
                widget.delete('1.0', f"{lines - cap}.0")
        except Exception:
            pass
        if follow:
            widget.see('end')
        widget.configure(state='disabled')

    def _drain_ui(self):
        try:
            while True:
                kind, payload = self.ui_q.get_nowait()
                try:
                    if kind == 'log':
                        self._append_log(getattr(self, 'status', None), payload)
                    elif kind == 'camp':
                        self._append_log(getattr(self, 'cam_log', None), payload, follow=self.cam_follow.get() if hasattr(self, 'cam_follow') else True)
                    elif kind == 'load':
                        self.load_results_cache()
                        self.refresh_graph_files()
                        self._refresh_runs()
                    elif kind == 'cam_evt':
                        self._cam_evt(*payload)
                    elif kind == 'cam_done':
                        self._cam_done(payload)
                    elif kind == 'aflog':
                        self._append_log(getattr(self, 'af_log', None), payload)
                    elif kind == 'refreshgr':
                        self.refresh_graph_files(payload or None)
                    elif kind == 'refreshgr_select':
                        p, rid = payload
                        if hasattr(self, 'refresh_graph_files'):
                            self.refresh_graph_files(p, select_rid=rid)
                        try:
                            self.notebook.select(self.tab_gr)
                        except Exception:
                            pass
                    elif kind == 'gr_prog':
                        pct, status_txt = payload
                        if hasattr(self, 'gr_prog_bar'):
                            self.gr_prog_bar['value'] = pct
                        if hasattr(self, 'gr_prog_lbl'):
                            self.gr_prog_lbl.configure(text=status_txt)
                    elif kind == 'gr_done':
                        r, p, rid, run_gdir, already_existed = payload
                        if hasattr(self, 'gr_prog_bar'):
                            self.gr_prog_bar['value'] = 100
                        if hasattr(self, 'gr_prog_lbl'):
                            self.gr_prog_lbl.configure(
                                text=f"Run {rid}: Complete! ({'Loaded from cache' if already_existed else 'Generated fresh'})"
                            )
                        if hasattr(self, 'refresh_graph_files'):
                            self.refresh_graph_files(p, select_rid=rid)
                        try:
                            self.notebook.select(self.tab_gr)
                        except Exception:
                            pass
                        self.ask_graph_destination(r, rid, run_gdir, already_existed=already_existed)
                    elif kind == 'opt_log':
                        self._append_log(getattr(self, 'opt_log', None), payload)
                    elif kind == 'opt_prog':
                        if hasattr(self, 'opt_progress'):
                            self.opt_progress['value'] = payload
                    elif kind == 'opt_status':
                        if hasattr(self, 'opt_status'):
                            self.opt_status.set(payload)
                    elif kind == 'opt_done':
                        self._handle_opt_done(payload)
                    elif kind == 'sim_done':
                        self._sim_done(payload)
                except Exception as e:
                    self._append_log(getattr(self, 'status', None), f"UI update error ({kind}): {e}")
        except queue.Empty:
            pass
        except Exception as e:
            self._append_log(getattr(self, 'status', None), f"UI update error: {e}")

        try:
            self._update_campaign_progress()
            cnt = getattr(self, '_drain_cnt', 0) + 1
            self._drain_cnt = cnt
            if self.cam_active and cnt % 20 == 0:
                self._refresh_live_campaign()
        except Exception:
            pass

        if getattr(self, '_drain_timer_running', True):
            self.after(50, self._drain_ui)

    def _setup_theme(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        self.option_add('*Background', BG)
        self.option_add('*Foreground', TXT)
        self.option_add('*selectBackground', ACCENT)
        self.option_add('*selectForeground', SEL_BG)
        self.option_add('*Text.background', PANEL2)
        self.option_add('*Text.foreground', TXT)
        self.option_add('*Text.insertBackground', ACCENT)
        self.option_add('*Listbox.background', PANEL2)
        self.option_add('*Listbox.foreground', TXT)
        self.option_add('*Listbox.selectBackground', ACCENT)
        self.option_add('*Listbox.selectForeground', SEL_BG)
        self.option_add('*Canvas.background', BG)
        self.option_add('*Menu.background', PANEL)
        self.option_add('*Menu.foreground', TXT)
        self.option_add('*Menu.activeBackground', ACCENT)
        self.option_add('*Menu.activeForeground', SEL_BG)
        self.option_add('*Menu.selectColor', SKY)

        style.configure('.', background=BG, foreground=TXT, fieldbackground=PANEL2,
                        bordercolor=RULE, lightcolor=PANEL, darkcolor=PANEL2,
                        troughcolor=PANEL2, focuscolor=ACCENT, font=('TkDefaultFont', 9))
        for w in ('TFrame', 'TLabel', 'TCheckbutton', 'TRadiobutton', 'TNotebook', 'TPanedwindow'):
            style.configure(w, background=BG, foreground=TXT)
        style.configure('TLabelframe', background=BG, bordercolor=RULE)
        style.configure('TLabelframe.Label', background=BG, foreground=ACCENT)
        style.configure('TButton', background=PANEL, foreground=TXT, bordercolor=RULE, focuscolor=ACCENT, padding=(7, 3))
        style.map('TButton', background=[('active', RULE), ('pressed', BAND)], foreground=[('active', TXT)])
        style.configure('TEntry', fieldbackground=PANEL2, foreground=TXT, insertcolor=TXT, bordercolor=RULE)
        style.configure('TCombobox', fieldbackground=PANEL2, background=PANEL, foreground=TXT, arrowcolor=SKY, bordercolor=RULE)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL2)], foreground=[('readonly', TXT)],
                  selectbackground=[('readonly', PANEL2)], selectforeground=[('readonly', TXT)])
        self.option_add('*TCombobox*Listbox.background', PANEL2)
        self.option_add('*TCombobox*Listbox.foreground', TXT)
        self.option_add('*TCombobox*Listbox.selectBackground', ACCENT)
        self.option_add('*TCombobox*Listbox.selectForeground', SEL_BG)
        style.configure('TNotebook', background=BG, bordercolor=RULE, tabmargins=(2, 4, 2, 0))
        style.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(12, 6))
        style.map('TNotebook.Tab', background=[('selected', BAND), ('active', RULE)], foreground=[('selected', ACCENT), ('active', TXT)])
        style.configure('Treeview', background=PANEL2, fieldbackground=PANEL2, foreground=TXT, bordercolor=RULE, rowheight=22)
        style.map('Treeview', background=[('selected', BAND)], foreground=[('selected', TXT)])
        style.configure('Treeview.Heading', background=BAND, foreground=SKY, relief='flat', padding=(6, 4))
        style.map('Treeview.Heading', background=[('active', RULE)])
        style.configure('TProgressbar', background=ACCENT, troughcolor=PANEL2, bordercolor=RULE)

    def _on_theme_change(self):
        try:
            name = self.theme_var.get()
        except Exception:
            name = DEFAULT_THEME
        if name not in THEMES:
            name = DEFAULT_THEME
        try:
            self._settings['tips'] = bool(self.tips_var.get())
            self._settings['tip_delay'] = int(float(self.tip_delay_var.get() or 0))
            self._settings['tip_wrap'] = int(float(self.tip_wrap_var.get() or 420))
        except Exception:
            pass
        if name == getattr(self, '_pal_name', None):
            if hasattr(self, 'theme_note'):
                self.theme_note.config(text='already active')
            self._save_state()
            return
        state = self._capture_state()
        state.setdefault('settings', {})['theme'] = name
        state['settings'] = dict(self._settings)
        state['settings']['theme'] = name
        self._settings['theme'] = name
        self._pal = _apply_palette(name)
        self._pal_name = name
        self._rebuild_ui()
        self._apply_state(state)

    def _apply_settings(self, save=True):
        try:
            self._settings['tips'] = bool(self.tips_var.get())
            self._settings['tip_delay'] = int(float(self.tip_delay_var.get() or 0))
            self._settings['tip_wrap'] = int(float(self.tip_wrap_var.get() or 420))
        except Exception:
            pass
        _TIP.set_options(
            enabled=self._settings['tips'],
            delay=self._settings['tip_delay'],
            wraplength=self._settings['tip_wrap']
        )
        if save:
            self._schedule_state_save()

    def _preview_tip(self):
        _TIP.schedule(self.tab_set, "This is a hover description. It now uses high-contrast colours, waits for the delay, and disappears as soon as you click or leave.")

    def _rebuild_ui(self):
        for w in self.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._build_ui()
        for fn in ('_refresh_runs', 'load_results_cache', 'refresh_graph_files'):
            try:
                getattr(self, fn)()
            except Exception:
                pass

    def _build_header(self):
        bar = tk.Frame(self, bg=BAND, height=52)
        bar.pack(side='top', fill='x')
        bar.pack_propagate(False)
        tk.Label(bar, text="AERO", bg=BAND, fg=ACCENT, font=('TkDefaultFont', 17, 'bold')).pack(side='left', padx=(14, 4))
        tk.Label(bar, text="wing campaign console", bg=BAND, fg=TXT, font=('TkDefaultFont', 12)).pack(side='left')
        self.header_status = tk.StringVar(value='')
        tk.Label(bar, textvariable=self.header_status, bg=BAND, fg=SKY, font=('TkDefaultFont', 9)).pack(side='right', padx=14)

    def _build_statusbar(self):
        self.sb_vars = {}
        self._sb_frame = ttk.Frame(self)
        self._sb_frame.pack(side='bottom', fill='x')
        self.sb_vars['env'] = tk.StringVar(value='')
        ttk.Label(self._sb_frame, textvariable=self.sb_vars['env'], foreground=MUTED, font=('TkDefaultFont', 8)).pack(side='left', padx=8)
        self._update_statusbar()

    def _update_statusbar(self):
        if not hasattr(self, 'sb_vars') or 'env' not in self.sb_vars:
            return
        jf, _ = A.find_java_jars()
        has_java = A.is_java_available()
        has_jf = os.path.isabs(jf) and os.path.isfile(jf)
        if has_java and has_jf:
            java_desc = "Java & JavaFoil ready"
        elif not has_java:
            java_desc = "Java JRE MISSING"
        else:
            java_desc = "JavaFoil jar MISSING"
        cand = self.discover_results() if hasattr(self, 'discover_results') else []
        latest = cand[0] if cand else ''
        parts = [
            f"v{A.VERSION}",
            f"airfoils: {len(self.names)}",
            f"out: {os.path.expanduser(A.OUT_DIR)}",
            f"java: {java_desc}"
        ]
        if latest:
            try:
                shown = os.path.relpath(latest, os.path.expanduser(A.OUT_DIR))
            except ValueError:
                shown = latest
            parts.append(f"latest results: {shown}")
        self.sb_vars['env'].set('   ·   '.join(parts))
        if hasattr(self, 'header_status'):
            self.header_status.set(f"out: {os.path.expanduser(self._lib_base())}   ·   airfoils: {len(self.names)}")

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True)
        self.tab_cfg = ttk.Frame(self.notebook)
        self.tab_af = ttk.Frame(self.notebook)
        self.tab_comb = ttk.Frame(self.notebook)
        self.tab_famous = self.tab_comb
        self.tab_cam = ttk.Frame(self.notebook)
        self.tab_res = ttk.Frame(self.notebook)
        self.tab_gr = ttk.Frame(self.notebook)
        self.tab_opt = ttk.Frame(self.notebook)
        self.tab_set = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_cfg, text="  Configure  ")
        self.notebook.add(self.tab_af, text="  Airfoils  ")
        self.notebook.add(self.tab_comb, text="  ⭐ Famous Wings  ")
        self.notebook.add(self.tab_cam, text="  Campaigns  ")
        self.notebook.add(self.tab_res, text="  Results  ")
        self.notebook.add(self.tab_gr, text="  Graphs  ")
        self.notebook.add(self.tab_opt, text="  Optimizer  ")
        self.notebook.add(self.tab_set, text="  Themes & Settings  ")
        self.build_configure()
        self.build_airfoils()
        self.build_famous_wings()
        self.build_campaigns()
        self.build_results()
        self.build_graphs()
        self.build_optimizer()
        self.build_settings()
        self.notebook.bind('<<NotebookTabChanged>>', lambda e: tip_hide(), add='+')

    def _build_menu(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Open output folder", command=self._open_cur_out)
        fm.add_command(label="Open current results file", command=self._open_cur_results)
        fm.add_separator()
        fm.add_command(label="Write report (current results)", accelerator="Ctrl+R", command=self.on_report_picked)
        fm.add_command(label="Reload airfoils", command=self.on_refresh_airfoils)
        fm.add_separator()
        fm.add_command(label="Quit", accelerator="Ctrl+Q", command=self._on_close)
        m.add_cascade(label="File", menu=fm)

        vm = tk.Menu(m, tearoff=0)
        vm.add_command(label="Refresh results & graphs", accelerator="F5", command=self._refresh_all)
        vm.add_command(label="Reset results filter/sort", command=self._reset_results_view)
        vm.add_command(label="Clear campaign log", command=self.on_campaign_clear_log)
        vm.add_separator()
        tabs = [
            ('Configure', self.tab_cfg),
            ('Airfoils', self.tab_af),
            ('Famous Wings', self.tab_comb),
            ('Campaigns', self.tab_cam),
            ('Results', self.tab_res),
            ('Graphs', self.tab_gr),
            ('Optimizer', self.tab_opt),
            ('Themes & Settings', self.tab_set)
        ]
        for i, (name, tab) in enumerate(tabs, start=1):
            vm.add_command(label=f"{i}. {name}", accelerator=f"Alt+{i}", command=lambda t=tab: self.notebook.select(t))
        m.add_cascade(label="View", menu=vm)

        setm = tk.Menu(m, tearoff=0)
        for key, pal in THEMES.items():
            setm.add_radiobutton(label=pal['label'], value=key, variable=self.theme_var, command=self._on_theme_change)
        setm.add_separator()
        setm.add_command(label="More settings...", command=lambda: self.notebook.select(self.tab_set))
        m.add_cascade(label="Appearance", menu=setm)

        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="User Manual (PDF)", command=self._open_user_manual)
        hm.add_command(label="Technical Guide (PDF)", command=self._open_technical_guide)
        hm.add_command(label="FSAE Optimization Guide (PDF)", command=self._open_fsae_guide)
        hm.add_command(label="Open Documentation Folder", command=self._open_docs_dir)
        hm.add_separator()
        hm.add_command(label="About aero_ui", command=self._show_about)
        hm.add_separator()
        hm.add_command(label="Open airfoil store", command=self.on_open_store)
        hm.add_command(label="Open JavaFoil folder", command=self._open_java_dir)
        hm.add_command(label="Open project folder", command=lambda: subprocess_open(os.path.dirname(os.path.abspath(__file__))))
        m.add_cascade(label="Help", menu=hm)

        self.config(menu=m)
        self.bind_all('<Control-r>', lambda e=None: self.on_report_picked())
        self.bind_all('<F5>', lambda e=None: self._refresh_all())
        self.bind_all('<Control-q>', lambda e=None: self._on_close())
        for i, tab in enumerate((self.tab_cfg, self.tab_af, self.tab_comb, self.tab_cam, self.tab_res, self.tab_gr, self.tab_opt, self.tab_set), start=1):
            self.bind_all(f'<Alt-Key-{i}>', lambda e=None, t=tab: (tip_hide(), self.notebook.select(t)))
        for seq, step in (('<Control-Tab>', 1), ('<Control-Shift-Tab>', -1)):
            self.bind_all(seq, lambda e=None, s=step: self._cycle_tab(s))

    def _cycle_tab(self, step):
        tabs = self.notebook.tabs()
        if not tabs:
            return
        cur = self.notebook.select()
        try:
            idx = tabs.index(cur)
        except ValueError:
            idx = 0
        nxt = tabs[(idx + step) % len(tabs)]
        tip_hide()
        self.notebook.select(nxt)

    def _open_cur_out(self):
        d = os.path.expanduser(self.cam_out.get())
        os.makedirs(d, exist_ok=True)
        subprocess_open(d)

    def _open_cur_results(self):
        p = os.path.expanduser(self.res_file.get())
        if os.path.exists(p):
            subprocess_open(os.path.dirname(p) or '.')
        else:
            self.log("results file not present yet: " + p)

    def _open_java_dir(self):
        jf, _ = A.find_java_jars()
        target_dir = os.path.dirname(jf) if (os.path.isabs(jf) and os.path.isfile(jf)) else A.JAVA_DIR
        if os.path.isdir(target_dir):
            subprocess_open(target_dir)
        else:
            self.log(f"JavaFoil folder not found: {target_dir}")

    def _show_about(self):
        msg = (
            f"aero_ui - multi-element wing campaign shell  (v{A.VERSION})\n\n"
            f"Airfoil library : {os.path.expanduser(A.AIRFOIL_DIR)}\n"
            f"Airfoil store   : {os.path.expanduser(A.AIRFOIL_STORE)}\n"
            f"JavaFoil        : {A.JAVA_DIR}\n"
            f"Default output  : {os.path.expanduser(A.OUT_DIR)}\n"
            f"State file      : {self._state_path()}\n\n"
            "Campaigns share one engine with the CLI (aero_auto.py) so GUI and terminal runs behave identically."
        )
        messagebox.showinfo("About aero_ui", msg)

    def _find_doc(self, filename):
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", filename),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "_internal", "docs", filename),
            os.path.join(getattr(sys, "_MEIPASS", ""), "docs", filename),
            os.path.join(os.path.abspath("."), "docs", filename),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return None

    def _open_user_manual(self):
        p = self._find_doc("USER_MANUAL.pdf")
        if p:
            subprocess_open(p)
        else:
            messagebox.showinfo("User Manual", "USER_MANUAL.pdf not found in docs folder.")

    def _open_technical_guide(self):
        p = self._find_doc("TECHNICAL_GUIDE.pdf")
        if p:
            subprocess_open(p)
        else:
            messagebox.showinfo("Technical Guide", "TECHNICAL_GUIDE.pdf not found in docs folder.")

    def _open_fsae_guide(self):
        p = self._find_doc("FSAE_OPTIMIZATION_GUIDE.pdf") or self._find_doc("fsea.pdf")
        if p:
            subprocess_open(p)
        else:
            messagebox.showinfo("FSAE Guide", "FSAE_OPTIMIZATION_GUIDE.pdf not found in docs folder.")

    def _open_docs_dir(self):
        p = self._find_doc("USER_MANUAL.pdf")
        if p:
            subprocess_open(os.path.dirname(p))
        else:
            d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
            if os.path.exists(d):
                subprocess_open(d)
            else:
                messagebox.showinfo("Documentation", "Documentation directory not found.")

    def _refresh_all(self):
        self.load_results_cache()
        self.refresh_graph_files()
        self.refresh_airfoils()

    def _build_ui(self):
        self._build_header()
        self._build_tabs()
        self._build_statusbar()
        self._build_menu()
        self.bind('<ButtonPress>', lambda e: tip_hide(), add='+')
        self.bind('<Escape>', lambda e: tip_hide(), add='+')

    # --- CONFIGURE TAB ---
    def build_configure(self):
        outer_cfg = ttk.Frame(self.tab_cfg)
        outer_cfg.pack(side='left', fill='both', padx=6, pady=6)
        cfg_canvas = tk.Canvas(outer_cfg, highlightthickness=0, width=420)
        cfg_vsb = ttk.Scrollbar(outer_cfg, orient='vertical', command=cfg_canvas.yview)
        cfg = ttk.Frame(cfg_canvas)
        cfg.bind('<Configure>', lambda e: cfg_canvas.configure(scrollregion=cfg_canvas.bbox('all')))
        cfg_win = cfg_canvas.create_window((0, 0), window=cfg, anchor='nw')
        cfg_canvas.configure(yscrollcommand=cfg_vsb.set)
        cfg_canvas.pack(side='left', fill='both', expand=True)
        cfg_vsb.pack(side='right', fill='y')
        bind_scrollable(cfg_canvas)

        self.vars = {}
        ttk.Label(cfg, text="Main element").grid(row=0, column=0, sticky='w')
        self.main_box = ttk.Combobox(cfg, values=self.names, state='readonly')
        self.main_box.grid(row=0, column=1, sticky='we', pady=2)
        add_tooltip(self.main_box, "Main element airfoil (defines the wing). Select from library.")
        if 's1223' in self.names:
            self.main_box.set('s1223')

        self.role_lbl = tk.StringVar(value=FW + " (span 1400 mm)")
        ttk.Label(cfg, textvariable=self.role_lbl).grid(row=1, column=0, columnspan=2, sticky='w')
        self._role_state = tk.StringVar(value=FW)
        for r, c in ((FW, 2), (RW, 3), (CUSTOM, 4)):
            rb = tk.Radiobutton(cfg, text=r, value=r, command=self.on_role, variable=self._role_state)
            rb.grid(row=c, column=0, columnspan=2, sticky='w')
            tips = {
                'front wing': "Front wing: span 1400mm, CL*A target 1.75, CD*A roof 0.45",
                'rear wing': "Rear wing: span 950mm, CL*A target 1.85, CD*A roof 0.95",
                'custom': "Custom: span 1000mm, no regulatory targets"
            }
            add_tooltip(rb, tips.get(r, ''))

        ttk.Separator(cfg, orient='horizontal').grid(row=5, column=0, columnspan=2, sticky='we', pady=4)

        fields = [
            ('chord', 'Main chord (mm)', A.DEFAULT_CHORD_MM, "Physical chord length of the main element in millimeters. Used for force calculations and mm-scaled geometry."),
            ('speed', 'Speed (m/s)', A.DEFAULT_SPEED, "Freestream velocity in m/s. Used for dynamic pressure q = 0.5 * rho * V^2 in force model."),
            ('re', 'Reynolds number', A.RE, "Reynolds number for JavaFoil polar analysis. Typical FSAE: 570000 (300mm chord, 27.74 m/s)."),
            ('al0', 'Alpha start (deg)', A.ALPHA[0], "Starting angle of attack for polar sweep. Negative values cover stall region."),
            ('al1', 'Alpha end (deg)', A.ALPHA[1], "Ending angle of attack for polar sweep. Usually small positive for post-stall."),
            ('alst', 'Alpha step (deg)', A.ALPHA[2], "Angle increment between polar points. Smaller = more resolution, longer compute.")
        ]
        for i, (k, lab, default, tip) in enumerate(fields):
            ttk.Label(cfg, text=lab).grid(row=6 + i, column=0, sticky='w')
            v = tk.StringVar(value=str(default))
            self.vars[k] = v
            entry = ttk.Entry(cfg, textvariable=v, width=10)
            entry.grid(row=6 + i, column=1, sticky='we')
            add_tooltip(entry, tip)

        ttk.Separator(cfg, orient='horizontal').grid(row=13, column=0, columnspan=2, sticky='we', pady=4)
        ttk.Label(cfg, text="Flap configuration").grid(row=14, column=0, columnspan=2, sticky='w')

        self.flap_rows = []
        flap_fields = [
            ('S%', 'Scale % of main chord', "Flap chord as percentage of main element chord (30 = 30%)."),
            ('A°', 'Mount angle (deg)', "Flap angle relative to main element chord line. Negative = deflected down."),
            ('X%', 'X position (% chord)', "Flap leading edge X position as percentage of main chord from main LE."),
            ('Y%', 'Y position (% chord)', "Flap vertical offset as percentage of main chord. Positive = above main.")
        ]
        for k in (1, 2, 3):
            frame = ttk.Frame(cfg)
            frame.grid(row=14 + k, column=0, columnspan=2, sticky='we', pady=1)
            vals = [
                tk.StringVar(value=''),
                tk.StringVar(value='30'),
                tk.StringVar(value='-6'),
                tk.StringVar(value='100'),
                tk.StringVar(value='5'),
                tk.BooleanVar(value=False)
            ]
            ttk.Label(frame, text=f"F{k}").pack(side='left')
            cb = ttk.Combobox(frame, values=self.names, textvariable=vals[0], width=14)
            cb.pack(side='left', padx=2)
            add_tooltip(cb, "Select flap airfoil from library. Empty = no flap in this slot.")
            for (lab, _desc, tip), var in zip(flap_fields, vals[1:5]):
                entry = ttk.Entry(frame, textvariable=var, width=5)
                entry.pack(side='left', padx=1)
                add_tooltip(entry, tip)
            en_chk = ttk.Checkbutton(frame, variable=vals[5], text='', command=lambda k=k: None)
            en_chk.pack(side='left')
            add_tooltip(en_chk, "Enable this flap slot. When checked, the flap is included in simulation.")
            self.flap_rows.append((vals, cb))

        ttk.Separator(cfg, orient='horizontal').grid(row=18, column=0, columnspan=2, sticky='we', pady=4)
        ttk.Label(cfg, text="Regulation options").grid(row=19, column=0, columnspan=2, sticky='w')
        self.reg_state = tk.BooleanVar(value=True)
        reg_cb = ttk.Checkbutton(cfg, text="enforce FSUK/FSG size limits", variable=self.reg_state)
        reg_cb.grid(row=20, column=0, columnspan=2, sticky='w')
        add_tooltip(reg_cb, "Enable FSUK 2026 / FSG v1.1 size limit checks (stack height/length, ground clearance).")

        self.ge_state = tk.BooleanVar(value=True)
        ge_cb = ttk.Checkbutton(cfg, text="Ground effect", variable=self.ge_state, command=self._toggle_ground_height)
        ge_cb.grid(row=21, column=0, columnspan=2, sticky='w')
        add_tooltip(ge_cb, "Enable ground effect simulation. When off, runs unbounded flow (no ground).")

        gh_label = ttk.Label(cfg, text="Ground height (% chord):")
        gh_label.grid(row=22, column=0, sticky='w')
        self.gh_entry = ttk.Entry(cfg, textvariable=self.gh_state, width=10)
        self.gh_entry.grid(row=22, column=1, sticky='we')
        add_tooltip(self.gh_entry, "Wing height above ground as % of main chord. Only used when Ground effect is ON.")

        cs_label = ttk.Label(cfg, text="Custom span (mm):")
        cs_label.grid(row=23, column=0, sticky='w')
        cs_entry = ttk.Entry(cfg, textvariable=self.custom_span_state, width=10)
        cs_entry.grid(row=23, column=1, sticky='we')
        add_tooltip(cs_entry, "Custom wing span in mm. Only used when role is set to 'custom'.")

        chk_btn = ttk.Button(cfg, text="Sanity check geometry", command=self.on_check)
        chk_btn.grid(row=24, column=0, columnspan=2, sticky='we', pady=3)
        add_tooltip(chk_btn, "Instant PASS/FAIL against size limits. Prints exact mm vs limit and gap/overlap %. Redraws preview.")

        sim_btn = ttk.Button(cfg, text="Simulate this wing now (JavaFoil)", command=self.on_simulate)
        sim_btn.grid(row=25, column=0, columnspan=2, sticky='we', pady=3)
        add_tooltip(sim_btn, "Run single JavaFoil analysis in background. Appends row to results.csv.")

        term_btn = ttk.Button(cfg, text="Run in Terminal (konsole)", command=self.on_simulate_terminal)
        term_btn.grid(row=26, column=0, columnspan=2, sticky='we', pady=3)
        add_tooltip(term_btn, "Launch simulation in separate konsole terminal (avoids GUI fork deadlock on Linux).")

        batch_btn = ttk.Button(cfg, text="Batch: Multiple Main/Flaps", command=self.on_batch_simulate)
        batch_btn.grid(row=27, column=0, columnspan=2, sticky='we', pady=3)
        add_tooltip(batch_btn, "Run multiple main/flap combinations sequentially. Select airfoils from dialogs.")

        self.derive_state = tk.StringVar(value='')
        ttk.Label(cfg, textvariable=self.derive_state, wraplength=330, justify='left', foreground=MUTED).grid(row=29, column=0, columnspan=2, sticky='w', pady=(8, 0))

        for k in ('chord', 'speed', 're'):
            self.vars[k].trace_add('write', lambda *_: self._update_derived())
        self._update_derived()

        preview = ttk.Frame(self.tab_cfg)
        preview.pack(side='left', fill='both', expand=True, padx=6, pady=6)
        self.status = tk.Text(preview, height=10, state='disabled', wrap='word')
        self.status.pack(fill='x', pady=2)
        self.canvas = None
        try:
            import matplotlib
            matplotlib.use('TkAgg')
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
            self.figure = Figure(figsize=(6, 5), dpi=100, facecolor=PANEL2)
            self.ax = self.figure.add_subplot(111)
            self.ax.set_facecolor(BG)
            self.canvas = FigureCanvasTkAgg(self.figure, master=preview)
            self.canvas.get_tk_widget().configure(bg=BG, highlightthickness=0)
            self.canvas.get_tk_widget().pack(fill='both', expand=True)
        except Exception as e:
            self.canvas = None
            self.log(f"(geometry preview unavailable: {e})")

    def on_role(self):
        role = self._role_state.get()
        lbl = {'front wing': FW, 'rear wing': RW}.get(role, CUSTOM)
        if role == 'custom':
            try:
                span = float(self.custom_span_state.get())
            except ValueError:
                span = 1000.0
        else:
            span = {'front wing': 1400.0, 'rear wing': 950.0}.get(role, 1000.0)
        self.role_lbl.set(f"{lbl} (span {span:.0f} mm)")
        if hasattr(self, 'derive_state'):
            self._update_derived()

    def _toggle_ground_height(self):
        if self.ge_state.get():
            self.gh_entry.configure(state='normal')
        else:
            self.gh_entry.configure(state='disabled')

    def _update_derived(self):
        try:
            chord = float(self.vars['chord'].get())
            speed = float(self.vars['speed'].get())
            re_set = float(self.vars['re'].get())
            nu = 1.511e-05
            re_calc = speed * chord * 0.001 / nu
            q = 0.6125 * speed ** 2
            role = self._role_state.get()
            if role == 'front wing':
                target = "CL*A 1.75 · CD*A roof 0.45"
            elif role == 'rear wing':
                target = "CL*A 1.85 · CD*A roof 0.95"
            else:
                target = "no regulatory targets"
            self.derive_state.set(f"Derived:  Re≈{re_calc:,.0f} (entered {re_set:,.0f})  ·  q≈{q:.0f} Pa  ·  {role}: {target}")
        except (KeyError, ValueError):
            self.derive_state.set("enter numeric chord / speed / Re values")

    def read_cfg(self):
        try:
            main = self.main_box.get()
            flaps = []
            for vals, cb in self.flap_rows:
                if not vals[5].get():
                    continue
                n = vals[0].get().strip()
                if not n:
                    continue
                flaps.append((n, float(vals[1].get()), float(vals[2].get()), float(vals[3].get()), float(vals[4].get())))
            if not main:
                self.log("pick a main airfoil")
                return None
            return (main, tuple(flaps))
        except ValueError:
            self.log("bad flap value")
            return None

    def on_check(self):
        cfg = self.read_cfg()
        if not cfg:
            return
        try:
            chord = float(self.vars['chord'].get() or A.DEFAULT_CHORD_MM)
        except ValueError:
            self.log("numeric chord required")
            return
        if chord <= 0:
            self.log("chord must be positive")
            return

        unknown = sorted({n for n in (cfg[0],) + tuple(f[0] for f in cfg[1]) if n not in A.AIRFOILS})
        if unknown:
            self.log("unknown airfoil(s): " + ", ".join(unknown) + " - Refresh the airfoil list first")
            return

        if self._role_state.get() == 'custom':
            try:
                A.SPAN = float(self.custom_span_state.get())
            except ValueError:
                A.SPAN = 1000.0
        else:
            A.SPAN = ATTR[self._role_state.get()][1]

        A.CHORD_MM = chord
        A.ROLE = ATTR[self._role_state.get()][0]
        A.REG = A.default_reg()
        A.REG_ENFORCE = self.reg_state.get()

        gh0 = None
        if self.ge_state.get() and self.gh_state.get().strip() not in ('', 'none', 'None'):
            try:
                gh0 = float(self.gh_state.get())
                if gh0 <= 0:
                    self.log("ground height must be positive (% of the main chord)")
                    return
            except ValueError:
                self.log("ground height must be a number")
                return
        A.set_ground_h(gh0)

        try:
            outs = A.build_outlines(cfg, ground_h=A.GROUND_H)
        except Exception as e:
            self.log(f"geometry error: {type(e).__name__}: {e}")
            return

        msg = [f"geometry: {len(outs)} elements", "", "regulatory checks (FSUK/FSG):"]
        ok = A.geometry_ok(cfg)
        msg.append("  " + ("PASS - inside the size limits" if ok else "FAIL - violates a size limit (see below)"))

        mount = A.wing_mount_chord()
        reg_errors = A.regulatory_reject(outs, mount)
        if reg_errors:
            for err in reg_errors:
                msg.append(f"  ❌ {err['rule']}: {err['description']}")
                msg.append(f"     → Actual: {err['actual']:.1f} mm | Limit: {err['limit']:.1f} mm")
                msg.append(f"     → Suggestion: {err['fix']}")

        if not ok:
            cols = A.geometry_columns(cfg)
            role = A.ROLE
            limits = [
                ('Stack_Length_mm', 'fw_max_stack_length_mm' if role == 'fw' else 'rw_max_stack_length_mm', 'max'),
                ('Stack_Height_mm', 'fw_max_stack_height_mm' if role == 'fw' else 'rw_max_total_height_mm', 'max'),
                ('Min_Clearance_mm', 'min_ground_clearance_mm', 'min')
            ]
            for k, limit_key, direction in limits:
                limit = A.REG.get(limit_key)
                if k in cols and limit is not None:
                    val = cols[k]
                    bad = (val > limit) if direction == 'max' else (val < limit)
                    status_icon = "❌" if bad else "✅"
                    msg.append(f"  {status_icon} {k}: {val:.1f} mm (limit {limit:.1f} mm)")

        gcols = A.geometry_columns(cfg)
        for pair in A.PAIRS[:len(outs) - 1]:
            gap = gcols.get(f"{pair}_Gap_pct")
            ov = gcols.get(f"{pair}_Overlap_pct")
            gap_str = f"{gap:.1f}%" if gap is not None else "N/A"
            ov_str = f"{ov:.1f}%" if ov is not None else "N/A"
            overlap_status = "⚠️" if (ov is not None and ov > 0) else "✅"
            msg.append(f"  {pair}: gap {gap_str} | overlap {ov_str} {overlap_status}")

        self.log("\n".join(msg))
        self.draw_geometry(cfg, chord, A.GROUND_H)

    def draw_geometry(self, cfg, chord, ground_h):
        if not self.canvas:
            return
        self.ax.clear()
        try:
            outs = A.build_outlines(cfg, ground_h=ground_h)
            cols = ['#0b3d91', '#c8102e', '#0e7c4b', '#f59e0b', '#6f42c1']
            self._geometry_outs = []
            for i, o in enumerate(outs):
                o_mm = np.asarray(o, float) * chord
                self._geometry_outs.append(o_mm)
                self.ax.plot(np.append(o_mm[:, 0], o_mm[0, 0]), np.append(o_mm[:, 1], o_mm[0, 1]), color=cols[i % 5], lw=1.6, picker=5)
                self.ax.fill(np.append(o_mm[:, 0], o_mm[0, 0]), np.append(o_mm[:, 1], o_mm[0, 1]), color=cols[i % 5], alpha=0.15)
            if ground_h:
                self.ax.axhline(0, color=RULE, lw=1.2)
            self.ax.set_aspect('equal')
            self.ax.set_title("element stack (mm) - green = regulatory PASS" if A.geometry_ok(cfg) else "element stack (mm) - RED = limit FAIL", color=TXT)
            self.ax.set_xlabel("x mm", color=MUTED)
            self.ax.set_ylabel("y mm", color=MUTED)
            self.ax.tick_params(colors=MUTED)
            for spine in self.ax.spines.values():
                spine.set_color(RULE)
            if self.figure:
                self.figure.set_facecolor(PANEL2)
            self._hover_annot = self.ax.annotate(
                '', xy=(0, 0), xytext=(20, 20), textcoords='offset points',
                bbox=dict(boxstyle='round,pad=0.5', fc='#1e293b', ec='#f79e0b', lw=1.5),
                fontsize=9, ha='left', va='bottom', visible=False,
                color='#f8fafc', zorder=100
            )
            if not hasattr(self, '_hover_cid'):
                self._hover_cid = self.canvas.mpl_connect('motion_notify_event', self._on_geometry_hover)
            if not hasattr(self, '_leave_cid'):
                self._leave_cid = self.canvas.mpl_connect('figure_leave_event', self._on_geometry_leave)
            self.canvas.draw()
        except Exception as e:
            self.ax.set_title(f"geometry error: {type(e).__name__}", color=TXT)
            self.canvas.draw_idle()

    def _on_geometry_leave(self, event=None):
        if hasattr(self, '_hover_annot') and self._hover_annot:
            self._hover_annot.set_visible(False)
            if self.canvas:
                self.canvas.draw_idle()

    def _on_geometry_hover(self, event):
        if event.inaxes != self.ax or not hasattr(self, '_geometry_outs') or not self._geometry_outs:
            if hasattr(self, '_hover_annot') and self._hover_annot:
                self._hover_annot.set_visible(False)
                if self.canvas:
                    self.canvas.draw_idle()
            return
        x = event.xdata
        y = event.ydata
        if x is None or y is None:
            if hasattr(self, '_hover_annot') and self._hover_annot:
                self._hover_annot.set_visible(False)
                if self.canvas:
                    self.canvas.draw_idle()
            return

        from matplotlib.path import Path
        best_dist = float('inf')
        best_info = None

        try:
            chord = float(self.vars['chord'].get() or A.DEFAULT_CHORD_MM)
        except Exception:
            chord = A.DEFAULT_CHORD_MM

        threshold = max(25.0, chord * 0.08)

        for elem_idx, elem in enumerate(self._geometry_outs):
            elem = np.asarray(elem, float)
            dists = np.hypot(elem[:, 0] - x, elem[:, 1] - y)
            min_d = float(dists.min())
            is_inside = False
            try:
                is_inside = Path(elem).contains_point((x, y))
            except Exception:
                pass

            if is_inside or min_d < threshold:
                effective_dist = 0.0 if is_inside else min_d
                if effective_dist < best_dist:
                    best_dist = effective_dist
                    j = int(dists.argmin())
                    px, py = elem[j]
                    prev_pt = elem[(j - 1) % len(elem)]
                    next_pt = elem[(j + 1) % len(elem)]
                    seg1_len = float(np.hypot(px - prev_pt[0], py - prev_pt[1]))
                    seg2_len = float(np.hypot(next_pt[0] - px, next_pt[1] - py))
                    best_info = {
                        'elem': elem_idx,
                        'point': (float(px), float(py)),
                        'seg1_len': seg1_len,
                        'seg2_len': seg2_len,
                        'is_inside': is_inside,
                    }

        if best_info and hasattr(self, '_hover_annot') and self._hover_annot:
            px, py = best_info['point']
            names = ['Main', 'Flap 1', 'Flap 2', 'Flap 3']
            elem_name = names[best_info['elem']] if best_info['elem'] < len(names) else f"Element {best_info['elem'] + 1}"
            limit_text = ''
            if A.CHORD_MM and getattr(self, 'reg_state', None) and self.reg_state.get():
                role = getattr(A, 'ROLE', 'fw')
                if role == 'fw':
                    limits = [
                        ('Stack Length', A.REG.get('fw_max_stack_length_mm', 500), 'mm'),
                        ('Stack Height', A.REG.get('fw_max_stack_height_mm', 250), 'mm'),
                        ('Min Clearance', A.REG.get('min_ground_clearance_mm', 30), 'mm')
                    ]
                else:
                    limits = [
                        ('Stack Length', A.REG.get('rw_max_stack_length_mm', 350), 'mm'),
                        ('Total Height', A.REG.get('rw_max_total_height_mm', 1100), 'mm'),
                        ('Min Clearance', A.REG.get('min_ground_clearance_mm', 30), 'mm')
                    ]
                limit_text = "\nRegulatory Limits:\n" + "\n".join([f"  {n}: {lim} {u}" for n, lim, u in limits])

            text = f"{elem_name} Element\nPoint: ({px:.1f}, {py:.1f}) mm\nCursor: ({x:.1f}, {y:.1f}) mm\nSegment lengths: {best_info['seg1_len']:.1f} mm | {best_info['seg2_len']:.1f} mm{limit_text}"
            self._hover_annot.xy = (px, py)
            self._hover_annot.set_text(text)
            self._hover_annot.set_visible(True)
            self.canvas.draw_idle()
            return

        if hasattr(self, '_hover_annot') and self._hover_annot:
            self._hover_annot.set_visible(False)
            self.canvas.draw_idle()

    def on_simulate(self):
        cfg = self.read_cfg()
        if not cfg:
            return
        if getattr(self, '_sim_running', False):
            self.log("a simulation is already running")
            return
        try:
            chord0 = float(self.vars['chord'].get())
            speed0 = float(self.vars['speed'].get())
            re0 = float(self.vars['re'].get())
        except ValueError:
            self.log("numeric chord/speed/RE required")
            return

        role_str = self._role_state.get()
        role0 = ATTR[role_str][0]
        if role_str == 'custom':
            try:
                span0 = float(self.custom_span_state.get())
            except ValueError:
                span0 = 1000.0
        else:
            span0 = ATTR[role_str][1]

        gh0 = None
        if self.ge_state.get() and self.gh_state.get().strip() not in ('', 'none', 'None'):
            try:
                gh0 = float(self.gh_state.get())
                if gh0 <= 0:
                    self.log("ground height must be positive (% of the main chord)")
                    return
            except ValueError:
                self.log("ground height must be a number")
        if not A.is_java_available():
            messagebox.showerror(
                "Java Runtime Required",
                "Java Runtime (JRE / JDK) is required to run JavaFoil simulations, but was not found on your system.\n\n"
                "Please download and install Java (e.g. Eclipse Temurin from https://adoptium.net) "
                "and ensure Java is installed on your computer."
            )
            self.log("Simulation aborted: Java runtime not found.")
            return

        jf, _ = A.find_java_jars()
        if not (os.path.isabs(jf) and os.path.isfile(jf)):
            messagebox.showerror(
                "JavaFoil Jar Not Found",
                f"Could not locate '{A.JAVAFOIL_JAR}'.\n"
                f"Please ensure javafoil.jar is located in the app's 'assets/JavaFoil/' folder or set the AERO_JAVA_DIR environment variable."
            )
            self.log("Simulation aborted: javafoil.jar not found.")
            return

        reg0 = self.reg_state.get()
        desc = cfg[0]

        prog = tk.Toplevel(self)
        prog.title("Simulating...")
        prog.geometry("360x120")
        prog.transient(self)
        prog.grab_set()
        ttk.Label(prog, text=f"Running JavaFoil simulation...\n{desc} + flaps\nThis may take 10-30 seconds.").pack(padx=20, pady=15)
        pb = ttk.Progressbar(prog, mode='indeterminate', length=300)
        pb.pack(padx=20, pady=(0, 15))
        pb.start(100)
        self._sim_prog = prog
        self._sim_running = True

        try:
            run_dir, results_path = self._new_run(
                'single', desc, main=desc,
                flow='ground' if gh0 else 'unbounded',
                height_pct=gh0, n_runs=0
            )
        except Exception as e:
            self._sim_running = False
            prog.destroy()
            self.log(f"could not create run folder: {e}")
            return

        self.log(f"simulating {desc} + flaps at alpha {A.ALPHA[0]}..{A.ALPHA[1]} step {A.ALPHA[2]}, RE={re0:g}, {'ground' if gh0 else 'unbounded'} ...")

        def work():
            try:
                A.RE = re0
                A.SPEED = speed0
                A.CHORD_MM = chord0
                A.ROLE = role0
                A.SPAN = span0
                A.REG = A.default_reg()
                A.REG_ENFORCE = reg0
                A.set_ground_h(gh0)
                A.RESULTS_FILE[0] = results_path
                row = A.run_one(cfg, 'ui', gh0)
                A.write_run_meta(run_dir, n_runs=1, status=row.get('Status'), score=row.get('Score'))
                self.ui_q.put(('sim_done', (row, None)))
            except Exception as e:
                import traceback
                self.ui_q.put(('sim_done', (None, f"{e}\n" + traceback.format_exc()[-1200:])))

        threading.Thread(target=work, daemon=True).start()

    def _sim_done(self, payload):
        row, err = payload
        self._sim_running = False
        prog = getattr(self, '_sim_prog', None)
        if prog:
            try:
                prog.destroy()
            except Exception:
                pass
            self._sim_prog = None
        if err:
            self.log(f"simulate failed: {err}")
            return
        if not row:
            return

        def f(k, spec=''):
            v = row.get(k)
            if v is None:
                return '--'
            try:
                return format(float(v), spec) if spec else str(v)
            except (ValueError, TypeError):
                return str(v)

        self.log(
            f"result: {row.get('Run_ID')} {row.get('Status')} | "
            f"Cl@0 {f('Cl_a0', '.3f')}  Cd@0 {f('Cd_a0', '.4f')}  max|L/D| {f('Max_LD', '.1f')}  "
            f"stall {row.get('Stall_Angle')} deg | downforce {f('Downforce_N', '.0f')} N"
        )
        self.load_results_cache()
        self.refresh_graph_files()
        self._refresh_runs()

    def on_simulate_terminal(self):
        cfg = self.read_cfg()
        if not cfg:
            return
        try:
            re0 = float(self.vars['re'].get())
            chord0 = float(self.vars['chord'].get())
            speed0 = float(self.vars['speed'].get())
            role0 = ATTR[self._role_state.get()][0]
            reg0 = self.reg_state.get()
            gh0 = None
            if self.ge_state.get() and self.gh_state.get().strip() not in ('', 'none', 'None'):
                gh0 = float(self.gh_state.get())
                if gh0 <= 0:
                    self.log("ground height must be positive (% of the main chord)")
                    return
        except ValueError:
            self.log("numeric chord/speed/RE required")
            return

        main = self.main_box.get()
        flaps = []
        try:
            for vals, cb in self.flap_rows:
                if not vals[5].get():
                    continue
                n = vals[0].get().strip()
                if not n:
                    continue
                flaps.append((n, float(vals[1].get()), float(vals[2].get()), float(vals[3].get()), float(vals[4].get())))
        except ValueError:
            self.log("bad flap value")
            return

        import json
        import tempfile
        import subprocess

        try:
            run_dir, results_path = self._new_run('single', main, main=main, flow='ground' if gh0 else 'unbounded', height_pct=gh0, n_runs=0, terminal=True)
            config = {
                'main': main,
                'flaps': flaps,
                're': re0,
                'chord': chord0,
                'speed': speed0,
                'role': role0,
                'reg_enforce': reg0,
                'ground_h': gh0,
                'results_file': results_path
            }
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(config, f)
                config_file = f.name
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_sim_terminal.py')
            terminal_bin = shutil.which('konsole') or shutil.which('xterm') or shutil.which('gnome-terminal')
            if not terminal_bin:
                self.log("No terminal emulator found (konsole/xterm/gnome-terminal)")
                return
            subprocess.Popen([terminal_bin, '-e', sys.executable, script, config_file])
            self.log(f"Launched simulation in terminal: {terminal_bin}")
        except Exception as e:
            self.log(f"Failed to launch terminal: {e}")

    def on_batch_simulate(self):
        try:
            re0 = float(self.vars['re'].get())
            chord0 = float(self.vars['chord'].get())
            speed0 = float(self.vars['speed'].get())
            role0 = ATTR[self._role_state.get()][0]
            reg0 = self.reg_state.get()
            gh0 = None
            if self.ge_state.get() and self.gh_state.get().strip() not in ('', 'none', 'None'):
                gh0 = float(self.gh_state.get())
                if gh0 <= 0:
                    self.log("ground height must be positive (% of the main chord)")
                    return
        except ValueError:
            self.log("numeric chord/speed/RE required")
            return

        flaps = []
        for vals, cb in self.flap_rows:
            if not vals[5].get():
                continue
            n = vals[0].get().strip()
            if not n:
                continue
            flaps.append((n, float(vals[1].get()), float(vals[2].get()), float(vals[3].get()), float(vals[4].get())))

        main_list = self._select_airfoils_dialog(
            "Batch Simulate - Main Airfoils",
            "Select main airfoils (Ctrl+Click for multiple):",
            self.names,
            [self.main_box.get()] if self.main_box.get() in self.names else []
        )
        if not main_list:
            return

        vary_flaps = messagebox.askyesno("Vary Flaps?", "Also vary flap airfoils? If Yes, you'll select flap airfoils for each slot.")
        flap_lists = []
        if vary_flaps and flaps:
            for i, (fname, s, a, x, y) in enumerate(flaps, 1):
                flist = self._select_airfoils_dialog(
                    f"Batch Simulate - Flap F{i} Airfoils",
                    f"Select airfoils for Flap F{i} (Ctrl+Click for multiple):\nCurrent: {fname}",
                    self.names,
                    [fname] if fname in self.names else []
                )
                if not flist:
                    return
                flap_lists.append(flist)
        else:
            flap_lists = [[f[0]] for f in flaps]

        import itertools
        combinations = []
        for main in main_list:
            for flap_combo in itertools.product(*flap_lists):
                flap_tuples = []
                for fname, (_, s, a, x, y) in zip(flap_combo, flaps):
                    flap_tuples.append((fname, s, a, x, y))
                combinations.append((main, tuple(flap_tuples)))

        if not combinations:
            self.log("No valid combinations")
            return
        if not messagebox.askyesno("Confirm Batch", f"Run {len(combinations)} simulations?"):
            return

        try:
            run_dir, results_path = self._new_run(
                'batch', f"{len(combinations)}x{main_list[0]}",
                n_mains=len(main_list), n_runs=0,
                flow='ground' if gh0 else 'unbounded', height_pct=gh0
            )
        except Exception as e:
            self.log(f"could not create run folder: {e}")
            return

        def work():
            A.RE = re0
            A.SPEED = speed0
            A.CHORD_MM = chord0
            A.ROLE = role0
            A.REG = A.default_reg()
            A.REG_ENFORCE = reg0
            A.set_ground_h(gh0)
            A.RESULTS_FILE[0] = results_path
            n_ok = 0
            self.log(f"Batch: {len(combinations)} configs at RE={re0:g}")
            for idx, (main, flap_cfg) in enumerate(combinations, 1):
                try:
                    cfg = (main, flap_cfg)
                    row = A.run_one(cfg, 'batch', gh0)
                    status = row.get('Status', 'Unknown')
                    if status == 'Valid':
                        n_ok += 1
                    df = f"{row.get('Downforce_N', 0):.0f}" if row.get('Downforce_N') else 'N/A'
                    self.log(f"[{idx}/{len(combinations)}] {main} | {status} | Df={df}N")
                except Exception as e:
                    self.log(f"[{idx}/{len(combinations)}] {main} | ERROR: {e}")
            A.write_run_meta(run_dir, n_runs=len(combinations), n_valid=n_ok)
            self.ui_q.put(('load', None))
            self.log(f"Batch complete: {len(combinations)} runs")

        threading.Thread(target=work, daemon=True).start()

    def _select_airfoils_dialog(self, title, prompt, all_names, defaults):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.geometry("400x500")
        ttk.Label(dialog, text=prompt).pack(padx=10, pady=10, anchor='w')
        frame = ttk.Frame(dialog)
        frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        lb = tk.Listbox(frame, selectmode='extended', height=20)
        lb.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(frame, orient='vertical', command=lb.yview)
        sb.pack(side='right', fill='y')
        lb.configure(yscrollcommand=sb.set)
        for name in all_names:
            lb.insert('end', name)
        for i, name in enumerate(all_names):
            if name in defaults:
                lb.selection_set(i)
                lb.see(i)
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill='x', padx=10, pady=10)
        result = []

        def on_ok():
            nonlocal result
            result = [all_names[i] for i in lb.curselection()]
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side='right', padx=5)
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side='right', padx=5)
        self.wait_window(dialog)
        return result

    # --- AIRFOILS TAB ---
    def build_airfoils(self):
        af = ttk.Frame(self.tab_af)
        af.pack(fill='both', expand=True, padx=8, pady=8)
        head = ttk.Frame(af)
        head.pack(fill='x')
        imp_btn = ttk.Button(head, text="Import airfoil (.dat)...", command=self.on_import_airfoil)
        imp_btn.pack(side='left')
        add_tooltip(imp_btn, "Copy one or more .dat files into the internal airfoil store. They will appear in all combos immediately.")
        imp_fold_btn = ttk.Button(head, text="Import folder...", command=self.on_import_airfoil_folder)
        imp_fold_btn.pack(side='left', padx=4)
        add_tooltip(imp_fold_btn, "Recursively import all .dat airfoil files from a chosen folder.")
        ttk.Label(head, text="   Store: ").pack(side='left')
        self.store_lbl = tk.StringVar(value=os.path.expanduser(A.AIRFOIL_STORE))
        ttk.Label(head, textvariable=self.store_lbl).pack(side='left')

        self.af_log = tk.Text(af, height=8, state='disabled', wrap='word')
        self.af_log.pack(fill='x', pady=(6, 2))
        add_tooltip(self.af_log, "Import/remove operations log.")

        frow = ttk.Frame(af)
        frow.pack(fill='x')
        ttk.Label(frow, text="Filter store:").pack(side='left')
        self.af_filter = tk.StringVar(value='')
        f_entry = ttk.Entry(frow, textvariable=self.af_filter, width=30)
        f_entry.pack(side='left', padx=4)
        self.af_filter.trace_add('write', lambda *_: self._apply_af_filter())
        add_tooltip(f_entry, "Live filter on the store list below (name / path substring).")
        self.af_count = tk.StringVar(value='')
        ttk.Label(frow, textvariable=self.af_count, foreground=MUTED).pack(side='left', padx=6)
        ttk.Button(frow, text="Clear", command=lambda: self.af_filter.set('')).pack(side='left')

        body = ttk.Frame(af)
        body.pack(fill='both', expand=True)
        self.af_list = tk.Listbox(body, height=16)
        self.af_list.pack(side='left', fill='both', expand=True)
        add_tooltip(self.af_list, "All airfoils in the internal store (~/.aero_auto/airfoils). Select one to remove.")
        sc = ttk.Scrollbar(body, command=self.af_list.yview)
        self.af_list.configure(yscrollcommand=sc.set)
        sc.pack(side='left', fill='y')

        side = ttk.Frame(body)
        side.pack(side='left', fill='y', padx=8)
        open_btn = ttk.Button(side, text="Open store folder", command=self.on_open_store)
        open_btn.pack(fill='x', pady=2)
        add_tooltip(open_btn, "Open the internal airfoil store folder in your file manager.")
        rem_btn = ttk.Button(side, text="Remove selected", command=self.on_remove_airfoil)
        rem_btn.pack(fill='x', pady=2)
        add_tooltip(rem_btn, "Delete the selected airfoil from the internal store (does not affect original .dat files).")
        ref_btn = ttk.Button(side, text="Refresh", command=self.on_refresh_airfoils)
        ref_btn.pack(fill='x', pady=2)
        add_tooltip(ref_btn, "Re-scan the store and AIRFOIL_DIR in case files changed on disk.")
        ttk.Label(side, text="\nAirfoils you add here\nare saved inside the app\ndata folder and appear in\nthe Configure tab combos\nimmediately.", justify='left').pack(anchor='w', pady=10)
        self.refresh_store_list()

    def refresh_store_list(self):
        try:
            fn = getattr(A, 'list_store', getattr(A, 'list_store_airfoils', None))
            self._af_entries = sorted(fn()) if fn else []
        except Exception:
            self._af_entries = []
        self._apply_af_filter()

    def _apply_af_filter(self):
        q = self.af_filter.get().strip().lower()
        if q:
            shown = [(n, p) for n, p in getattr(self, '_af_entries', []) if q in (n + ' ' + os.path.basename(p)).lower()]
        else:
            shown = getattr(self, '_af_entries', [])
        self.af_list.delete(0, 'end')
        for name, path in shown:
            self.af_list.insert('end', f"{name}   ({os.path.basename(path)})")
        self.af_count.set(f"{len(shown)} of {len(getattr(self, '_af_entries', []))} in store")

    def on_import_airfoil(self):
        paths = filedialog.askopenfilenames(
            title="Select Airfoil Profile File(s)",
            filetypes=[('Airfoil profiles (*.dat, *.txt, *.cor, *.csv)', '*.dat *.DAT *.txt *.TXT *.cor *.csv'), ('All files', '*.*')]
        )
        if not paths:
            return
        successes = 0
        for p in paths:
            default_name = os.path.splitext(os.path.basename(p))[0]
            name = default_name
            if len(paths) == 1:
                user_name = simpledialog.askstring("Name this airfoil", "Name shown in the app:", initialvalue=default_name)
                if user_name is None:
                    return
                if user_name.strip():
                    name = user_name.strip()
            try:
                store_name, dst = A.install_airfoil(p, name)
                self.af_log_put(f"imported '{store_name}' -> {dst}")
                successes += 1
            except Exception as e:
                self.af_log_put(f"failed importing '{os.path.basename(p)}': {e}")
        if successes > 0:
            fresh = A.load_all(A.AIRFOIL_STORE)
            A.AIRFOILS.update(fresh)
            self.refresh_airfoils()
            self.refresh_store_list()
            self.af_log_put(f"Imported {successes} airfoil(s) successfully.")

    def on_import_airfoil_folder(self):
        folder = filedialog.askdirectory(title="Select Folder with Airfoils (.dat, .txt, .cor)")
        if not folder:
            return
        candidates = []
        for root, _, files in os.walk(folder):
            for f in sorted(files):
                p = os.path.join(root, f)
                # match .dat, .txt, .cor, .csv, or extensionless coordinate files
                if f.lower().endswith(('.dat', '.txt', '.cor', '.csv')) or ('.' not in f and os.path.getsize(p) < 1000000):
                    try:
                        c, _ = A.load_airfoil(p)
                        if c is not None:
                            candidates.append(p)
                    except Exception:
                        pass
        if not candidates:
            messagebox.showinfo("No Airfoils Found", f"No valid airfoil coordinate files found in:\n{folder}")
            return
        successes = 0
        for p in candidates:
            name = os.path.splitext(os.path.basename(p))[0]
            try:
                store_name, dst = A.install_airfoil(p, name)
                self.af_log_put(f"imported '{store_name}' -> {dst}")
                successes += 1
            except Exception as e:
                self.af_log_put(f"failed '{os.path.basename(p)}': {e}")
        if successes > 0:
            fresh = A.load_all(A.AIRFOIL_STORE)
            A.AIRFOILS.update(fresh)
            self.refresh_airfoils()
            self.refresh_store_list()
            self.af_log_put(f"Batch imported {successes} airfoil(s) from {folder}")
            messagebox.showinfo("Import Complete", f"Imported {successes} airfoil(s) into the app store.")

    def on_remove_airfoil(self):
        sel = self.af_list.curselection()
        if not sel:
            return
        line = self.af_list.get(sel[0])
        name = line.split('(')[0].strip()
        if not messagebox.askyesno("Remove airfoil", f"Remove '{name}' from the app store?"):
            return
        if A.remove_store_airfoil(name):
            A.AIRFOILS.pop(name, None)
            self.refresh_airfoils()
            self.refresh_store_list()
            self.af_log_put(f"removed '{name}'")

    def on_open_store(self):
        os.makedirs(A.AIRFOIL_STORE, exist_ok=True)
        try:
            subprocess_open(A.AIRFOIL_STORE)
        except Exception as e:
            self.af_log_put(f"open failed: {e}")

    def on_refresh_airfoils(self):
        self.refresh_airfoils()
        self.refresh_store_list()
        self.af_log_put("airfoil list refreshed from disk")

    def af_log_put(self, s):
        self._append_log(self.af_log, s)

    def refresh_airfoils(self):
        try:
            fresh = A.load_all(A.AIRFOIL_DIR)
            fresh.update(A.load_all(A.AIRFOIL_STORE))
            A.AIRFOILS = fresh
            self.names = sorted(A.AIRFOILS.keys())
            if not self.names:
                self.log("no airfoils found - check the airfoil folder")
            vals = list(self.names)
            box = getattr(self, 'main_box', None)
            if box:
                box.configure(values=vals)
                if box.get() not in self.names:
                    box.set(vals[0] if vals else '')
            for vals_, cb in getattr(self, 'flap_rows', []):
                cb.configure(values=vals)
                if vals_ and vals_[0].get() and vals_[0].get() not in self.names:
                    vals_[0].set('')
            self._rebuild_airfoil_consumers()
        except (Exception, SystemExit) as e:
            self.log(f"airfoil refresh failed: {e}")

    def _rebuild_airfoil_consumers(self):
        vals = list(self.names)
        cb = getattr(self, 'opt_main_box', None)
        if cb is not None:
            cur = cb.get()
            cb.configure(values=vals)
            if cur not in self.names:
                self.opt_main_box.set(self.names[0] if self.names else '')
        for vals_, cb in getattr(self, 'opt_flap_rows', []):
            cb.configure(values=vals)
            if vals_ and vals_[0].get() and vals_[0].get() not in self.names:
                vals_[0].set('')
        for lb in (getattr(self, 'cam_mains', None), getattr(self, 'cam_flaps', None)):
            if lb is None:
                continue
            chosen = {lb.get(i) for i in lb.curselection()}
            lb.delete(0, 'end')
            for n in self.names:
                lb.insert('end', n)
            for i, n in enumerate(self.names):
                if n in chosen:
                    lb.selection_set(i)
        self._update_statusbar()

    # --- FAMOUS WINGS TAB ---
    def build_famous_wings(self):
        comb = ttk.Frame(self.tab_comb)
        comb.pack(fill='both', expand=True, padx=6, pady=6)

        paned = ttk.PanedWindow(comb, orient='horizontal')
        paned.pack(fill='both', expand=True)

        # Left pane: Filter & Packages list
        left_pane = ttk.Frame(paned, width=390)
        paned.add(left_pane, weight=1)

        filter_frame = ttk.LabelFrame(left_pane, text="Filter Championship & Competition Wings")
        filter_frame.pack(fill='x', padx=4, pady=4)

        f_row1 = ttk.Frame(filter_frame)
        f_row1.pack(fill='x', padx=4, pady=2)
        ttk.Label(f_row1, text="Search:").pack(side='left')
        self.comb_filter = tk.StringVar(value='')
        comb_search_ent = ttk.Entry(f_row1, textvariable=self.comb_filter)
        comb_search_ent.pack(side='left', fill='x', expand=True, padx=4)
        add_tooltip(comb_search_ent, "Filter by team name, competition, year, car model, or airfoil.")

        f_row2 = ttk.Frame(filter_frame)
        f_row2.pack(fill='x', padx=4, pady=2)
        ttk.Label(f_row2, text="Comp:").pack(side='left')
        self.comb_comp = tk.StringVar(value='All Competitions')
        comp_choices = [
            'All Competitions',
            'FSG (Germany)',
            'FSAE Michigan (USA)',
            'FSA (Austria)',
            'FS Switzerland',
            'FSUK (UK)',
            'FS East (Hungary)',
            'FS Italy',
            'FS Netherlands',
            'FS Spain',
            'Wind Tunnel Benchmark'
        ]
        comp_cb = ttk.Combobox(f_row2, textvariable=self.comb_comp, values=comp_choices, state='readonly', width=17)
        comp_cb.pack(side='left', padx=2)
        add_tooltip(comp_cb, "Filter by Formula Student competition series.")

        ttk.Label(f_row2, text="Role:").pack(side='left', padx=(4, 0))
        self.comb_cat = tk.StringVar(value='All Wings')
        cat_cb = ttk.Combobox(f_row2, textvariable=self.comb_cat,
                              values=['All Wings', 'Front Wing', 'Rear Wing', 'Benchmark'],
                              state='readonly', width=11)
        cat_cb.pack(side='left', padx=2)
        add_tooltip(cat_cb, "Filter by wing position.")

        f_row3 = ttk.Frame(filter_frame)
        f_row3.pack(fill='x', padx=4, pady=(2, 4))
        self.comb_count_lbl = tk.StringVar(value='')
        ttk.Label(f_row3, textvariable=self.comb_count_lbl, foreground=MUTED, font=('TkDefaultFont', 8)).pack(side='left')
        ttk.Button(f_row3, text="Clear Filters", command=self._clear_comb_filters).pack(side='right')

        self.comb_filter.trace_add('write', lambda *_: self._apply_comb_filter())
        self.comb_comp.trace_add('write', lambda *_: self._apply_comb_filter())
        self.comb_cat.trace_add('write', lambda *_: self._apply_comb_filter())

        tree_frame = ttk.Frame(left_pane)
        tree_frame.pack(fill='both', expand=True, padx=4, pady=4)

        self.comb_tree = ttk.Treeview(tree_frame, columns=('comp', 'year', 'role', 'els'), show='headings', selectmode='browse', height=14)
        self.comb_tree['columns'] = ('name', 'comp', 'year', 'role', 'els')
        self.comb_tree.heading('name', text='Car & Wing Package')
        self.comb_tree.heading('comp', text='Competition')
        self.comb_tree.heading('year', text='Year')
        self.comb_tree.heading('role', text='Role')
        self.comb_tree.heading('els', text='Elements')

        self.comb_tree.column('name', width=190, anchor='w')
        self.comb_tree.column('comp', width=95, anchor='w')
        self.comb_tree.column('year', width=45, anchor='center')
        self.comb_tree.column('role', width=75, anchor='center')
        self.comb_tree.column('els', width=55, anchor='center')

        comb_sc = ttk.Scrollbar(tree_frame, orient='vertical', command=self.comb_tree.yview)
        self.comb_tree.configure(yscrollcommand=comb_sc.set)
        self.comb_tree.pack(side='left', fill='both', expand=True)
        comb_sc.pack(side='right', fill='y')

        self.comb_tree.bind('<<TreeviewSelect>>', lambda e: self._on_comb_select())
        self.comb_tree.bind('<Double-1>', lambda e: self._comb_load_to_configure())
        add_tooltip(self.comb_tree, "Click to inspect values & profile. Double-click to load into Configure (Tab 1).")

        ttk.Label(left_pane,
                  text="💡 Double-click any configuration to load it into Configure (Tab 1).\nUse action buttons on the right to simulate, optimize, or export DXF.",
                  foreground=MUTED, justify='left', wraplength=370).pack(anchor='w', padx=6, pady=4)

        # Right pane: Inspector, Visualizer & Actions
        right_pane = ttk.Frame(paned)
        paned.add(right_pane, weight=3)

        header_card = tk.Frame(right_pane, bg=PANEL, bd=1, relief='solid')
        header_card.pack(fill='x', padx=4, pady=4)

        top_h = tk.Frame(header_card, bg=PANEL)
        top_h.pack(fill='x', padx=8, pady=(6, 2))

        self.comb_title_var = tk.StringVar(value="Select a Wing Package")
        self.comb_title_lbl = tk.Label(top_h, textvariable=self.comb_title_var, font=('TkDefaultFont', 12, 'bold'),
                                       bg=PANEL, fg=ACCENT, anchor='w')
        self.comb_title_lbl.pack(side='left')

        self.comb_rules_badge = tk.Label(top_h, text="✅ 100% FSUK / FSG Compliant",
                                         bg='#064e3b', fg='#34d399', font=('TkDefaultFont', 8, 'bold'),
                                         padx=6, pady=2)
        self.comb_rules_badge.pack(side='right')

        sub_h = tk.Frame(header_card, bg=PANEL)
        sub_h.pack(fill='x', padx=8, pady=(0, 2))
        self.comb_achieve_var = tk.StringVar(value="")
        tk.Label(sub_h, textvariable=self.comb_achieve_var, font=('TkDefaultFont', 9, 'bold'),
                 bg=PANEL, fg='#f59e0b', anchor='w').pack(side='left')

        team_h = tk.Frame(header_card, bg=PANEL)
        team_h.pack(fill='x', padx=8, pady=(0, 4))
        self.comb_team_var = tk.StringVar(value="")
        tk.Label(team_h, textvariable=self.comb_team_var, font=('TkDefaultFont', 9),
                 bg=PANEL, fg=SKY, anchor='w').pack(side='left')

        # Badges row
        badge_row = tk.Frame(header_card, bg=PANEL)
        badge_row.pack(fill='x', padx=8, pady=(0, 6))

        self.comb_badge_comp = tk.Label(badge_row, text="", bg=PANEL2, fg='#38bdf8', font=('TkDefaultFont', 8, 'bold'), padx=6, pady=2)
        self.comb_badge_comp.pack(side='left', padx=(0, 4))
        self.comb_badge_cat = tk.Label(badge_row, text="", bg=PANEL2, fg=TXT, font=('TkDefaultFont', 8), padx=6, pady=2)
        self.comb_badge_cat.pack(side='left', padx=4)
        self.comb_badge_els = tk.Label(badge_row, text="", bg=PANEL2, fg=TXT, font=('TkDefaultFont', 8), padx=6, pady=2)
        self.comb_badge_els.pack(side='left', padx=4)
        self.comb_badge_aero = tk.Label(badge_row, text="", bg=PANEL2, fg=TXT, font=('TkDefaultFont', 8), padx=6, pady=2)
        self.comb_badge_aero.pack(side='left', padx=4)
        self.comb_badge_span = tk.Label(badge_row, text="", bg=PANEL2, fg=TXT, font=('TkDefaultFont', 8), padx=6, pady=2)
        self.comb_badge_span.pack(side='left', padx=4)

        act_frame = ttk.Frame(right_pane)
        act_frame.pack(fill='x', padx=4, pady=2)

        btn_cfg = ttk.Button(act_frame, text="🚀 Load to Configure (Tab 1)", command=self._comb_load_to_configure)
        btn_cfg.pack(side='left', padx=2)
        add_tooltip(btn_cfg, "Load airfoils, angles, and geometry into Configure (Tab 1) and calculate sizing.")

        btn_opt = ttk.Button(act_frame, text="🎯 Send to Optimizer (Tab 6)", command=self._comb_send_to_optimizer)
        btn_opt.pack(side='left', padx=2)
        add_tooltip(btn_opt, "Set this package as baseline in Tab 6 Optimizer to refine downforce and pitch stability.")

        btn_sim = ttk.Button(act_frame, text="🏎️ Run Simulation Now", command=self._comb_simulate_now)
        btn_sim.pack(side='left', padx=2)
        add_tooltip(btn_sim, "Instantly run JavaFoil analysis on this package and record aerodynamic forces in Results.")

        btn_dxf = ttk.Button(act_frame, text="📐 Export AutoCAD DXF", command=self._comb_export_dxf)
        btn_dxf.pack(side='left', padx=2)
        add_tooltip(btn_dxf, "Export precise 2D spline airfoil outlines to AutoCAD DXF for SolidWorks / CAD / CFD.")

        geom_container = ttk.Frame(right_pane)
        geom_container.pack(fill='both', expand=True, padx=4, pady=4)

        self.comb_canvas = None
        self.comb_ax = None
        self.comb_fig = None
        try:
            import matplotlib
            matplotlib.use('TkAgg')
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
            self.comb_fig = Figure(figsize=(6, 3.2), dpi=100, facecolor=PANEL2)
            self.comb_ax = self.comb_fig.add_subplot(111)
            self.comb_ax.set_facecolor(BG)
            self.comb_canvas = FigureCanvasTkAgg(self.comb_fig, master=geom_container)
            self.comb_canvas.get_tk_widget().configure(bg=BG, highlightthickness=0)
            self.comb_canvas.get_tk_widget().pack(fill='both', expand=True)
        except Exception as e:
            self.comb_canvas = None
            ttk.Label(geom_container, text=f"(geometry preview unavailable: {e})").pack()

        bot_nb = ttk.Notebook(right_pane)
        bot_nb.pack(fill='both', expand=True, padx=4, pady=2)

        # Tab 1: Element Stack Table
        t1_frame = ttk.Frame(bot_nb)
        bot_nb.add(t1_frame, text="  📐 Element Stack & Alignment  ")

        self.comb_stack_tree = ttk.Treeview(t1_frame, columns=('el', 'foil', 'scale', 'angle', 'x', 'y', 'gap', 'overlap'),
                                            show='headings', height=5)
        cols_cfg = [
            ('el', 'Element', 70, 'center'),
            ('foil', 'Airfoil Profile', 150, 'w'),
            ('scale', 'Scale %', 70, 'center'),
            ('angle', 'Mount Angle', 90, 'center'),
            ('x', 'X Position %', 90, 'center'),
            ('y', 'Y Position %', 90, 'center'),
            ('gap', 'Slot Gap %', 90, 'center'),
            ('overlap', 'Overlap %', 90, 'center'),
        ]
        for cid, chead, cwidth, canchor in cols_cfg:
            self.comb_stack_tree.heading(cid, text=chead)
            self.comb_stack_tree.column(cid, width=cwidth, anchor=canchor)

        stack_sc = ttk.Scrollbar(t1_frame, orient='vertical', command=self.comb_stack_tree.yview)
        self.comb_stack_tree.configure(yscrollcommand=stack_sc.set)
        self.comb_stack_tree.pack(side='top', fill='both', expand=True)
        stack_sc.pack(side='right', fill='y')

        self.comb_dims_var = tk.StringVar(value="")
        tk.Label(t1_frame, textvariable=self.comb_dims_var, bg=BG, fg=MUTED, font=('TkDefaultFont', 8),
                 justify='left', anchor='w').pack(fill='x', padx=4, pady=2)

        # Tab 2: Aerodynamic Values & Target Performance
        t2_frame = ttk.Frame(bot_nb)
        bot_nb.add(t2_frame, text="  📊 Aerodynamic Values & Target Forces  ")

        self.comb_vals_tree = ttk.Treeview(t2_frame, columns=('param', 'val', 'unit', 'desc'), show='headings', height=5)
        self.comb_vals_tree.heading('param', text='Aerodynamic Parameter')
        self.comb_vals_tree.heading('val', text='Value')
        self.comb_vals_tree.heading('unit', text='Units')
        self.comb_vals_tree.heading('desc', text='Engineering Context & Formula Student Target')
        self.comb_vals_tree.column('param', width=160, anchor='w')
        self.comb_vals_tree.column('val', width=80, anchor='center')
        self.comb_vals_tree.column('unit', width=60, anchor='center')
        self.comb_vals_tree.column('desc', width=350, anchor='w')

        vals_sc = ttk.Scrollbar(t2_frame, orient='vertical', command=self.comb_vals_tree.yview)
        self.comb_vals_tree.configure(yscrollcommand=vals_sc.set)
        self.comb_vals_tree.pack(side='left', fill='both', expand=True)
        vals_sc.pack(side='right', fill='y')

        # Tab 3: Aerodynamic Rationale & Flow Physics
        t3_frame = ttk.Frame(bot_nb)
        bot_nb.add(t3_frame, text="  📖 Design Philosophy & Flow Physics  ")

        self.comb_desc_txt = tk.Text(t3_frame, height=6, bg=PANEL2, fg=TXT, wrap='word', bd=0, relief='flat', font=('TkDefaultFont', 9))
        self.comb_desc_txt.pack(fill='both', expand=True, padx=4, pady=4)
        self.comb_desc_txt.config(state='disabled')

        self._apply_comb_filter()

    def _clear_comb_filters(self):
        if hasattr(self, 'comb_filter'):
            self.comb_filter.set('')
        if hasattr(self, 'comb_comp'):
            self.comb_comp.set('All Competitions')
        if hasattr(self, 'comb_cat'):
            self.comb_cat.set('All Wings')

    def _apply_comb_filter(self):
        q = getattr(self, 'comb_filter', None)
        query = q.get().strip().lower() if q else ''
        comp = getattr(self, 'comb_comp', None)
        comp_val = comp.get() if comp else 'All Competitions'
        cat = getattr(self, 'comb_cat', None)
        cat_val = cat.get() if cat else 'All Wings'

        all_pkgs = getattr(A, 'get_famous_packages', lambda: [])()
        filtered = []
        for p in all_pkgs:
            if comp_val != 'All Competitions':
                c_clean = comp_val.split('(')[0].strip().lower()
                c_paren = comp_val.split('(')[1].rstrip(')').strip().lower() if '(' in comp_val else ''
                p_short = p.get('comp_short', '').split('(')[0].strip().lower()
                p_full = (p.get('competition', '') + ' ' + p.get('comp_short', '')).lower()
                match = (c_clean == p_short) or (c_paren and c_paren in p_full) or (c_clean in p_full.split()) or ('benchmark' in c_clean and 'benchmark' in p_full)
                if not match:
                    continue
            if cat_val != 'All Wings' and cat_val.lower() not in p.get('category', '').lower():
                continue
            if query:
                haystack = (p.get('name', '') + ' ' + p.get('team', '') + ' ' + p.get('competition', '') + ' ' +
                            p.get('car', '') + ' ' + str(p.get('year', '')) + ' ' + p.get('main', '') + ' ' +
                            ' '.join(f[0] for f in p.get('flaps', [])) + ' ' + p.get('category', '')).lower()
                if query not in haystack:
                    continue
            filtered.append(p)

        self._comb_filtered_pkgs = filtered
        if hasattr(self, 'comb_count_lbl'):
            self.comb_count_lbl.set(f"Showing {len(filtered)} of {len(all_pkgs)} competition packages")

        if hasattr(self, 'comb_tree'):
            self.comb_tree.delete(*self.comb_tree.get_children())
            for p in filtered:
                el_str = f"{len(p.get('flaps', [])) + 1}-el"
                short_name = f"{p.get('team', '').split('(')[0].strip()} ({p.get('car', '')})"
                self.comb_tree.insert('', 'end', iid=p['id'],
                                      values=(short_name, p.get('comp_short', ''), p.get('year', ''), p.get('category', ''), el_str))
            if filtered:
                first_id = filtered[0]['id']
                self.comb_tree.selection_set(first_id)
                self.comb_tree.focus(first_id)
                self._on_comb_select(pkg_id=first_id)

    def _get_selected_comb_pkg(self):
        if not hasattr(self, 'comb_tree'):
            return None
        sel = self.comb_tree.selection()
        if not sel:
            return None
        pkg_id = sel[0]
        return getattr(A, 'get_famous_package', lambda _: None)(pkg_id)

    def _on_comb_select(self, event=None, pkg_id=None):
        if pkg_id is None:
            pkg = self._get_selected_comb_pkg()
        else:
            pkg = getattr(A, 'get_famous_package', lambda _: None)(pkg_id)
        if not pkg:
            return

        self._comb_current_pkg = pkg

        self.comb_title_var.set(pkg['name'])
        self.comb_achieve_var.set(pkg.get('achievement', ''))
        self.comb_team_var.set(f"🏁 {pkg.get('competition', '')} · {pkg.get('team', '')} · Car: {pkg.get('car', '')} ({pkg.get('year', '')})")
        self.comb_badge_comp.config(text=f"Event: {pkg.get('comp_short', '')}")
        self.comb_badge_cat.config(text=f"Role: {pkg.get('role', '').title()}")
        num_els = len(pkg.get('flaps', [])) + 1
        self.comb_badge_els.config(text=f"{num_els} Elements (Main + {num_els - 1} Flaps)")
        ge_str = f"Ground Effect (h={pkg.get('gh_pct', 0)}%)" if pkg.get('ge') else "Free Stream"
        v_kmh = int(pkg.get('speed', 0) * 3.6)
        self.comb_badge_aero.config(text=f"V = {pkg.get('speed', 0)} m/s ({v_kmh} km/h) · Re {pkg.get('re', 0):,} · {ge_str}")
        self.comb_badge_span.config(text=f"Span: {int(pkg.get('span', 1400))} mm")

        # Element Stack Treeview
        if hasattr(self, 'comb_stack_tree'):
            self.comb_stack_tree.delete(*self.comb_stack_tree.get_children())
            cfg = (pkg['main'], tuple(pkg.get('flaps', [])))
            cols = {}
            try:
                A.ROLE = 'fw' if 'front' in pkg.get('role', '') else 'rw'
                A.CHORD_MM = pkg.get('chord', 250.0)
                gh_val = pkg.get('gh_pct') if pkg.get('ge') else None
                A.set_ground_h(gh_val)
                cols = A.geometry_columns(cfg)
            except Exception:
                pass

            g0 = cols.get('M_F1_Gap_pct', None)
            o0 = cols.get('M_F1_Overlap_pct', None)
            g0_str = f"{g0:.1f}%" if g0 is not None else "—"
            o0_str = f"{o0:.1f}%" if o0 is not None else "—"
            self.comb_stack_tree.insert('', 'end', values=(
                "Main", pkg['main'], "100.0%", "0.0°", "0.0%", "0.0%", g0_str, o0_str
            ))

            for i, (fn, sc, ang, xp, yp) in enumerate(pkg.get('flaps', []), start=1):
                pair_name = A.PAIRS[i - 1] if i - 1 < len(A.PAIRS) else f"F{i}"
                next_pair = A.PAIRS[i] if i < len(A.PAIRS) else None
                gap_val = cols.get(f"{next_pair}_Gap_pct", None) if next_pair else None
                ov_val = cols.get(f"{next_pair}_Overlap_pct", None) if next_pair else None
                gap_str = f"{gap_val:.1f}%" if gap_val is not None else "—"
                ov_str = f"{ov_val:.1f}%" if ov_val is not None else "—"
                self.comb_stack_tree.insert('', 'end', values=(
                    f"Flap {i}", fn, f"{sc:.1f}%", f"{ang:.1f}°", f"{xp:.1f}%", f"{yp:.1f}%", gap_str, ov_str
                ))

            sl = cols.get('Stack_Length_mm', 0)
            sh = cols.get('Stack_Height_mm', 0)
            clearance = cols.get('Min_Clearance_mm', 0) if pkg.get('ge') else None
            clear_str = f" | Min Ground Clearance: {clearance:.1f} mm (Limit ≥ 35 mm)" if clearance is not None else ""
            role_limit = 600.0 if 'front' in pkg.get('role', '') else 250.0
            self.comb_dims_var.set(
                f"Main Chord: {pkg['chord']:.1f} mm | Span: {pkg['span']:.1f} mm | "
                f"Stack Length: {sl:.1f} mm (Rule Limit ≤ {role_limit:.1f} mm) | "
                f"Stack Height: {sh:.1f} mm{clear_str}"
            )

        # Aerodynamic Values Treeview
        if hasattr(self, 'comb_vals_tree'):
            self.comb_vals_tree.delete(*self.comb_vals_tree.get_children())
            targets = pkg.get('targets', {})
            speed = pkg.get('speed', 20.0)
            chord_m = pkg.get('chord', 250.0) / 1000.0
            span_m = pkg.get('span', 1400.0) / 1000.0
            area_m2 = chord_m * span_m
            q_pa = 0.5 * 1.225 * (speed ** 2)

            cl = targets.get('cl', 3.0)
            cd = targets.get('cd', 0.9)
            ld = targets.get('ld', cl / cd if cd > 0 else 3.0)
            df_n = targets.get('df_n', q_pa * area_m2 * cl)
            drag_n = targets.get('drag_n', q_pa * area_m2 * cd)

            val_rows = [
                ("Design Downforce", f"{df_n:.1f} ({df_n/9.81:.1f} kgf)", "N", f"Vertical aerodynamic load at design speed ({speed:.1f} m/s / {int(speed*3.6)} km/h)"),
                ("Design Drag", f"{drag_n:.1f} ({drag_n/9.81:.1f} kgf)", "N", f"Aerodynamic resistance at design speed ({speed:.1f} m/s / {int(speed*3.6)} km/h)"),
                ("Lift Coefficient (Cl)", f"{cl:.2f}", "—", "Overall 2D/3D multi-element lift coefficient"),
                ("Drag Coefficient (Cd)", f"{cd:.2f}", "—", "Total profile + pressure drag coefficient"),
                ("Aerodynamic Efficiency (L/D)", f"{ld:.2f}", "—", "Lift-to-drag ratio (downforce produced per unit drag penalty)"),
                ("Operating Velocity", f"{speed:.1f} ({int(speed*3.6)} km/h)", "m/s", "FSAE competition dynamic event design airspeed"),
                ("Dynamic Pressure (q)", f"{q_pa:.1f}", "Pa", "Freestream air dynamic pressure q = 0.5 * rho * V^2 (rho = 1.225 kg/m³)"),
                ("Reynolds Number (Re)", f"{pkg.get('re', 300000):,}", "—", f"Viscous scale based on main chord ({int(pkg.get('chord', 250))} mm)"),
                ("Wing Planform Area", f"{area_m2:.3f}", "m²", f"Span ({int(pkg.get('span', 1400))} mm) × Main Chord ({int(pkg.get('chord', 250))} mm)"),
                ("Aspect Ratio (AR)", f"{(span_m/chord_m):.2f}", "—", "Wingspan to main chord ratio (higher = lower induced drag)"),
                ("Pitch Stability Margin", "≥ 3.5°", "deg", "Safety buffer between design alpha and flap stall dive angle"),
            ]
            for param, val, unit, desc in val_rows:
                self.comb_vals_tree.insert('', 'end', values=(param, val, unit, desc))

        # Rationale Text
        if hasattr(self, 'comb_desc_txt'):
            self.comb_desc_txt.config(state='normal')
            self.comb_desc_txt.delete('1.0', 'end')
            aero = pkg.get('aerodynamics', {})
            txt_parts = [
                f"🏆 COMPETITION PEDIGREE & ACHIEVEMENTS: {pkg.get('achievement', 'N/A')}\n",
                f"🏎️ EVENT & TEAM: {pkg.get('competition', '')} — {pkg.get('team', '')} ({pkg.get('year', '')} {pkg.get('car', '')})\n\n",
                f"🎯 DESIGN INTENT: {aero.get('design_intent', 'N/A')}\n",
                f"💨 FLOW PHYSICS: {aero.get('flow_physics', 'N/A')}\n",
                f"🏁 OPERATING ENVELOPE: {aero.get('operating_envelope', 'N/A')}\n\n",
                "⭐ ENGINEERING HIGHLIGHTS & ARCHITECTURE:\n"
            ]
            for h in pkg.get('highlights', []):
                txt_parts.append(f"  • {h}\n")
            self.comb_desc_txt.insert('1.0', "".join(txt_parts))
            self.comb_desc_txt.config(state='disabled')

        self._draw_famous_geometry(pkg)

    def _draw_famous_geometry(self, pkg):
        if not getattr(self, 'comb_ax', None) or not getattr(self, 'comb_canvas', None):
            return
        self.comb_ax.clear()
        try:
            cfg = (pkg['main'], tuple(pkg.get('flaps', [])))
            chord = pkg.get('chord', 250.0)
            gh_val = pkg.get('gh_pct') if pkg.get('ge') else None
            outs = A.build_outlines(cfg, ground_h=gh_val)
            cols = ['#0284c7', '#e11d48', '#10b981', '#f59e0b', '#8b5cf6']
            all_pts = []
            for i, o in enumerate(outs):
                o_mm = np.asarray(o, float) * chord
                all_pts.append(o_mm)
                color = cols[i % len(cols)]
                self.comb_ax.plot(np.append(o_mm[:, 0], o_mm[0, 0]), np.append(o_mm[:, 1], o_mm[0, 1]),
                                  color=color, lw=1.8)
                self.comb_ax.fill(np.append(o_mm[:, 0], o_mm[0, 0]), np.append(o_mm[:, 1], o_mm[0, 1]),
                                  color=color, alpha=0.22)
                lbl = "Main" if i == 0 else f"Flap {i}"
                foil = pkg['main'] if i == 0 else pkg['flaps'][i - 1][0]
                mid_idx = len(o_mm) // 4
                mx, my = o_mm[mid_idx, 0], o_mm[mid_idx, 1]
                y_off = 14 if i % 2 == 0 else -18
                self.comb_ax.annotate(f"{lbl}: {foil}", xy=(mx, my), xytext=(0, y_off),
                                      textcoords='offset points', fontsize=8, fontweight='bold',
                                      color=color, ha='center',
                                      bbox=dict(boxstyle='round,pad=0.2', fc='#0f172a', ec=color, lw=0.8, alpha=0.85))

            if pkg.get('ge') and gh_val is not None:
                self.comb_ax.axhline(0, color='#64748b', lw=1.5, ls='--')
                self.comb_ax.text(0, 2, " GROUND PLANE (y = 0 mm)", color='#94a3b8', fontsize=8, va='bottom')

            stacked = np.vstack(all_pts)
            xmin, xmax = stacked[:, 0].min(), stacked[:, 0].max()
            ymin, ymax = stacked[:, 1].min(), stacked[:, 1].max()
            stack_len = xmax - xmin
            stack_ht = ymax - ymin

            self.comb_ax.set_aspect('equal')
            self.comb_ax.set_title(f"{pkg['name']}  [Stack: {stack_len:.1f} mm × {stack_ht:.1f} mm]",
                                   color=TXT, fontsize=9, fontweight='bold')
            self.comb_ax.set_xlabel("X (mm)", color=MUTED, fontsize=8)
            self.comb_ax.set_ylabel("Y (mm)", color=MUTED, fontsize=8)
            self.comb_ax.tick_params(colors=MUTED, labelsize=8)
            for spine in self.comb_ax.spines.values():
                spine.set_color(RULE)
            if getattr(self, 'comb_fig', None):
                self.comb_fig.tight_layout()
            self.comb_canvas.draw_idle()
        except Exception as e:
            pass

    def _comb_load_to_configure(self, pkg=None):
        pkg = pkg or getattr(self, '_comb_current_pkg', None) or self._get_selected_comb_pkg()
        if not pkg:
            messagebox.showinfo("Select Package", "Please select a wing package first.")
            return

        if hasattr(self, 'main_box'):
            self.main_box.set(pkg['main'])

        role = pkg.get('role', 'front wing')
        if hasattr(self, '_role_state'):
            self._role_state.set(role)
            lbl = {'front wing': FW, 'rear wing': RW}.get(role, CUSTOM)
            self.role_lbl.set(f"{lbl} (span {int(pkg.get('span', 1400))} mm)")
            if role == 'custom':
                self.custom_span_state.set(str(pkg.get('span', 1000.0)))

        if hasattr(self, 'vars'):
            if 'chord' in self.vars:
                self.vars['chord'].set(str(pkg.get('chord', 250.0)))
            if 'speed' in self.vars:
                self.vars['speed'].set(str(pkg.get('speed', 20.0)))
            if 're' in self.vars:
                self.vars['re'].set(str(pkg.get('re', 350000)))

        if hasattr(self, 'ge_state'):
            self.ge_state.set(bool(pkg.get('ge', True)))
        if hasattr(self, 'gh_state'):
            self.gh_state.set(str(pkg.get('gh_pct', 30.0)))

        flaps = pkg.get('flaps', [])
        for i, (vals, cb) in enumerate(getattr(self, 'flap_rows', [])):
            if i < len(flaps):
                fn, sc, ang, xp, yp = flaps[i]
                vals[0].set(fn)
                vals[1].set(str(sc))
                vals[2].set(str(ang))
                vals[3].set(str(xp))
                vals[4].set(str(yp))
                vals[5].set(True)
            else:
                vals[0].set('')
                vals[5].set(False)

        self.notebook.select(self.tab_cfg)
        self.on_check()
        self.log(f"Loaded famous package '{pkg['name']}' into Configure tab.")

    def _comb_send_to_optimizer(self, pkg=None):
        pkg = pkg or getattr(self, '_comb_current_pkg', None) or self._get_selected_comb_pkg()
        if not pkg:
            messagebox.showinfo("Select Package", "Please select a wing package first.")
            return

        cfg = (pkg['main'], tuple(pkg.get('flaps', [])))
        self._opt_base_cfg = cfg
        self._opt_best_cfg = cfg

        if hasattr(self, 'opt_main_box'):
            self.opt_main_box.set(pkg['main'])

        if hasattr(self, 'opt_vars'):
            if 'chord' in self.opt_vars:
                self.opt_vars['chord'].set(str(pkg.get('chord', 250.0)))
            if 'speed' in self.opt_vars:
                self.opt_vars['speed'].set(str(pkg.get('speed', 20.0)))
            if 're' in self.opt_vars:
                self.opt_vars['re'].set(str(pkg.get('re', 350000)))

        if hasattr(self, 'opt_ge_v'):
            self.opt_ge_v.set(bool(pkg.get('ge', True)))
        if hasattr(self, 'opt_gh_state'):
            self.opt_gh_state.set(str(pkg.get('gh_pct', 30.0)))

        flaps = pkg.get('flaps', [])
        for i, (vals, cb) in enumerate(getattr(self, 'opt_flap_rows', [])):
            if i < len(flaps):
                fn, sc, ang, xp, yp = flaps[i]
                vals[0].set(fn)
                vals[1].set(str(sc))
                vals[2].set(str(ang))
                vals[3].set(str(xp))
                vals[4].set(str(yp))
                vals[5].set(True)
            else:
                vals[0].set('')
                vals[5].set(False)

        if hasattr(self, 'opt_base_info'):
            self.opt_base_info.config(state='normal')
            self.opt_base_info.delete('1.0', 'end')
            hl0 = pkg.get('highlights', [''])[0]
            self.opt_base_info.insert('end', f"Base: {pkg['name']}\\n"
                                             f"Main: {pkg['main']} | Flaps: {len(flaps)} | Chord: {pkg['chord']}mm | Speed: {pkg['speed']}m/s\\n"
                                             f"Design: {hl0}")
            self.opt_base_info.config(state='disabled')

        self._opt_log(f"Loaded base from Famous Wings: {pkg['name']}")
        self.notebook.select(self.tab_opt)

    _comb_load_to_opt = _comb_send_to_optimizer

    def _comb_simulate_now(self, pkg=None):
        pkg = pkg or getattr(self, '_comb_current_pkg', None) or self._get_selected_comb_pkg()
        if not pkg:
            messagebox.showinfo("Select Package", "Please select a wing package first.")
            return
        self._comb_load_to_configure(pkg)
        self.after(100, self.on_simulate)

    def _comb_export_dxf(self, pkg=None):
        pkg = pkg or getattr(self, '_comb_current_pkg', None) or self._get_selected_comb_pkg()
        if not pkg:
            messagebox.showinfo("Select Package", "Please select a wing package first.")
            return

        initial = f"{pkg['id']}.dxf"
        p = filedialog.asksaveasfilename(
            title=f"Export CAD Model (DXF) - {pkg['name']}",
            defaultextension=".dxf",
            initialfile=initial,
            filetypes=[("AutoCAD DXF File", "*.dxf"), ("All Files", "*.*")]
        )
        if not p:
            return

        try:
            cfg = (pkg['main'], tuple(pkg.get('flaps', [])))
            gh_val = pkg.get('gh_pct') if pkg.get('ge') else None
            A.export_dxf(cfg, p, chord_mm=pkg.get('chord', 250.0), ground_h=gh_val,
                         title=f"{pkg['name']} ({pkg.get('team', '')})")
            messagebox.showinfo("DXF Export Successful",
                                f"Successfully exported 2D CAD profile:\n\n{p}\n\nReady for import into SolidWorks, AutoCAD, Siemens NX, CATIA, and Onshape.")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export DXF: {e}")


    # --- CAMPAIGNS TAB ---

    def build_campaigns(self):
        outer = ttk.Frame(self.tab_cam)
        outer.pack(fill='both', expand=True)
        paned = ttk.PanedWindow(outer, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=4, pady=4)
        left = ttk.Frame(paned)
        canvas = tk.Canvas(left, highlightthickness=0, width=410)
        vsb = ttk.Scrollbar(left, orient='vertical', command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>', lambda e=None: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        bind_scrollable(canvas)

        def section(text=None):
            lf = ttk.LabelFrame(inner, text=text)
            lf.pack(fill='x', padx=4, pady=4)
            return lf

        self.cam_cpu = os.cpu_count() or 1
        self.cam_workers = tk.StringVar(value=str(min(4, self.cam_cpu)))

        box = section("1. Time budget")
        row = ttk.Frame(box)
        row.pack(fill='x', padx=6, pady=2)
        ttk.Label(row, text="Hours:").pack(side='left')
        self.cam_hours = tk.StringVar(value='0.5')
        h_entry = ttk.Entry(row, textvariable=self.cam_hours, width=8)
        h_entry.pack(side='left', padx=4)
        add_tooltip(h_entry, "Total wall-clock time for the whole campaign (0.1 = 6 minutes). Split equally over the scenarios below; the deadline is strict.")
        for txt, hrs in (('30m', 0.5), ('1h', 1.0), ('4h', 4.0), ('12h', 12.0), ('24h', 24.0)):
            ttk.Button(row, text=txt, width=4, command=lambda h=hrs: self.cam_hours.set(f"{h:g}")).pack(side='left', padx=1)
        ttk.Label(box, text="Short budgets terminate the scenarios fast, good for a smoke test.", foreground=MUTED, wraplength=360, justify='left').pack(anchor='w', padx=6, pady=(0, 4))

        box = section("2. Parallelism & output folder")
        row = ttk.Frame(box)
        row.pack(fill='x', padx=6, pady=2)
        ttk.Label(row, text="Workers:").pack(side='left')
        w_entry = ttk.Entry(row, textvariable=self.cam_workers, width=6)
        w_entry.pack(side='left', padx=4)
        add_tooltip(w_entry, f"Parallel JavaFoil runs (this machine has {self.cam_cpu} cpus). Each worker uses its own JavaFoil copy under <out>/work/w0..wN; workers are cleaned up when the scenario ends.")
        ttk.Label(row, text=f"({self.cam_cpu} cpus)").pack(side='left')

        row = ttk.Frame(box)
        row.pack(fill='x', padx=6, pady=2)
        ttk.Label(row, text="Out folder:").pack(side='left')
        self.cam_out = tk.StringVar(value=os.path.expanduser(A.OUT_DIR))
        o_entry = ttk.Entry(row, textvariable=self.cam_out, width=24)
        o_entry.pack(side='left', padx=4)
        add_tooltip(o_entry, "Base output folder. Every scenario writes its own results.csv: unbounded -> this folder, ground -> ground/h<pct>/.")
        ttk.Button(row, text="Browse", command=self._cam_browse_out).pack(side='left', padx=1)
        ttk.Button(row, text="Open", command=self._cam_open_out).pack(side='left', padx=1)

        box = section("3. Flow scenarios")
        self.cam_flow_unb = tk.BooleanVar(value=True)
        self.cam_flow_gnd = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(box, text="Unbounded (free stream)", variable=self.cam_flow_unb)
        cb.pack(anchor='w', padx=6)
        add_tooltip(cb, "Run a campaign in free stream, no ground plane.")
        row = ttk.Frame(box)
        row.pack(fill='x', padx=6, pady=2)
        cb = ttk.Checkbutton(row, text="Ground effect, heights % chord:", variable=self.cam_flow_gnd)
        cb.pack(side='left')
        add_tooltip(cb, "Run a campaign above the ground plane at each height given (percent of main chord).")
        self.cam_heights = tk.StringVar(value="50,100,300")
        hh = ttk.Entry(row, textvariable=self.cam_heights, width=12)
        hh.pack(side='left', padx=4)
        add_tooltip(hh, "Ground height of main plane chord line above tarmac.\n\n• Single height (e.g. 35): Runs 1 campaign scenario at that fixed ride height.\n• Multiple heights (e.g. 30, 50, 100): Runs a batch sweep with a separate scenario for each height to test pitch/ride-height sensitivity (braking dive vs steady-state cornering vs straight).\n• Formats: Percent of main chord (e.g. 35 or 35%) or absolute length (e.g. 105mm).")

        box = section("4. Wing role (limits & span)")
        self.cam_role = tk.StringVar(value={'rear wing': 'Rear wing', 'front wing': 'Front wing'}.get(self._role_state.get(), 'Custom'))
        row = ttk.Frame(box)
        row.pack(fill='x', padx=6, pady=2)
        rb1 = tk.Radiobutton(row, text="Rear wing", value="Rear wing", variable=self.cam_role)
        rb1.pack(side='left', padx=2)
        rb2 = tk.Radiobutton(row, text="Front wing", value="Front wing", variable=self.cam_role)
        rb2.pack(side='left', padx=2)
        rb3 = tk.Radiobutton(row, text="Custom", value="Custom", variable=self.cam_role)
        rb3.pack(side='left', padx=2)
        for rb_ in (rb1, rb2, rb3):
            add_tooltip(rb_, "Selects the FSUK/FSG size limits and the default span (rear 950 mm / front 1400 mm / custom 1000 mm).")
        ttk.Label(box, text="Unbounded uses the rear-wing limits by default, ground the front-wing span; custom keeps the span from the Configure tab.", foreground=MUTED, wraplength=360, justify='left').pack(anchor='w', padx=6, pady=(0, 4))

        box = section("5. Airfoil pool")
        row_t = ttk.Frame(box)
        row_t.pack(fill='x', padx=6, pady=2)
        ttk.Label(row_t, text="Main elements").pack(side='left')
        ttk.Label(row_t, text="Flap pool").pack(side='left', padx=(26, 0))
        row_l = ttk.Frame(box)
        row_l.pack(fill='x', padx=6, pady=2)
        self.cam_mains = tk.Listbox(row_l, selectmode='extended', height=6, exportselection=False, width=24)
        self.cam_mains.pack(side='left')
        vs1 = ttk.Scrollbar(row_l, command=self.cam_mains.yview)
        self.cam_mains.configure(yscrollcommand=vs1.set)
        vs1.pack(side='left', fill='y')
        self.cam_flaps = tk.Listbox(row_l, selectmode='extended', height=6, exportselection=False, width=24)
        self.cam_flaps.pack(side='left', padx=(10, 0))
        vs2 = ttk.Scrollbar(row_l, command=self.cam_flaps.yview)
        self.cam_flaps.configure(yscrollcommand=vs2.set)
        vs2.pack(side='left', fill='y')
        for n in self.names:
            self.cam_mains.insert('end', n)
            self.cam_flaps.insert('end', n)
        row_b = ttk.Frame(box)
        row_b.pack(fill='x', padx=6, pady=2)
        for lb, tt in ((self.cam_mains, "Airfoils allowed as the main element (phase 0 singles + exploration)."), (self.cam_flaps, "Airfoils allowed as flap elements (also used for flap slots in exploration).")):
            sub = ttk.Frame(row_b)
            sub.pack(side='left', padx=(0, 10))
            ttk.Button(sub, text="All", width=4, command=lambda l=lb: self._cam_pool_sel(l, True)).pack(side='left', padx=1)
            ttk.Button(sub, text="None", width=4, command=lambda l=lb: self._cam_pool_sel(l, False)).pack(side='left', padx=1)
            ttk.Button(sub, text="Inv", width=4, command=lambda l=lb: self._cam_pool_inv(l)).pack(side='left', padx=1)
            add_tooltip(sub, tt)
        self._cam_prefill_pool()

        box = section("6. Options")
        self.cam_resume = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(box, text="Resume previous results.csv", variable=self.cam_resume)
        cb.pack(anchor='w', padx=6)
        add_tooltip(cb, "Load earlier results so a restart never re-runs known configs and Run_IDs stay unique.")
        self.cam_enforce = tk.BooleanVar(value=self.reg_state.get())
        cb = ttk.Checkbutton(box, text="Enforce FSUK/FSG size limits", variable=self.cam_enforce)
        cb.pack(anchor='w', padx=6)
        add_tooltip(cb, "Reject configs that break the physical size limits before JavaFoil runs.")
        self.cam_check = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(box, text="Self-check before each scenario", variable=self.cam_check)
        cb.pack(anchor='w', padx=6)
        add_tooltip(cb, "The ~1-minute JavaFoil self-check runs first; a scenario that fails is skipped and the next one starts.")
        self.cam_report = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(box, text="Build report folder when finished (Best/ + graphs)", variable=self.cam_report)
        cb.pack(anchor='w', padx=6)
        add_tooltip(cb, "Automatically build the full report (Best/ + graphs) for every scenario folder.")
        self.cam_open = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(box, text="Open results folder when finished", variable=self.cam_open)
        cb.pack(anchor='w', padx=6)
        add_tooltip(cb, "Open the base output folder in the file manager once the campaign ends.")

        box = section("7. Actions")
        row = ttk.Frame(box)
        row.pack(fill='x', padx=6, pady=2)
        self.cam_start_btn = ttk.Button(row, text="Start campaign", command=self.on_campaign)
        self.cam_start_btn.pack(side='left', padx=2)
        self.cam_stop_btn = ttk.Button(row, text="Stop all", state='disabled', command=self.on_campaign_stop)
        self.cam_stop_btn.pack(side='left', padx=2)
        self.cam_skip_btn = ttk.Button(row, text="Skip scenario", state='disabled', command=self.on_campaign_skip)
        self.cam_skip_btn.pack(side='left', padx=2)
        add_tooltip(self.cam_stop_btn, "Stop everything after the runs that are already in progress.")
        add_tooltip(self.cam_skip_btn, "Finish only the current scenario, then skip the remaining ones.")
        row = ttk.Frame(box)
        row.pack(fill='x', padx=6, pady=2)
        ttk.Button(row, text="Self-check only", command=self.on_campaign_check).pack(side='left', padx=2)
        ttk.Button(row, text="Write report now", command=self.on_report).pack(side='left', padx=2)
        ttk.Button(row, text="Open results folder", command=self._cam_open_out).pack(side='left', padx=2)
        ttk.Button(row, text="Copy plan", command=self._copy_campaign_plan).pack(side='left', padx=2)
        add_tooltip(row.winfo_children()[-1], "Copy the validated campaign plan (scenarios, budgets, pools, options) to the clipboard.")
        ttk.Label(box, text="Self-check validates JavaFoil/faketime for every selected scenario without running the full campaign.", foreground=MUTED, wraplength=360, justify='left').pack(anchor='w', padx=6, pady=(0, 4))

        right = ttk.Frame(paned)
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        topbar = ttk.LabelFrame(right, text="Live monitor")
        topbar.pack(fill='x', pady=(0, 2))
        self.cam_stats = tk.StringVar(value="not running")
        ttk.Label(topbar, textvariable=self.cam_stats, font=('TkDefaultFont', 10, 'bold')).pack(anchor='w', padx=6, pady=(4, 0))
        self.cam_scen = tk.StringVar(value="no campaign selected")
        ttk.Label(topbar, textvariable=self.cam_scen).pack(anchor='w', padx=6)
        self.cam_prog = ttk.Progressbar(topbar, maximum=100, mode='determinate')
        self.cam_prog.pack(fill='x', padx=6, pady=4)
        self.cam_prog_lbl = tk.StringVar(value='')
        ttk.Label(topbar, textvariable=self.cam_prog_lbl).pack(anchor='w', padx=6, pady=(0, 4))

        table_frame = ttk.LabelFrame(right, text="Current best (live)")
        table_frame.pack(fill='x', pady=2)
        cols = ('Elements', 'Main', 'Cl@0', 'Cd@0', 'Stall', 'Tier', 'Score')
        self.cam_tree = ttk.Treeview(table_frame, columns=cols, show='headings', height=6)
        for c in cols:
            self.cam_tree.heading(c, text=c)
            anchor = 'w' if c == 'Main' else 'e'
            self.cam_tree.column(c, width=70, anchor=anchor)
        self.cam_tree.column('Main', width=140)
        self.cam_tree.pack(fill='x', padx=4, pady=(2, 4))

        scen_frame = ttk.LabelFrame(right, text="Scenarios")
        scen_frame.pack(fill='x', pady=2)
        self.cam_scen_tree = ttk.Treeview(scen_frame, columns=('status', 'runs'), show='tree headings', height=4)
        self.cam_scen_tree.heading('#0', text="Scenario")
        self.cam_scen_tree.heading('status', text="Status")
        self.cam_scen_tree.heading('runs', text="Runs")
        self.cam_scen_tree.column('#0', width=310)
        self.cam_scen_tree.column('status', width=170)
        self.cam_scen_tree.column('runs', width=70, anchor='e')
        self.cam_scen_tree.pack(fill='x', padx=4, pady=(2, 4))
        self.cam_scen_tree.bind('<Double-1>', self._open_cam_scenario_folder)
        add_tooltip(self.cam_scen_tree, "Per-scenario status. Double-click a row to open that scenario's output folder.")

        log_frame = ttk.LabelFrame(right, text="Campaign log")
        log_frame.pack(fill='both', expand=True, pady=2)
        self.cam_log = tk.Text(log_frame, height=14, state='disabled', wrap='word')
        self.cam_log.pack(side='left', fill='both', expand=True, padx=(4, 0), pady=2)
        lsb = ttk.Scrollbar(log_frame, command=self.cam_log.yview)
        self.cam_log.configure(yscrollcommand=lsb.set)
        lsb.pack(side='left', fill='y')
        lbar = ttk.Frame(log_frame)
        lbar.pack(side='left', fill='y', padx=4, pady=2)
        ttk.Button(lbar, text="Clear", command=self.on_campaign_clear_log).pack(fill='x', pady=1)
        add_tooltip(lbar.winfo_children()[-1], "Clear the log window (does not touch results.csv).")
        ttk.Button(lbar, text="Save...", command=self.on_campaign_save_log).pack(fill='x', pady=1)
        add_tooltip(lbar.winfo_children()[-1], "Save the whole log to a text file.")
        ttk.Button(lbar, text="Copy", command=self.on_campaign_copy_log).pack(fill='x', pady=1)
        add_tooltip(lbar.winfo_children()[-1], "Copy the whole log to the clipboard.")
        self.cam_follow = tk.BooleanVar(value=True)
        ttk.Checkbutton(lbar, text="Auto\nscroll", variable=self.cam_follow).pack(anchor='w', pady=3)
        self._live_tick = 0

    def _cam_pool_sel(self, lb, select_all):
        if select_all:
            lb.selection_set(0, 'end')
        else:
            lb.selection_clear(0, 'end')

    def _cam_pool_inv(self, lb):
        for i in range(lb.size()):
            if lb.selection_includes(i):
                lb.selection_clear(i)
            else:
                lb.selection_set(i)

    def _cam_prefill_pool(self):
        favs = ('s1223', 'e423', 'be50', 'clarky', 'fx63137', 'naca0012')
        for i, name in enumerate(self.names):
            if any(f in name.lower() for f in favs):
                self.cam_mains.selection_set(i)
                self.cam_flaps.selection_set(i)
        if not self.cam_mains.curselection():
            self.cam_mains.selection_set(0, min(5, len(self.names) - 1))
            self.cam_flaps.selection_set(0, min(5, len(self.names) - 1))

    def _cam_selected(self, lb):
        return [self.names[i] for i in lb.curselection()]

    def _cam_browse_out(self):
        d = filedialog.askdirectory(initialdir=os.path.expanduser(self.cam_out.get()))
        if d:
            self.cam_out.set(d)

    def _cam_open_out(self):
        d = os.path.expanduser(self.cam_out.get())
        os.makedirs(d, exist_ok=True)
        subprocess_open(d)

    def _collect_campaign_plan(self, log_fail=True):
        mains = self._cam_selected(self.cam_mains)
        flaps = self._cam_selected(self.cam_flaps)
        if not mains:
            if log_fail:
                self.camp("select at least one airfoil in the Main elements pool")
            return None
        if not flaps:
            if log_fail:
                self.camp("select at least one airfoil in the Flap pool")
            return None
        try:
            hrs = float(self.cam_hours.get())
            if hrs <= 0:
                raise ValueError()
        except ValueError:
            if log_fail:
                self.camp("hours must be a positive number")
            return None
        try:
            w = int(self.cam_workers.get())
            if w <= 0:
                raise ValueError()
        except ValueError:
            if log_fail:
                self.camp("workers must be a positive integer")
            return None

        unb = self.cam_flow_unb.get()
        gnd = self.cam_flow_gnd.get()
        if not unb and not gnd:
            if log_fail:
                self.camp("pick at least one flow scenario (unbounded and/or ground effect)")
            return None

        flow = 'both' if (unb and gnd) else ('unbounded' if unb else 'ground')
        role_label = self.cam_role.get().strip().lower()
        if 'front' in role_label:
            role = 'fw'
            span = 1400.0
        elif 'rear' in role_label:
            role = 'rw'
            span = 950.0
        else:
            role = 'custom'
            try:
                span = float(self.custom_span_state.get())
            except ValueError:
                span = 1000.0

        try:
            chord = float(self.vars['chord'].get())
        except (KeyError, ValueError):
            chord = A.DEFAULT_CHORD_MM

        if gnd:
            raw_h = self.cam_heights.get().strip()
            if not raw_h:
                if log_fail:
                    self.camp("enter at least one ground height (e.g. 30, 50, 100)")
                return None
            try:
                heights = A.parse_heights(raw_h, chord)
            except Exception as e:
                if log_fail:
                    self.camp(f"invalid ground heights: {e}")
                return None
        else:
            heights = []

        plan = {
            'role': role,
            'flow': flow,
            'hours': hrs,
            'workers': w,
            'heights': heights,
            'chord': chord,
            'span': span,
            'out': os.path.expanduser(self.cam_out.get()),
            'enforce': self.cam_enforce.get(),
            'resume': self.cam_resume.get()
        }
        return plan, mains, flaps

    def on_campaign(self, check_only=False):
        if self.cam_active:
            self.camp("a campaign is already running")
            return
        got = self._collect_campaign_plan(log_fail=not check_only)
        if not got:
            return
        plan, mains, flaps = got
        if not A.is_java_available():
            messagebox.showerror(
                "Java Runtime Required",
                "Java Runtime (JRE / JDK) is required to run campaigns, but was not found on your system.\n\n"
                "Please download and install Java (e.g. Eclipse Temurin from https://adoptium.net) "
                "and ensure Java is installed on your computer."
            )
            self.camp("Campaign aborted: Java runtime not found.")
            return

        jf, _ = A.find_java_jars()
        if not (os.path.isabs(jf) and os.path.isfile(jf)):
            messagebox.showerror(
                "JavaFoil Jar Not Found",
                f"Could not locate '{A.JAVAFOIL_JAR}'.\n"
                f"Please ensure javafoil.jar is located in the app's 'assets/JavaFoil/' folder or set the AERO_JAVA_DIR environment variable."
            )
            self.camp("Campaign aborted: javafoil.jar not found.")
            return

        if check_only:
            plan = dict(plan, hours=0)
        self.cam_plan = plan
        self.cam_total = plan['hours'] * 3600
        self.cam_workers_n = max(1, int(plan['workers']))
        self.cam_t0 = time.time()
        self.cam_runs_base = len(A.RESULTS)
        self.cam_scen_idx = 0
        self.cam_active = True
        self.cam_start_btn.configure(state='disabled')
        self.cam_stop_btn.configure(state='normal')
        self.cam_skip_btn.configure(state='normal')
        self.cam_prog['value'] = 0
        self.cam_scen_tree.delete(*self.cam_scen_tree.get_children())
        self.cam_stats.set("self-checking…" if check_only else "starting…")
        self.cam_check_only = check_only

        if check_only:
            out_dir = os.path.expanduser(self.cam_out.get())
            self._camp_run_dir = None
        else:
            label = f"{plan['role']}_{plan['flow']}"
            try:
                self._camp_run_dir = A.new_run_dir('campaign', label, base=self._lib_base())
                h_str = ", ".join(f"{h:g}" for h in plan['heights']) if isinstance(plan['heights'], (list, tuple)) else str(plan['heights'])
                A.write_run_meta(
                    self._camp_run_dir, kind='campaign', label=label,
                    hours=plan['hours'], workers=plan['workers'],
                    role=plan['role'], flow=plan['flow'], heights=h_str,
                    mains=mains, flaps=flaps,
                    n_scenarios=len(A.plan_scenarios(plan)), n_runs=0
                )
            except Exception as e:
                self._camp_run_dir = None
                self.camp(f"could not create run folder: {e}")
            out_dir = os.path.expanduser(self.cam_out.get())

        self._cam_scen_dirs = {
            A.scenario_label(sc, plan.get('chord')): A.scenario_dir(sc)
            for sc in A.plan_scenarios(plan)
        }

        run_check = self.cam_check.get()
        resume = self.cam_resume.get()
        A.STOP.clear()
        A.INTERRUPT.clear()

        def on_event(kind, payload):
            self.ui_q.put(('cam_evt', (kind, payload)))

        def work():
            import traceback
            old_run = A.RUN_DIR
            old_out = A.OUT_DIR
            A.OUT_DIR = out_dir
            buf = _QueueWriter(self.ui_q, 'camp')
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = buf
            sys.stderr = buf
            try:
                A.run_plan(plan, mains, flaps, check_only=check_only, no_check=not run_check, resume=resume, on_event=on_event)
                self.ui_q.put(('cam_done', True))
            except Exception as e:
                traceback.print_exc()
                self.ui_q.put(('camp', f"\n[ERROR] Campaign failed: {type(e).__name__}: {e}\n"))
                self.ui_q.put(('cam_done', False))
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                A.OUT_DIR = old_out
                A.RUN_DIR = old_run

        threading.Thread(target=work, daemon=True).start()

    def on_campaign_stop(self):
        A.STOP.set()
        self.camp("stop requested - finishing current runs then exiting...")

    def on_campaign_skip(self):
        A.INTERRUPT.set()
        self.camp("skip scenario requested - moving to the next scenario...")

    def on_campaign_check(self):
        self.on_campaign(check_only=True)

    def on_campaign_clear_log(self):
        self.cam_log.configure(state='normal')
        self.cam_log.delete('1.0', 'end')
        self.cam_log.configure(state='disabled')

    def on_campaign_copy_log(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.cam_log.get('1.0', 'end'))
        except Exception:
            pass

    def on_campaign_save_log(self):
        p = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text file', '*.txt')])
        if p:
            try:
                with open(p, 'w') as f:
                    f.write(self.cam_log.get('1.0', 'end'))
            except Exception:
                pass

    def _copy_campaign_plan(self):
        got = self._collect_campaign_plan(log_fail=False)
        if not got:
            self.camp("invalid plan - fix the fields above first")
            return
        plan, mains, flaps = got
        import pprint
        text = pprint.pformat({'plan': plan, 'mains': mains, 'flaps': flaps})
        self.clipboard_clear()
        self.clipboard_append(text)
        self.camp("campaign plan copied to clipboard")

    def _cam_evt(self, kind, payload):
        if kind == 'scenario_start':
            self.cam_scen_idx = payload.get('index', 0)
            self.cam_scen_total = payload.get('total', 1)
            name = payload.get('name', '')
            self.cam_scen.set(f"scenario {self.cam_scen_idx + 1}/{self.cam_scen_total}: {name}")
            iid = name
            if not self.cam_scen_tree.exists(iid):
                self.cam_scen_tree.insert('', 'end', iid=iid, text=name, values=('running', 0))
            else:
                self.cam_scen_tree.item(iid, values=('running', 0))
        elif kind == 'scenario_done':
            name = payload.get('name', '')
            status = 'done' if payload.get('ok', True) else 'failed'
            runs = payload.get('runs', 0)
            iid = name
            if self.cam_scen_tree.exists(iid):
                self.cam_scen_tree.item(iid, values=(status, runs))
        elif kind == 'run':
            pass

    def _open_cam_scenario_folder(self, event=None):
        sel = self.cam_scen_tree.selection()
        if not sel:
            return
        name = sel[0]
        base = os.path.expanduser(self.cam_out.get())
        target = os.path.join(base, name) if os.path.isdir(os.path.join(base, name)) else base
        subprocess_open(target)

    def _cam_done(self, ok):
        self.cam_active = False
        self.cam_start_btn.configure(state='normal')
        self.cam_stop_btn.configure(state='disabled')
        self.cam_skip_btn.configure(state='disabled')
        if ok:
            self.cam_scen.set("all scenarios done")
            self.cam_stats.set("finished · self-check only (no runs)" if self.cam_check_only else "finished")
            self.cam_prog['value'] = 100
        else:
            self.cam_scen.set("campaign failed - see log")
        self._refresh_live_campaign()
        if ok and not self.cam_check_only and getattr(self, '_camp_run_dir', None):
            n = self._campaign_run_count()
            try:
                A.write_run_meta(self._camp_run_dir, n_runs=n, results='results.csv')
            except Exception:
                pass
            self._refresh_runs()
            self.load_results_cache()
            self.refresh_graph_files()
            if self.cam_report.get():
                self._report_all_scenarios()
            if self.cam_open.get():
                d = getattr(self, '_camp_run_dir', None)
                if d and os.path.isdir(d):
                    subprocess_open(d)
                else:
                    self._cam_open_out()

    def _report_all_scenarios(self):
        base = getattr(self, '_camp_run_dir', None) or os.path.expanduser(self.cam_out.get())
        dirs = sorted({
            os.path.join(base, 'ground', f"h{sc['height']:g}pct") if sc['height'] is not None else base
            for sc in A.plan_scenarios(self.cam_plan)
        })
        for d in dirs:
            p = os.path.join(d, 'results.csv')
            if os.path.exists(p):
                self._run_report(p)

    def _campaign_run_count(self):
        total = 0
        for sd in getattr(self, '_cam_scen_dirs', {}).values():
            try:
                total += len(A.read_results_csv(os.path.join(sd, 'results.csv')))
            except Exception:
                pass
        return total

    def _update_campaign_progress(self):
        if not self.cam_active:
            return
        try:
            el = time.time() - self.cam_t0
            if getattr(self, 'cam_check_only', False):
                self.cam_stats.set(f"self-checking … {el:.0f} s")
                return
            total = self.cam_total or 1e-09
            pct = min(100.0, (el / total) * 100.0)
            self.cam_prog['value'] = pct
            cnt = self._campaign_run_count()
            rate = cnt / el if el > 0 else 0
            rem = max(0, total - el)
            if rem >= 3600:
                eta = f"{rem / 3600:.1f} h"
            elif rem >= 60:
                eta = f"{rem / 60:.1f} m"
            else:
                eta = f"{rem:.0f} s"
            self.cam_stats.set(f"{cnt} new run(s) in {el / 60:.1f} min  ·  {rate:.2f} runs/s  ·  ETA {eta}")
            self.cam_prog_lbl.set(f"{pct:.1f}% of the {self.cam_total / 3600:.2f} h budget used")
        except TypeError:
            pass

    def _refresh_live_campaign(self):
        try:
            d = A.results_df()
            if d is None or d.empty:
                return
            if d.shape[0] == getattr(self, '_live_prev_len', -1) and self._live_tick % 10 != 0:
                return
            self._live_prev_len = d.shape[0]
            self._live_tick += 1
            rated = d[d['Tier'] <= 3]
            if rated.empty:
                return
            top = rated.sort_values(['Tier', 'Score'], ascending=[True, False]).head(12)
            self.cam_tree.delete(*self.cam_tree.get_children())
            for _, r in top.iterrows():
                self.cam_tree.insert('', 'end', values=(
                    r.get('Elements'),
                    str(r.get('Main')),
                    self._fmt(r.get('Cl_a0'), '.2f'),
                    self._fmt(r.get('Cd_a0'), '.3f'),
                    self._fmt(r.get('Stall_Angle'), '.0f'),
                    r.get('Tier'),
                    self._fmt(r.get('Score'), '.1f')
                ))
        except Exception:
            pass

    @staticmethod
    def _fmt(v, spec=''):
        try:
            if v is None:
                return '--'
            f = float(v)
            if f != f or f in (float('inf'), float('-inf')):
                return '--'
            return format(f, spec)
        except (TypeError, ValueError):
            return '--'

    def camp(self, line):
        self._append_log(self.cam_log, line, follow=self.cam_follow.get() if hasattr(self, 'cam_follow') else True)

    def on_report(self, path=None):
        p = path or os.path.expanduser(self.cam_out.get())
        csv = os.path.join(p, 'results.csv') if os.path.isdir(p) else p
        if os.path.exists(csv):
            self._run_report(csv)
        else:
            self.camp("results.csv not found for report in " + p)

    def _run_report(self, path):
        self.camp(f"writing report for {path} …")

        def work():
            import contextlib
            buf = io.StringIO()
            with self._cli_lock:
                with contextlib.redirect_stdout(buf):
                    args = ['aero_report.py', '--results', path]
                    saved = sys.argv
                    sys.argv = args
                    try:
                        R.main()
                        self.camp("report written to " + os.path.join(os.path.dirname(path), 'Best'))
                    except SystemExit:
                        pass
                    except Exception as e:
                        self.camp("report error: " + str(e))
                    finally:
                        sys.argv = saved
            self.ui_q.put(('camp', buf.getvalue()[-2000:]))
            self.ui_q.put(('refreshgr', path))

        threading.Thread(target=work, daemon=True).start()
    # --- RESULTS TAB ---
    def build_results(self):
        res = ttk.Frame(self.tab_res)
        res.pack(fill='both', expand=True, padx=6, pady=6)
        
        # Run Library
        browser = ttk.LabelFrame(res, text='Run Library')
        browser.pack(fill='x', padx=6, pady=4)
        btns = ttk.Frame(browser)
        btns.pack(fill='x', padx=6, pady=(4, 2))
        ttk.Button(btns, text='Refresh', command=self._refresh_runs).pack(side='left')
        imp = ttk.Button(btns, text='Import existing results…', command=self.on_import_existing)
        imp.pack(side='left', padx=4)
        add_tooltip(imp, 'Copy an existing results.csv (and its graphs/) into the library as a dated run.')
        exp = ttk.Button(btns, text='Export run…', command=self.on_export_run)
        exp.pack(side='left', padx=4)
        add_tooltip(exp, 'Zip the selected run folder so it can be archived or shared.')
        best = ttk.Button(btns, text='Open best sheet', command=self.on_open_best)
        best.pack(side='left', padx=4)
        add_tooltip(best, 'Open the Best/ report folder (best sheet + graphs) of the selected run.')
        self.res_runs_lbl = tk.StringVar(value='')
        ttk.Label(btns, textvariable=self.res_runs_lbl, foreground=MUTED).pack(side='right')
        
        self.res_folder_tree = ttk.Treeview(
            browser, columns=('Date', 'Kind', 'Main', 'Best', 'Runs'), show='tree headings', height=6
        )
        self.res_folder_tree.heading('#0', text='Run / Folder Hierarchy')
        self.res_folder_tree.heading('Date', text='Date')
        self.res_folder_tree.heading('Kind', text='Kind')
        self.res_folder_tree.heading('Main', text='Main')
        self.res_folder_tree.heading('Best', text='Best score')
        self.res_folder_tree.heading('Runs', text='#')
        self.res_folder_tree.column('#0', width=260)
        for c, w in (('Date', 130), ('Kind', 90), ('Main', 90), ('Best', 80), ('Runs', 50)):
            self.res_folder_tree.column(c, width=w, anchor='w')
        vsf = ttk.Scrollbar(browser, command=self.res_folder_tree.yview)
        self.res_folder_tree.configure(yscrollcommand=vsf.set)
        vsf.pack(side='right', fill='y')
        self.res_folder_tree.pack(fill='x', padx=6, pady=4)
        self.res_folder_tree.bind('<<TreeviewSelect>>', self._on_run_select)
        self.res_folder_tree.bind('<Double-1>', lambda e=None: self.on_gen_graphs())
        
        # Results Table
        table_frame = ttk.LabelFrame(res, text='Results Table')
        table_frame.pack(fill='both', expand=True, padx=6, pady=4)
        
        top = ttk.Frame(table_frame)
        top.pack(fill='x', padx=4, pady=2)
        self.res_file = tk.StringVar(value=os.path.join(A.OUT_DIR, 'results.csv'))
        ttk.Entry(top, textvariable=self.res_file, width=38).pack(side='left')
        ttk.Button(top, text='Load', command=self.load_results_cache).pack(side='left', padx=3)
        ttk.Button(top, text='Browse...', command=self.on_browse).pack(side='left')
        ttk.Button(top, text='Show targets', command=self.on_targets).pack(side='left', padx=3)
        ext_btn = ttk.Button(top, text='Extract JavaFoil Graphs', command=self.on_extract_configured_graphs)
        ext_btn.pack(side='left', padx=3)
        add_tooltip(ext_btn, "Extract JavaFoil's authentic native aerodynamic graphs for the configured wing.")
        
        # Real-time Executive KPI Summary Cards
        self.kpi_frame = ttk.Frame(table_frame)
        self.kpi_frame.pack(fill='x', padx=4, pady=4)
        self.kpi_runs = tk.StringVar(value="Runs: --")
        self.kpi_df = tk.StringVar(value="Max Downforce: --")
        self.kpi_ld = tk.StringVar(value="Max L/D: --")
        self.kpi_score = tk.StringVar(value="Best Score: --")
        self.kpi_valid = tk.StringVar(value="Valid: --")
        self.kpi_time = tk.StringVar(value="Sim Time: --")
        
        for k_var, color in (
            (self.kpi_runs, '#7dd3fc'),
            (self.kpi_df, '#f79e0b'),
            (self.kpi_ld, '#34d399'),
            (self.kpi_score, '#fbbf24'),
            (self.kpi_valid, '#a78bfa'),
            (self.kpi_time, '#94a3b8')
        ):
            card = tk.Label(self.kpi_frame, textvariable=k_var, bg='#172033', fg=color,
                            font=('Helvetica', 9, 'bold'), padx=8, pady=3, relief='groove', bd=1)
            card.pack(side='left', padx=2)
        
        top2 = ttk.Frame(table_frame)
        top2.pack(fill='x', padx=4, pady=(2, 2))
        self.res_filter = tk.StringVar()
        f_entry = ttk.Entry(top2, textvariable=self.res_filter, width=18)
        f_entry.pack(side='left')
        f_entry.bind('<KeyRelease>', lambda e=None: self._apply_results_view())
        add_tooltip(f_entry, 'Live filter: type any keyword. Click column header to rank/sort.')
        ttk.Button(top2, text='Clear', command=self._reset_results_view).pack(side='left', padx=2)
        ttk.Button(top2, text='Export View CSV', command=self._export_view).pack(side='left', padx=2)
        
        # Horizontal scroll quick buttons
        ttk.Button(top2, text='◀ Left', width=6, command=lambda: self.tree.xview_scroll(-5, 'units')).pack(side='left', padx=(4, 1))
        ttk.Button(top2, text='Right ▶', width=6, command=lambda: self.tree.xview_scroll(5, 'units')).pack(side='left', padx=1)
        
        # Column View Preset selector
        ttk.Label(top2, text='Columns:').pack(side='left', padx=(6, 2))
        self.col_view_mode = tk.StringVar(value='All Columns (50+)')
        cv_combo = ttk.Combobox(
            top2, textvariable=self.col_view_mode,
            values=['All Columns (50+)', 'Aerodynamics & Performance', 'Wing Geometry & Flaps', 'Core Telemetry'],
            state='readonly', width=20
        )
        cv_combo.pack(side='left', padx=2)
        cv_combo.bind('<<ComboboxSelected>>', lambda e: self._on_col_view_change())
        add_tooltip(cv_combo, 'Filter which columns are displayed in the Results Table.')
        
        self.res_stats = tk.StringVar(value='')
        ttk.Label(top2, textvariable=self.res_stats, foreground=MUTED).pack(side='left', padx=4)
        
        gen_btn = ttk.Button(top2, text='📊 Generate Graphs', command=self.on_gen_graphs)
        gen_btn.pack(side='right', padx=2)
        add_tooltip(gen_btn, 'Generate high-resolution polar curves, velocity flow field, JavaFoil native graphs, and 2D CAD for the selected run.')
        ttk.Button(top2, text='⚙️ Load to Configure', command=self.on_apply_to_config).pack(side='right', padx=2)
        ttk.Button(top2, text='🚀 Send to Optimizer', command=self.on_send_to_optimizer).pack(side='right', padx=2)
        ttk.Label(top2, text='(Right-click row for CAD & options)', foreground=MUTED).pack(side='right', padx=4)

        # Multi-Objective Scoring Profile Selector Bar
        prof_frame = ttk.Frame(table_frame)
        prof_frame.pack(fill='x', padx=4, pady=(2, 4))
        ttk.Label(prof_frame, text='🏆 Ranking Metric:', font=('Helvetica', 9, 'bold')).pack(side='left', padx=(2, 4))
        first_prof = list(A.SCORING_PROFILES.values())[0]
        self.res_scoring_profile = tk.StringVar(value=first_prof['name'])
        prof_names = [p['name'] for p in A.SCORING_PROFILES.values()]
        self.prof_combo = ttk.Combobox(prof_frame, textvariable=self.res_scoring_profile, values=prof_names, state='readonly', width=38)
        self.prof_combo.pack(side='left', padx=2)
        self.prof_combo.bind('<<ComboboxSelected>>', lambda e: self._on_scoring_profile_change())
        add_tooltip(self.prof_combo, 'Select an FSAE competition scoring metric to instantly re-rank all wing runs.')
        
        self.prof_desc_lbl = tk.Label(
            prof_frame, text=first_prof['description'],
            bg='#1e293b', fg='#94a3b8', font=('Segoe UI', 8), padx=8, pady=3, relief='flat'
        )
        self.prof_desc_lbl.pack(side='left', fill='x', expand=True, padx=(6, 2))
        
        # Dedicated Grid Container for Treeview + Scrollbars (enables true horizontal scrolling)
        tree_container = ttk.Frame(table_frame)
        tree_container.pack(fill='both', expand=True, padx=4, pady=2)
        
        self.tree = ttk.Treeview(tree_container, show='headings', height=14, selectmode='browse')
        vs = ttk.Scrollbar(tree_container, orient='vertical', command=self.tree.yview)
        hs = ttk.Scrollbar(tree_container, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        
        self.tree.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)
        
        # Cross-platform horizontal mouse wheel and arrow key bindings
        self.tree.bind('<Shift-MouseWheel>', lambda e: self.tree.xview_scroll(int(-1 * (e.delta / 120)), 'units'))
        self.tree.bind('<Shift-Button-4>', lambda e: self.tree.xview_scroll(-3, 'units'))
        self.tree.bind('<Shift-Button-5>', lambda e: self.tree.xview_scroll(3, 'units'))
        self.tree.bind('<Left>', lambda e: self.tree.xview_scroll(-2, 'units'))
        self.tree.bind('<Right>', lambda e: self.tree.xview_scroll(2, 'units'))
        
        self.tree.tag_configure('odd', background='#172033')
        self.tree.tag_configure('even', background='#0f172a')
        self.tree.tag_configure('status_valid', foreground='#34d399')
        self.tree.tag_configure('status_failed', foreground='#f87171')
        self.tree.tag_configure('tier_1', foreground='#fbbf24')
        
        self.tree.bind('<ButtonRelease-1>', self.on_row)
        self.tree.bind('<Double-1>', lambda e=None: self.on_gen_graphs())
        self.tree.bind('<Button-3>', self._show_tree_context_menu)
        self.tree.bind('<Button-2>', self._show_tree_context_menu)
        
        self.detail = tk.Text(table_frame, height=7, state='disabled', wrap='word', bg='#0a0f1d', fg='#e2e8f0')
        self.detail.pack(fill='x', padx=4, pady=(4, 2))
        
        # Enhanced CSV Data Viewer
        csv_frame = ttk.LabelFrame(res, text='CSV Data Viewer')
        csv_frame.pack(fill='both', expand=True, padx=6, pady=4)
        
        csv_bar = ttk.Frame(csv_frame)
        csv_bar.pack(fill='x', padx=4, pady=2)
        self.csv_info_var = tk.StringVar(value='No file loaded')
        ttk.Label(csv_bar, textvariable=self.csv_info_var, font=('Helvetica', 8, 'italic'), foreground=MUTED).pack(side='left', padx=4)
        
        ttk.Button(csv_bar, text='Refresh CSV', command=self._refresh_csv_view).pack(side='left', padx=3)
        ttk.Button(csv_bar, text='Save CSV (Safe Backup)', command=self._save_csv).pack(side='left', padx=3)
        calc_btn = ttk.Button(csv_bar, text='Open in External Calc / Spreadsheet ↗', command=self._open_in_calc)
        calc_btn.pack(side='left', padx=4)
        add_tooltip(calc_btn, 'Launch your system spreadsheet editor (LibreOffice Calc, Excel, etc.) with this CSV.')
        
        ttk.Label(csv_bar, text="Search:").pack(side='right', padx=(6, 2))
        self.csv_search_var = tk.StringVar()
        cs_entry = ttk.Entry(csv_bar, textvariable=self.csv_search_var, width=18)
        cs_entry.pack(side='right', padx=2)
        cs_entry.bind('<KeyRelease>', lambda e=None: self._search_csv())
        ttk.Button(csv_bar, text='Find', command=self._search_csv).pack(side='right', padx=1)
        ttk.Button(csv_bar, text='Clear', command=self._clear_csv_search).pack(side='right', padx=1)
        
        text_f = ttk.Frame(csv_frame)
        text_f.pack(fill='both', expand=True, padx=4, pady=4)
        csv_vsb = ttk.Scrollbar(text_f, orient='vertical')
        csv_hsb = ttk.Scrollbar(text_f, orient='horizontal')
        self.csv_text = tk.Text(
            text_f, height=8, state='normal', wrap='none',
            yscrollcommand=csv_vsb.set, xscrollcommand=csv_hsb.set,
            font=('DejaVu Sans Mono', 9), bg='#0b1329', fg='#e2e8f0',
            insertbackground='#f79e0b'
        )
        csv_vsb.configure(command=self.csv_text.yview)
        csv_hsb.configure(command=self.csv_text.xview)
        csv_vsb.pack(side='right', fill='y')
        csv_hsb.pack(side='bottom', fill='x')
        self.csv_text.pack(side='left', fill='both', expand=True)
        
        self.csv_text.tag_configure('header', background='#172a45', foreground='#7dd3fc', font=('DejaVu Sans Mono', 9, 'bold'))
        self.csv_text.tag_configure('found', background='#f59e0b', foreground='#000000')
        self._csv_truncated = False

    def _refresh_runs(self):
        if not hasattr(self, 'res_folder_tree'):
            return
        self.res_folder_tree.delete(*self.res_folder_tree.get_children())
        base = os.path.expanduser(self._lib_base())
        self._run_dirs = {}
        
        # 1. Active Campaign Hierarchy
        active_root = A.OUT_DIR
        if os.path.isdir(active_root):
            root_id = self.res_folder_tree.insert(
                '', 'end', text=f"📁 Active Campaign ({os.path.basename(active_root)})",
                open=True, values=('', 'Active', '', '', '')
            )
            unb_csv = os.path.join(active_root, 'results.csv')
            if os.path.exists(unb_csv):
                self._run_dirs[unb_csv] = unb_csv
                try:
                    dt = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(unb_csv)))
                except Exception:
                    dt = ''
                self.res_folder_tree.insert(
                    root_id, 'end', iid=unb_csv,
                    text="📄 Unbounded Flow (results.csv)",
                    values=(dt, 'Unbounded', '', '', '')
                )
            ground_dir = os.path.join(active_root, 'ground')
            if os.path.isdir(ground_dir):
                gr_root = self.res_folder_tree.insert(
                    root_id, 'end', text="📁 Ground Effect Scenarios",
                    open=True, values=('', 'Ground', '', '', '')
                )
                for h_folder in sorted(os.listdir(ground_dir)):
                    h_path = os.path.join(ground_dir, h_folder)
                    if os.path.isdir(h_path):
                        h_csv = os.path.join(h_path, 'results.csv')
                        if os.path.exists(h_csv):
                            self._run_dirs[h_csv] = h_csv
                            try:
                                dt = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(h_csv)))
                            except Exception:
                                dt = ''
                            self.res_folder_tree.insert(
                                gr_root, 'end', iid=h_csv,
                                text=f"📄 Ground {h_folder} (results.csv)",
                                values=(dt, 'Ground', h_folder, '', '')
                            )
                            
        # 2. Archived Run Library & Saved Campaigns
        lib_candidates = []
        lib_bases = [
            os.path.join(A.OUT_DIR, 'library'),
            base,
            os.path.expanduser('~/.aero_auto/runs')
        ]
        seen_dirs = set()
        for l_base in lib_bases:
            if not os.path.isdir(l_base):
                continue
            for item in sorted(os.listdir(l_base)):
                full_item = os.path.join(l_base, item)
                if os.path.isdir(full_item) and full_item not in seen_dirs:
                    csv_p = os.path.join(full_item, 'results.csv')
                    g_csv = glob.glob(os.path.join(full_item, 'ground', '*', 'results.csv'))
                    if os.path.exists(csv_p) or g_csv:
                        seen_dirs.add(full_item)
                        meta = {}
                        if hasattr(A, 'read_run_meta'):
                            try:
                                meta = A.read_run_meta(full_item) or {}
                            except Exception:
                                pass
                        lib_candidates.append((full_item, csv_p if os.path.exists(csv_p) else g_csv[0], meta))
                        
        if lib_candidates:
            lib_root = self.res_folder_tree.insert(
                '', 'end', text=f"📁 Archived Run Library ({len(lib_candidates)} runs)",
                open=True, values=('', 'Library', '', '', len(lib_candidates))
            )
            for d, csv, m in lib_candidates:
                created = str(m.get('created', ''))[:19].replace('T', ' ')
                if not created:
                    try:
                        created = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(csv)))
                    except Exception:
                        created = ''
                kind = str(m.get('kind', 'archive'))
                main = str(m.get('main') or m.get('label') or os.path.basename(d))
                score = m.get('score', '')
                try:
                    best = f"{float(score):.1f}" if score != '' else ''
                except (TypeError, ValueError):
                    best = ''
                nruns = m.get('n_runs', '')
                iid = csv
                self._run_dirs[iid] = csv
                folder_node = self.res_folder_tree.insert(
                    lib_root, 'end', iid=iid,
                    text=f"📁 {os.path.basename(d)}",
                    values=(created, kind, main, best, nruns)
                )
                sub_ground = os.path.join(d, 'ground')
                if os.path.isdir(sub_ground):
                    for sub_h in sorted(os.listdir(sub_ground)):
                        sub_h_csv = os.path.join(sub_ground, sub_h, 'results.csv')
                        if os.path.exists(sub_h_csv):
                            self._run_dirs[sub_h_csv] = sub_h_csv
                            self.res_folder_tree.insert(
                                folder_node, 'end', iid=sub_h_csv,
                                text=f"📄 Ground {sub_h} (results.csv)",
                                values=(created, 'Ground', sub_h, '', '')
                            )
        self.res_runs_lbl.set(f"Run Library ready")

    def _on_run_select(self, event=None):
        sel = self.res_folder_tree.selection()
        if not sel:
            return
        iid = sel[0]
        csv_path = getattr(self, '_run_dirs', {}).get(iid)
        if csv_path and os.path.exists(csv_path):
            self.res_file.set(csv_path)
            self.gr_results.set(csv_path)
            self.load_results_cache()

    def discover_results(self):
        base = A.OUT_DIR
        paths = [os.path.join(base, 'results.csv')]
        paths += sorted(glob.glob(os.path.join(base, 'ground', '*', 'results.csv')))
        paths += sorted(glob.glob(os.path.join(base, 'library', '*', 'results.csv')))
        paths += sorted(glob.glob(os.path.join(base, 'library', '*', 'ground', '*', 'results.csv')))
        paths += sorted(glob.glob(os.path.join(base, 'ground', '*', 'summary', '*.csv')))
        for d in (os.path.expanduser(self._lib_base()), os.path.expanduser('~/.aero_auto/runs')):
            if os.path.isdir(d):
                paths += sorted(glob.glob(os.path.join(d, '*', 'results.csv')))
                paths += sorted(glob.glob(os.path.join(d, '*', 'ground', '*', 'results.csv')))
        cur = os.path.expanduser(self.res_file.get())
        if cur not in paths and os.path.exists(cur):
            paths.insert(0, cur)
        return [p for p in dict.fromkeys(paths) if os.path.exists(p)]

    COL_ALIGN_WIDTH = {
        'Run_ID': ('center', 100),
        'Rank': ('center', 65),
        'Score': ('e', 80),
        'Score_Balanced': ('e', 85),
        'Score_Autocross': ('e', 85),
        'Score_Efficiency': ('e', 85),
        'Score_Robust': ('e', 85),
        'Score_LapTime': ('e', 85),
        'Tier': ('center', 60),
        'Status': ('center', 80),
        'Cl_a0': ('e', 85),
        'Cd_a0': ('e', 85),
        'Cm_a0': ('e', 75),
        'Max_LD': ('e', 85),
        'Downforce_N': ('e', 95),
        'Drag_N': ('e', 85),
        'Cl_peak': ('e', 80),
        'Cd_peak': ('e', 80),
        'Stall_Angle': ('e', 85),
        'Cl_am2': ('e', 75),
        'Cl_ap2': ('e', 75),
        'Elements': ('center', 75),
        'Main': ('w', 120),
        'Flow': ('center', 80),
        'Height_pct': ('e', 85),
        'F1_Airfoil': ('w', 110),
        'F1_Scale': ('e', 75),
        'F1_Angle': ('e', 75),
        'F1_X': ('e', 75),
        'F1_Y': ('e', 75),
        'Main_to_F1_Gap_pct': ('e', 95),
        'Main_to_F1_Overlap_pct': ('e', 95),
        'Main_to_F1_Step_pct': ('e', 95),
        'F2_Airfoil': ('w', 110),
        'F2_Scale': ('e', 75),
        'F2_Angle': ('e', 75),
        'F2_X': ('e', 75),
        'F2_Y': ('e', 75),
        'F1_to_F2_Gap_pct': ('e', 95),
        'F1_to_F2_Overlap_pct': ('e', 95),
        'F1_to_F2_Step_pct': ('e', 95),
        'F3_Airfoil': ('w', 110),
        'F3_Scale': ('e', 75),
        'F3_Angle': ('e', 75),
        'F3_X': ('e', 75),
        'F3_Y': ('e', 75),
        'F2_to_F3_Gap_pct': ('e', 95),
        'F2_to_F3_Overlap_pct': ('e', 95),
        'F2_to_F3_Step_pct': ('e', 95),
        'Stack_Length_mm': ('e', 110),
        'Stack_Height_mm': ('e', 110),
        'Min_Clearance_mm': ('e', 110),
        'Stack_Length_pct': ('e', 95),
        'Stack_Height_pct': ('e', 95),
        'Min_Clearance_pct': ('e', 95),
        'Duration_s': ('e', 85),
        'Date': ('center', 140),
        'Speed_ms': ('e', 80),
        'Alpha_Interval': ('center', 105),
        'Phase': ('center', 75),
    }

    def _get_active_columns(self):
        if not hasattr(self, 'results') or self.results is None or self.results.empty:
            return []
        mode = getattr(self, 'col_view_mode', None)
        mode_val = mode.get() if mode else 'All Columns (50+)'
        
        all_cols = list(self.results.columns)
        PRIORITY = [
            'Run_ID', 'Rank', 'Score', 'Score_Balanced', 'Score_Autocross', 'Score_Efficiency', 'Score_Robust', 'Score_LapTime', 'Tier', 'Status',
            'Cl_a0', 'Cd_a0', 'Cm_a0', 'Max_LD', 'Downforce_N', 'Drag_N',
            'Cl_peak', 'Cd_peak', 'Stall_Angle', 'Cl_am2', 'Cl_ap2',
            'Elements', 'Main', 'Flow', 'Height_pct',
            'F1_Airfoil', 'F1_Scale', 'F1_Angle', 'F1_X', 'F1_Y',
            'Main_to_F1_Gap_pct', 'Main_to_F1_Overlap_pct', 'Main_to_F1_Step_pct',
            'F2_Airfoil', 'F2_Scale', 'F2_Angle', 'F2_X', 'F2_Y',
            'F1_to_F2_Gap_pct', 'F1_to_F2_Overlap_pct', 'F1_to_F2_Step_pct',
            'F3_Airfoil', 'F3_Scale', 'F3_Angle', 'F3_X', 'F3_Y',
            'F2_to_F3_Gap_pct', 'F2_to_F3_Overlap_pct', 'F2_to_F3_Step_pct',
            'Stack_Length_mm', 'Stack_Height_mm', 'Min_Clearance_mm',
            'Stack_Length_pct', 'Stack_Height_pct', 'Min_Clearance_pct',
            'Duration_s', 'Date', 'Speed_ms', 'Alpha_Interval', 'Phase'
        ]
        
        if mode_val == 'Aerodynamics & Performance':
            subset = [
                'Run_ID', 'Rank', 'Score', 'Score_Balanced', 'Score_Autocross', 'Score_Efficiency', 'Score_Robust', 'Score_LapTime', 'Tier', 'Status',
                'Cl_a0', 'Cd_a0', 'Cm_a0', 'Max_LD', 'Downforce_N', 'Drag_N',
                'Cl_peak', 'Cd_peak', 'Stall_Angle', 'Cl_am2', 'Cl_ap2',
                'Speed_ms', 'Duration_s', 'Date'
            ]
            return [c for c in subset if c in all_cols]
        elif mode_val == 'Wing Geometry & Flaps':
            subset = [
                'Run_ID', 'Status', 'Elements', 'Main', 'Flow', 'Height_pct',
                'F1_Airfoil', 'F1_Scale', 'F1_Angle', 'F1_X', 'F1_Y',
                'Main_to_F1_Gap_pct', 'Main_to_F1_Overlap_pct',
                'F2_Airfoil', 'F2_Scale', 'F2_Angle', 'F2_X', 'F2_Y',
                'F1_to_F2_Gap_pct', 'F1_to_F2_Overlap_pct',
                'F3_Airfoil', 'F3_Scale', 'F3_Angle', 'F3_X', 'F3_Y',
                'Stack_Length_mm', 'Stack_Height_mm', 'Min_Clearance_mm', 'Score'
            ]
            return [c for c in subset if c in all_cols]
        elif mode_val == 'Core Telemetry':
            subset = [
                'Run_ID', 'Elements', 'Main', 'Cl_a0', 'Cd_a0',
                'Max_LD', 'Downforce_N', 'Duration_s', 'Tier', 'Score', 'Status'
            ]
            return [c for c in subset if c in all_cols]
        else: # All Columns (50+)
            ordered = [c for c in PRIORITY if c in all_cols]
            for c in all_cols:
                if c not in ordered:
                    ordered.append(c)
            return ordered

    def _on_col_view_change(self):
        if not hasattr(self, 'results') or self.results is None or self.results.empty:
            return
        self._setup_tree_columns()
        self._apply_results_view()

    def _setup_tree_columns(self):
        cols = self._get_active_columns()
        self.tree['columns'] = cols
        self._results_cols = cols
        for c in cols:
            align, w = self.COL_ALIGN_WIDTH.get(c, ('center', 90))
            self.tree.heading(c, text=c, anchor='center', command=lambda col=c: self._sort_results_by(col))
            self.tree.column(c, width=w, minwidth=60, stretch=False, anchor=align)

    def _format_cell(self, col, val):
        if val is None or (isinstance(val, float) and np.isnan(val)) or val == '' or str(val).lower() == 'nan':
            return '--'
        try:
            v = float(val)
            if col in ('Cl_a0', 'Cd_a0', 'Cm_a0', 'Cd_peak', 'Cl_peak', 'Cl_am2', 'Cl_ap2'):
                return f"{v:.4f}"
            elif col in ('Max_LD', 'Score', 'Score_Balanced', 'Score_Autocross', 'Score_Efficiency', 'Score_Robust', 'Score_LapTime'):
                return f"{v:.2f}"
            elif col in ('Downforce_N', 'Drag_N', 'Duration_s'):
                return f"{v:.1f}"
            elif col in ('F1_Scale', 'F1_Angle', 'F1_X', 'F1_Y',
                         'F2_Scale', 'F2_Angle', 'F2_X', 'F2_Y',
                         'F3_Scale', 'F3_Angle', 'F3_X', 'F3_Y',
                         'Stall_Angle', 'Height_pct',
                         'Stack_Length_mm', 'Stack_Height_mm', 'Min_Clearance_mm',
                         'Main_to_F1_Gap_pct', 'Main_to_F1_Overlap_pct', 'Main_to_F1_Step_pct',
                         'F1_to_F2_Gap_pct', 'F1_to_F2_Overlap_pct', 'F1_to_F2_Step_pct',
                         'F2_to_F3_Gap_pct', 'F2_to_F3_Overlap_pct', 'F2_to_F3_Step_pct',
                         'Stack_Length_pct', 'Stack_Height_pct', 'Min_Clearance_pct',
                         'Speed_ms'):
                return f"{v:.1f}" if (v % 1 != 0) else f"{int(v)}"
            elif col in ('Elements', 'Rank', 'Tier'):
                return f"{int(v)}"
            elif abs(v) < 1e-4 and v != 0:
                return f"{v:.2e}"
            elif abs(v) >= 1000:
                return f"{v:.1f}"
            elif isinstance(val, float):
                return f"{v:.3f}"
        except (ValueError, TypeError):
            pass
        return str(val)

    def load_results_cache(self):
        p = os.path.expanduser(self.res_file.get())
        if not os.path.exists(p):
            cand = self.discover_results()
            if not cand:
                return
            p = cand[0]
            self.res_file.set(p)
        try:
            self.results = A.read_results_csv(p)
            if not self.results.empty:
                for col in A.SCORE_FIELDS:
                    if col not in self.results.columns:
                        self.results[col] = float('nan')
                # If historical CSV doesn't have the multi-profile scores, backfill them on the fly
                if 'Score_Autocross' in self.results.columns and (self.results['Score_Autocross'].isna().all() or self.results['Score_Autocross'].isnull().all()):
                    records = self.results.to_dict('records')
                    scored = [A.rate_all_profiles(r, str(r.get('Status', ''))) for r in records]
                    score_df = pd.DataFrame(scored, index=self.results.index)
                    for c in score_df.columns:
                        if c.startswith('Score'):
                            self.results[c] = score_df[c]
            self._tree_frame = self.results.reset_index(drop=True)
            self._sort_col = None
            self._sort_asc = True
            self._setup_tree_columns()
            self._apply_results_view()
            n = len(self.results)
            ns = self._tree_frame
            what = os.path.dirname(p) or '.'
            if 'Duration_s' in ns.columns and 'Date' in ns.columns:
                dur = pd.to_numeric(ns['Duration_s'], errors='coerce')
                tot = dur.sum()
                span = f"  |  sim time {tot:.0f}s across {n} runs" if tot else f"  |  {n} runs"
                dates = ns['Date'].dropna().astype(str)
                if len(dates):
                    span += f"  |  first {dates.min()}  ->  last {dates.max()}"
            else:
                span = f"  |  {n} runs"
            self.set_detail(f"{n} simulations loaded from {what}{span}")
            self._refresh_csv_view()
        except Exception as e:
            self.set_detail(f"load failed: {e}")

    def _sort_results_by(self, col):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            # When ranking by performance metrics, high values are top -> start descending
            high_first = {
                'Score', 'Score_Balanced', 'Score_Autocross', 'Score_Efficiency', 'Score_Robust', 'Score_LapTime',
                'Downforce_N', 'Max_LD', 'Cl_a0', 'Cl_peak',
                'Elements', 'F1_Scale', 'F2_Scale', 'F3_Scale'
            }
            self._sort_asc = False if col in high_first else True
        self._apply_results_view()

    def _on_scoring_profile_change(self):
        sel_name = self.res_scoring_profile.get() if hasattr(self, 'res_scoring_profile') else ""
        target_col = "Score_Balanced"
        target_desc = ""
        for k, p in A.SCORING_PROFILES.items():
            if p["name"] == sel_name:
                if k == "balanced": target_col = "Score_Balanced"
                elif k == "autocross": target_col = "Score_Autocross"
                elif k == "efficiency": target_col = "Score_Efficiency"
                elif k == "robust": target_col = "Score_Robust"
                elif k == "laptime": target_col = "Score_LapTime"
                target_desc = p["description"]
                break
        if hasattr(self, 'prof_desc_lbl'):
            self.prof_desc_lbl.configure(text=target_desc)
        if hasattr(self, '_tree_frame') and self._tree_frame is not None and not self._tree_frame.empty:
            if target_col in self._tree_frame.columns:
                self._sort_col = target_col
                self._sort_asc = False
                self._apply_results_view()
            elif 'Score' in self._tree_frame.columns:
                self._sort_col = 'Score'
                self._sort_asc = False
                self._apply_results_view()

    def _apply_results_view(self):
        if not hasattr(self, '_tree_frame') or self._tree_frame is None or self._tree_frame.empty:
            return
        view = self._tree_frame
        q = self.res_filter.get().strip().lower()
        if q:
            mask = view.astype(str).apply(lambda col: col.str.lower().str.contains(q, regex=False)).any(axis=1)
            view = view[mask]
            
        # Numerical ranking & sorting based on headline click
        if self._sort_col and self._sort_col in view.columns:
            num_s = pd.to_numeric(view[self._sort_col], errors='coerce')
            if num_s.notna().sum() > 0:
                view = view.sort_values(
                    self._sort_col,
                    ascending=self._sort_asc,
                    key=lambda s: pd.to_numeric(s, errors='coerce'),
                    na_position='last'
                )
            else:
                view = view.sort_values(
                    self._sort_col,
                    ascending=self._sort_asc,
                    key=lambda s: s.astype(str).str.lower(),
                    na_position='last'
                )
        self._view_rows = view.index.tolist()
        
        # Update column headings with sort indicator arrows
        cols = getattr(self, '_results_cols', [])
        for c in cols:
            if c == self._sort_col:
                arrow = " ▲" if self._sort_asc else " ▼"
                self.tree.heading(c, text=f"{c}{arrow}", anchor='center')
            else:
                self.tree.heading(c, text=c, anchor='center')

        # Real-time KPIs calculation
        try:
            n_tot = len(view)
            self.kpi_runs.set(f"Runs: {n_tot}")
            if 'Downforce_N' in view.columns:
                df_num = pd.to_numeric(view['Downforce_N'], errors='coerce')
                self.kpi_df.set(f"Max Downforce: {df_num.max():.1f} N" if pd.notna(df_num.max()) else "Max Downforce: --")
            if 'Max_LD' in view.columns:
                ld_num = pd.to_numeric(view['Max_LD'], errors='coerce')
                self.kpi_ld.set(f"Max L/D: {ld_num.max():.2f}" if pd.notna(ld_num.max()) else "Max L/D: --")
            if 'Score' in view.columns:
                sc_num = pd.to_numeric(view['Score'], errors='coerce')
                self.kpi_score.set(f"Best Score: {sc_num.max():.2f}" if pd.notna(sc_num.max()) else "Best Score: --")
            if 'Status' in view.columns:
                n_val = (view['Status'].astype(str).str.lower() == 'valid').sum()
                pct = (n_val / max(1, n_tot)) * 100
                self.kpi_valid.set(f"Valid: {pct:.1f}% ({n_val}/{n_tot})")
            if 'Duration_s' in view.columns:
                dur_num = pd.to_numeric(view['Duration_s'], errors='coerce')
                tot_s = dur_num.sum()
                self.kpi_time.set(f"Sim Time: {tot_s:.0f}s" if pd.notna(tot_s) and tot_s > 0 else "Sim Time: --")
        except Exception:
            pass

        # Populate rows with formatted and aligned values
        self.tree.delete(*self.tree.get_children())
        cap = 1000
        status_col = cols.index('Status') if 'Status' in cols else None
        tier_col = cols.index('Tier') if 'Tier' in cols else None
        
        for pos, (orig_idx, row_series) in enumerate(view.iterrows()):
            if pos >= cap:
                break
            vals = [self._format_cell(c, row_series.get(c)) for c in cols]
            tags = ['odd' if pos % 2 == 1 else 'even']
            if status_col is not None:
                st = str(row_series.get('Status', '')).lower()
                if st == 'valid':
                    tags.append('status_valid')
                elif st in ('failed', 'stall', 'error'):
                    tags.append('status_failed')
            if tier_col is not None and str(row_series.get('Tier', '')) == '1':
                tags.append('tier_1')
            self.tree.insert('', 'end', iid=str(pos), values=vals, tags=tuple(tags))

        sort_txt = f"Ranked by: {self._sort_col} ({'▲ Asc' if self._sort_asc else '▼ Desc'}) · " if self._sort_col else ""
        stat = f"{sort_txt}{len(self._view_rows)} shown" + (f" of {len(self._tree_frame)}" if q else "") + (f" · first {cap} rendered" if len(self._view_rows) > cap else "")
        self.res_stats.set(stat)

    def _reset_results_view(self):
        self.res_filter.set('')
        self._sort_col = None
        self._sort_asc = True
        self._apply_results_view()

    def on_targets(self):
        if not T:
            self.log('aero_targets not available')
            return
        rp = os.path.expanduser(self.res_file.get())
        if not os.path.exists(rp):
            self.log(f"no results at {rp} - pick a run first")
            return
        role0 = ATTR[self._role_state.get()][0]

        def work():
            import io, contextlib
            buf = io.StringIO()
            with self._cli_lock:
                with contextlib.redirect_stdout(buf):
                    saved = sys.argv
                    sys.argv = ['aero_targets.py', '--results', rp, '--role', role0, '--top', '10']
                    try:
                        T.main()
                    except SystemExit:
                        pass
                    except Exception as e:
                        import traceback
                        traceback.print_exc(file=buf)
                        buf.write(f"\naero_targets failed: {type(e).__name__}: {e}")
                    finally:
                        sys.argv = saved
            self.log(buf.getvalue()[-2500:])
        threading.Thread(target=work, daemon=True).start()

    def _selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            i = int(sel[0])
            return self._tree_frame.loc[self._view_rows[i]]
        except Exception:
            return None

    def row_detail(self, r):
        def f(k, spec=''):
            v = r.get(k)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return '--'
            if spec:
                return f"{v:{spec}}".strip()
            return str(v)

        flaps = []
        for k in (1, 2, 3):
            n = f(f"F{k}_Airfoil")
            if n != '--':
                flaps.append(
                    f"F{k}: {n} {f(f'F{k}_Scale')}% {f(f'F{k}_Angle')}deg X{f(f'F{k}_X')} Y{f(f'F{k}_Y')}"
                )

        line1 = f"{r.get('Run_ID', '')}  {r.get('Status', '')}  |  {r.get('Date', '')}  |  duration {f('Duration_s')} s  |  {r.get('Alpha_Interval', '')}"
        line2 = f"elements: {f('Elements')}  main: {r.get('Main', '--')}" + (f"  ｜  {'  ,  '.join(flaps)}" if flaps else "")
        line3 = f"flow: {f('Flow')}" + (f"  height {f('Height_pct')}% chord" if str(r.get('Flow', '')).lower() == 'ground' else "")
        line4 = (
            f"polar: Cl_peak {f('Cl_peak')} @ stall {f('Stall_Angle')}deg | Cl_a0 {f('Cl_a0', '.4f')}  "
            f"Cd_a0 {f('Cd_a0', '.5f')}  Cm_a0 {f('Cm_a0')} | Cl -2/+2 {f('Cl_am2')} / {f('Cl_ap2')} | max L/D {f('Max_LD')}"
        )
        line5 = f"aerodynamics: downforce {f('Downforce_N', '.1f')} N   drag {f('Drag_N', '.4f')} N   (q = 0.5*1.225*v^2, area from span)"
        line6 = (
            f"geometry: stack length {f('Stack_Length_mm', '.0f')} mm  height {f('Stack_Height_mm', '.0f')} mm  "
            f"clearance {f('Min_Clearance_mm', '.0f')} mm  |  rank {f('Rank')}  tier {f('Tier')}  score {f('Score', '.2f')}"
        ).strip()

        lines = [line1, line2, line3, line4, line5, line6]
        return '\n'.join(lines)

    def set_detail(self, text):
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', text)
        self.detail.configure(state='disabled')

    def on_row(self, event=None):
        r = self._selected_row()
        if r is None or (hasattr(r, "empty") and r.empty):
            return
        self.set_detail(self.row_detail(r))

    def _show_tree_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)
            r = self._selected_row()
            if r is not None and not (hasattr(r, 'empty') and r.empty):
                self.set_detail(self.row_detail(r))
        r = self._selected_row()
        if r is None or (hasattr(r, 'empty') and r.empty):
            return
        menu = tk.Menu(self.tree, tearoff=0)
        rid = r.get('Run_ID', '')
        menu.add_command(label=f"Run {rid} Options:", state='disabled')
        menu.add_separator()
        menu.add_command(label="🚀  Send to Optimizer (Set as Base Design)", command=lambda: self.on_send_to_optimizer(r))
        menu.add_command(label="📐  Export 2D CAD Model (AutoCAD DXF)...", command=lambda: self.on_export_cad_dxf(r))
        menu.add_command(label="🎨  Export Vector Geometry (SVG)...", command=lambda: self.on_export_cad_svg(r))
        menu.add_command(label="⚙️  Load to Configure Tab", command=self.on_apply_to_config)
        menu.add_separator()
        menu.add_command(label="📊  Generate All Graphs (Code + JavaFoil) & View", command=lambda: self._gen_graphs(r, switch=True))
        menu.add_command(label="📁  Open Run Graphs Folder in File Manager", command=lambda: self.on_open_run_folder(r))
        menu.add_command(label="📋  Copy Run Telemetry / Summary to Clipboard", command=lambda: self.on_copy_run_telemetry(r))
        menu.add_command(label="🗜️  Export Run Archive (.zip)...", command=lambda: self.on_export_selected_run_archive(r))
        menu.tk_popup(event.x_root, event.y_root)

    def on_send_to_optimizer(self, r=None):
        if r is None:
            r = self._selected_row()
        if r is None or (hasattr(r, 'empty') and r.empty):
            messagebox.showwarning("No Run Selected", "Please select a simulation run first.")
            return
        ok = self.set_optimizer_base_from_row(r)
        if ok:
            self.log(f"Transferred Run {r.get('Run_ID')} to Optimizer as base design.")

    def on_export_cad_dxf(self, r=None):
        if r is None:
            r = self._selected_row()
        if r is None or (hasattr(r, 'empty') and r.empty):
            messagebox.showwarning("No Run Selected", "Please select a simulation run first.")
            return
        cfg = self._row_to_cfg(r)
        if not cfg:
            messagebox.showerror("Error", "Could not extract wing configuration from this run.")
            return
        rid = str(r.get('Run_ID', 'wing'))
        p = filedialog.asksaveasfilename(
            title="Export 2D CAD Model (DXF)",
            defaultextension=".dxf",
            initialfile=f"wing_run_{rid}.dxf",
            filetypes=[("AutoCAD DXF File", "*.dxf"), ("All Files", "*.*")]
        )
        if not p:
            return
        chord = A.CHORD_MM or A.DEFAULT_CHORD_MM
        gh = float(r['Height_pct']) if str(r.get('Flow', '')).lower() == 'ground' and 'Height_pct' in r and pd.notna(r['Height_pct']) else None
        try:
            A.export_dxf(cfg, p, chord_mm=chord, ground_h=gh, title=f"Run {rid} - {A.describe(cfg)}")
            self.log(f"Exported CAD DXF to {p}")
            messagebox.showinfo("Export Complete", f"Successfully exported 2D CAD model:\n{p}\n\nLayers created: MAIN_ELEMENT, FLAP_1..N, GROUND_PLANE, BOUNDING_BOX.")
        except Exception as e:
            messagebox.showerror("Export Failed", f"DXF export failed: {e}")

    def on_export_cad_svg(self, r=None):
        if r is None:
            r = self._selected_row()
        if r is None or (hasattr(r, 'empty') and r.empty):
            messagebox.showwarning("No Run Selected", "Please select a simulation run first.")
            return
        cfg = self._row_to_cfg(r)
        if not cfg:
            messagebox.showerror("Error", "Could not extract wing configuration from this run.")
            return
        rid = str(r.get('Run_ID', 'wing'))
        p = filedialog.asksaveasfilename(
            title="Export Vector Geometry (SVG)",
            defaultextension=".svg",
            initialfile=f"wing_run_{rid}.svg",
            filetypes=[("SVG Vector Image", "*.svg"), ("All Files", "*.*")]
        )
        if not p:
            return
        chord = A.CHORD_MM or A.DEFAULT_CHORD_MM
        gh = float(r['Height_pct']) if str(r.get('Flow', '')).lower() == 'ground' and 'Height_pct' in r and pd.notna(r['Height_pct']) else None
        try:
            A.export_svg(cfg, p, chord_mm=chord, ground_h=gh, title=f"Run {rid} - {A.describe(cfg)}")
            self.log(f"Exported SVG to {p}")
            messagebox.showinfo("Export Complete", f"Successfully exported vector geometry:\n{p}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"SVG export failed: {e}")

    def on_open_run_folder(self, r=None):
        if r is None:
            r = self._selected_row()
        if r is None or (hasattr(r, 'empty') and r.empty):
            return
        p = os.path.expanduser(self.res_file.get())
        rid = str(r.get('Run_ID', ''))
        run_gdir = os.path.join(os.path.dirname(p), 'graphs', f"run_{rid}")
        target = run_gdir if os.path.isdir(run_gdir) else os.path.join(os.path.dirname(p), 'graphs')
        if not os.path.isdir(target):
            os.makedirs(target, exist_ok=True)
        subprocess_open(target)

    def on_copy_run_telemetry(self, r=None):
        if r is None:
            r = self._selected_row()
        if r is None or (hasattr(r, 'empty') and r.empty):
            return
        detail_text = self.row_detail(r)
        try:
            self.clipboard_clear()
            self.clipboard_append(detail_text)
            self.log(f"Copied telemetry for Run {r.get('Run_ID')} to clipboard.")
        except Exception as e:
            self.log(f"Clipboard copy failed: {e}")

    def on_export_selected_run_archive(self, r=None):
        if r is None:
            r = self._selected_row()
        if r is None or (hasattr(r, 'empty') and r.empty):
            return
        rid = str(r.get('Run_ID', 'run'))
        p = os.path.expanduser(self.res_file.get())
        out = filedialog.asksaveasfilename(
            title="Export Run Archive (.zip)",
            defaultextension=".zip",
            initialfile=f"simulation_run_{rid}.zip",
            filetypes=[('Zip archive', '*.zip')]
        )
        if not out:
            return
        try:
            import zipfile
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr(f"run_{rid}_telemetry.txt", self.row_detail(r))
                row_df = pd.DataFrame([r])
                z.writestr(f"run_{rid}_data.csv", row_df.to_csv(index=False))
                run_gdir = os.path.join(os.path.dirname(p), 'graphs', f"run_{rid}")
                if os.path.isdir(run_gdir):
                    for root, _, files in os.walk(run_gdir):
                        for f in files:
                            fp = os.path.join(root, f)
                            z.write(fp, os.path.join('graphs', f))
                else:
                    gdir = os.path.join(os.path.dirname(p), 'graphs')
                    for f in glob.glob(os.path.join(gdir, f"*{rid}*.png")):
                        z.write(f, os.path.join('graphs', os.path.basename(f)))
            self.log(f"Exported run archive to {out}")
            messagebox.showinfo("Export Complete", f"Exported complete run archive:\n{out}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Archive export failed: {e}")

    def _gen_graphs(self, r, switch=True, force_regen=False):
        p = os.path.expanduser(self.res_file.get())
        if not os.path.exists(p):
            return
        try:
            rid = str(r['Run_ID'])
        except Exception:
            return
        base_dir = os.path.dirname(p)
        gdir = os.path.join(base_dir, 'graphs')
        run_gdir = os.path.join(gdir, f"run_{rid}")
        os.makedirs(gdir, exist_ok=True)
        os.makedirs(run_gdir, exist_ok=True)
        
        self.gr_results.set(p)
        self.gr_selected_rid = rid
        if switch:
            try:
                self.notebook.select(self.tab_gr)
            except Exception:
                pass

        # Check if already generated
        existing_pngs = glob.glob(os.path.join(run_gdir, "*.png")) if os.path.isdir(run_gdir) else []
        if not existing_pngs:
            existing_pngs = glob.glob(os.path.join(gdir, f"*_{rid}.png")) + glob.glob(os.path.join(gdir, f"*{rid}*.png"))

        if existing_pngs and not force_regen:
            self.ui_q.put(('gr_prog', (100, f"Run {rid}: {len(existing_pngs)} graphs ready (loaded from cache)")))
            self.ui_q.put(('gr_done', (r, p, rid, run_gdir, True)))
            return

        self.ui_q.put(('gr_prog', (5, f"Starting generation for Run {rid}...")))
        chord = A.CHORD_MM or A.DEFAULT_CHORD_MM
        span_fw = getattr(A, 'DEFAULT_SPAN_FW_MM', 1400.0)
        span_rw = getattr(A, 'DEFAULT_SPAN_RW_MM', 950.0)
        cfg = self._row_to_cfg(r)
        gh = float(r['Height_pct']) if str(r.get('Flow', '')).lower() == 'ground' and 'Height_pct' in r and pd.notna(r['Height_pct']) else None
        re_val = float(r.get('Re', A.RE)) if pd.notna(r.get('Re', None)) else A.RE
        v_val = float(r.get('Speed', A.DEFAULT_SPEED)) if pd.notna(r.get('Speed', None)) else A.DEFAULT_SPEED

        def work():
            outs = []
            # 1. Matplotlib code graphs (saved into both run_gdir and gdir)
            self.ui_q.put(('gr_prog', (25, f"Run {rid} [1/4]: Generating aerodynamic polar & geometry...")))
            if R:
                for target_dir in (run_gdir, gdir):
                    polar = os.path.join(target_dir, f"polar_{rid}.png")
                    geometry = os.path.join(target_dir, f"geometry_{rid}.png")
                    try:
                        if not os.path.exists(polar) or force_regen:
                            R.plot_polar(r, polar)
                            if target_dir == run_gdir: outs.append('polar')
                    except Exception as e:
                        self.log(f"polar graph failed: {e}")
                    try:
                        if not os.path.exists(geometry) or force_regen:
                            R.plot_geometry(r, geometry, chord)
                            if target_dir == run_gdir: outs.append('geometry')
                    except Exception as e:
                        self.log(f"geometry graph failed: {e}")

            # 2. Velocity field
            self.ui_q.put(('gr_prog', (50, f"Run {rid} [2/4]: Simulating velocity flow field...")))
            if R:
                for target_dir in (run_gdir, gdir):
                    field = os.path.join(target_dir, f"field_{rid}.png")
                    try:
                        if not os.path.exists(field) or force_regen:
                            R.plot_field(r, field, chord, span_fw, span_rw)
                            if target_dir == run_gdir: outs.append('velocity field')
                    except Exception as e:
                        self.log(f"field graph failed: {e}")
            
            # 3. Native authentic JavaFoil graphs
            self.ui_q.put(('gr_prog', (75, f"Run {rid} [3/4]: Extracting JavaFoil authentic native charts (Cp, Cf, δ)...")))
            if cfg:
                try:
                    jf_files = A.export_javafoil_graphs(
                        cfg, gh, run_gdir, run_id=rid,
                        re=re_val, v_inf=v_val
                    )
                    if jf_files:
                        outs.append(f"JavaFoil native ({len(jf_files)} plots)")
                        file_list = list(jf_files.values()) if isinstance(jf_files, dict) else list(jf_files)
                        for jf_f in file_list:
                            try:
                                shutil.copy2(jf_f, os.path.join(gdir, os.path.basename(jf_f)))
                            except Exception:
                                pass
                except Exception as e:
                    self.log(f"JavaFoil graph extraction failed: {e}")

            # 4. Automatic 2D CAD DXF and SVG generation in run folder
            self.ui_q.put(('gr_prog', (90, f"Run {rid} [4/4]: Generating 2D CAD models (DXF + SVG)...")))
            if cfg:
                try:
                    dxf_p = os.path.join(run_gdir, f"wing_{rid}.dxf")
                    svg_p = os.path.join(run_gdir, f"wing_{rid}.svg")
                    if not os.path.exists(dxf_p) or force_regen:
                        A.export_dxf(cfg, dxf_p, chord_mm=chord, ground_h=gh)
                    if not os.path.exists(svg_p) or force_regen:
                        A.export_svg(cfg, svg_p, chord_mm=chord, ground_h=gh)
                    outs.append("CAD DXF + SVG")
                except Exception:
                    pass

            self.ui_q.put(('gr_prog', (100, f"Run {rid}: Graphs generated successfully!")))
            self.ui_q.put(('gr_done', (r, p, rid, run_gdir, False)))
            self.ui_q.put(('log', f"Run {rid} plots & CAD ready in {run_gdir}: {', '.join(outs) if outs else 'cached'}"))

        threading.Thread(target=work, daemon=True).start()

    def on_gen_graphs(self):
        if not R:
            self.log('aero_report not importable')
            return
        r = self._selected_row()
        if r is None or (hasattr(r, 'empty') and r.empty):
            self.set_detail('Select a row in the table first, then click Generate Graphs.')
            return
        self._gen_graphs(r, switch=True)

    def ask_graph_destination(self, r, rid, run_gdir, already_existed=False):
        """
        Prompts the user whether to view generated graphs inside the app or in the OS file manager.
        """
        dlg = tk.Toplevel(self.winfo_toplevel())
        dlg.title(f"Graphs Ready — Run {rid}")
        dlg.geometry("560x280")
        dlg.minsize(500, 260)
        dlg.transient(self.winfo_toplevel())

        bg_col = '#0f172a'
        fg_col = '#f8fafc'
        card_bg = '#1e293b'

        dlg.configure(bg=bg_col)

        main_frame = tk.Frame(dlg, bg=bg_col, padx=20, pady=16)
        main_frame.pack(fill='both', expand=True)

        header_text = f"✅ Graphs Available (Run {rid})" if already_existed else f"🎉 Graphs Generated Successfully! (Run {rid})"
        lbl_head = tk.Label(main_frame, text=header_text, font=('Segoe UI', 12, 'bold'), fg='#38bdf8' if already_existed else '#4ade80', bg=bg_col)
        lbl_head.pack(anchor='w', pady=(0, 6))

        card = tk.Frame(main_frame, bg=card_bg, relief='groove', bd=1, padx=12, pady=10)
        card.pack(fill='x', pady=6)

        airfoil_info = ""
        if r is not None and not (hasattr(r, 'empty') and r.empty):
            m = r.get('Main', 'Wing')
            elem = r.get('Elements', 'Multi-element')
            cl = r.get('Cl_a0', '')
            cd = r.get('Cd_a0', '')
            airfoil_info = f"Profile: {m} ({elem} elem)  |  Cl: {cl}  |  Cd: {cd}\n"

        status_msg = (
            f"{airfoil_info}"
            f"Folder: {run_gdir}\n"
            f"Contents: Polars, Geometry, Velocity Field, JavaFoil native (Cp, Cf, δ), CAD (DXF + SVG)"
        )
        tk.Label(card, text=status_msg, font=('Segoe UI', 9), fg='#cbd5e1', bg=card_bg, justify='left').pack(anchor='w')

        tk.Label(main_frame, text="Where would you like to view the graphs?", font=('Segoe UI', 10, 'bold'), fg=fg_col, bg=bg_col).pack(anchor='w', pady=(12, 10))

        btn_frame = tk.Frame(main_frame, bg=bg_col)
        btn_frame.pack(fill='x', pady=(4, 0))

        def on_view_inside():
            dlg.destroy()
            try:
                self.notebook.select(self.tab_gr)
                self.focus_set()
            except Exception:
                pass

        def on_open_fm():
            dlg.destroy()
            subprocess_open(run_gdir)
            try:
                self.notebook.select(self.tab_gr)
                self.focus_set()
            except Exception:
                pass

        def on_regen():
            dlg.destroy()
            self._gen_graphs(r, switch=True, force_regen=True)

        b_inside = tk.Button(
            btn_frame, text="📊 Inside the App", font=('Segoe UI', 10, 'bold'),
            bg='#2563eb', fg='white', activebackground='#1d4ed8', activeforeground='white',
            padx=14, pady=6, relief='flat', cursor='hand2', command=on_view_inside
        )
        b_inside.pack(side='left', padx=(0, 8))

        b_fm = tk.Button(
            btn_frame, text="📁 In File Manager", font=('Segoe UI', 10),
            bg='#334155', fg='#f1f5f9', activebackground='#475569', activeforeground='white',
            padx=14, pady=6, relief='flat', cursor='hand2', command=on_open_fm
        )
        b_fm.pack(side='left', padx=4)

        if already_existed:
            b_regen = tk.Button(
                btn_frame, text="🔄 Regenerate Fresh", font=('Segoe UI', 9),
                bg='#1e293b', fg='#94a3b8', activebackground='#334155', activeforeground='white',
                padx=10, pady=6, relief='flat', cursor='hand2', command=on_regen
            )
            b_regen.pack(side='right', padx=(8, 0))

        dlg.bind('<Return>', lambda e: on_view_inside())
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        dlg.update_idletasks()
        try:
            pw = self.winfo_toplevel().winfo_width()
            ph = self.winfo_toplevel().winfo_height()
            px = self.winfo_toplevel().winfo_rootx()
            py = self.winfo_toplevel().winfo_rooty()
            w = max(560, dlg.winfo_reqwidth())
            h = max(280, dlg.winfo_reqheight())
            cx = max(0, px + (pw - w) // 2)
            cy = max(0, py + (ph - h) // 2)
            dlg.geometry(f"{w}x{h}+{cx}+{cy}")
        except Exception:
            pass

        dlg.deiconify()
        dlg.lift()
        try:
            dlg.grab_set()
        except Exception:
            pass
        b_inside.focus_set()

    def on_import_existing(self):
        p = filedialog.askopenfilename(
            title='Import results.csv into the library',
            initialfile='results.csv',
            filetypes=[('CSV', '*.csv'), ('All files', '*.*')]
        )
        if not p:
            return
        label = os.path.basename(os.path.dirname(os.path.abspath(p))) or None
        try:
            run = A.import_results_into_library(
                p, 'import', label, base=os.path.expanduser(self._lib_base())
            )
            if run:
                self.log(f"imported {p} -> {run}")
                self._refresh_runs()
            else:
                self.log(f"nothing imported from {p}")
        except Exception as e:
            messagebox.showerror('Import failed', str(e))

    def on_export_run(self):
        sel = self.res_folder_tree.selection()
        if not sel:
            self.log('select a run to export first')
            return
        iid = sel[0]
        d = iid if os.path.isdir(iid) else os.path.dirname(getattr(self, '_run_dirs', {}).get(iid, ''))
        if not d or not os.path.isdir(d):
            self.log('that run has no folder on disk')
            return
        base = os.path.basename(d.rstrip(os.sep)) or 'run'
        out = filedialog.asksaveasfilename(
            defaultextension='.zip',
            initialfile=base + '.zip',
            filetypes=[('Zip archive', '*.zip')]
        )
        if not out:
            return
        try:
            import zipfile
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                for root, _dirs, files in os.walk(d):
                    for f in files:
                        fp = os.path.join(root, f)
                        z.write(fp, os.path.relpath(fp, os.path.dirname(d)))
            self.log(f"exported run to {out}")
        except Exception as e:
            messagebox.showerror('Export failed', str(e))

    def _export_view(self):
        if not hasattr(self, '_tree_frame') or self._tree_frame is None or self._tree_frame.empty:
            self.set_detail('Nothing to export - load a results file first.')
            return
        idx = getattr(self, '_view_rows', None)
        view = self._tree_frame.loc[idx] if idx is not None and len(idx) else self._tree_frame
        src = os.path.expanduser(self.res_file.get())
        default_name = os.path.splitext(os.path.basename(src) or 'results.csv')[0] + '_view.csv'
        p = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(src) or '.',
            initialfile=default_name,
            defaultextension='.csv',
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')]
        )
        if not p:
            return
        try:
            view.to_csv(p, index=False)
            self.set_detail(f"Exported {len(view)} row(s) to {p}")
        except Exception as e:
            self.set_detail(f"Export failed: {e}")

    def on_open_best(self):
        sel = self.res_folder_tree.selection()
        if not sel:
            self.log('select a run first')
            return
        iid = sel[0]
        d = iid if os.path.isdir(iid) else os.path.dirname(getattr(self, '_run_dirs', {}).get(iid, ''))
        best = os.path.join(d, 'Best')
        target = best if os.path.isdir(best) else d
        if not subprocess_open(target):
            self.log(f"could not open {target}")

    def _save_csv(self):
        p = os.path.expanduser(self.res_file.get())
        if not p:
            messagebox.showerror('Error', 'No file selected')
            return
        if getattr(self, '_csv_truncated', False):
            messagebox.showwarning(
                'Too large to edit here',
                'This results file is too large to edit safely in this text box.\nUse the command line tools or an external editor instead.'
            )
            return
        content = self.csv_text.get('1.0', 'end-1c')
        if not messagebox.askyesno('Overwrite results file?', f"Overwrite:\n{p}\n\nA timestamped backup will be kept."):
            return
        try:
            import tempfile
            d = os.path.dirname(os.path.abspath(p)) or '.'
            bak = None
            if os.path.exists(p):
                bak = p.replace('.csv', f"_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
                shutil.copy(p, bak)
            fd, tmp = tempfile.mkstemp(prefix='.tmp_save_', suffix='.csv', dir=d)
            with os.fdopen(fd, 'w', newline='') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
            self.load_results_cache()
            messagebox.showinfo('Saved', f"Saved {p}" + (f"\nBackup: {bak}" if bak else ''))
        except Exception as e:
            messagebox.showerror('Error', f"Failed to save: {e}")

    def _refresh_csv_view(self):
        p = os.path.expanduser(self.res_file.get())
        self._csv_truncated = False
        if not os.path.exists(p):
            self.csv_text.configure(state='normal')
            self.csv_text.delete('1.0', 'end')
            self.csv_text.insert('1.0', 'File not found')
            self.csv_text.configure(state='disabled')
            self.csv_info_var.set('File not found')
            return
        try:
            sz = os.path.getsize(p)
            sz_str = f"{sz/1024:.1f} KB" if sz < 1048576 else f"{sz/1048576:.2f} MB"
            with open(p, 'r', errors='ignore') as f:
                content = f.read()
            lines = content.splitlines()
            n_lines = len(lines)
            self.csv_info_var.set(f"📄 {os.path.basename(p)} ({sz_str}, {n_lines} lines)")
            MAX_CHARS = 400000
            self.csv_text.configure(state='normal')
            self.csv_text.delete('1.0', 'end')
            if len(content) > MAX_CHARS:
                self._csv_truncated = True
                self.csv_text.insert('1.0', content[:MAX_CHARS] + '\n\n... [preview truncated for speed - this file is too large to edit here]')
                self.csv_text.configure(state='disabled')
            else:
                self.csv_text.insert('1.0', content)
            self.csv_text.tag_add('header', '1.0', '2.0')
        except Exception as e:
            self.csv_text.configure(state='normal')
            self.csv_text.delete('1.0', 'end')
            self.csv_text.insert('1.0', f"Error reading file: {e}")
            self.csv_text.configure(state='disabled')
            self.csv_info_var.set(f"Error reading file: {e}")

    def _open_in_calc(self):
        p = os.path.expanduser(self.res_file.get())
        if not os.path.exists(p):
            messagebox.showwarning("File Not Found", f"Cannot find:\n{p}")
            return
        if not subprocess_open(p):
            self.log(f"Could not open {p} in external spreadsheet viewer.")

    def _search_csv(self):
        query = self.csv_search_var.get().strip()
        self.csv_text.tag_remove('found', '1.0', 'end')
        if not query:
            return
        idx = '1.0'
        count = 0
        while True:
            idx = self.csv_text.search(query, idx, nocase=True, stopindex='end')
            if not idx:
                break
            lastidx = f"{idx}+{len(query)}c"
            self.csv_text.tag_add('found', idx, lastidx)
            if count == 0:
                self.csv_text.see(idx)
            idx = lastidx
            count += 1
        self.csv_info_var.set(f"Found {count} match(es) for '{query}'")

    def _clear_csv_search(self):
        self.csv_search_var.set('')
        self.csv_text.tag_remove('found', '1.0', 'end')
        self._refresh_csv_view()

    def on_report_picked(self):
        p = self.gr_results.get() or os.path.expanduser(os.path.join(A.OUT_DIR, 'results.csv'))
        if os.path.exists(p):
            self.on_report(p)
            self.ui_q.put(('refreshgr', p))

    def on_browse(self):
        p = filedialog.askopenfilename(initialfile='results.csv')
        if p:
            self.res_file.set(p)
            self.load_results_cache()

    def on_extract_configured_graphs(self):
        """Extracts JavaFoil's authentic native graphs for the currently configured wing."""
        cfg_tuple = self.read_cfg()
        if not cfg_tuple:
            return
        main, flaps, gh, rle, ch, v, re_val, a0, a1, st, sp = cfg_tuple
        cfg = (main, flaps)
        ground_h = gh
        run_tag = f"live_{main}_{len(flaps)}elem"
        gdir = os.path.join(A.OUT_DIR, "graphs")
        os.makedirs(gdir, exist_ok=True)
        self.log(f"Extracting JavaFoil native graphs for {run_tag} in background...")

        def work():
            outs = []
            try:
                dummy_r = {
                    "Main": main,
                    "Elements": 1 + len(flaps),
                    "Cl_a0": 0.0, "Cd_a0": 0.0, "Cm_a0": 0.0, "Max_LD": 0.0, "Downforce_N": 0.0,
                    "Flow": "ground" if ground_h is not None else "unbounded",
                    "Height_pct": ground_h or 0,
                    "Run_ID": run_tag
                }
                for k, (fn, sc, ang, xpos, ypos) in enumerate(flaps, 1):
                    dummy_r[f"F{k}_Airfoil"] = fn
                    dummy_r[f"F{k}_Scale"] = sc
                    dummy_r[f"F{k}_Angle"] = ang
                    dummy_r[f"F{k}_X"] = xpos
                    dummy_r[f"F{k}_Y"] = ypos
                if R is not None:
                    try:
                        R.plot_geometry(dummy_r, os.path.join(gdir, f"geometry_{run_tag}.png"), ch)
                        outs.append("custom geometry")
                    except Exception:
                        pass

                jf_outs = A.export_javafoil_graphs(cfg, ground_h, gdir, run_id=run_tag,
                                                   re=re_val, alphas=(a0, a1, st), v_inf=v)
                if jf_outs:
                    outs.append(f"JavaFoil native ({len(jf_outs)} plots: polar, Cp, BL)")

                self.ui_q.put(("refreshgr", os.path.join(A.OUT_DIR, "results.csv")))
                self.ui_q.put(("log", f"Graphs extracted to {gdir}: {', '.join(outs) or 'none'}"))
                self.after(200, lambda: self.notebook.select(self.tab_gr))
            except Exception as e:
                self.ui_q.put(("log", f"JavaFoil graph extraction failed: {e}"))

        threading.Thread(target=work, daemon=True).start()

    on_extract_javafoil_graphs = on_extract_configured_graphs

    def on_apply_to_config(self):
        r = self._selected_row()
        if r is None or (hasattr(r, "empty") and r.empty):
            self.set_detail('select a row in the table first, then hit Load to Configure')
            return
        cfg = self._row_to_cfg(r)
        if not cfg:
            self.set_detail('could not extract wing configuration from selected row')
            return
        self._opt_best_cfg = cfg
        self._opt_apply_best()
        self.set_detail(f"Loaded {A.describe(cfg)} into Configure tab")

    discover_all_csvs = discover_results
    sort_by_column = _sort_results_by
    _filter_and_render_table = _apply_results_view
    def build_graphs(self):
        gr = ttk.Frame(self.tab_gr)
        gr.pack(fill='both', expand=True, padx=6, pady=6)

        # 1. Active Run Generation Progress Banner
        self.gr_prog_frame = ttk.LabelFrame(gr, text='Active Run Generation Progress')
        self.gr_prog_frame.pack(fill='x', padx=6, pady=(0, 6))

        prow = ttk.Frame(self.gr_prog_frame)
        prow.pack(fill='x', padx=8, pady=4)
        self.gr_prog_lbl = ttk.Label(
            prow,
            text='Ready — Select a simulation run to view or generate aerodynamic graphs.',
            font=('Segoe UI', 9, 'bold')
        )
        self.gr_prog_lbl.pack(side='left', fill='x', expand=True)

        self.gr_prog_bar = ttk.Progressbar(self.gr_prog_frame, orient='horizontal', mode='determinate')
        self.gr_prog_bar.pack(fill='x', padx=8, pady=(0, 6))

        # 2. Results Files / Runs Directory Browser (Compact)
        browser = ttk.LabelFrame(gr, text='Results File & Campaigns')
        browser.pack(fill='x', padx=6, pady=(0, 6))
        trow = ttk.Frame(browser)
        trow.pack(fill='x', padx=6, pady=(4, 0))
        ttk.Button(trow, text='Refresh', command=self._refresh_gr_folders).pack(side='left')
        wr = ttk.Button(trow, text='Write report', command=self.on_report_picked)
        wr.pack(side='left', padx=4)
        add_tooltip(wr, 'Build the full report (Best/ + graphs) for the currently selected run.')
        op = ttk.Button(trow, text='Open in viewer', command=self.on_open_graph)
        op.pack(side='left', padx=4)
        add_tooltip(op, 'Open the selected image with the OS image viewer.')
        self.gr_folder_tree = ttk.Treeview(browser, columns=('Date', 'Images'), show='tree headings', height=4)
        self.gr_folder_tree.heading('#0', text='Results file')
        self.gr_folder_tree.heading('Date', text='Modified')
        self.gr_folder_tree.heading('Images', text='Images')
        self.gr_folder_tree.column('#0', width=360)
        self.gr_folder_tree.column('Date', width=140)
        self.gr_folder_tree.column('Images', width=80)
        self.gr_folder_tree.pack(fill='x', padx=6, pady=4)
        self.gr_folder_tree.bind('<<TreeviewSelect>>', self._on_gr_folder_select)

        # 3. Main Viewer Area
        mid = ttk.Frame(gr)
        mid.pack(fill='both', expand=True, pady=4)
        
        # Left Panel: Run Filter + Image List + Action Buttons
        pick = ttk.Frame(mid)
        pick.pack(side='left', fill='y')

        filter_box = ttk.LabelFrame(pick, text='Run Filter')
        filter_box.pack(fill='x', pady=(0, 4))
        
        f_top = ttk.Frame(filter_box)
        f_top.pack(fill='x', padx=4, pady=2)
        ttk.Label(f_top, text='Viewing Run:', font=('Segoe UI', 9, 'bold')).pack(side='left')
        self.gr_run_combo = ttk.Combobox(f_top, state='readonly', width=16)
        self.gr_run_combo.pack(side='left', fill='x', expand=True, padx=(4, 0))
        self.gr_run_combo.bind('<<ComboboxSelected>>', self._on_gr_run_combo_select)
        add_tooltip(self.gr_run_combo, 'Filter graphs to a specific run so past images do not clutter your view.')

        f_bot = ttk.Frame(filter_box)
        f_bot.pack(fill='x', padx=4, pady=(2, 4))
        cb_only = ttk.Checkbutton(
            f_bot, text='Show selected run only',
            variable=self.gr_only_active_run, command=self._on_gr_filter_toggle
        )
        cb_only.pack(anchor='w')
        add_tooltip(cb_only, 'When checked, hides graphs from all other runs to prevent confusion.')

        ttk.Label(pick, text='Run Aerodynamic Graphs:').pack(anchor='w', pady=(2, 0))
        self.img_list = tk.Listbox(pick, width=38, height=16, selectmode='browse')
        self.img_list.pack(fill='both', expand=True)
        add_tooltip(self.img_list, 'Select an aerodynamic chart or CAD model to display in the viewer.')
        self.img_list.bind('<<ListboxSelect>>', self.on_pick_graph)

        # Action Buttons Under Image List
        btn_box = ttk.Frame(pick)
        btn_box.pack(fill='x', pady=(4, 0))
        
        b_fm = ttk.Button(btn_box, text='📁 Open in File Manager', command=self.on_open_current_run_folder)
        b_fm.pack(fill='x', pady=1)
        add_tooltip(b_fm, 'Open the run folder in Windows Explorer / OS file manager.')

        b_os = ttk.Button(btn_box, text='🔍 Open in OS Viewer', command=self.on_open_graph)
        b_os.pack(fill='x', pady=1)
        add_tooltip(b_os, 'Open the selected graph in the default image viewer.')

        b_reg = ttk.Button(btn_box, text='🔄 Regenerate Run Graphs', command=self.on_regenerate_current_run_graphs)
        b_reg.pack(fill='x', pady=1)
        add_tooltip(b_reg, 'Force recalculation and re-rendering of all graphs for this run.')

        # Right Panel: Large Image Canvas / Label
        self.gimg_lbl = ttk.Label(mid, text='select an image', anchor='center')
        self.gimg_lbl.pack(side='left', fill='both', expand=True, padx=6)

        # 4. Bottom Status
        self.gr_status = tk.StringVar(value='')
        ttk.Label(gr, textvariable=self.gr_status).pack(fill='x', pady=(4, 0))

        self._refresh_gr_folders()

    def _refresh_gr_folders(self):
        self.gr_folder_tree.delete(*self.gr_folder_tree.get_children())
        base = A.OUT_DIR
        for p in self.discover_results():
            try:
                rel = os.path.relpath(p, base)
            except Exception:
                rel = p
            gdir = os.path.join(os.path.dirname(p), 'graphs')
            nimg = len(glob.glob(os.path.join(gdir, '*.png'))) if os.path.isdir(gdir) else 0
            try:
                dt = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(p)))
            except OSError:
                dt = ''
            self.gr_folder_tree.insert('', 'end', text=rel, values=(dt, nimg), iid=p)

    def _on_gr_folder_select(self, event=None):
        sel = self.gr_folder_tree.selection()
        if not sel:
            return
        csv_path = sel[0]
        if os.path.exists(csv_path):
            self.gr_results.set(csv_path)
            self.refresh_graph_files(csv_path)

    def _on_gr_run_combo_select(self, event=None):
        val = self.gr_run_combo.get()
        if not val:
            return
        if "--- All Runs" in val:
            self.gr_selected_rid = ""
            self.refresh_graph_files(select_rid="")
        elif val.startswith("Run "):
            rid = val.replace("Run ", "").strip()
            self.gr_selected_rid = rid
            self.refresh_graph_files(select_rid=rid)

    def _on_gr_filter_toggle(self):
        self.refresh_graph_files(select_rid=self.gr_selected_rid)

    def refresh_graph_files(self, path=None, select_rid=None):
        cur = os.path.expanduser(path or self.gr_results.get() or '')
        paths = self.discover_results()
        if cur and os.path.exists(cur) and cur not in paths:
            paths.insert(0, cur)
        if cur and os.path.exists(cur):
            self.gr_results.set(cur)
        elif paths:
            cur = paths[0]
            self.gr_results.set(cur)
        else:
            cur = ''
        p = cur
        gdir = os.path.join(os.path.dirname(p), 'graphs') if p else ''
        legacy = os.path.join(os.path.dirname(p), 'Best', 'graphs') if p else ''

        # 1. Discover all runs that have generated graphs
        available_runs = {}
        if gdir and os.path.isdir(gdir):
            for d in sorted(glob.glob(os.path.join(gdir, "run_*"))):
                if os.path.isdir(d):
                    rid = os.path.basename(d).replace("run_", "")
                    pngs = sorted(glob.glob(os.path.join(d, "*.png")))
                    if pngs:
                        available_runs[rid] = pngs
            for f in sorted(glob.glob(os.path.join(gdir, "*.png"))):
                bn = os.path.basename(f)
                m = re.search(r'_([0-9a-zA-Z]+)\.png$', bn)
                if m:
                    rid = m.group(1)
                    if rid not in available_runs:
                        available_runs[rid] = []
                    if f not in available_runs[rid]:
                        available_runs[rid].append(f)
        if legacy and os.path.isdir(legacy):
            legacy_pngs = sorted(glob.glob(os.path.join(legacy, "*.png")))
            if legacy_pngs:
                available_runs['best'] = legacy_pngs

        all_rids = sorted(available_runs.keys(), key=lambda x: (int(x) if x.isdigit() else 999999, str(x)))

        # Update combobox items
        combo_vals = [f"Run {r}" for r in all_rids]
        if combo_vals:
            combo_vals.append("--- All Runs / All Images ---")
        if hasattr(self, 'gr_run_combo'):
            self.gr_run_combo['values'] = combo_vals

        if select_rid is not None:
            self.gr_selected_rid = str(select_rid)
        elif not self.gr_selected_rid and all_rids:
            self.gr_selected_rid = all_rids[-1]

        if hasattr(self, 'gr_run_combo'):
            if self.gr_selected_rid and f"Run {self.gr_selected_rid}" in combo_vals:
                self.gr_run_combo.set(f"Run {self.gr_selected_rid}")
            elif combo_vals:
                self.gr_run_combo.set(combo_vals[0])

        filter_only_active = self.gr_only_active_run.get() if hasattr(self, 'gr_only_active_run') else True
        combo_selection = self.gr_run_combo.get() if hasattr(self, 'gr_run_combo') else ""

        self._graph_paths = []
        display_items = []

        if filter_only_active and combo_selection != "--- All Runs / All Images ---" and self.gr_selected_rid:
            rid = self.gr_selected_rid
            target_files = available_runs.get(rid, [])
            if not target_files and gdir:
                run_gdir = os.path.join(gdir, f"run_{rid}")
                if os.path.isdir(run_gdir):
                    target_files = sorted(glob.glob(os.path.join(run_gdir, "*.png")))

            def graph_sort_and_label(f):
                bn = os.path.basename(f).lower()
                if 'polar' in bn and 'javafoil' not in bn:
                    return (0, "📊 Aerodynamic Polar (Cl vs Cd)")
                elif 'geometry' in bn:
                    return (1, "📐 Wing Profile & Slot Geometry")
                elif 'field' in bn:
                    return (2, "💨 Flow Velocity Field")
                elif 'javafoil_polar_cl_cd' in bn:
                    return (3, "📈 JavaFoil Drag Polar (Cl vs Cd)")
                elif 'javafoil_polar_cl_alfa' in bn:
                    return (4, "📈 JavaFoil Lift Curve (Cl vs α)")
                elif 'javafoil_polar_cm_alfa' in bn:
                    return (5, "📈 JavaFoil Pitching Moment (Cm vs α)")
                elif 'javafoil_velocity_cp' in bn:
                    return (6, "🌊 JavaFoil Surface Pressure Cp")
                elif 'javafoil_bl_cf' in bn:
                    return (7, "🔬 JavaFoil Skin Friction Cf")
                elif 'javafoil_bl_delta' in bn:
                    return (8, "📏 JavaFoil Boundary Layer (δ)")
                else:
                    return (9, f"📊 {os.path.basename(f)}")

            sorted_labeled = sorted([(graph_sort_and_label(f), f) for f in target_files], key=lambda x: x[0][0])
            for (order, lbl), f in sorted_labeled:
                self._graph_paths.append(f)
                display_items.append(lbl)
        else:
            all_files = []
            if gdir and os.path.isdir(gdir):
                top_pngs = sorted(glob.glob(os.path.join(gdir, '*.png')))
                sub_pngs = sorted(glob.glob(os.path.join(gdir, '*', '*.png')))
                all_files = sorted(set(top_pngs + sub_pngs))
            if legacy and os.path.isdir(legacy):
                all_files = sorted(set(all_files + sorted(glob.glob(os.path.join(legacy, '*.png')))))
            for f in all_files:
                rel = os.path.relpath(f, gdir) if gdir and f.startswith(gdir) else os.path.basename(f)
                self._graph_paths.append(f)
                display_items.append(rel)

        self.img_list.delete(0, 'end')
        for itm in display_items:
            self.img_list.insert('end', itm)

        cur_rid = self.gr_selected_rid or 'all'
        if filter_only_active and combo_selection != "--- All Runs / All Images ---":
            if self._graph_paths:
                self.gr_status.set(f"Run {cur_rid}: {len(self._graph_paths)} graph(s) displayed from {gdir}/run_{cur_rid}")
            else:
                self.gr_status.set(f"Run {cur_rid}: No graphs generated yet. Click '⚡ Generate Graphs' to create them.")
        else:
            self.gr_status.set(f"All Runs: {len(self._graph_paths)} image(s) found in {gdir}")

        if self._graph_paths:
            self.img_list.selection_set(0)
            self.show_image(self._graph_paths[0])
        else:
            self.gimg_lbl.configure(image='', text=f"No graphs for Run {cur_rid}\nClick '📊 Generate Graphs' to generate.")

    def on_pick_graph(self, event=None):
        sel = self.img_list.curselection()
        if not sel:
            return
        path = self._graph_paths[sel[0]]
        self.show_image(path)

    def show_image(self, path):
        if not HAS_PIL:
            self.gimg_lbl.configure(image='', text=f"[Pillow missing - open with your viewer]\n{path}")
            return
        if not path or not os.path.exists(path):
            self.gimg_lbl.configure(image='', text='select an image')
            return
        self._cur_graph_path = path
        try:
            with Image.open(path) as img:
                w = max(self.gimg_lbl.winfo_width(), 650)
                h = max(self.gimg_lbl.winfo_height(), 460)
                img.thumbnail((w, h))
                self._gimg = ImageTk.PhotoImage(img)
            self.gimg_lbl.configure(image=self._gimg, text='')
        except Exception as e:
            self.gimg_lbl.configure(image='', text=f"cannot show {os.path.basename(path)}: {e}")

    def on_open_graph(self):
        sel = self.img_list.curselection()
        if sel:
            subprocess_open(self._graph_paths[sel[0]])
        elif self._cur_graph_path and os.path.exists(self._cur_graph_path):
            subprocess_open(self._cur_graph_path)

    def on_open_current_run_folder(self):
        p = os.path.expanduser(self.res_file.get() or self.gr_results.get() or '')
        gdir = os.path.join(os.path.dirname(p), 'graphs') if p else ''
        rid = self.gr_selected_rid
        target = os.path.join(gdir, f"run_{rid}") if (rid and rid != 'all') else gdir
        if not os.path.isdir(target):
            target = gdir if os.path.isdir(gdir) else os.path.dirname(p)
        if not os.path.isdir(target):
            os.makedirs(target, exist_ok=True)
        subprocess_open(target)

    def on_regenerate_current_run_graphs(self):
        r = self._selected_row()
        rid = self.gr_selected_rid
        if (r is None or (hasattr(r, 'empty') and r.empty)) and rid:
            if hasattr(self, '_tree_frame') and self._tree_frame is not None and not self._tree_frame.empty:
                if 'Run_ID' in self._tree_frame.columns:
                    m = self._tree_frame[self._tree_frame['Run_ID'].astype(str) == str(rid)]
                    if not m.empty:
                        r = m.iloc[0]
        if r is not None and not (hasattr(r, 'empty') and r.empty):
            self._gen_graphs(r, switch=True, force_regen=True)
        else:
            messagebox.showinfo("Regenerate Graphs", "Please select a run in the Results table to regenerate graphs.")

    def build_optimizer(self):
        opt = ttk.Frame(self.tab_opt)
        opt.pack(fill='both', expand=True, padx=6, pady=6)
        canvas = tk.Canvas(opt, highlightthickness=0)
        scrollbar = ttk.Scrollbar(opt, orient='vertical', command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind(
            '<Configure>',
            lambda e, c=canvas: c.configure(scrollregion=c.bbox('all'))
        )
        win = canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')
        canvas.bind(
            '<Configure>',
            lambda e, c=canvas, w=win: c.itemconfigure(w, width=e.width)
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        bind_scrollable(canvas)
        
        top = ttk.LabelFrame(scrollable_frame, text='Base Wing Configuration (Manual Entry)')
        top.pack(fill='x', pady=6, padx=6, anchor='n')
        
        row = ttk.Frame(top)
        row.pack(fill='x', padx=6, pady=4)
        ttk.Label(row, text='Main element:').pack(side='left')
        self.opt_main_box = ttk.Combobox(row, values=self.names, state='readonly', width=20)
        self.opt_main_box.pack(side='left', padx=4)
        if 's1223' in self.names:
            self.opt_main_box.set('s1223')
        add_tooltip(self.opt_main_box, 'Main element airfoil')
        
        row = ttk.Frame(top)
        row.pack(fill='x', padx=6, pady=4)
        ttk.Label(row, text='Results file:').pack(side='left')
        self.opt_res_file = tk.StringVar(value=os.path.join(A.OUT_DIR, 'results.csv'))
        ttk.Entry(row, textvariable=self.opt_res_file, width=50).pack(side='left', padx=4)
        ttk.Button(row, text='Browse...', command=self._opt_browse).pack(side='left')
        ttk.Button(row, text='Load base', command=self._opt_load_base).pack(side='left', padx=4)
        
        self.opt_base_info = tk.Text(top, height=4, state='disabled', wrap='word')
        self.opt_base_info.pack(fill='x', padx=6, pady=6)
        
        ttk.Separator(top, orient='horizontal').pack(fill='x', pady=4)
        ttk.Label(top, text='Flap Configuration').pack(anchor='w', padx=6)
        self.opt_flap_rows = []
        for k in (1, 2, 3):
            frame = ttk.Frame(top)
            frame.pack(fill='x', padx=6, pady=2)
            ttk.Label(frame, text=f'F{k}').pack(side='left')
            vals = [
                tk.StringVar(value=''),
                tk.StringVar(value='30'),
                tk.StringVar(value='-6'),
                tk.StringVar(value='100'),
                tk.StringVar(value='5'),
                tk.BooleanVar(value=False)
            ]
            cb = ttk.Combobox(frame, values=self.names, textvariable=vals[0], width=14)
            cb.pack(side='left', padx=2)
            for lab, var, tip in zip(
                ['S%', 'A°', 'X%', 'Y%'],
                vals[1:5],
                ['Scale % of main chord', 'Mount angle (deg)', 'X position (% chord)', 'Y position (% chord)']
            ):
                entry = ttk.Entry(frame, textvariable=var, width=5)
                entry.pack(side='left', padx=1)
                add_tooltip(entry, tip)
            ttk.Checkbutton(frame, variable=vals[5], text='Enable').pack(side='left')
            add_tooltip(frame.winfo_children()[-1], 'Enable this flap slot')
            self.opt_flap_rows.append((vals, cb))
            
        ttk.Separator(top, orient='horizontal').pack(fill='x', pady=4)
        param_frame = ttk.Frame(top)
        param_frame.pack(fill='x', padx=6, pady=4)
        fields = [
            ('chord', 'Chord (mm)', A.DEFAULT_CHORD_MM),
            ('speed', 'Speed (m/s)', A.DEFAULT_SPEED),
            ('re', 'Reynolds', A.RE),
            ('al0', 'Alpha start', A.ALPHA[0]),
            ('al1', 'Alpha end', A.ALPHA[1]),
            ('alst', 'Alpha step', A.ALPHA[2]),
        ]
        self.opt_vars = {}
        for i, (k, lab, default) in enumerate(fields):
            ttk.Label(param_frame, text=lab).grid(row=i, column=0, sticky='w')
            v = tk.StringVar(value=str(default))
            self.opt_vars[k] = v
            ttk.Entry(param_frame, textvariable=v, width=10).grid(row=i, column=1, sticky='we')
            
        ttk.Separator(top, orient='horizontal').pack(fill='x', pady=4)
        gframe = ttk.Frame(top)
        self.opt_ge_v = tk.BooleanVar(value=True)
        ttk.Checkbutton(gframe, text='Ground effect', variable=self.opt_ge_v).pack(side='left')
        ttk.Label(gframe, text='Height (% chord):').pack(side='left', padx=(10, 0))
        self.opt_gh_state = tk.StringVar(value='300')
        ttk.Entry(gframe, textvariable=self.opt_gh_state, width=8).pack(side='left', padx=4)
        gframe.pack(fill='x', padx=6, pady=4)
        
        # Optimization Strategy & Baseline Preservation
        strat_frame = ttk.LabelFrame(scrollable_frame, text='Optimization Strategy & Baseline Preservation')
        strat_frame.pack(fill='x', pady=6)
        
        row_strat = ttk.Frame(strat_frame)
        row_strat.pack(fill='x', padx=6, pady=4)
        ttk.Label(row_strat, text='Target Goal:', font=('Helvetica', 9, 'bold')).pack(side='left')
        self.opt_goal_mode = tk.StringVar(value='🛡️ Maximize Stability (Preserve Base DF & Maximize Pitch Robustness)')
        goal_choices = [
            '🛡️ Maximize Stability (Preserve Base DF & Maximize Pitch Robustness)',
            '🏎️ Maximize Downforce (Respect Stall Margin & Rules)',
            '⚡ Maximize Aerodynamic Efficiency (L/D, Keep Downforce)',
            '🎯 Balanced Multi-Objective Refinement',
            '📐 Compact Packaging (Minimize Envelope, Keep DF)',
        ]
        goal_combo = ttk.Combobox(row_strat, textvariable=self.opt_goal_mode, values=goal_choices, state='readonly', width=58)
        goal_combo.pack(side='left', padx=6)
        goal_combo.bind('<<ComboboxSelected>>', lambda e: self._on_opt_goal_changed())
        add_tooltip(goal_combo, 'Select engineering objective. Stability mode strictly protects base downforce while eliminating stall spikes.')

        self.opt_goal_desc = tk.Label(
            strat_frame, text='Stability Priority: Keeps baseline Downforce/Cl within retention tolerance while maximizing stall margin (>=3°) and minimizing pitch sensitivity (smooth Cl curve across +-2° pitch dive).',
            bg='#1e293b', fg='#94a3b8', font=('Segoe UI', 8), padx=8, pady=4, relief='flat', justify='left', wraplength=700
        )
        self.opt_goal_desc.pack(fill='x', padx=6, pady=2)

        row_ret = ttk.Frame(strat_frame)
        row_ret.pack(fill='x', padx=6, pady=4)
        ttk.Label(row_ret, text='Downforce Retention:').pack(side='left')
        self.opt_retention_mode = tk.StringVar(value='Strict (±5% of Base)')
        ret_combo = ttk.Combobox(
            row_ret, textvariable=self.opt_retention_mode,
            values=['Strict (±5% of Base)', 'Balanced (±10% of Base)', 'Flexible (±20% of Base)', 'Free (Unconstrained)'],
            state='readonly', width=24
        )
        ret_combo.pack(side='left', padx=4)
        add_tooltip(ret_combo, 'Enforces that candidate wings retain baseline downforce without collapsing lift to cheat stability scores.')

        self.opt_reg_v = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_ret, text='Enforce FSUK/FSG Rules (Bounding Box & Ground Clearance)', variable=self.opt_reg_v).pack(side='left', padx=12)

        row_real = ttk.Frame(strat_frame)
        row_real.pack(fill='x', padx=6, pady=4)
        self.opt_real_v = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_real, text='Enforce Real-World Aerodynamic Slot Integration (1.5-4.5% Gap, Overlap & Camber Hierarchy)', variable=self.opt_real_v).pack(side='left')

        # Optimization Parameters
        params = ttk.LabelFrame(scrollable_frame, text='Optimization Parameters')
        params.pack(fill='x', pady=6)
        pframe = ttk.Frame(params)
        pframe.pack(fill='x', padx=6, pady=6)
        ttk.Label(pframe, text='Iterations:').grid(row=0, column=0, sticky='w')
        self.opt_iters = tk.IntVar(value=30)
        ttk.Entry(pframe, textvariable=self.opt_iters, width=8).grid(row=0, column=1, padx=4)
        ttk.Label(pframe, text='Search Resolution:').grid(row=0, column=2, sticky='w', padx=(10, 0))
        self.opt_step_preset = tk.StringVar(value='Fine (±1.5% Gap & ±1.5° Angle)')
        step_combo = ttk.Combobox(
            pframe, textvariable=self.opt_step_preset,
            values=[
                'Fine (±1.5% Gap & ±1.5° Angle)',
                'Medium (±3.0% Gap & ±3.0° Angle)',
                'Broad (±5.0% Gap & ±5.0° Angle)'
            ],
            state='readonly', width=28
        )
        step_combo.grid(row=0, column=3, padx=4)
        add_tooltip(step_combo, 'Scale of perturbation around base flap slots. Fine tuning discovers high-efficiency sweet spots.')
        self.opt_perturb = tk.DoubleVar(value=0.015)
        
        prog = ttk.Frame(scrollable_frame)
        prog.pack(fill='x', pady=6)
        ttk.Label(prog, text='Progress:').pack(side='left')
        self.opt_progress = ttk.Progressbar(prog, mode='determinate', length=400)
        self.opt_progress.pack(side='left', padx=4, fill='x', expand=True)
        self.opt_status = tk.StringVar(value='Ready')
        ttk.Label(prog, textvariable=self.opt_status).pack(side='left', padx=4)
        
        btns = ttk.Frame(scrollable_frame)
        btns.pack(fill='x', pady=6)
        ttk.Button(btns, text='Start Optimization', command=self._opt_start).pack(side='left', padx=4)
        ttk.Button(btns, text='Stop', command=self._opt_stop).pack(side='left', padx=4)
        ttk.Button(btns, text='Apply Best', command=self._opt_apply_best).pack(side='left', padx=4)
        
        self.opt_log = tk.Text(scrollable_frame, height=12, state='disabled', wrap='word')
        self.opt_log.pack(fill='both', expand=True, pady=6)
        self._opt_running = False
        self._opt_base_cfg = None
        self._opt_best_cfg = None
        self._opt_best_score = -1e+09
        self._opt_base_metrics = None

    def _on_opt_goal_changed(self):
        goal = self.opt_goal_mode.get()
        if 'Stability' in goal:
            msg = '🛡️ Stability Priority: Keeps baseline Downforce/Cl within retention tolerance while maximizing stall margin (>=3°) and minimizing pitch sensitivity (smooth Cl curve across +-2° pitch dive).'
        elif 'Downforce' in goal:
            msg = '🏎️ Max Downforce Priority: Searches flap geometries that maximize peak downforce within FSUK/FSG bounding limits and >=2° stall margin.'
        elif 'Efficiency' in goal:
            msg = '⚡ Aerodynamic Efficiency Priority: Maximizes L/D ratio while ensuring total downforce does not drop below 85% of baseline.'
        elif 'Compact' in goal:
            msg = '📐 Packaging Priority: Minimizes wing stack length and height envelope while preserving >=90% of baseline downforce.'
        else:
            msg = '🎯 Balanced Refinement: Optimizes Formula Student multi-objective score (DF, Margin, L/D, and Robustness).'
        if hasattr(self, 'opt_goal_desc'):
            self.opt_goal_desc.configure(text=msg)

    def _opt_browse(self):
        p = filedialog.askopenfilename(initialfile='results.csv')
        if p:
            self.opt_res_file.set(p)

    def _opt_load_base(self):
        p = os.path.expanduser(self.opt_res_file.get())
        if not os.path.exists(p):
            messagebox.showerror('Error', f"File not found: {p}")
            return
        try:
            df = A.read_results_csv(p)
            if df.empty:
                messagebox.showerror('Error', 'No data in results file')
                return
            valid = df[df.get('Status', '') == 'Valid']
            if valid.empty:
                messagebox.showerror('Error', 'No valid runs in results file')
                return
            best = valid.sort_values('Score', ascending=False).iloc[0]
            cfg = self._row_to_cfg(best)
            if not cfg:
                messagebox.showerror('Error', 'Could not parse configuration from row')
                return
            self._opt_base_cfg = cfg
            self._opt_best_cfg = cfg
            self._opt_base_metrics = dict(best)
            self.opt_main_box.set(cfg[0])
            for i, vals_cb in enumerate(self.opt_flap_rows):
                vals, cb = vals_cb
                if i < len(cfg[1]):
                    fn, sc, ang, xpos, ypos = cfg[1][i]
                    vals[0].set(fn)
                    vals[1].set(str(sc))
                    vals[2].set(str(ang))
                    vals[3].set(str(xpos))
                    vals[4].set(str(ypos))
                    vals[5].set(True)
                else:
                    vals[0].set('')
                    vals[5].set(False)
            self._update_opt_info(best)
            self._opt_log(f"Loaded base: {A.describe(cfg)}")
        except Exception as e:
            messagebox.showerror('Error', f"Failed to load base: {e}")

    def set_optimizer_base_from_row(self, row):
        try:
            cfg = self._row_to_cfg(row)
            if not cfg:
                return False
            self._opt_base_cfg = cfg
            self._opt_best_cfg = cfg
            self._opt_base_metrics = dict(row)
            if hasattr(self, 'opt_main_box'):
                self.opt_main_box.set(cfg[0])
            for i, vals_cb in enumerate(getattr(self, 'opt_flap_rows', [])):
                vals, cb = vals_cb
                if i < len(cfg[1]):
                    fn, sc, ang, xpos, ypos = cfg[1][i]
                    vals[0].set(fn)
                    vals[1].set(str(sc))
                    vals[2].set(str(ang))
                    vals[3].set(str(xpos))
                    vals[4].set(str(ypos))
                    vals[5].set(True)
                else:
                    vals[0].set('')
                    vals[5].set(False)
            self._update_opt_info(row)
            self._opt_log(f"Loaded base from Run {row.get('Run_ID')}: {A.describe(cfg)}")
            try:
                self.notebook.select(self.tab_opt)
            except Exception:
                pass
            return True
        except Exception as e:
            self.log(f"Failed to set base from row: {e}")
            return False

    def _row_to_cfg(self, row):
        try:
            main = row.get('Main', '')
            if not main:
                return None
            flaps = []
            for k in (1, 2, 3):
                fname = row.get(f"F{k}_Airfoil", '')
                if not fname or fname == 'None' or str(fname).lower() == 'nan' or str(fname).strip() == '':
                    continue
                flaps.append((
                    fname,
                    float(row.get(f"F{k}_Scale", 30)),
                    float(row.get(f"F{k}_Angle", -6)),
                    float(row.get(f"F{k}_X", 100)),
                    float(row.get(f"F{k}_Y", 5))
                ))
            return (main, tuple(flaps))
        except Exception:
            return None

    def _update_opt_info(self, row):
        df_n = row.get('Downforce_N', 0)
        dg_n = row.get('Drag_N', 0)
        cl = row.get('Cl_a0', 0)
        cd = row.get('Cd_a0', 0)
        ld = row.get('Max_LD', 0)
        st = row.get('Stall_Angle', 0)
        margin = A.DESIGN_ALPHA - float(st) if (st is not None and str(st) != '' and not pd.isna(st)) else 0.0
        try: cl_f = float(cl)
        except Exception: cl_f = 0.0
        try: cd_f = float(cd)
        except Exception: cd_f = 0.0
        try: ld_f = float(ld)
        except Exception: ld_f = 0.0
        try: df_f = float(df_n)
        except Exception: df_f = 0.0
        try: dg_f = float(dg_n)
        except Exception: dg_f = 0.0
        txt = (
            f"Base Wing: {row.get('Run_ID', 'Run')} | Main: {row.get('Main', '')} ({row.get('Elements', 1)} elements)\n"
            f"Baseline Aero: Cl₀: {cl_f:.4f} | Cd₀: {cd_f:.4f} | L/D: {ld_f:.2f}\n"
            f"Baseline Forces: Downforce: {df_f:.1f} N | Drag: {dg_f:.1f} N | Stall Margin: {margin:.1f}°"
        )
        self.opt_base_info.configure(state='normal')
        self.opt_base_info.delete('1.0', 'end')
        self.opt_base_info.insert('1.0', txt)
        self.opt_base_info.configure(state='disabled')

    def _calculate_optimizer_score(self, row, goal_mode, base_metrics, retention_pct=5.0):
        def num(val, default=0.0):
            try:
                v = float(val)
                return v if math.isfinite(v) else default
            except (TypeError, ValueError):
                return default

        cl = abs(num(row.get('Cl_a0', 0.0)))
        cd = num(row.get('Cd_a0', 0.0))
        ld = num(row.get('Max_LD', 0.0))
        df = num(row.get('Downforce_N', 0.0))
        st = num(row.get('Stall_Angle', -999.0))
        cl_m2 = abs(num(row.get('Cl_am2', 0.0)))
        cl_p2 = abs(num(row.get('Cl_ap2', 0.0)))

        b_cl = abs(num(base_metrics.get('Cl_a0', 0.0))) if base_metrics else cl
        b_cd = num(base_metrics.get('Cd_a0', 0.0)) if base_metrics else cd
        b_ld = num(base_metrics.get('Max_LD', 0.0)) if base_metrics else ld
        b_df = num(base_metrics.get('Downforce_N', 0.0)) if base_metrics else df

        # Baseline downforce retention constraint
        retention_penalty = 0.0
        if b_cl > 0.1:
            cl_drop = (b_cl - cl) / b_cl
            if cl_drop > (retention_pct / 100.0):
                retention_penalty = 150.0 * (cl_drop - (retention_pct / 100.0))
            elif cl_drop < -0.15 and goal_mode == 'stability':
                # Mild penalty if downforce increases too much when purely optimizing stability
                retention_penalty = 15.0 * abs(cl_drop + 0.15)

        # Drag inflation penalty
        drag_penalty = 0.0
        if b_cd > 0.01 and cd > b_cd * 1.10:
            drag_penalty = 100.0 * (cd - b_cd * 1.10) / b_cd

        if goal_mode == 'stability':
            min_pitch_ratio = min(cl_m2, cl_p2) / max(cl, 0.01) if (cl_m2 > 0 and cl_p2 > 0) else 0.8
            pitch_var = abs(cl_m2 - cl) + abs(cl_p2 - cl)
            margin = max(0.0, A.DESIGN_ALPHA - st)
            margin_score = min(50.0, margin * 10.0)
            robust_score = min(40.0, min_pitch_ratio * 40.0)
            stability_score = 100.0 + margin_score + robust_score - (15.0 * pitch_var) - retention_penalty - drag_penalty
            return float(stability_score)

        elif goal_mode == 'downforce':
            margin = max(0.0, A.DESIGN_ALPHA - st)
            margin_penalty = 0.0 if margin >= 2.0 else 50.0 * (2.0 - margin)
            return float(100.0 * (cl / max(b_cl, 1.0)) - margin_penalty - drag_penalty)

        elif goal_mode == 'efficiency':
            df_floor_penalty = 0.0
            if b_cl > 0.1 and cl < b_cl * 0.85:
                df_floor_penalty = 100.0 * (b_cl * 0.85 - cl) / b_cl
            return float(10.0 * ld - df_floor_penalty)

        elif goal_mode == 'compact':
            sl = num(row.get('Stack_Length_mm', 300.0))
            sh = num(row.get('Stack_Height_mm', 200.0))
            df_penalty = 0.0
            if b_cl > 0.1 and cl < b_cl * 0.90:
                df_penalty = 80.0 * (b_cl * 0.90 - cl) / b_cl
            return float(200.0 - (sl / 5.0) - (sh / 3.0) - df_penalty)

        else: # balanced
            return float(num(row.get('Score_Balanced', row.get('Score', 0.0))))

    def _opt_start(self):
        # Auto-resolve base configuration if unset or update from UI inputs
        base_cfg = None
        main_opt = getattr(self, 'opt_main_box', None)
        main_name = main_opt.get().strip() if main_opt else ''
        opt_flaps = []
        for vals, cb in getattr(self, 'opt_flap_rows', []):
            if vals[5].get():  # Enabled checkbox
                fn = vals[0].get().strip()
                if fn:
                    try:
                        sc = float(vals[1].get())
                        ang = float(vals[2].get())
                        xp = float(vals[3].get())
                        yp = float(vals[4].get())
                        opt_flaps.append((fn, sc, ang, xp, yp))
                    except (ValueError, tk.TclError):
                        pass
        if main_name and opt_flaps:
            base_cfg = (main_name, tuple(opt_flaps))

        if not base_cfg and self._opt_base_cfg:
            base_cfg = self._opt_base_cfg

        if not base_cfg:
            main_cfg = self.main_box.get().strip() if hasattr(self, 'main_box') else ''
            cfg_flaps = []
            for vals, cb in getattr(self, 'flap_rows', []):
                if vals[5].get():
                    fn = vals[0].get().strip()
                    if fn:
                        try:
                            sc = float(vals[1].get())
                            ang = float(vals[2].get())
                            xp = float(vals[3].get())
                            yp = float(vals[4].get())
                            cfg_flaps.append((fn, sc, ang, xp, yp))
                        except (ValueError, tk.TclError):
                            pass
            if main_cfg and cfg_flaps:
                base_cfg = (main_cfg, tuple(cfg_flaps))

        if not base_cfg:
            try:
                res_path = os.path.expanduser(self.opt_res_file.get())
                if os.path.exists(res_path):
                    df_res = A.read_results_csv(res_path)
                    valid_df = df_res[df_res.get('Status', '') == 'Valid']
                    if not valid_df.empty:
                        best_row = valid_df.sort_values('Score', ascending=False).iloc[0]
                        base_cfg = self._row_to_cfg(best_row)
                        if base_cfg:
                            self._opt_base_metrics = dict(best_row)
            except Exception:
                pass

        if not base_cfg or not base_cfg[1]:
            messagebox.showerror('Error', 'Please configure at least one flap element (or load a multi-element wing run from Results) to optimize.')
            return

        self._opt_base_cfg = base_cfg
        if self._opt_running:
            return
        try:
            iters_val = int(self.opt_iters.get())
            preset = self.opt_step_preset.get()
            perturb_val = 0.015 if 'Fine' in preset else (0.03 if 'Medium' in preset else 0.05)
            chord_val = float(self.opt_vars['chord'].get())
            speed_val = float(self.opt_vars['speed'].get())
            re_val = float(self.opt_vars['re'].get())
            gh0_val = None
            if self.opt_ge_v.get() and self.opt_gh_state.get().strip() not in ('', 'none', 'None'):
                gh0_val = float(self.opt_gh_state.get())
                if gh0_val <= 0:
                    messagebox.showerror('Error', 'Ground height must be positive (% chord)')
                    return
            enforce_reg = bool(self.opt_reg_v.get())
            enforce_real = bool(self.opt_real_v.get())
            ret_mode = self.opt_retention_mode.get()
            ret_pct = 5.0 if '5%' in ret_mode else (10.0 if '10%' in ret_mode else (20.0 if '20%' in ret_mode else 100.0))
            goal_raw = self.opt_goal_mode.get()
            goal_key = 'stability' if 'Stability' in goal_raw else ('downforce' if 'Downforce' in goal_raw else ('efficiency' if 'Efficiency' in goal_raw else ('compact' if 'Compact' in goal_raw else 'balanced')))
        except (ValueError, tk.TclError) as e:
            messagebox.showerror('Error', f"Check numeric inputs: {e}")
            return
        try:
            run_dir, results_path = self._new_run(
                'optimizer', str(base_cfg[0]), n_runs=0,
                flow='ground' if gh0_val else 'unbounded', height_pct=gh0_val,
                main=str(base_cfg[0])
            )
        except Exception as e:
            messagebox.showerror('Error', f"Could not create run folder: {e}")
            return
        self._opt_running = True
        self._opt_stop_flag = False
        self.opt_status.set('Running...')
        self.opt_progress['value'] = 0
        self.opt_progress['maximum'] = iters_val
        self._opt_log(f"Starting optimization [{goal_key.upper()}] with Base Wing: {A.describe(base_cfg)}...")

        def work():
            import random, math
            best = None
            best_score = -math.inf
            try:
                if getattr(A, 'WORKER_DIRS', None) is None or A.WORKER_DIRS.empty():
                    A.setup_workers(1)
            except Exception as e:
                self._opt_log(f"Worker queue setup note: {e}")

            A.RESULTS_FILE[0] = results_path
            A.RE = re_val
            A.SPEED = speed_val
            A.CHORD_MM = chord_val
            A.ROLE = 'fw'
            A.REG = A.default_reg()
            A.REG_ENFORCE = enforce_reg
            A.REAL_WING_ENFORCE = enforce_real
            A.set_ground_h(gh0_val)

            # Check baseline validity and evaluate baseline telemetry
            base_geom_ok = A.geometry_ok(base_cfg)
            if not base_geom_ok:
                self._opt_log("⚠️ Note: Baseline wing does not meet current geometric/regulatory constraints. Perturbations will search for compliant arrangements.")

            base_metrics = getattr(self, '_opt_base_metrics', None)
            if not base_metrics and base_geom_ok:
                self._opt_log("Evaluating baseline wing telemetry in JavaFoil...")
                try:
                    base_row = A.run_one(base_cfg, 'base', gh0_val)
                    if base_row.get('Status') == 'Valid':
                        base_metrics = dict(base_row)
                        self._opt_base_metrics = base_metrics
                        best = base_cfg
                        best_score = self._calculate_optimizer_score(base_metrics, goal_key, base_metrics, ret_pct)
                        df_val = float(base_row.get('Downforce_N', 0) or 0)
                        ld_val = float(base_row.get('Max_LD', 0) or 0)
                        st_val = base_row.get('Stall_Angle', 0)
                        marg_val = A.DESIGN_ALPHA - float(st_val) if st_val is not None else 0.0
                        self._opt_log(f"Baseline Telemetry: DF={df_val:.1f}N | L/D={ld_val:.1f} | Margin={marg_val:.1f}° | Base Score={best_score:.2f}")
                except Exception as e:
                    self._opt_log(f"Baseline evaluation note: {e}")
            elif base_metrics and base_geom_ok:
                best = base_cfg
                best_score = self._calculate_optimizer_score(base_metrics, goal_key, base_metrics, ret_pct)
                df_val = float(base_metrics.get('Downforce_N', 0) or 0)
                ld_val = float(base_metrics.get('Max_LD', 0) or 0)
                self._opt_log(f"Using baseline telemetry: DF={df_val:.1f}N | L/D={ld_val:.1f} | Base Score={best_score:.2f}")

            for i in range(iters_val):
                if self._opt_stop_flag:
                    break
                candidate_cfg = None
                center_cfg = best if (best is not None and random.random() < 0.70) else base_cfg
                for attempt in range(25):
                    main = center_cfg[0]
                    flaps = list(center_cfg[1])
                    new_flaps = []
                    eff_scale = 1.0 if attempt < 12 else 0.5
                    eff_perturb = perturb_val * eff_scale
                    for fname, s, a, x, y in flaps:
                        ns = max(10, min(100, s + random.uniform(-1, 1) * (eff_perturb * 25)))
                        na = max(-60, min(20, a + random.uniform(-1, 1) * (eff_perturb * 40)))
                        nx = max(80, min(220, x + random.uniform(-1, 1) * (eff_perturb * 30)))
                        ny = max(-30, min(50, y + random.uniform(-1, 1) * (eff_perturb * 25)))
                        new_flaps.append((fname, round(ns, 1), round(na, 1), round(nx, 1), round(ny, 1)))
                    cand = (main, tuple(new_flaps))
                    if A.geometry_ok(cand):
                        candidate_cfg = cand
                        break

                if candidate_cfg is None:
                    self._opt_log(f"  Iter {i + 1}/{iters_val}: Skipped (candidate geometries failed physical/regulatory constraints)")
                    self.ui_q.put(('opt_prog', i + 1))
                    self.ui_q.put(('opt_status', f"Iteration {i + 1}/{iters_val} (skipped)"))
                    time.sleep(0.01)
                    continue

                try:
                    row = A.run_one(candidate_cfg, 'opt', gh0_val)
                    if row.get('Status') == 'Valid':
                        score = self._calculate_optimizer_score(row, goal_key, base_metrics, ret_pct)
                        df_val = float(row.get('Downforce_N', 0) or 0)
                        ld_val = float(row.get('Max_LD', 0) or 0)
                        st_val = row.get('Stall_Angle', 0)
                        marg_val = A.DESIGN_ALPHA - float(st_val) if st_val is not None else 0.0
                        if score > best_score:
                            best = candidate_cfg
                            best_score = score
                            self._opt_log(f"  Iter {i + 1}/{iters_val}: 🌟 New Best Score {score:.2f} (DF: {df_val:.1f}N, L/D: {ld_val:.1f}, Margin: {marg_val:.1f}°)")
                        else:
                            self._opt_log(f"  Iter {i + 1}/{iters_val}: Score {score:.2f} (DF: {df_val:.1f}N, L/D: {ld_val:.1f}, Margin: {marg_val:.1f}°)")
                    else:
                        self._opt_log(f"  Iter {i + 1}/{iters_val}: JavaFoil status {row.get('Status')}")
                except Exception as e:
                    self._opt_log(f"  Iter {i + 1}/{iters_val} error: {e}")

                self.ui_q.put(('opt_prog', i + 1))
                self.ui_q.put(('opt_status', f"Iteration {i + 1}/{iters_val}"))
                time.sleep(0.01)

            try:
                A.write_run_meta(run_dir, n_runs=iters_val)
            except Exception:
                pass
            self.ui_q.put(('opt_done', (best, best_score)))

        def _run():
            try:
                work()
            except Exception as e:
                self.ui_q.put(('opt_log', f"optimizer crashed: {e}"))
                self.ui_q.put(('opt_done', (None, -math.inf)))

        threading.Thread(target=_run, daemon=True).start()

    def _opt_stop(self):
        self._opt_stop_flag = True
        self._opt_log('Stop requested...')

    def _handle_opt_done(self, payload):
        best_cfg, best_score = payload
        self._opt_running = False
        if best_cfg and best_score is not None and best_score > -1e+08:
            self.opt_status.set(f"Done - best score {best_score:.2f}")
            self._opt_log(f"Optimization complete. Best score: {best_score:.2f} ({A.describe(best_cfg)})")
            self._opt_best_cfg = best_cfg
            self._opt_best_score = best_score
        else:
            self.opt_status.set('Done - no valid configuration found')
            self._opt_log('Optimization finished without a valid configuration (all candidates failed geometry/size checks or JavaFoil).')
        self._refresh_runs()

    def _opt_apply_best(self):
        if not self._opt_best_cfg:
            messagebox.showerror('Error', 'No best configuration found')
            return
        main, flaps = self._opt_best_cfg
        self.main_box.set(main)
        if hasattr(self, 'opt_main_box'):
            self.opt_main_box.set(main)
        for i, vals_cb in enumerate(self.flap_rows):
            vals, cb = vals_cb
            if i < len(flaps):
                fname, s, a, x, y = flaps[i]
                vals[0].set(fname)
                vals[1].set(str(s))
                vals[2].set(str(a))
                vals[3].set(str(x))
                vals[4].set(str(y))
                vals[5].set(True)
            else:
                vals[0].set('')
                vals[5].set(False)
        for i, vals_cb in enumerate(getattr(self, 'opt_flap_rows', [])):
            vals, cb = vals_cb
            if i < len(flaps):
                fname, s, a, x, y = flaps[i]
                vals[0].set(fname)
                vals[1].set(str(s))
                vals[2].set(str(a))
                vals[3].set(str(x))
                vals[4].set(str(y))
                vals[5].set(True)
            else:
                vals[0].set('')
                vals[5].set(False)
        self.notebook.select(self.tab_cfg)
        self.on_check()

    def _opt_log(self, msg):
        self.ui_q.put(('opt_log', msg))

    # =====================================================================
    # TAB 7: THEMES & SETTINGS
    # =====================================================================
    def build_settings(self):
        root = tk.Frame(self.tab_set, bg=BG)
        root.pack(fill='both', expand=True, padx=16, pady=14)
        tk.Label(root, text='Themes & Settings', bg=BG, fg=ACCENT, font=('TkDefaultFont', 15, 'bold')).pack(anchor='w')
        tk.Label(
            root,
            text='Appearance, hover descriptions and navigation. Choices are saved automatically.',
            bg=BG, fg=MUTED
        ).pack(anchor='w', pady=(0, 10))
        cols = tk.Frame(root, bg=BG)
        cols.pack(fill='both', expand=True)
        appear = tk.LabelFrame(
            cols, text=' Theme ', bg=BG, fg=ACCENT, bd=1, relief='groove',
            labelanchor='nw', font=('TkDefaultFont', 10, 'bold')
        )
        appear.pack(side='left', fill='both', expand=True, padx=(0, 10))
        tk.Label(
            appear, text='Pick a palette. The window re-themes instantly.',
            bg=BG, fg=MUTED, wraplength=300, justify='left'
        ).pack(anchor='w', padx=10, pady=(6, 4))
        self.theme_var = tk.StringVar(value=self._settings.get('theme', DEFAULT_THEME))
        for key, pal in THEMES.items():
            rowf = tk.Frame(appear, bg=BG)
            rowf.pack(fill='x', padx=10, pady=3)
            rb = tk.Radiobutton(
                rowf, text=pal['label'], variable=self.theme_var, value=key,
                command=self._on_theme_change, bg=BG, fg=TXT, selectcolor=PANEL2,
                activebackground=BG, activeforeground=ACCENT, highlightthickness=0,
                anchor='w', font=('TkDefaultFont', 10)
            )
            rb.pack(side='left')
            sw = tk.Frame(rowf, bg=BG)
            sw.pack(side='right')
            for c in (pal['BG'], pal['PANEL'], pal['ACCENT'], pal['SKY'], pal['TXT']):
                tk.Label(sw, bg=c, width=2, height=1, bd=1, relief='solid').pack(side='left', padx=1)
        btns = tk.Frame(appear, bg=BG)
        btns.pack(fill='x', padx=10, pady=(8, 10))
        tk.Button(
            btns, text='Apply theme', command=self._on_theme_change, bg=PANEL, fg=TXT,
            activebackground=ACCENT, activeforeground=SEL_BG, relief='flat', padx=10, pady=4
        ).pack(side='left')
        self.theme_note = tk.Label(btns, text='', bg=BG, fg=SKY)
        self.theme_note.pack(side='left', padx=8)
        
        right = tk.Frame(cols, bg=BG)
        right.pack(side='left', fill='both', expand=True)
        desc = tk.LabelFrame(
            right, text=' Hover descriptions ', bg=BG, fg=ACCENT, bd=1, relief='groove',
            labelanchor='nw', font=('TkDefaultFont', 10, 'bold')
        )
        desc.pack(fill='x')
        self.tips_var = tk.BooleanVar(value=self._settings.get('tips', True))
        tk.Checkbutton(
            desc, text='Show hover descriptions', variable=self.tips_var,
            command=self._apply_settings, bg=BG, fg=TXT, selectcolor=PANEL2,
            activebackground=BG, activeforeground=ACCENT, highlightthickness=0, anchor='w'
        ).pack(anchor='w', padx=10, pady=(8, 2))
        tk.Label(
            desc,
            text='Descriptions appear after a short delay and are dismissed on click, Esc or when you switch tabs, so nothing keeps floating around.',
            bg=BG, fg=MUTED, wraplength=320, justify='left'
        ).pack(anchor='w', padx=10, pady=(0, 6))
        for label, var_name, val, lo, hi in (
            ('Delay before showing (ms)', 'tip_delay_var', self._settings.get('tip_delay', 450), 0, 2000),
            ('Wrap width (px)', 'tip_wrap_var', self._settings.get('tip_wrap', 420), 160, 900)
        ):
            r = tk.Frame(desc, bg=BG)
            r.pack(fill='x', padx=10, pady=3)
            tk.Label(r, text=label, bg=BG, fg=TXT, width=24, anchor='w').pack(side='left')
            var = tk.StringVar(value=str(val))
            setattr(self, var_name, var)
            tk.Scale(
                r, from_=lo, to=hi, orient='horizontal', variable=var, length=180,
                bg=BG, fg=TXT, troughcolor=PANEL2, activebackground=ACCENT, highlightthickness=0,
                showvalue=True, command=lambda _v=None: self._apply_settings(save=False)
            ).pack(side='left', padx=6)
        tk.Button(
            desc, text='Preview description', command=self._preview_tip, bg=PANEL, fg=TXT,
            activebackground=ACCENT, activeforeground=SEL_BG, relief='flat', padx=10, pady=4
        ).pack(anchor='w', padx=10, pady=(6, 10))
        nav = tk.LabelFrame(
            right, text=' Navigation ', bg=BG, fg=ACCENT, bd=1, relief='groove',
            labelanchor='nw', font=('TkDefaultFont', 10, 'bold')
        )
        nav.pack(fill='both', expand=True, pady=(10, 0))
        tips = [
            ('Alt + 1 … 7', 'jump straight to a tab'),
            ('Ctrl + Tab / Ctrl + Shift + Tab', 'cycle through tabs'),
            ('Ctrl + R', 'write the report for the current results file'),
            ('F5', 'refresh results + graphs'),
            ('Esc', 'dismiss a hover description'),
            ('Ctrl + Q', 'quit')
        ]
        for k, v in tips:
            r = tk.Frame(nav, bg=BG)
            r.pack(fill='x', padx=10, pady=1)
            tk.Label(r, text=k, bg=BG, fg=SKY, width=30, anchor='w', font=('TkDefaultFont', 9, 'bold')).pack(side='left')
            tk.Label(r, text=v, bg=BG, fg=MUTED, anchor='w').pack(side='left')
        tk.Label(
            nav, text='Tip: every control has a hover description you can turn off here.',
            bg=BG, fg=MUTED, wraplength=320, justify='left'
        ).pack(anchor='w', padx=10, pady=(6, 8))


def main():
    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
