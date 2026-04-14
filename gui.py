"""GUI for Audio Transcription Tool — themed presentation layer."""
from __future__ import annotations

import os
import re
import tkinter as tk
from datetime import datetime
from threading import Thread
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from audio_player import AudioPlayer
from transcript_manager import TranscriptManager
from audit_logger import AuditLogger
from edit_session import EditSession
from utils import format_time_hms, format_flexible_timestamp, parse_flexible_timestamp

# ── Color palette ──────────────────────────────────────────────────────
C = {
    "bg_dark":   "#1A1A24",   # primary dark
    "bg_mid":    "#2E2E38",   # secondary dark
    "accent":    "#FFE600",   # yellow accent
    "white":     "#FFFFFF",
    "green":     "#2DB757",   # validated / success
    "teal":      "#27ACAA",   # content validation
    "purple":    "#750E5C",   # decorative
    "red":       "#FF4136",   # deletion / error
    "orange":    "#FF6D00",   # edited / unsaved
    # Derived
    "fg_light":  "#CCCCCC",   # light text on dark
    "seg_bg":    "#FFFFFF",   # segment normal
    "seg_val":   "#E8F8ED",   # fully validated segment
    "seg_part":  "#FFF8E1",   # partially validated
    "orig_bg":   "#F0F0F0",   # original text bg
    "border":    "#3A3A48",   # subtle border on dark
}


# ── Tooltip ────────────────────────────────────────────────────────────

class _Tooltip:
    def __init__(self, widget, text):
        self.widget = widget; self.text = text; self._tw = None
        widget.bind("<Enter>", self._show); widget.bind("<Leave>", self._hide)

    def _show(self, e):
        if self._tw: return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tw = tk.Toplevel(self.widget); tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, bg="#FFFFDD", fg="#333", relief=tk.SOLID,
                 bd=1, font=("Arial", 8), padx=5, pady=3, wraplength=250,
                 justify=tk.LEFT).pack()
        self._tw = tw

    def _hide(self, e):
        if self._tw: self._tw.destroy(); self._tw = None

def _tip(w, text):
    _Tooltip(w, text); return w


# ═══════════════════════════════════════════════════════════════════════

class TranscriptionToolGUI:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Audio Transcription Correction Tool")
        self.root.geometry("1400x900")
        self.root.configure(bg=C["bg_dark"])

        self._closing = False
        self._after_ids = {k: None for k in ("time", "marker", "backup", "slider", "save")}

        self.transcript: Optional[TranscriptManager] = None
        self.audio = AudioPlayer()
        self.session: Optional[EditSession] = None

        self.lines_per_view = tk.IntVar(value=5)
        self.auto_save = tk.BooleanVar(value=True)
        self.show_original = tk.BooleanVar(value=False)
        self.show_validation = tk.BooleanVar(value=True)
        self._segment_widgets: list = []
        self._current_idx = 0
        self._first_play = True
        self._edit_timers: dict = {}

        self._viz_loaded = False
        self._audio_file = None
        self._audio_np = None
        self._sample_rate = None
        self._marker_line = None
        self._search_win = None

        self._apply_theme()
        self._create_welcome_screen()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_theme(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=C["bg_dark"], foreground=C["white"],
                        fieldbackground=C["bg_mid"], borderwidth=0)
        style.configure("TFrame", background=C["bg_dark"])
        style.configure("TLabel", background=C["bg_dark"], foreground=C["fg_light"])
        style.configure("TLabelframe", background=C["bg_dark"], foreground=C["accent"])
        style.configure("TLabelframe.Label", background=C["bg_dark"], foreground=C["accent"],
                        font=("Arial", 9, "bold"))
        style.configure("TCheckbutton", background=C["bg_dark"], foreground=C["fg_light"])
        style.configure("TButton", background=C["bg_mid"], foreground=C["white"],
                        padding=(6, 3))
        style.map("TButton",
                  background=[("active", C["accent"]), ("pressed", C["accent"])],
                  foreground=[("active", C["bg_dark"]), ("pressed", C["bg_dark"])])
        style.configure("TEntry", fieldbackground=C["bg_mid"], foreground=C["white"])
        style.configure("TSpinbox", fieldbackground=C["bg_mid"], foreground=C["white"])
        style.configure("TNotebook", background=C["bg_dark"], borderwidth=0)
        style.configure("TNotebook.Tab", background=C["bg_mid"], foreground=C["fg_light"],
                        padding=(10, 4))
        style.map("TNotebook.Tab",
                  background=[("selected", C["accent"])],
                  foreground=[("selected", C["bg_dark"])])
        style.configure("TScale", background=C["bg_dark"], troughcolor=C["bg_mid"])
        style.configure("TPanedwindow", background=C["bg_dark"])
        style.configure("TScrollbar", background=C["bg_mid"], troughcolor=C["bg_dark"])
        style.configure("Treeview", background=C["bg_mid"], foreground=C["white"],
                        fieldbackground=C["bg_mid"], rowheight=22)
        style.configure("Treeview.Heading", background=C["bg_dark"],
                        foreground=C["accent"], font=("Arial", 9, "bold"))
        style.map("Treeview", background=[("selected", C["accent"])],
                  foreground=[("selected", C["bg_dark"])])

        # Accent button
        style.configure("Accent.TButton", background=C["accent"], foreground=C["bg_dark"],
                        font=("Arial", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", C["orange"])],
                  foreground=[("active", C["bg_dark"])])

    # ── Timer helpers ──────────────────────────────────────────────────

    def _after(self, name, ms, func):
        old = self._after_ids.get(name)
        if old is not None:
            try: self.root.after_cancel(old)
            except Exception: pass
        self._after_ids[name] = self.root.after(ms, func)

    def _cancel_all_afters(self):
        for aid in self._after_ids.values():
            if aid:
                try: self.root.after_cancel(aid)
                except Exception: pass
        self._after_ids = {k: None for k in self._after_ids}
        for aid in self._edit_timers.values():
            try: self.root.after_cancel(aid)
            except Exception: pass
        self._edit_timers.clear()

    # ═══════════════════════════════════════════════════════════════════
    #  WELCOME
    # ═══════════════════════════════════════════════════════════════════

    def _create_welcome_screen(self):
        self._welcome = tk.Frame(self.root, bg=C["bg_dark"])
        self._welcome.pack(fill=tk.BOTH, expand=True)
        c = tk.Frame(self._welcome, bg=C["bg_dark"])
        c.place(relx=0.5, rely=0.40, anchor="center")

        tk.Label(c, text="Audio Transcription Correction Tool",
                 font=("Arial", 20, "bold"), fg=C["accent"], bg=C["bg_dark"]).pack(pady=(0, 25))

        fields = [
            ("Audio / Video File:", "_w_audio", self._browse_audio,
             "(optional – leave empty to edit without audio)"),
            ("Transcript File:", "_w_transcript", self._browse_transcript, ""),
            ("Output File:", "_w_output", self._browse_output,
             "(optional – leave empty to edit in place)"),
            ("Audit Log File:", "_w_audit", self._browse_audit,
             "(optional – auto-created next to transcript if empty)"),
        ]
        for label, attr, cmd, hint in fields:
            row = tk.Frame(c, bg=C["bg_dark"]); row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=label, width=20, anchor="w", fg=C["fg_light"],
                     bg=C["bg_dark"], font=("Arial", 9)).pack(side=tk.LEFT)
            var = tk.StringVar(); setattr(self, attr, var)
            tk.Entry(row, textvariable=var, width=80, bg=C["bg_mid"], fg=C["white"],
                     insertbackground=C["white"], relief=tk.FLAT, font=("Arial", 9)
                     ).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
            tk.Button(row, text="Browse…", bg=C["bg_mid"], fg=C["white"],
                      activebackground=C["accent"], activeforeground=C["bg_dark"],
                      relief=tk.FLAT, padx=8, command=cmd).pack(side=tk.LEFT)
            if hint:
                tk.Label(c, text=hint, fg="#777", bg=C["bg_dark"],
                         font=("Arial", 8)).pack(anchor="w", padx=25)

        tk.Button(c, text="  Start Editing  ", bg=C["accent"], fg=C["bg_dark"],
                  font=("Arial", 11, "bold"), relief=tk.FLAT, padx=20, pady=6,
                  activebackground=C["orange"], command=self._start_session).pack(pady=22)
        self._w_status = tk.Label(c, text="", fg=C["red"], bg=C["bg_dark"])
        self._w_status.pack()

    def _browse_audio(self):
        p = filedialog.askopenfilename(title="Audio / Video",
            filetypes=[("Media", "*.mp3 *.wav *.mp4 *.avi *.mkv *.flac *.ogg *.m4a"), ("All", "*.*")])
        if p: self._w_audio.set(p)

    def _browse_transcript(self):
        p = filedialog.askopenfilename(title="Transcript",
            filetypes=[("Transcript", "*.json *.txt"), ("All", "*.*")])
        if p: self._w_transcript.set(p)

    def _browse_output(self):
        p = filedialog.asksaveasfilename(title="Output File", defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("JSON", "*.json"), ("All", "*.*")])
        if p: self._w_output.set(p)

    def _browse_audit(self):
        p = filedialog.askopenfilename(title="Audit Log",
            filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if p: self._w_audit.set(p)

    # ═══════════════════════════════════════════════════════════════════
    #  LOADING
    # ═══════════════════════════════════════════════════════════════════

    def _start_session(self):
        tp = self._w_transcript.get().strip()
        if not tp: self._w_status.config(text="Select a transcript file."); return
        if not os.path.exists(tp): self._w_status.config(text="Transcript file not found."); return
        self._paths = {"transcript": tp, "audio": self._w_audio.get().strip(),
                       "audit": self._w_audit.get().strip(), "output": self._w_output.get().strip()}
        self._welcome.destroy()
        self._show_loading(); self.root.after(30, self._load_step1)

    def _show_loading(self):
        self._load_frame = tk.Frame(self.root, bg=C["bg_dark"])
        self._load_frame.pack(fill=tk.BOTH, expand=True)
        c = tk.Frame(self._load_frame, bg=C["bg_dark"])
        c.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(c, text="Loading…", font=("Arial", 16, "bold"),
                 fg=C["accent"], bg=C["bg_dark"]).pack(pady=(0, 15))
        self._load_label = tk.Label(c, text="", font=("Arial", 10),
                                    fg=C["fg_light"], bg=C["bg_dark"])
        self._load_label.pack(pady=5)
        self._load_bar = ttk.Progressbar(c, mode="indeterminate", length=320)
        self._load_bar.pack(pady=15); self._load_bar.start(15)

    def _load_msg(self, t):
        self._load_label.config(text=t); self.root.update_idletasks()

    def _load_step1(self):
        if self._closing: return
        self._load_msg("Loading transcript…")
        self.transcript = TranscriptManager()
        if not self.transcript.load_transcript(self._paths["transcript"]):
            self._load_bar.stop()
            self._load_label.config(text="Failed to load transcript.", fg=C["red"]); return
        out = self._paths.get("output", "")
        if out: self.transcript.output_file = out
        else: self.transcript.output_file = self.transcript.original_file
        self.root.after(20, self._load_step2)

    def _load_step2(self):
        if self._closing: return
        self._load_msg("Setting up audit log…")
        ap, tp = self._paths["audit"], self._paths["transcript"]
        if ap and os.path.exists(ap):
            audit = AuditLogger(tp); audit.audit_file_path = ap
            audit.audit_data = audit._load_or_create_audit_log(); audit._start_new_session()
        else: audit = AuditLogger(tp)
        self.session = EditSession(self.transcript, audit)
        self.root.after(20, self._load_step3)

    def _load_step3(self):
        if self._closing: return
        n = self.transcript.get_segment_count()
        self._load_msg(f"Building interface ({n} segments)…")
        self._load_bar.stop(); self._load_frame.destroy()
        self._build_main_ui()
        self.root.after(10, self._deferred_init)

    def _deferred_init(self):
        if self._closing: return
        self._update_view(); self._update_stats()
        ap = self._paths.get("audio", "")
        if ap and os.path.exists(ap): self._audio_file = ap; self._load_audio_bg(ap)
        else: self._show_no_audio()
        self._tick_time(); self._tick_backup()
        del self._paths

    # ═══════════════════════════════════════════════════════════════════
    #  MAIN UI
    # ═══════════════════════════════════════════════════════════════════

    def _build_main_ui(self):
        mb = tk.Menu(self.root, bg=C["bg_mid"], fg=C["white"], activebackground=C["accent"],
                     activeforeground=C["bg_dark"])
        fm = tk.Menu(mb, tearoff=0, bg=C["bg_mid"], fg=C["white"],
                     activebackground=C["accent"], activeforeground=C["bg_dark"])
        fm.add_command(label="Save  Ctrl+S", command=self._do_save)
        fm.add_command(label="Find  Ctrl+F", command=self._open_search)
        fm.add_separator()
        fm.add_command(label="Exit", command=self._on_closing)
        mb.add_cascade(label="File", menu=fm)
        self.root.config(menu=mb)
        self.root.bind("<Control-s>", lambda e: self._do_save())
        self.root.bind("<Control-f>", lambda e: self._open_search())
        self.root.bind("<Control-z>", self._do_undo)
        self.root.bind("<Control-Shift-E>", self._do_jump_next_edited)

        # Info bar
        bar = tk.Frame(self.root, bg=C["bg_mid"], padx=8, pady=4)
        bar.pack(fill=tk.X, padx=0, pady=0)
        in_place = (self.transcript.output_file == self.transcript.original_file)
        desc = "editing in place" if in_place else f"→ {os.path.basename(self.transcript.output_file)}"
        tk.Label(bar, text=f"  {os.path.basename(self.transcript.original_file)}  ({desc})",
                 fg=C["white"], bg=C["bg_mid"], font=("Arial", 9)).pack(side=tk.LEFT)
        self._lbl_status = tk.Label(bar, text="", fg=C["fg_light"], bg=C["bg_mid"],
                                    font=("Arial", 8))
        self._lbl_status.pack(side=tk.RIGHT, padx=10)
        self._lbl_save = tk.Label(bar, text="✓ No changes", fg=C["green"], bg=C["bg_mid"],
                                  font=("Arial", 9, "bold"))
        self._lbl_save.pack(side=tk.RIGHT, padx=5)

        self._banner = tk.Label(self.root, text="", fg=C["orange"], bg=C["bg_dark"],
                                font=("Arial", 9), anchor="center")

        # Playback strip
        self._build_playback_strip()

        # Main pane — tight spacing
        self._pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self._pane.pack(fill=tk.BOTH, expand=True, padx=2, pady=(2, 2))
        self._pane.add(self._build_left_panel(), weight=0)

        self._nb = ttk.Notebook(self._pane)
        self._pane.add(self._nb, weight=1)

        tab_t = ttk.Frame(self._nb)
        self._nb.add(tab_t, text="  Transcript  ")
        self._build_transcript_tab(tab_t)

        tab_v = ttk.Frame(self._nb)
        self._nb.add(tab_v, text="  Audio Visualization  ")
        self._viz_tab = tab_v
        self._viz_placeholder = tk.Label(tab_v, text="Click here to load visualization",
                                         font=("Arial", 11), fg=C["fg_light"],
                                         bg=C["bg_dark"], cursor="hand2")
        self._viz_placeholder.pack(expand=True, fill=tk.BOTH)
        self._viz_placeholder.bind("<Button-1>", lambda e: self._init_viz())
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _show_no_audio(self):
        self._banner.config(text="  No audio file loaded – transcript editing only  ")
        self._banner.pack(fill=tk.X, before=self._pane)

    def _set_status(self, t):
        if hasattr(self, "_lbl_status"): self._lbl_status.config(text=t)

    # ── Left panel ─────────────────────────────────────────────────────

    def _build_left_panel(self):
        outer = tk.Frame(self._pane, bg=C["bg_dark"], width=195)
        cv = tk.Canvas(outer, bg=C["bg_dark"], bd=0, highlightthickness=0, width=190)
        sb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=cv.yview)
        inner = tk.Frame(cv, bg=C["bg_dark"])
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        lf_opts = dict(padx=3, pady=3)

        # Stats
        sf = ttk.LabelFrame(inner, text="Statistics", padding=3)
        sf.pack(fill=tk.X, **lf_opts)
        self._lbl_total = ttk.Label(sf, text="Segments: 0"); self._lbl_total.pack(anchor=tk.W)
        self._lbl_dur = ttk.Label(sf, text="Duration: 00:00:00"); self._lbl_dur.pack(anchor=tk.W)
        self._lbl_val = ttk.Label(sf, text="Validated: 0%"); self._lbl_val.pack(anchor=tk.W)

        # View
        vf = ttk.LabelFrame(inner, text="View", padding=3)
        vf.pack(fill=tk.X, **lf_opts)
        r = ttk.Frame(vf); r.pack(fill=tk.X)
        ttk.Label(r, text="Lines:").pack(side=tk.LEFT)
        ttk.Spinbox(r, from_=1, to=20, textvariable=self.lines_per_view,
                     command=self._update_view, width=4).pack(side=tk.LEFT, padx=4)
        for txt, var, cmd in [("Validation controls", self.show_validation, self._update_view),
                              ("Auto-save (3 s)", self.auto_save, None)]:
            ttk.Checkbutton(vf, text=txt, variable=var, command=cmd).pack(anchor=tk.W)

        # Navigation
        nf = ttk.LabelFrame(inner, text="Navigation", padding=3)
        nf.pack(fill=tk.X, **lf_opts)
        self._lbl_seg = ttk.Label(nf, text="Segment: 0/0"); self._lbl_seg.pack(pady=1)
        br = ttk.Frame(nf); br.pack(fill=tk.X)
        for sym, cmd in [("⏮", self._nav_start), ("◀", self._nav_prev),
                         ("▶", self._nav_next), ("⏭", self._nav_end)]:
            ttk.Button(br, text=sym, width=3, command=cmd).pack(side=tk.LEFT, padx=1)
        jr = ttk.Frame(nf); jr.pack(fill=tk.X, pady=2)
        ttk.Label(jr, text="#").pack(side=tk.LEFT)
        self._ent_jump = ttk.Entry(jr, width=6)
        self._ent_jump.pack(side=tk.LEFT, padx=2)
        self._ent_jump.bind("<Return>", lambda e: self._nav_to_seg())
        ttk.Button(jr, text="Go", width=3, command=self._nav_to_seg).pack(side=tk.LEFT)

        # Timestamp
        tf = ttk.LabelFrame(inner, text="Jump to Time", padding=3)
        tf.pack(fill=tk.X, **lf_opts)
        tr = ttk.Frame(tf); tr.pack(fill=tk.X)
        self._ent_ts = ttk.Entry(tr, width=12)
        self._ent_ts.pack(side=tk.LEFT, padx=2)
        self._ent_ts.bind("<Return>", lambda e: self._nav_to_time())
        ttk.Button(tr, text="Go", width=3, command=self._nav_to_time).pack(side=tk.LEFT)
        ttk.Label(tf, text="or use dropdowns:", foreground="#777",
                  font=("Arial", 7)).pack(anchor=tk.W, pady=(2, 0))
        dr = ttk.Frame(tf); dr.pack(fill=tk.X, pady=1)
        self._ts_hh = tk.StringVar(value="00"); self._ts_mm = tk.StringVar(value="00")
        self._ts_ss = tk.StringVar(value="00")
        for var, vals in [(self._ts_hh, [f"{i:02d}" for i in range(24)]),
                          (self._ts_mm, [f"{i:02d}" for i in range(60)]),
                          (self._ts_ss, [f"{i:02d}" for i in range(60)])]:
            ttk.Spinbox(dr, textvariable=var, values=vals, width=3, wrap=True).pack(side=tk.LEFT)
            if var is not self._ts_ss:
                ttk.Label(dr, text=":", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        ttk.Button(dr, text="Go", width=3, command=self._nav_to_time_dropdown).pack(side=tk.LEFT, padx=3)

        # Actions
        af = ttk.LabelFrame(inner, text="Actions", padding=3)
        af.pack(fill=tk.X, **lf_opts)
        ttk.Button(af, text="🔍 Find (Ctrl+F)", command=self._open_search).pack(fill=tk.X, pady=1)
        ttk.Button(af, text="✓ Validate to Here", command=self._do_validate_to_current).pack(fill=tk.X, pady=1)
        ttk.Button(af, text="💾 Save Now", command=self._do_save).pack(fill=tk.X, pady=1)

        return outer

    # ── Transcript tab ─────────────────────────────────────────────────

    def _build_transcript_tab(self, parent):
        toggle = tk.Frame(parent, bg=C["bg_dark"])
        toggle.pack(fill=tk.X, padx=3, pady=(3, 0))
        ttk.Checkbutton(toggle, text="Show original text", variable=self.show_original,
                        command=self._update_view).pack(side=tk.LEFT)

        f = tk.Frame(parent, bg=C["bg_dark"])
        f.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        cv = tk.Canvas(f, bg=C["seg_bg"], bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=cv.yview)
        self._seg_frame = tk.Frame(cv, bg=C["seg_bg"])
        self._seg_frame.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=self._seg_frame, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    # ── Playback strip ─────────────────────────────────────────────────

    def _build_playback_strip(self):
        cf = tk.Frame(self.root, bg=C["bg_mid"], padx=8, pady=4)
        cf.pack(fill=tk.X, side=tk.BOTTOM)
        r = tk.Frame(cf, bg=C["bg_mid"]); r.pack(fill=tk.X)

        bstyle = dict(bg=C["bg_dark"], fg=C["white"], activebackground=C["accent"],
                      activeforeground=C["bg_dark"], relief=tk.FLAT, padx=4, pady=2)
        for txt, cmd in [("⏸", self._pb_pause), ("⏹", self._pb_stop),
                         ("-5s", lambda: self._pb_skip(-5)), ("+5s", lambda: self._pb_skip(5))]:
            tk.Button(r, text=txt, width=4, command=cmd, **bstyle).pack(side=tk.LEFT, padx=1)

        self._lbl_cur = tk.Label(r, text="00:00:00", width=9, anchor="e",
                                 fg=C["fg_light"], bg=C["bg_mid"], font=("Consolas", 9))
        self._lbl_cur.pack(side=tk.LEFT, padx=(8, 2))

        tk.Button(r, text="▶", width=3, command=self._pb_play,
                  bg=C["accent"], fg=C["bg_dark"], activebackground=C["orange"],
                  relief=tk.FLAT, font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=2)

        self._prog_var = tk.DoubleVar()
        self._slider = ttk.Scale(r, from_=0, to=100, variable=self._prog_var,
                                 orient=tk.HORIZONTAL, command=self._on_slider)
        self._slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self._slider_busy = False

        self._lbl_end = tk.Label(r, text="00:00:00", width=9, anchor="w",
                                 fg=C["fg_light"], bg=C["bg_mid"], font=("Consolas", 9))
        self._lbl_end.pack(side=tk.LEFT, padx=(2, 8))

        tk.Label(r, text="🔊", font=("Arial", 9), bg=C["bg_mid"]).pack(side=tk.LEFT)
        self._vol_var = tk.IntVar(value=100)
        ttk.Scale(r, from_=0, to=100, variable=self._vol_var, orient=tk.HORIZONTAL,
                  command=self._on_vol, length=80).pack(side=tk.LEFT, padx=(2, 0))
        self._lbl_vol = tk.Label(r, text="100%", width=4, font=("Arial", 8),
                                 fg=C["fg_light"], bg=C["bg_mid"])
        self._lbl_vol.pack(side=tk.LEFT)

        self._lbl_time = tk.Label(cf, text="", font=("Arial", 8),
                                  fg="#777", bg=C["bg_mid"])
        self._lbl_time.pack(anchor=tk.W, pady=(2, 0))

    # ═══════════════════════════════════════════════════════════════════
    #  SEGMENT RENDERING
    # ═══════════════════════════════════════════════════════════════════

    def _update_view(self, *_):
        for w in self._segment_widgets: w.destroy()
        self._segment_widgets.clear()
        n = self.lines_per_view.get()
        for seg in self.transcript.get_segments_range(self._current_idx, n):
            self._render_segment(seg)
        total = self.transcript.get_segment_count()
        first = self._current_idx + 1 if total else 0
        last = min(self._current_idx + n, total)
        self._lbl_seg.config(text=f"Segment: {first}–{last} / {total}")

    def _render_segment(self, seg):
        s = self.session
        is_edit = seg.index in s.edited
        is_ins = seg.index in s.inserted
        val = self.transcript.get_validation_status(seg.index)
        full_val = val["speaker_validated"] and val["content_validated"]
        orig = s.get_original(seg.index)

        bg = (C["seg_val"] if full_val
              else C["seg_part"] if (val["speaker_validated"] or val["content_validated"])
              else C["seg_bg"])

        frame = tk.Frame(self._seg_frame, relief=tk.SOLID, borderwidth=1,
                         bg=bg, highlightbackground=C["border"], highlightthickness=1)
        frame.pack(fill=tk.X, padx=4, pady=3)
        frame.columnconfigure(1, weight=1)
        self._segment_widgets.append(frame)

        # ═══ LEFT: timestamp + speaker ═══
        left = tk.Frame(frame, bg=bg, width=130)
        left.grid(row=0, column=0, sticky="ns", padx=(4, 2), pady=4)

        tk.Label(left, text=format_flexible_timestamp(seg.start),
                 font=("Consolas", 8), fg="#666", bg=bg).pack(anchor=tk.W)
        tk.Label(left, text=format_flexible_timestamp(seg.end),
                 font=("Consolas", 8), fg="#666", bg=bg).pack(anchor=tk.W)

        sp = tk.Entry(left, width=14, font=("Arial", 9, "bold"), relief=tk.FLAT, bd=1)
        sp.insert(0, seg.speaker)
        if is_ins: sp.config(bg=C["accent"], fg=C["bg_dark"])
        elif seg.speaker != orig["speaker"]: sp.config(bg="#C8F7D5", fg="#0A5C2B")
        else: sp.config(bg="#EEE", fg="#333")
        sp.pack(anchor=tk.W, pady=(3, 0))
        sp.bind("<KeyRelease>", lambda e, i=seg.index, w=sp: self._on_speaker(i, w))
        sp.bind("<FocusOut>", lambda e, i=seg.index: self._flush_edit(i))

        if val["speaker_validated"]:
            tk.Label(left, text="✓ Speaker", fg=C["green"], font=("Arial", 7), bg=bg).pack(anchor=tk.W)
        if is_ins:
            tk.Label(left, text="➕ New", fg=C["orange"], font=("Arial", 7, "bold"), bg=bg).pack(anchor=tk.W, pady=(2, 0))
        elif is_edit:
            tk.Label(left, text="✏ Edited", fg=C["orange"], font=("Arial", 7, "bold"), bg=bg).pack(anchor=tk.W, pady=(2, 0))
        if full_val:
            tk.Label(left, text="✓ Validated", fg=C["green"], font=("Arial", 7, "bold"), bg=bg).pack(anchor=tk.W)

        # ═══ CENTER: text ═══
        center = tk.Frame(frame, bg=bg)
        center.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)

        if self.show_original.get():
            orig_sp = orig["speaker"] if not is_ins else ""
            orig_txt = orig["text"] if not is_ins else ""
            lbl_t = f"Original [{orig_sp}]:" if orig_sp else "Original:"
            tk.Label(center, text=lbl_t, font=("Arial", 7, "italic"), fg="#999", bg=bg).pack(anchor=tk.W)
            ow = tk.Text(center, height=2, wrap=tk.WORD, font=("Arial", 10),
                         bg=C["orig_bg"], fg="#666", relief=tk.FLAT, bd=1, padx=4, pady=3)
            ow.pack(fill=tk.X)
            ow.insert("1.0", orig_txt); ow.config(state=tk.DISABLED)
            tk.Label(center, text="Edited:", font=("Arial", 7, "italic"), fg="#999", bg=bg).pack(anchor=tk.W)

        tw = tk.Text(center, height=3, wrap=tk.WORD, font=("Arial", 10), bg="white",
                     fg="#222", relief=tk.FLAT, bd=1, padx=4, pady=3,
                     insertbackground="#333")
        tw.pack(fill=tk.BOTH, expand=True)

        tw.tag_config("del", overstrike=True, foreground=C["red"])
        tw.tag_config("add", background="#C8F7D5", foreground="#0A5C2B")
        tw.tag_config("eq", foreground="#222")
        tw.tag_config("hl", background=C["accent"], foreground=C["bg_dark"])

        orig_text = orig["text"] if not is_ins else ""
        self._fill_diff(tw, orig_text, seg.text)
        self._fill_highlight(tw, seg.text)

        tw.bind("<KeyRelease>", lambda e, i=seg.index, w=tw: self._on_text(i, w))
        tw.bind("<FocusOut>", lambda e, i=seg.index, w=tw: self._on_text_out(i, w))

        if val["content_validated"]:
            tk.Label(center, text="✓ Content validated", fg=C["green"],
                     font=("Arial", 7), bg=bg).pack(anchor=tk.W)

        # ═══ RIGHT: 2×3 button grid ═══
        right = tk.Frame(frame, bg=bg)
        right.grid(row=0, column=2, sticky="nsew", padx=(2, 4), pady=4)
        for c_i in range(3): right.columnconfigure(c_i, weight=1, uniform="btn")

        btn_kw = dict(relief=tk.FLAT, bd=1, font=("Arial", 8))
        _tip(tk.Button(right, text="▶ Play", bg=C["bg_mid"], fg=C["white"],
                       activebackground=C["accent"], command=lambda s=seg: self._pb_segment(s),
                       **btn_kw), "Play this segment's audio"
             ).grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        _tip(tk.Button(right, text="↶ Undo", bg=C["accent"], fg=C["bg_dark"],
                       activebackground=C["orange"],
                       command=lambda i=seg.index: self._do_undo_row(i),
                       **btn_kw), "Undo all changes for this row"
             ).grid(row=0, column=1, sticky="ew", padx=1, pady=1)
        _tip(tk.Button(right, text="➕ Insert", bg=C["bg_mid"], fg=C["white"],
                       activebackground=C["green"],
                       command=lambda i=seg.index: self._dlg_insert(i),
                       **btn_kw), "Insert a new segment after this one"
             ).grid(row=0, column=2, sticky="ew", padx=1, pady=1)

        if self.show_validation.get() and not full_val:
            _tip(tk.Button(right, text="✓ Row", bg=C["green"], fg=C["white"],
                           activebackground="#1E8E42",
                           command=lambda i=seg.index: self._do_val_row(i), **btn_kw),
                 "Validate entire row").grid(row=1, column=0, sticky="ew", padx=1, pady=1)
            if not val["speaker_validated"]:
                _tip(tk.Button(right, text="✓ Spk", bg=C["teal"], fg=C["white"],
                               activebackground="#1E8E8E",
                               command=lambda i=seg.index: self._do_val_speaker(i), **btn_kw),
                     "Validate speaker only").grid(row=1, column=1, sticky="ew", padx=1, pady=1)
            if not val["content_validated"]:
                _tip(tk.Button(right, text="✓ Txt", bg=C["purple"], fg=C["white"],
                               activebackground="#5C0A48",
                               command=lambda i=seg.index: self._do_val_content(i), **btn_kw),
                     "Validate content only").grid(row=1, column=2, sticky="ew", padx=1, pady=1)

    # ── Text helpers ───────────────────────────────────────────────────

    def _fill_diff(self, tw, original, current):
        tw.delete("1.0", tk.END)
        for op, i1, i2, j1, j2 in EditSession.compute_diff_ops(original, current):
            if op == "equal": tw.insert(tk.END, current[j1:j2], "eq")
            elif op == "replace":
                tw.insert(tk.END, original[i1:i2], "del")
                tw.insert(tk.END, current[j1:j2], "add")
            elif op == "delete": tw.insert(tk.END, original[i1:i2], "del")
            elif op == "insert": tw.insert(tk.END, current[j1:j2], "add")

    def _fill_highlight(self, tw, text):
        pat = self.session.active_search_pattern if self.session else ""
        if not pat: return
        try:
            for m in re.compile(pat, re.IGNORECASE).finditer(text):
                tw.tag_add("hl", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        except re.error: pass

    # ═══════════════════════════════════════════════════════════════════
    #  EDIT HANDLERS
    # ═══════════════════════════════════════════════════════════════════

    def _on_text(self, idx, tw):
        new = tw.get("1.0", tk.END).strip()
        if not self.session.apply_text(idx, new): return
        self._refresh_save_label(); self._reset_edit_timer(idx)

    def _on_speaker(self, idx, sp):
        new = sp.get().strip()
        if not self.session.apply_speaker(idx, new): return
        orig = self.session.get_original(idx)
        is_ins = idx in self.session.inserted
        if is_ins: sp.config(bg=C["accent"], fg=C["bg_dark"])
        elif new != orig["speaker"]: sp.config(bg="#C8F7D5", fg="#0A5C2B")
        else: sp.config(bg="#EEE", fg="#333")
        self._refresh_save_label(); self._reset_edit_timer(idx)

    def _on_text_out(self, idx, tw):
        new = tw.get("1.0", tk.END).strip()
        self.session.apply_text(idx, new); self._flush_edit(idx)
        orig = self.session.get_original(idx)
        is_ins = idx in self.session.inserted
        self._fill_diff(tw, orig["text"] if not is_ins else "", new)
        self._fill_highlight(tw, new)

    def _reset_edit_timer(self, idx):
        if idx in self._edit_timers: self.root.after_cancel(self._edit_timers[idx])
        self._edit_timers[idx] = self.root.after(1000, lambda: self._commit_edit(idx))
        self._schedule_auto_save()

    def _flush_edit(self, idx):
        aid = self._edit_timers.pop(idx, None)
        if aid: self.root.after_cancel(aid)
        self.session.commit_edit(idx)

    def _commit_edit(self, idx):
        self._edit_timers.pop(idx, None); self.session.commit_edit(idx)

    # ═══════════════════════════════════════════════════════════════════
    #  ACTIONS
    # ═══════════════════════════════════════════════════════════════════

    def _do_undo_row(self, idx):
        self.session.undo_row(idx)
        self._refresh_save_label(); self._schedule_auto_save(); self._update_view()

    def _do_undo(self, event):
        if self.session and self.session.undo_last():
            self._refresh_save_label(); self._update_view()
        return "break"

    def _do_val_row(self, i):
        if self.session.validate_row(i):
            self._refresh_save_label(); self._schedule_auto_save()
            self._update_view(); self._update_stats()

    def _do_val_speaker(self, i):
        if self.session.validate_speaker(i):
            self._refresh_save_label(); self._schedule_auto_save()
            self._update_view(); self._update_stats()

    def _do_val_content(self, i):
        if self.session.validate_content(i):
            self._refresh_save_label(); self._schedule_auto_save()
            self._update_view(); self._update_stats()

    def _do_validate_to_current(self):
        t = self.transcript.get_segment_count()
        if not t: return
        lv = min(self._current_idx + self.lines_per_view.get() - 1, t - 1)
        if not messagebox.askyesno("Confirm", f"Validate segments 1–{lv + 1}?"): return
        self.session.validate_to_index(lv)
        self._refresh_save_label(); self._schedule_auto_save()
        self._update_view(); self._update_stats()

    # ═══════════════════════════════════════════════════════════════════
    #  INSERT
    # ═══════════════════════════════════════════════════════════════════

    def _dlg_insert(self, after_idx):
        d = tk.Toplevel(self.root, bg=C["bg_dark"]); d.title("Insert Segment")
        d.geometry("500x320"); d.transient(self.root); d.grab_set()
        cur = self.transcript.segments[after_idx]
        nxt_end = (self.transcript.segments[after_idx + 1].start
                   if after_idx < len(self.transcript.segments) - 1 else cur.end + 5.0)
        tk.Label(d, text="Insert new segment", font=("Arial", 10, "bold"),
                 fg=C["accent"], bg=C["bg_dark"]).pack(pady=10)
        entries = {}
        for lbl, default in [("Start:", format_flexible_timestamp(cur.end)),
                              ("End:", format_flexible_timestamp(nxt_end)),
                              ("Speaker:", cur.speaker)]:
            r = tk.Frame(d, bg=C["bg_dark"]); r.pack(fill=tk.X, padx=20, pady=2)
            tk.Label(r, text=lbl, width=10, anchor="w", fg=C["fg_light"],
                     bg=C["bg_dark"]).pack(side=tk.LEFT)
            e = tk.Entry(r, width=25, bg=C["bg_mid"], fg=C["white"],
                         insertbackground=C["white"], relief=tk.FLAT)
            e.insert(0, default); e.pack(side=tk.LEFT, fill=tk.X, expand=True); entries[lbl] = e
        tk.Label(d, text="Text:", fg=C["fg_light"], bg=C["bg_dark"]).pack(anchor=tk.W, padx=20)
        tw = tk.Text(d, height=4, wrap=tk.WORD, bg=C["bg_mid"], fg=C["white"],
                     insertbackground=C["white"], relief=tk.FLAT)
        tw.pack(fill=tk.BOTH, expand=True, padx=20)
        def do_it():
            try:
                st = parse_flexible_timestamp(entries["Start:"].get())
                et = parse_flexible_timestamp(entries["End:"].get())
                sp = entries["Speaker:"].get().strip(); txt = tw.get("1.0", tk.END).strip()
                if st >= et: messagebox.showerror("Error", "Start ≥ End", parent=d); return
                if not txt: messagebox.showerror("Error", "Text empty", parent=d); return
                self.session.insert_segment(after_idx, sp, st, et, txt)
                self._refresh_save_label(); self._schedule_auto_save()
                self._update_view(); d.destroy()
            except ValueError as e: messagebox.showerror("Error", str(e), parent=d)
        bf = tk.Frame(d, bg=C["bg_dark"]); bf.pack(pady=8)
        tk.Button(bf, text="Insert", bg=C["green"], fg=C["white"], relief=tk.FLAT,
                  padx=12, command=do_it).pack(side=tk.LEFT, padx=5)
        tk.Button(bf, text="Cancel", bg=C["bg_mid"], fg=C["white"], relief=tk.FLAT,
                  padx=12, command=d.destroy).pack(side=tk.LEFT, padx=5)

    # ═══════════════════════════════════════════════════════════════════
    #  NAVIGATION
    # ═══════════════════════════════════════════════════════════════════

    def _nav_start(self): self._current_idx = 0; self._update_view()
    def _nav_end(self):
        self._current_idx = max(0, self.transcript.get_segment_count() - self.lines_per_view.get())
        self._update_view()
    def _nav_prev(self):
        self._current_idx = max(0, self._current_idx - self.lines_per_view.get()); self._update_view()
    def _nav_next(self):
        self._current_idx = min(self.transcript.get_segment_count() - 1,
                                self._current_idx + self.lines_per_view.get()); self._update_view()
    def _nav_to_seg(self):
        try:
            n = int(self._ent_jump.get()); t = self.transcript.get_segment_count()
            if 1 <= n <= t: self._current_idx = n - 1; self._update_view()
        except ValueError: pass
    def _nav_to_time(self):
        try: target = parse_flexible_timestamp(self._ent_ts.get().strip())
        except ValueError: return
        self._current_idx = self.session.find_segment_at_time(target); self._update_view()
        if self.audio.is_loaded: self.audio.set_position(target)
    def _nav_to_time_dropdown(self):
        try: target = int(self._ts_hh.get()) * 3600 + int(self._ts_mm.get()) * 60 + int(self._ts_ss.get())
        except ValueError: return
        self._current_idx = self.session.find_segment_at_time(target); self._update_view()
        if self.audio.is_loaded: self.audio.set_position(target)
    def _do_jump_next_edited(self, event):
        if not self.session: return "break"
        idx = self.session.next_edited_index(self._current_idx)
        if idx is not None: self._current_idx = idx; self._update_view()
        return "break"

    # ═══════════════════════════════════════════════════════════════════
    #  SEARCH
    # ═══════════════════════════════════════════════════════════════════

    def _open_search(self):
        if self._search_win and self._search_win.winfo_exists():
            self._search_win.lift(); self._search_win.focus_force(); return
        sw = tk.Toplevel(self.root, bg=C["bg_dark"]); sw.title("Find in Transcript")
        sw.geometry("560x450"); sw.transient(self.root); sw.resizable(True, True)
        self._search_win = sw

        top = tk.Frame(sw, bg=C["bg_dark"]); top.pack(fill=tk.X, padx=8, pady=8)
        tk.Label(top, text="Find:", fg=C["fg_light"], bg=C["bg_dark"]).pack(side=tk.LEFT)
        self._s_var = tk.StringVar()
        se = tk.Entry(top, textvariable=self._s_var, width=30, bg=C["bg_mid"],
                      fg=C["white"], insertbackground=C["white"], relief=tk.FLAT)
        se.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        se.bind("<Return>", lambda e: self._s_next()); se.focus_set()

        opt = tk.Frame(sw, bg=C["bg_dark"]); opt.pack(fill=tk.X, padx=8)
        self._s_rx = tk.BooleanVar(value=False); self._s_cs = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Regex", variable=self._s_rx).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(opt, text="Case sensitive", variable=self._s_cs).pack(side=tk.LEFT, padx=5)
        tk.Label(opt, text="Tip: * = any chars (e.g. FI*MA → FINMA)",
                 fg="#777", bg=C["bg_dark"], font=("Arial", 7)).pack(side=tk.LEFT, padx=10)

        bf = tk.Frame(sw, bg=C["bg_dark"]); bf.pack(fill=tk.X, padx=8, pady=5)
        for txt, cmd in [("Find Next", self._s_next), ("Find Prev", self._s_prev),
                         ("List All", self._s_list), ("Clear", self._s_clear)]:
            ttk.Button(bf, text=txt, command=cmd, width=10).pack(side=tk.LEFT, padx=2)

        self._s_info = tk.Label(sw, text="", fg=C["fg_light"], bg=C["bg_dark"], font=("Arial", 8))
        self._s_info.pack(anchor=tk.W, padx=10)

        lf = tk.Frame(sw, bg=C["bg_dark"]); lf.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 8))
        cols = ("seg", "time", "text")
        self._s_tree = ttk.Treeview(lf, columns=cols, show="headings", height=10)
        self._s_tree.heading("seg", text="#"); self._s_tree.column("seg", width=40, stretch=False)
        self._s_tree.heading("time", text="Time"); self._s_tree.column("time", width=90, stretch=False)
        self._s_tree.heading("text", text="Text"); self._s_tree.column("text", width=380)
        tsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self._s_tree.yview)
        self._s_tree.configure(yscrollcommand=tsb.set)
        self._s_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._s_tree.bind("<<TreeviewSelect>>", self._s_select)
        sw.protocol("WM_DELETE_WINDOW", self._s_close); self._s_last_q = ""

    def _s_ensure(self):
        q = self._s_var.get()
        if q != self._s_last_q:
            self.session.build_search(q, self._s_rx.get(), self._s_cs.get()); self._s_last_q = q
    def _s_next(self):
        self._s_ensure(); idx = self.session.search_next()
        if idx is None: self._s_info.config(text="No matches"); return
        self._current_idx = idx; self._update_view()
        self._s_info.config(text=self.session.search_status_text())
    def _s_prev(self):
        self._s_ensure(); idx = self.session.search_prev()
        if idx is None: self._s_info.config(text="No matches"); return
        self._current_idx = idx; self._update_view()
        self._s_info.config(text=self.session.search_status_text())
    def _s_list(self):
        self._s_ensure()
        for it in self._s_tree.get_children(): self._s_tree.delete(it)
        if not self.session.search_matches:
            self._s_info.config(text="No matches"); self._update_view(); return
        seen = set()
        for i, sr in enumerate(self.session.search_matches):
            if sr.segment_index in seen: continue
            seen.add(sr.segment_index); seg = self.transcript.segments[sr.segment_index]
            self._s_tree.insert("", tk.END, iid=str(i),
                                values=(sr.segment_index + 1, format_flexible_timestamp(seg.start),
                                        seg.text[:80].replace("\n", " ")))
        self._s_info.config(text=f"{len(self.session.search_matches)} matches in {len(seen)} segments")
        self._update_view()
    def _s_select(self, event):
        sel = self._s_tree.selection()
        if not sel: return
        self._current_idx = int(self._s_tree.item(sel[0], "values")[0]) - 1; self._update_view()
    def _s_clear(self):
        self.session.clear_search(); self._s_last_q = ""; self._s_info.config(text="")
        for it in self._s_tree.get_children(): self._s_tree.delete(it)
        self._update_view()
    def _s_close(self):
        self.session.clear_search(); self._update_view()
        if self._search_win: self._search_win.destroy(); self._search_win = None

    # ═══════════════════════════════════════════════════════════════════
    #  PLAYBACK
    # ═══════════════════════════════════════════════════════════════════

    def _pb_play(self):
        if not self.transcript.get_segment_count() or not self.audio.is_loaded: return
        n = self.lines_per_view.get()
        st, et = self.transcript.get_time_range_for_segments(self._current_idx, n)
        if self._first_play: st = 0.0; self._first_play = False
        self.audio.play_segment(st, et)
    def _pb_segment(self, seg):
        if not self.audio.is_loaded: return
        self._first_play = False; self.audio.play_segment(seg.start, seg.end)
    def _pb_pause(self):
        if self.audio.is_loaded: self.audio.pause()
    def _pb_stop(self): self.audio.stop()
    def _pb_skip(self, s):
        if not self.audio.is_loaded: return
        c = self.audio.get_position(); d = self.audio.get_duration()
        self.audio.set_position(max(0, min(c + s, d)))
    def _on_slider(self, val):
        if not self.audio.is_loaded or self._slider_busy: return
        self._slider_busy = True
        dur = self.audio.get_duration()
        if dur > 0:
            pos = (float(val) / 100) * dur; self.audio.set_position(pos)
            self._after("slider", 300, lambda: self._slider_done(pos))
        self.root.after(150, lambda: setattr(self, "_slider_busy", False))
    def _slider_done(self, pos):
        self._current_idx = self.session.find_segment_at_time(pos); self._update_view()
    def _on_vol(self, val):
        v = int(float(val)); self.audio.set_volume(v); self._lbl_vol.config(text=f"{v}%")
    def _tick_time(self):
        if self._closing: return
        if self.audio.is_loaded:
            c = self.audio.get_position(); d = self.audio.get_duration()
            self._lbl_time.config(text=f"{format_time_hms(c)} / {format_time_hms(d)}")
            self._lbl_cur.config(text=format_time_hms(c))
            self._lbl_end.config(text=format_time_hms(d))
            if not self._slider_busy and d > 0: self._prog_var.set((c / d) * 100)
        self._after_ids["time"] = self.root.after(150, self._tick_time)

    # ═══════════════════════════════════════════════════════════════════
    #  AUDIO LOADING
    # ═══════════════════════════════════════════════════════════════════

    def _load_audio_bg(self, path):
        self._set_status("Loading audio…")
        def w():
            ok = self.audio.load_media(path)
            self.root.after(0, lambda: self._audio_ready(ok, path))
        Thread(target=w, daemon=True).start()
    def _audio_ready(self, ok, path):
        if self._closing: return
        if ok: self._first_play = True; self._set_status(f"Audio: {os.path.basename(path)}")
        else: self._set_status("Audio load failed"); self._show_no_audio()

    # ═══════════════════════════════════════════════════════════════════
    #  VISUALIZATION (lazy)
    # ═══════════════════════════════════════════════════════════════════

    def _on_tab_changed(self, event):
        if self._nb.index("current") == 1 and not self._viz_loaded: self._init_viz()

    def _init_viz(self):
        if self._viz_loaded: return
        self._viz_loaded = True
        if hasattr(self, "_viz_placeholder"): self._viz_placeholder.destroy()
        import matplotlib; matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        self._fig, (self._ax_w, self._ax_f) = plt.subplots(2, 1, figsize=(14, 4))
        self._fig.tight_layout(pad=2.0); self._fig.patch.set_facecolor(C["bg_dark"])
        for ax, xl, yl, t in [
            (self._ax_w, "Time (s)", "Amplitude", "Audio Waveform"),
            (self._ax_f, "Frequency (Hz)", "Power (dB)", "Frequency Spectrum")]:
            ax.set_facecolor(C["bg_mid"])
            ax.set_xlabel(xl, color=C["fg_light"]); ax.set_ylabel(yl, color=C["fg_light"])
            ax.set_title(t, color=C["accent"], fontsize=10)
            ax.tick_params(colors=C["fg_light"], labelsize=8)
            ax.grid(True, alpha=0.15, color="#555")
        if not self._audio_file:
            self._ax_w.text(0.5, 0.5, "No audio file loaded", ha="center", va="center",
                            color=C["accent"], fontsize=11, transform=self._ax_w.transAxes)
        self._canvas_plot = FigureCanvasTkAgg(self._fig, master=self._viz_tab)
        self._canvas_plot.draw()
        self._canvas_plot.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        if self._audio_file and self.audio.is_loaded:
            Thread(target=self._compute_waveform, args=(self._audio_file,), daemon=True).start()
        self._tick_marker()

    def _compute_waveform(self, path):
        try: import scipy.io.wavfile as wavfile; from scipy import signal as sp_sig
        except ImportError: self.root.after(0, lambda: self._viz_msg("scipy not installed")); return
        try:
            import numpy as np; ad, sr = None, None
            if path.lower().endswith(".wav"): sr, ad = wavfile.read(path)
            else:
                try:
                    from pydub import AudioSegment as AS
                    a = AS.from_file(path); ad = np.array(a.get_array_of_samples()); sr = a.frame_rate
                    if a.channels == 2: ad = ad.reshape((-1, 2)).mean(axis=1)
                    ad = ad.astype(np.float32) / {1:128.,2:32768.,4:2147483648.}.get(a.sample_width,1.)
                except Exception as e: self.root.after(0, lambda: self._viz_msg(f"pydub: {e}")); return
            if ad is None: return
            if len(ad.shape) > 1: ad = ad.mean(axis=1)
            ad = ad.astype(np.float32); mx = np.max(np.abs(ad))
            if mx > 0: ad /= mx
            self._audio_np = ad; self._sample_rate = sr
            self.root.after(0, self._draw_waveform)
        except Exception as e: self.root.after(0, lambda: self._viz_msg(str(e)))

    def _draw_waveform(self):
        if self._closing or self._audio_np is None: return
        import numpy as np; from scipy import signal as sp_sig
        ad, sr = self._audio_np, self._sample_rate
        ad_d = ad[::max(1, len(ad)//5000)]
        t_d = np.arange(len(ad_d)) * (len(ad)/len(ad_d)) / sr
        ax = self._ax_w; ax.clear(); ax.set_facecolor(C["bg_mid"])
        ax.plot(t_d, ad_d, color=C["green"], linewidth=0.5)
        ax.set(xlim=[0, len(ad)/sr], ylim=[-1.1,1.1])
        ax.set_xlabel("Time (s)", color=C["fg_light"]); ax.set_ylabel("Amplitude", color=C["fg_light"])
        ax.set_title("Audio Waveform", color=C["accent"], fontsize=10)
        ax.tick_params(colors=C["fg_light"], labelsize=8); ax.grid(True, alpha=0.15, color="#555")
        ax2 = self._ax_f; ax2.clear(); ax2.set_facecolor(C["bg_mid"])
        try:
            f, p = sp_sig.welch(ad, sr, nperseg=min(2048, len(ad)))
            ax2.plot(f, 10*np.log10(p+1e-10), color=C["teal"], linewidth=1)
        except Exception: pass
        ax2.set_xlabel("Frequency (Hz)", color=C["fg_light"]); ax2.set_ylabel("Power (dB)", color=C["fg_light"])
        ax2.set_title("Frequency Spectrum", color=C["accent"], fontsize=10)
        ax2.tick_params(colors=C["fg_light"], labelsize=8); ax2.grid(True, alpha=0.15, color="#555")
        ax2.set_xlim([0, min(8000, sr//2)]); self._canvas_plot.draw()

    def _viz_msg(self, msg):
        if self._closing or not self._viz_loaded: return
        self._ax_w.clear(); self._ax_w.set_facecolor(C["bg_mid"])
        self._ax_w.text(0.5, 0.5, msg, ha="center", va="center",
                        color=C["accent"], fontsize=10, transform=self._ax_w.transAxes)
        self._canvas_plot.draw()

    def _tick_marker(self):
        if self._closing or not self._viz_loaded: return
        try:
            if self.audio.is_loaded and self._audio_np is not None:
                pos = self.audio.get_position()
                if self._marker_line:
                    try: self._marker_line.remove()
                    except Exception: pass
                self._marker_line = self._ax_w.axvline(pos, color=C["red"],
                    linewidth=2, linestyle="--", alpha=0.7)
                self._canvas_plot.draw_idle()
        except Exception: pass
        self._after_ids["marker"] = self.root.after(250, self._tick_marker)

    # ═══════════════════════════════════════════════════════════════════
    #  SAVE / BACKUP
    # ═══════════════════════════════════════════════════════════════════

    def _refresh_save_label(self):
        if self.session and self.session.unsaved:
            self._lbl_save.config(text="● Unsaved", fg=C["orange"])
        else: self._lbl_save.config(text="✓ Saved", fg=C["green"])
    def _schedule_auto_save(self):
        if not self.auto_save.get(): return
        self._after("save", 3000, self._auto_save)
    def _auto_save(self):
        if self._closing or not self.session: return
        if self.session.unsaved:
            if self.session.save(): self._lbl_save.config(text="✓ Saved", fg=C["green"])
            else: self._lbl_save.config(text="✗ Failed", fg=C["red"])
        self.session.save_audit_if_needed()
    def _do_save(self):
        if not self.session or not self.transcript.get_segment_count(): return
        self.session.flush_all_pending()
        for idx in list(self._edit_timers): self._flush_edit(idx)
        if self.session.save():
            self.session.log_export(); self._lbl_save.config(text="✓ Saved", fg=C["green"])
            self._set_status(f"Saved → {os.path.basename(self.transcript.output_file)}")
        else: self._lbl_save.config(text="✗ Failed", fg=C["red"])
    def _tick_backup(self):
        if self._closing: return
        if self.session and self.session.unsaved and self.transcript.segments:
            try:
                bd = os.path.join(os.path.dirname(self.transcript.output_file) or ".", "backups")
                os.makedirs(bd, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.session.save(os.path.join(bd, f"{ts}_{os.path.basename(self.transcript.output_file)}"))
            except Exception: pass
        self._after_ids["backup"] = self.root.after(300_000, self._tick_backup)

    # ═══════════════════════════════════════════════════════════════════
    #  STATS
    # ═══════════════════════════════════════════════════════════════════

    def _update_stats(self):
        t = self.transcript.get_segment_count()
        self._lbl_total.config(text=f"Segments: {t}")
        if t:
            d = self.transcript.get_total_duration()
            self._lbl_dur.config(text=f"Duration: {format_time_hms(d)}")
            p = self.transcript.get_validation_progress()
            self._lbl_val.config(text=f"Validated: {p['fully_validated']}/{t} ({p['percentage']:.0f}%)")

    # ═══════════════════════════════════════════════════════════════════
    #  CLOSE
    # ═══════════════════════════════════════════════════════════════════

    def _on_closing(self):
        for idx in list(self._edit_timers):
            try: self.root.after_cancel(self._edit_timers[idx])
            except Exception: pass
        self._edit_timers.clear()
        if self.session: self.session.flush_all_pending()
        if self.session and self.session.unsaved:
            r = messagebox.askyesnocancel("Unsaved Changes", "Save before closing?")
            if r is True: self.session.save()
            elif r is None: return
        self._closing = True; self._cancel_all_afters()
        if self._search_win and self._search_win.winfo_exists(): self._search_win.destroy()
        if self.session: self.session.end_session()
        self.audio.release()
        if self._viz_loaded:
            try: import matplotlib.pyplot as plt; plt.close("all")
            except Exception: pass
        self.root.destroy()
