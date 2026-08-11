#!/usr/bin/env python3
"""ui.py - the window LAYER the AI windows are built from. Styling only.

WHY THIS EXISTS. The usual way to theme a tkinter window is a palette table plus
a function that recolors every widget, and that function needs a list of the
widgets to walk. The list is kept by hand. Add a widget, forget to add it to the
list, and the widget survives a live theme switch still wearing the old theme's
colors -- a bug you only see if you happen to switch themes and happen to look
at that corner of the window.

Here, a widget registers its color ROLES at construction. One registry, filled
by the same call that builds the widget, so there is no second step to forget:

    ui = UI("cream")
    ui.window(win)                                 # the toplevel
    bar = ui.frame(win)                            # bg
    ui.label(bar, "Mode:")                         # bg + ink
    ui.primary_button(bar, "Send", self.on_send)   # accent + accent_fg
    ...
    ui.retheme("midnight")                         # recolors EVERYTHING tracked

WHAT THIS IS NOT. This layer does not give a look tkinter cannot already draw.
A tk.Button is a rectangle the OS paints; wrapping it does not round its
corners. Rounded or custom-drawn widgets have to be Canvas-drawn (see
thinking_star.py, which is exactly that), and that is a separate decision with
its own costs -- a Canvas button must re-implement the focus ring, space/enter
activation, the disabled state, and hover, all of which tk hands you free.
Until that decision is made, this layer's whole job is that recoloring is
correct by construction instead of by memory.

STYLING ONLY, and that boundary is load-bearing. Nothing here reads files, talks
to a network, imports the chat harness, or touches a rule, gate, or mode. A
window built on this layer has exactly the safety behavior it wrote itself; the
layer only decides what color it is.

THE FLOWER KEEPS ITS OWN TABLE. thinking_star.py declares itself stdlib-only
and dependency-free ("it is a drawing, full stop"), so it is NOT converted to
import from here. The dependency runs one way -- a window imports both -- and
_selftest() below asserts the two tables agree on the background they share,
which is the one role that would visibly break if they drifted.

ASCII-only on purpose (ENGINEERING_LESSONS 14: non-ASCII in tree scripts has
come back as mojibake under PowerShell 5.1 more than once).

    python ui.py --selftest        build every widget in every theme, switch
                                  through all of them, verify, exit 0
    python ui.py --preview         a swatch window, for looking at a palette
"""
import sys
import tkinter as tk
from tkinter import scrolledtext

# ---------------------------------------------------------------------------
# THE PALETTE TABLE
#
# One home for window color, so a value cannot be right in one file and stale in
# another. Three looks, and all of them are the SAME window recolored -- a
# switch, not a fork:
#
#   cream     the default: cream paper, pink and blue accents
#   dark      the same identity on a neutral near-black, for after hours
#   midnight  deep near-black, champagne gold, warm ivory type
#
# Adding a theme means filling every role below. The selftest enforces that,
# because a role missing from one palette is a crash mid-switch, live.
# ---------------------------------------------------------------------------
PALETTES = {
    "cream": {
        "bg": "#f8f6f3",             # window background
        "paper": "#fffdf9",          # transcript + entry background
        "ink": "#2b2b33",            # body text
        "muted": "#6f6659",          # status line + [note] voice
        "accent": "#e1196e",         # Send button, text cursor
        "accent_active": "#b8125a",  # Send while pressed
        "accent_fg": "white",        # text on the Send button
        "you": "#b8125a",            # the person's lines in the transcript
        "edge": "#e6ddd1",           # hairline borders
        "btn": "#efe9e0",            # secondary buttons
        "status_bg": "#f1ece4",      # the status strip
        "select_bg": "#f3cede",      # text selection in the transcript
        "crisis": "#a00000",         # the crisis reply -- loud on purpose
        "send_disabled": "#e8b7cc",
        "radio_style": "indicator",  # classic circles, readable on light ground
        "radio_sel": "white",        # indicator interior
    },
    "dark": {
        # Plain dark mode: the cream identity -- the same pink and blue -- on a
        # neutral near-black. This one is dark REGULAR; midnight below is the
        # deliberately styled one.
        "bg": "#16181c",
        "paper": "#1e2126",
        "ink": "#d9dce1",
        "muted": "#8b919c",
        "accent": "#e84d8b",
        "accent_active": "#c62f6e",
        "accent_fg": "white",
        "you": "#f07eae",
        "edge": "#2b2f36",
        "btn": "#23272e",
        "status_bg": "#111317",
        "select_bg": "#3a2833",
        "crisis": "#ff5a52",
        "send_disabled": "#7a4a5e",
        "radio_style": "segment",   # same dark-ground indicator problem as midnight
        "radio_sel": "#4a2b3a",
    },
    "midnight": {
        "bg": "#101218",
        "paper": "#171a22",
        "ink": "#e7e2d6",
        "muted": "#8b8577",
        "accent": "#c9a962",
        "accent_active": "#b4924c",
        "accent_fg": "#101218",
        "you": "#dcbd7e",
        "edge": "#2a2e3a",
        "btn": "#1d212b",
        "status_bg": "#0c0e13",
        "select_bg": "#3a3626",
        "crisis": "#ff5a52",
        "send_disabled": "#6e6046",
        # Flat segments instead of indicator circles: on a dark ground the stock
        # Windows radio indicator does not show WHICH option is selected, no
        # matter what selectcolor is set to (measured pixel-level, not guessed).
        # Where a radio group is a switch the person must be able to READ, that
        # is a defect and not a style preference. The chosen option sits on a
        # warm bronze ground; the others stay quiet dark buttons.
        "radio_style": "segment",
        "radio_sel": "#4d4128",
    },
}

# Every palette must fill every role, or a theme switch lands on a KeyError in
# front of the person. _selftest() enforces it; the split matters because
# radio_style is a rendering MODE, not a color, and must not be hex-checked.
COLOR_ROLES = ("bg", "paper", "ink", "muted", "accent", "accent_active",
               "accent_fg", "you", "edge", "btn", "status_bg", "select_bg",
               "crisis", "send_disabled", "radio_sel")
MODE_ROLES = {"radio_style": ("indicator", "segment")}
THEMES = tuple(sorted(PALETTES))
DEFAULT_THEME = "cream"


# ---------------------------------------------------------------------------
# PAINTERS
#
# Most widgets need nothing but a {tk option -> palette role} map. Three need
# real logic, so they get a painter function instead: the mode radios branch on
# a rendering mode, an OptionMenu has a second widget hiding inside it (the
# popup, which stays a white system menu on a dark theme if you forget), and
# the transcript carries text tags that live outside .configure().
# ---------------------------------------------------------------------------
def paint_radio(w, pal):
    """One radio entry, styled for the active palette. Dark grounds get flat
    SEGMENTS (indicatoron=0: the background IS the selection state) because the
    stock Windows indicator does not show WHICH one is picked on a dark ground
    under any selectcolor. When the group is a switch that has to be readable at
    a glance, that is a defect, so the palette carries the rendering mode."""
    if pal["radio_style"] == "segment":
        w.config(indicatoron=0, bd=0, padx=8, pady=3, bg=pal["btn"],
                 fg=pal["ink"], activebackground=pal["edge"],
                 activeforeground=pal["ink"], selectcolor=pal["radio_sel"],
                 highlightthickness=0)
    else:
        w.config(indicatoron=1, bd=0, padx=1, pady=1, bg=pal["bg"],
                 fg=pal["ink"], activebackground=pal["bg"],
                 activeforeground=pal["ink"], selectcolor=pal["radio_sel"],
                 highlightthickness=0)


def paint_option_menu(w, pal):
    """The button AND its popup list. Skipping the popup is the classic tkinter
    dark-theme bug: a themed control that opens a white system menu."""
    w.config(bg=pal["btn"], fg=pal["ink"], activebackground=pal["edge"],
             activeforeground=pal["ink"], highlightbackground=pal["edge"])
    w["menu"].config(bg=pal["paper"], fg=pal["ink"],
                     activebackground=pal["btn"], activeforeground=pal["ink"])


def paint_transcript(w, pal):
    """The read-only transcript pane and its three voices: the person in the
    accent, quiet notes muted, the crisis reply loud. Streamed model text stays
    plain ink. Fonts are set at construction; tag_configure merges the two."""
    w.configure(bg=pal["paper"], fg=pal["ink"], highlightbackground=pal["edge"],
                selectbackground=pal["select_bg"], insertbackground=pal["ink"])
    w.tag_configure("you", foreground=pal["you"])
    w.tag_configure("note", foreground=pal["muted"])
    w.tag_configure("crisis", foreground=pal["crisis"])


def paint_input(w, pal):
    """The typing box. Its caret takes the accent, and so does the focus edge,
    which is the only cue that keyboard focus is in the box."""
    w.configure(bg=pal["paper"], fg=pal["ink"], insertbackground=pal["accent"],
                highlightbackground=pal["edge"], highlightcolor=pal["accent"])


class UI:
    """Holds the active palette and every widget built through it.

    One rule makes the live switch safe: a color set anywhere OTHER than through
    this object survives a theme switch in only one direction, so it eventually
    shows the wrong theme. Build through the factories, or pass a painter to
    track() for anything the factories do not cover.
    """

    def __init__(self, theme=DEFAULT_THEME):
        if theme not in PALETTES:
            raise ValueError("no such theme: %s (themes: %s)"
                             % (theme, ", ".join(THEMES)))
        self.theme = theme
        self.pal = PALETTES[theme]
        self._tracked = []          # [(widget, roles_or_None, painter_or_None)]

    # ---- registry ---------------------------------------------------------

    def track(self, widget, roles=None, painter=None):
        """Register an already-built widget and paint it now. Returns the
        widget, so it composes: self.txt = ui.track(SomeWidget(...), ...)."""
        self._tracked.append((widget, roles, painter))
        self._paint(widget, roles, painter)
        return widget

    def _paint(self, w, roles, painter):
        if painter is not None:
            painter(w, self.pal)
        else:
            w.configure(**dict((opt, self.pal[role])
                               for opt, role in roles.items()))

    def retheme(self, name):
        """Recolor every tracked widget, live. STYLING ONLY -- no rule, gate,
        or behavior changes. Dialogs that have been closed are dropped on the
        way through: a destroyed widget still sits in the list holding a dead
        Tcl name, and configuring it raises."""
        if name not in PALETTES:
            raise ValueError("no such theme: %s" % name)
        self.theme = name
        self.pal = PALETTES[name]
        alive = []
        for w, roles, painter in self._tracked:
            try:
                if not w.winfo_exists():
                    continue
            except tk.TclError:
                continue            # interpreter already tore it down
            alive.append((w, roles, painter))
            self._paint(w, roles, painter)
        self._tracked = alive

    def tracked_count(self):
        """Live widget count. The selftest uses it to prove the registry is
        actually filling instead of silently dropping everything."""
        return len(self._tracked)

    # ---- factories -------------------------------------------------------
    # Each owns exactly the options apply_theme used to own, plus the
    # structural flags that were the same at every call site (relief, bd).
    # Anything a caller varies -- font, width, geometry -- passes through **kw.

    def window(self, win):
        """The toplevel itself. Tracked so Toplevel dialogs follow the switch
        instead of freezing on the theme they opened under."""
        return self.track(win, {"bg": "bg"})

    def frame(self, parent, on="bg", **kw):
        return self.track(tk.Frame(parent, **kw), {"bg": on})

    def label(self, parent, text="", tone="ink", on="bg", **kw):
        return self.track(tk.Label(parent, text=text, **kw),
                          {"bg": on, "fg": tone})

    def primary_button(self, parent, text, command, **kw):
        """The one loud button in a window (Send). Accent ground, and a
        disabled color that reads as unavailable rather than as missing."""
        kw.setdefault("relief", "flat")
        kw.setdefault("bd", 0)
        kw.setdefault("cursor", "hand2")
        b = tk.Button(parent, text=text, command=command, **kw)
        return self.track(b, {"bg": "accent", "fg": "accent_fg",
                              "activebackground": "accent_active",
                              "activeforeground": "accent_fg",
                              "disabledforeground": "send_disabled"})

    def soft_button(self, parent, text, command, **kw):
        kw.setdefault("relief", "flat")
        kw.setdefault("bd", 0)
        kw.setdefault("cursor", "hand2")
        b = tk.Button(parent, text=text, command=command, **kw)
        return self.track(b, {"bg": "btn", "fg": "ink",
                              "activebackground": "edge",
                              "activeforeground": "ink"})

    def radio(self, parent, text, value, variable, command=None, **kw):
        rb = tk.Radiobutton(parent, text=text, value=value, variable=variable,
                            command=command, **kw)
        return self.track(rb, painter=paint_radio)

    def option_menu(self, parent, variable, choices, command=None, **kw):
        kw.setdefault("relief", "flat")
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 1)
        font = kw.pop("font", None)
        m = tk.OptionMenu(parent, variable, *choices, command=command)
        cfg = dict(kw)
        if font is not None:
            cfg["font"] = font
        m.config(**cfg)
        return self.track(m, painter=paint_option_menu)

    def transcript(self, parent, **kw):
        """The scrolling read-only pane. Starts disabled: callers flip to
        normal, insert, and flip back (see the window's append())."""
        kw.setdefault("wrap", "word")
        kw.setdefault("state", "disabled")
        kw.setdefault("relief", "flat")
        kw.setdefault("bd", 0)
        kw.setdefault("padx", 10)
        kw.setdefault("pady", 8)
        kw.setdefault("highlightthickness", 1)
        font = kw.pop("font", ("Consolas", 10))
        t = scrolledtext.ScrolledText(parent, font=font, **kw)
        # Tag FONTS are structure, so they are set once here; tag COLORS come
        # from paint_transcript on every switch. tag_configure merges them.
        t.tag_configure("you", font=(font[0], font[1], "bold"))
        t.tag_configure("note", font=(font[0], max(1, font[1] - 1), "italic"))
        t.tag_configure("crisis", font=(font[0], font[1], "bold"))
        return self.track(t, painter=paint_transcript)

    def input_box(self, parent, **kw):
        kw.setdefault("height", 3)
        kw.setdefault("wrap", "word")
        kw.setdefault("relief", "flat")
        kw.setdefault("bd", 0)
        kw.setdefault("padx", 8)
        kw.setdefault("pady", 6)
        kw.setdefault("highlightthickness", 1)
        return self.track(tk.Text(parent, **kw), painter=paint_input)

    def entry(self, parent, **kw):
        """A one-line field. Stays a NATIVE Entry on purpose: real selection,
        real IME, real keyboard handling. Anything a person types a decision into
        should be a real text field, not a drawing of one."""
        return self.track(tk.Entry(parent, **kw), painter=paint_input)

    def strip(self, parent, **kw):
        """The footer band. Its own ground so the ambient chrome reads as
        chrome and not as part of the transcript."""
        return self.track(tk.Frame(parent, **kw), {"bg": "status_bg"})

    def strip_label(self, parent, text="", tone="muted", **kw):
        return self.track(tk.Label(parent, text=text, **kw),
                          {"bg": "status_bg", "fg": tone})


# ---------------------------------------------------------------------------
def _selftest():
    """Build one of every widget, walk every theme, and check the invariants a
    palette can break. Each of these has a real failure it is standing in for:

      - a role missing from one theme  -> KeyError mid-switch, live
      - a bad hex value                -> TclError the moment it is applied
      - flower bg != window bg         -> a visible seam around the flower
      - a dead widget left in the list -> TclError on the next switch
    """
    import thinking_star

    problems = []

    # 1. every theme fills every role, colors look like colors, modes are valid
    for name in THEMES:
        pal = PALETTES[name]
        for role in COLOR_ROLES:
            if role not in pal:
                problems.append("%s missing color role %s" % (name, role))
        for role, allowed in MODE_ROLES.items():
            if pal.get(role) not in allowed:
                problems.append("%s has bad %s: %r" % (name, role, pal.get(role)))
        extra = set(pal) - set(COLOR_ROLES) - set(MODE_ROLES)
        if extra:
            problems.append("%s has unknown roles: %s" % (name, sorted(extra)))

    # 2. the window table and the flower table agree on the shared background.
    #    They are deliberately separate tables (the flower is stdlib-only), so
    #    this is the seam where drift would show as a visible ring.
    for name in THEMES:
        if name not in thinking_star.PALETTES:
            problems.append("thinking_star has no palette named %s" % name)
        elif thinking_star.PALETTES[name]["bg"] != PALETTES[name]["bg"]:
            problems.append("%s bg mismatch: window %s, flower %s"
                            % (name, PALETTES[name]["bg"],
                               thinking_star.PALETTES[name]["bg"]))

    # 3. build one of everything, then switch through every theme. A widget
    #    styled outside the registry, or a palette that cannot actually be
    #    applied, dies here instead of in front of the person.
    root = tk.Tk()
    root.withdraw()
    ui = UI(DEFAULT_THEME)
    ui.window(root)
    bar = ui.frame(root)
    ui.label(bar, "Mode:")
    var = tk.StringVar(value="plan")
    for m in ("chat", "plan", "build"):
        ui.radio(bar, m, m, var)
    mvar = tk.StringVar(value="a")
    ui.option_menu(bar, mvar, ["a", "b"], font=("Segoe UI", 9))
    ui.transcript(root)
    ui.input_box(root)
    ui.primary_button(root, "Send", lambda: None)
    ui.soft_button(root, "Finish chat", lambda: None)
    st = ui.strip(root)
    ui.strip_label(st, "status")
    ui.entry(st)
    star = thinking_star.ThinkingStar(root, size=32, theme=DEFAULT_THEME)

    built = ui.tracked_count()
    if built < 12:
        problems.append("registry only tracked %d widgets" % built)

    for name in list(THEMES) + [DEFAULT_THEME]:
        try:
            ui.retheme(name)
            star.set_theme(name, PALETTES[name]["bg"])
            root.update_idletasks()
        except Exception as e:
            problems.append("retheme(%s) raised %s: %s"
                            % (name, type(e).__name__, e))
    if ui.theme != DEFAULT_THEME:
        problems.append("did not land back on %s" % DEFAULT_THEME)

    # 4. a destroyed widget must be pruned, not crash the next switch. This is
    #    the bug the layer could ADD: dialogs come and go, and their widgets
    #    stay in the list holding dead Tcl names.
    doomed = ui.frame(root)
    before = ui.tracked_count()
    doomed.destroy()
    try:
        ui.retheme("dark")
        ui.retheme(DEFAULT_THEME)
    except Exception as e:
        problems.append("switch after destroy raised %s: %s"
                        % (type(e).__name__, e))
    if ui.tracked_count() != before - 1:
        problems.append("destroyed widget not pruned (%d -> %d, wanted %d)"
                        % (before, ui.tracked_count(), before - 1))

    root.destroy()

    if problems:
        for p in problems:
            sys.__stdout__.write("  FAIL  %s\n" % p)
        sys.__stdout__.write("UI SELFTEST FAILED (%d problem(s))\n" % len(problems))
        return 1
    sys.__stdout__.write(
        "UI SELFTEST OK - %d widgets, %d themes (%s), roles complete, "
        "flower bg matched, destroyed widget pruned\n"
        % (built, len(THEMES), ", ".join(THEMES)))
    return 0


def _preview(theme):
    """A swatch window. For looking at a palette, not for testing it."""
    root = tk.Tk()
    root.title("ui.py palette preview -- %s" % theme)
    root.geometry("520x360")
    ui = UI(theme)
    ui.window(root)
    head = ui.frame(root)
    head.pack(fill="x", padx=10, pady=(10, 4))
    ui.label(head, "theme:", font=("Segoe UI", 9)).pack(side="left")
    tvar = tk.StringVar(value=theme)
    ui.option_menu(head, tvar, list(THEMES),
                   command=lambda c: ui.retheme(c),
                   font=("Segoe UI", 9)).pack(side="left", padx=4)
    txt = ui.transcript(root, height=8)
    txt.pack(fill="both", expand=True, padx=10, pady=6)
    txt.configure(state="normal")
    txt.insert("end", "you > every widget below is tracked\n", "you")
    txt.insert("end", "ai  > plain ink, the streamed voice\n")
    txt.insert("end", "(a quiet note)\n", "note")
    txt.insert("end", "the crisis reply, loud on purpose\n", "crisis")
    txt.configure(state="disabled")
    ui.input_box(root, height=2, font=("Segoe UI", 10)).pack(
        fill="x", padx=10, pady=(0, 6))
    row = ui.frame(root)
    row.pack(fill="x", padx=10, pady=(0, 8))
    ui.primary_button(row, "Send", lambda: None,
                      font=("Segoe UI", 10, "bold"), width=10).pack(side="left")
    ui.soft_button(row, "Finish chat", lambda: None,
                   font=("Segoe UI", 9), width=12).pack(side="left", padx=6)
    st = ui.strip(root)
    st.pack(fill="x", side="bottom")
    ui.strip_label(st, "  status strip: switch the theme and watch every "
                       "widget follow", font=("Segoe UI", 8)).pack(side="left")
    root.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    theme = DEFAULT_THEME
    if "--theme" in sys.argv:
        try:
            theme = sys.argv[sys.argv.index("--theme") + 1]
        except IndexError:
            pass
        if theme not in PALETTES:
            sys.exit("no such theme: %s (themes: %s)" % (theme, ", ".join(THEMES)))
    _preview(theme)
