#!/usr/bin/env python3
"""
open_in_aero_auto.py - ENPRT FSUK 2027 Wing Configuration Launcher & JavaFoil Bridge

Interactive desktop application and CLI launcher for ENPRT FSAE aerodynamic wing
configurations. Allows 1-click loading of validated campaign packages into Aero Auto
or directly into the JavaFoil interactive GUI.

Usage:
  1. Standalone GUI App (User-friendly preset browser & launcher):
     python3 open_in_aero_auto.py
     ./open_in_aero_auto.sh
     open_in_aero_auto.bat

  2. Direct CLI Launch (Backwards-compatible):
     python3 open_in_aero_auto.py --config configs/FWA_hero.json
     python3 open_in_aero_auto.py --config configs/RW_hero.json
"""

import os
import sys
import json
import shutil
import time
import argparse
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Resolve Application Directories
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSSIBLE_APP_DIRS = [
    SCRIPT_DIR,
    os.path.join(SCRIPT_DIR, "..", "08_AERO_AUTO_APP", "engine"),
    "/home/user/Applications/aero_auto",
    os.environ.get("AERO_AUTO_APP", "")
]

APP_DIR = None
for d in POSSIBLE_APP_DIRS:
    if d and os.path.isdir(d) and os.path.exists(os.path.join(d, "aero_ui.py")):
        APP_DIR = os.path.abspath(d)
        break

if not APP_DIR:
    APP_DIR = SCRIPT_DIR

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:
    import aero_ui
    import aero_auto as A
except ImportError as e:
    print(f"Error importing aero_auto suite: {e}", file=sys.stderr)
    sys.exit(1)


# Built-in ENPRT Campaign Presets
BUILTIN_PRESETS = [
    {
        "id": "FWA_hero",
        "name": "FWA Hero (Front Wing Maximum Downforce)",
        "role": aero_ui.FW,
        "main": "e423",
        "chord": 300.0,
        "gh": 35.0,
        "speed": 16.6667,
        "re": 570000,
        "note": "CL*A = 2.0975. High-downforce front wing with E423 main and 2 slotted S1223 flaps.",
        "flaps": [
            ["s1223", 43.0, -24.0, 101.0, 9.0],
            ["s1223", 32.0, -30.0, 141.55, 19.0]
        ]
    },
    {
        "id": "FWA_stable",
        "name": "FWA Pitch-Stable (Front Wing Safe Handling)",
        "role": aero_ui.FW,
        "main": "s1223",
        "chord": 300.0,
        "gh": 35.0,
        "speed": 16.6667,
        "re": 570000,
        "note": "Pitch drop only 0.249. Predictable handling under braking dive with S1223 main and 2 S1223 flaps.",
        "flaps": [
            ["s1223", 43.0, -24.0, 101.0, 5.0],
            ["s1223", 32.0, -16.0, 141.55, 15.0]
        ]
    },
    {
        "id": "FWB_hero",
        "name": "FWB Hero (Front Wing Separation Resistant)",
        "role": aero_ui.FW,
        "main": "NACA8412",
        "chord": 300.0,
        "gh": 35.0,
        "speed": 16.6667,
        "re": 570000,
        "note": "CL*A = 1.8283. High laminar boundary layer attachment with NACA 8412 main and 2 FX 63-137 flaps.",
        "flaps": [
            ["WORTMANN FX 63-137", 43.0, -24.0, 98.0, 5.0],
            ["WORTMANN FX 63-137", 32.0, -30.0, 138.55, 15.0]
        ]
    },
    {
        "id": "FWB_stable",
        "name": "FWB Pitch-Stable (Ultra-Robust Pitch Margin)",
        "role": aero_ui.FW,
        "main": "NACA8412",
        "chord": 300.0,
        "gh": 35.0,
        "speed": 16.6667,
        "re": 570000,
        "note": "Pitch drop only 0.102. NACA 8412 main + FX 63-137 flap 1 + Clark Y flap 2 for linear stall recovery.",
        "flaps": [
            ["WORTMANN FX 63-137", 40.0, -26.0, 98.0, 5.0],
            ["clarky", 32.0, -30.0, 136.0, 15.0]
        ]
    },
    {
        "id": "RW_hero",
        "name": "RW Hero (Rear Wing 4-Element Baseline)",
        "role": aero_ui.RW,
        "main": "e423",
        "chord": 300.0,
        "gh": 35.0,
        "speed": 16.6667,
        "re": 570000,
        "note": "CL*A = 1.6713 @ 0 deg. 4-element high-lift cascade (E423 + 2 S1223 + E423 upper flap) meeting FS 950mm envelope.",
        "flaps": [
            ["s1223", 39.0, -26.0, 101.0, 11.0],
            ["s1223", 31.0, -36.0, 138.15, 15.0],
            ["e423", 28.0, -36.0, 168.5, 21.0]
        ]
    },
    {
        "id": "RW_incidence3",
        "name": "RW +3 deg Incidence (Rear Wing Maximum Downforce)",
        "role": aero_ui.RW,
        "main": "e423",
        "chord": 300.0,
        "gh": 35.0,
        "speed": 16.6667,
        "re": 570000,
        "note": "CL*A = 1.8083 @ +3 deg incidence. All-S1223 flap cascade for maximum high-speed downforce and cornering traction.",
        "flaps": [
            ["s1223", 39.0, -26.0, 101.0, 11.0],
            ["s1223", 31.0, -36.0, 138.15, 15.0],
            ["s1223", 28.0, -36.0, 168.5, 21.0]
        ]
    }
]


def launch_in_aero_auto(cfg):
    """Launches the main Aero Auto application with the given configuration pre-loaded."""
    app = aero_ui.App()
    try:
        app.load_config_json(cfg)
    except Exception as e:
        print(f"[warn] Failed to load config into App: {e}", file=sys.stderr)
    try:
        app.notebook.select(app.tab_cfg)
    except Exception:
        pass
    app.mainloop()


def launch_in_javafoil_gui(cfg):
    """Launches JavaFoil GUI with wing coordinates written into the Geometry tab."""
    cfg_tuple = (cfg["main"], tuple(cfg.get("flaps", [])))
    gh = cfg.get("gh")
    re_val = cfg.get("re", 570000)
    title = cfg.get("name", "FSAE Multi-Element Wing")
    ok, msg, proc = A.launch_javafoil_gui(cfg_tuple, ground_h=gh, re_val=re_val, title=title)
    return ok, msg, proc


class LauncherApp(tk.Tk):
    """Standalone graphical launcher for ENPRT wing configurations."""

    def __init__(self, initial_cfg_path=None):
        super().__init__()
        self.title("ENPRT FSUK 2027 - Wing Configuration Launcher")
        self.geometry("820x620")
        self.minsize(760, 560)
        self.configure(bg="#0f172a")

        self.presets = list(BUILTIN_PRESETS)
        self.current_cfg = self.presets[0]

        # Scan configs directory for any extra user configs
        cfg_dir = os.path.join(SCRIPT_DIR, "configs")
        if os.path.isdir(cfg_dir):
            existing_ids = {p.get("id") for p in self.presets} | {p.get("name") for p in self.presets}
            for fn in sorted(os.listdir(cfg_dir)):
                if fn.endswith(".json"):
                    full_p = os.path.join(cfg_dir, fn)
                    try:
                        with open(full_p, "r", encoding="utf-8") as f:
                            d = json.load(f)
                            cid = d.get("id") or d.get("name") or os.path.splitext(fn)[0]
                            if cid not in existing_ids:
                                if "id" not in d:
                                    d["id"] = cid
                                self.presets.append(d)
                                existing_ids.add(cid)
                    except Exception:
                        pass

        self._build_ui()

        if initial_cfg_path and os.path.exists(initial_cfg_path):
            self.load_from_path(initial_cfg_path)
        else:
            self.select_preset_by_index(0)

    def _build_ui(self):
        # Header banner
        header = tk.Frame(self, bg="#1e293b", padx=20, pady=12, bd=1, relief=tk.SOLID)
        header.pack(fill=tk.X)

        title_lbl = tk.Label(header, text="ENPRT FSUK 2027 Aero Configuration Launcher",
                             font=("Segoe UI", 14, "bold"), fg="#38bdf8", bg="#1e293b")
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(header,
                           text="Interactive Wing Package Selector: 1-Click Launch into Aero Auto & JavaFoil GUI",
                           font=("Segoe UI", 9), fg="#94a3b8", bg="#1e293b")
        sub_lbl.pack(anchor="w", pady=(2, 0))

        # Main 2-column layout
        main_body = tk.Frame(self, bg="#0f172a", padx=16, pady=12)
        main_body.pack(fill=tk.BOTH, expand=True)

        # Left Column: Presets List
        left_col = tk.Frame(main_body, bg="#1e293b", width=280, bd=1, relief=tk.SOLID)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))

        left_header = tk.Frame(left_col, bg="#1e293b", padx=10, pady=8)
        left_header.pack(fill=tk.X)
        tk.Label(left_header, text="Select Configuration:", font=("Segoe UI", 10, "bold"),
                 fg="#f8fafc", bg="#1e293b").pack(anchor="w")

        self.preset_listbox = tk.Listbox(left_col, font=("Segoe UI", 9), bg="#0f172a", fg="#f8fafc",
                                         selectbackground="#0284c7", selectforeground="#ffffff",
                                         highlightthickness=0, bd=0, activestyle="none")
        self.preset_listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.preset_listbox.bind("<<ListboxSelect>>", self._on_preset_select)

        for p in self.presets:
            tag = "[FW]" if "front" in p.get("role", "").lower() else "[RW]"
            self.preset_listbox.insert(tk.END, f" {tag} {p['id']}")

        btn_browse_file = tk.Button(left_col, text="Browse Custom JSON...", font=("Segoe UI", 9),
                                    bg="#334155", fg="#f8fafc", activebackground="#475569",
                                    activeforeground="#ffffff", relief=tk.FLAT, padx=8, pady=4,
                                    command=self.on_browse_json)
        btn_browse_file.pack(fill=tk.X, padx=8, pady=(0, 8))

        # Right Column: Details & JSON Panel
        right_col = tk.Frame(main_body, bg="#1e293b", bd=1, relief=tk.SOLID, padx=14, pady=12)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.lbl_cfg_title = tk.Label(right_col, text="Configuration Details",
                                      font=("Segoe UI", 12, "bold"), fg="#38bdf8", bg="#1e293b")
        self.lbl_cfg_title.pack(anchor="w")

        self.lbl_cfg_subtitle = tk.Label(right_col, text="", font=("Segoe UI", 9),
                                         fg="#94a3b8", bg="#1e293b")
        self.lbl_cfg_subtitle.pack(anchor="w", pady=(1, 8))

        # Notebook for formatted summary vs raw JSON
        self.tabs = ttk.Notebook(right_col)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        self.tab_summary = tk.Frame(self.tabs, bg="#0f172a")
        self.tab_json = tk.Frame(self.tabs, bg="#0f172a")

        self.tabs.add(self.tab_summary, text="  Aerodynamic Summary  ")
        self.tabs.add(self.tab_json, text="  Raw JSON Configuration  ")

        # Summary text view
        self.summary_txt = tk.Text(self.tab_summary, font=("Consolas", 9), bg="#0f172a", fg="#f8fafc",
                                   wrap=tk.WORD, bd=0, padx=10, pady=10, state="disabled")
        self.summary_txt.pack(fill=tk.BOTH, expand=True)

        # Raw JSON view
        self.json_txt = tk.Text(self.tab_json, font=("Consolas", 9), bg="#0f172a", fg="#38bdf8",
                                wrap=tk.NONE, bd=0, padx=10, pady=10, state="disabled")
        self.json_txt.pack(fill=tk.BOTH, expand=True)

        # Bottom Action Bar
        bottom_bar = tk.Frame(self, bg="#0f172a", padx=16, pady=12)
        bottom_bar.pack(fill=tk.X)

        self.btn_launch_aero = tk.Button(bottom_bar, text="Launch in Aero Auto", font=("Segoe UI", 10, "bold"),
                                         bg="#0284c7", fg="#ffffff", activebackground="#0369a1",
                                         activeforeground="#ffffff", relief=tk.FLAT, padx=16, pady=6,
                                         command=self.on_launch_aero)
        self.btn_launch_aero.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_launch_jf = tk.Button(bottom_bar, text="Test in JavaFoil GUI", font=("Segoe UI", 9, "bold"),
                                       bg="#10b981", fg="#ffffff", activebackground="#059669",
                                       activeforeground="#ffffff", relief=tk.FLAT, padx=14, pady=6,
                                       command=self.on_launch_javafoil)
        self.btn_launch_jf.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_copy_coords = tk.Button(bottom_bar, text="Copy Coordinates", font=("Segoe UI", 9),
                                         bg="#334155", fg="#f8fafc", activebackground="#475569",
                                         activeforeground="#ffffff", relief=tk.FLAT, padx=10, pady=6,
                                         command=self.on_copy_coordinates)
        self.btn_copy_coords.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_copy_json = tk.Button(bottom_bar, text="Copy JSON", font=("Segoe UI", 9),
                                       bg="#334155", fg="#f8fafc", activebackground="#475569",
                                       activeforeground="#ffffff", relief=tk.FLAT, padx=10, pady=6,
                                       command=self.on_copy_json)
        self.btn_copy_json.pack(side=tk.LEFT, padx=(0, 8))

        btn_exit = tk.Button(bottom_bar, text="Exit", font=("Segoe UI", 9),
                             bg="#334155", fg="#f8fafc", activebackground="#475569",
                             activeforeground="#ffffff", relief=tk.FLAT, padx=12, pady=6,
                             command=self.destroy)
        btn_exit.pack(side=tk.RIGHT)

        # Status footer
        self.status_lbl = tk.Label(self, text="Ready. Select a wing configuration above.",
                                   font=("Segoe UI", 8, "italic"), fg="#94a3b8", bg="#0f172a",
                                   anchor="w", padx=16, pady=4)
        self.status_lbl.pack(fill=tk.X, side=tk.BOTTOM)

    def select_preset_by_index(self, idx):
        if 0 <= idx < len(self.presets):
            self.preset_listbox.selection_clear(0, tk.END)
            self.preset_listbox.selection_set(idx)
            self.preset_listbox.see(idx)
            self._display_config(self.presets[idx])

    def _on_preset_select(self, event=None):
        sel = self.preset_listbox.curselection()
        if sel:
            self._display_config(self.presets[sel[0]])

    def _display_config(self, cfg):
        self.current_cfg = cfg
        name = cfg.get("name", cfg.get("id", "Wing Configuration"))
        role = cfg.get("role", "front wing").title()
        chord = cfg.get("chord", 300.0)
        gh = cfg.get("gh", 35.0)

        self.lbl_cfg_title.config(text=name)
        self.lbl_cfg_subtitle.config(text=f"Role: {role}  |  Main Chord: {chord:.1f} mm  |  Ground Clearance: {gh:.1f}% chord")

        # Format aerodynamic summary
        lines = []
        lines.append("=== AERODYNAMIC TARGET & PERFORMANCE NOTE ===")
        lines.append(f"  {cfg.get('note', 'No performance notes recorded.')}\n")

        lines.append("=== MULTI-ELEMENT GEOMETRY STACK ===")
        lines.append(f"  Main Airfoil   : {cfg.get('main', 's1223')}")
        flaps = cfg.get("flaps", [])
        lines.append(f"  Flap Count     : {len(flaps)} elements")
        for i, f in enumerate(flaps, 1):
            lines.append(f"    Flap #{i:<2} : {f[0]:<18} | Chord Scale: {f[1]}% | Deflection: {f[2]} deg | LE Position: ({f[3]}%, {f[4]}%)")

        lines.append("\n=== OPERATING FLOW CONDITIONS ===")
        speed = cfg.get("speed", 16.6667)
        re_val = cfg.get("re", 570000)
        lines.append(f"  Freestream Velocity : {speed:.2f} m/s ({speed * 3.6:.1f} km/h)")
        lines.append(f"  Reynolds Number     : {re_val:,}")
        lines.append(f"  Ground Effect Model : {'Active (Ground Height = ' + str(gh) + '% chord)' if gh is not None else 'Unbounded Flow'}")

        self.summary_txt.config(state="normal")
        self.summary_txt.delete("1.0", tk.END)
        self.summary_txt.insert(tk.END, "\n".join(lines))
        self.summary_txt.config(state="disabled")

        # Format JSON view
        json_str = json.dumps(cfg, indent=2)
        self.json_txt.config(state="normal")
        self.json_txt.delete("1.0", tk.END)
        self.json_txt.insert(tk.END, json_str)
        self.json_txt.config(state="disabled")

        self.status_lbl.config(text=f"Selected: {name}")

    def on_browse_json(self):
        cfg_dir = os.path.join(SCRIPT_DIR, "configs")
        init_dir = cfg_dir if os.path.isdir(cfg_dir) else SCRIPT_DIR
        fn = filedialog.askopenfilename(
            parent=self,
            title="Open Wing Configuration JSON",
            initialdir=init_dir,
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if fn:
            self.load_from_path(fn)

    def load_from_path(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "id" not in cfg:
                cfg["id"] = os.path.splitext(os.path.basename(path))[0]
            # Check if already present
            existing_idx = None
            for idx, p in enumerate(self.presets):
                if p.get("id") == cfg["id"]:
                    existing_idx = idx
                    break
            if existing_idx is not None:
                self.presets[existing_idx] = cfg
                self.select_preset_by_index(existing_idx)
            else:
                self.presets.append(cfg)
                tag = "[FW]" if "front" in cfg.get("role", "").lower() else "[RW]"
                self.preset_listbox.insert(tk.END, f" {tag} {cfg['id']}")
                self.select_preset_by_index(len(self.presets) - 1)
            self.status_lbl.config(text=f"Loaded configuration file: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not load configuration file:\n{e}", parent=self)

    def on_launch_aero(self):
        cfg = self.current_cfg
        self.status_lbl.config(text=f"Launching Aero Auto with {cfg.get('id', 'wing')}...")
        self.destroy()
        launch_in_aero_auto(cfg)

    def on_launch_javafoil(self):
        cfg = self.current_cfg
        self.status_lbl.config(text="Launching JavaFoil interactive GUI with pre-loaded coordinates...")
        self.update()
        ok, msg, _ = launch_in_javafoil_gui(cfg)
        if ok:
            messagebox.showinfo(
                "JavaFoil GUI Launched",
                f"JavaFoil has launched with geometry pre-loaded!\n\n"
                f"In the JavaFoil window:\n"
                f"  1. Switch to the 'Geometry' tab.\n"
                f"  2. Click 'Update View' (coordinates are already written in!).\n"
                f"  3. Switch to 'Analyze' to compute aerodynamic polars.\n\n"
                f"(Coordinates have also been copied to your system clipboard)",
                parent=self
            )
            self.status_lbl.config(text="JavaFoil GUI running interactively.")
        else:
            messagebox.showerror("JavaFoil Launch Error", msg, parent=self)
            self.status_lbl.config(text="JavaFoil launch failed.")

    def on_copy_coordinates(self):
        cfg = self.current_cfg
        cfg_tuple = (cfg["main"], tuple(cfg.get("flaps", [])))
        gh = cfg.get("gh")
        try:
            outs = A.build_outlines(cfg_tuple, gh)
            title = cfg.get("name", "FSAE Multi-Element Wing")
            lines = [f"{title}\n"]
            for i, o in enumerate(outs):
                if i > 0:
                    lines.append("9999.9 9999.9\n")
                for pt in o:
                    lines.append(f"{pt[0]:.6f} {pt[1]:.6f}\n")
            coords = "".join(lines)
            self.clipboard_clear()
            self.clipboard_append(coords)
            self.update()
            self.status_lbl.config(text="Wing coordinates copied to clipboard!")
        except Exception as e:
            messagebox.showerror("Error", f"Could not generate wing coordinates:\n{e}", parent=self)

    def on_copy_json(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(json.dumps(self.current_cfg, indent=2))
            self.update()
            self.status_lbl.config(text="Configuration JSON copied to clipboard!")
        except Exception as e:
            messagebox.showerror("Error", f"Could not copy JSON:\n{e}", parent=self)


def main():
    ap = argparse.ArgumentParser(description="ENPRT FSUK 2027 Wing Configuration Launcher")
    ap.add_argument("--config", "-c", default=None, help="Path to config JSON file in configs/ (CLI direct launch)")
    ap.add_argument("--gui", action="store_true", help="Force open interactive launcher GUI")
    args = ap.parse_args()

    if args.config and not args.gui:
        # CLI direct launch into Aero Auto
        cfg_path = args.config if os.path.isabs(args.config) else os.path.join(SCRIPT_DIR, args.config)
        if not os.path.exists(cfg_path):
            print(f"Error: Config file not found: {cfg_path}", file=sys.stderr)
            sys.exit(1)
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        launch_in_aero_auto(cfg)
    else:
        # Launch standalone GUI App
        app = LauncherApp(initial_cfg_path=args.config)
        app.mainloop()


if __name__ == "__main__":
    main()
