#!/usr/bin/env python3
"""thinking_star.py - the my_ai thinking indicator, as a tkinter Canvas widget.

The design is Ron's daughter's flower (spinner_design lane, v5.3, 2026-08-03):
at rest a small "solar system" -- a glowing core with a white ring, static
twinkling dust, and five little planets in close orbit. When the AI starts
working the flower BLOOMS out of the glow and breathes -- deeper when fully
open, with a wave of attention traveling petal to petal, a blue glint riding
the wave, a faint heartbeat in the core, and one mote of thought escaping per
breath. When the reply lands the petals fold back in, sparks drift out, and
the planets fall back to their close orbits.

Widget contract (what gui.py uses):
    star = ThinkingStar(parent, size=64)   # any size; geometry scales
    star.start()                           # begin animating (after-loop)
    star.set_busy(True)                    # bloom + breathe
    star.set_busy(False)                   # retract to rest
Nothing here talks to the network, reads files, or imports chat.py. It is a
drawing, full stop. Standard library only, ASCII only (ENGINEERING_LESSONS 14).

THEMES (2026-08-03, Ron's ask): the flower is drawn from a named palette so the
same geometry can live on the cream school window or the midnight one. Colors
in the drawing code are role names resolved through self.pal, never literals --
the ONE geometry, recolored, is the whole point (a switch, not a fork).

    star = ThinkingStar(parent, size=64, theme="midnight")

    python thinking_star.py --selftest     # windowless-ish check: 90 ticks per
                                           # theme incl. a busy cycle, then OK
    python thinking_star.py --theme midnight   # standalone preview, recolored
"""
import math
import random
import sys
import tkinter as tk

REF = 264.0          # reference canvas the geometry was designed on

# Each palette fills the same roles; the drawing code only ever asks for roles.
# "cream" is the daughter's-flower original (v5.3) and stays byte-identical to
# the constants it replaced. "midnight" is the 5-star-hotel-at-midnight look:
# champagne-gold petals, ice-blue glint, warm ivory core on deep near-black.
PALETTES = {
    "cream": {
        "bg": "#f8f6f3",        # canvas behind everything
        "petal": "#e1196e",     # outer petal stroke + warm dust/sparks/motes
        "halo": "#ee8caf",      # the bloom glow lerps from bg toward this
        "blue": "#1e5aaa",      # inner petal stroke + cool sparks
        "glint": "#6db3ff",     # the attention wave's flash on the inner stroke
        "violet": "#7b7bec",    # planets, cool dust, alternating motes
        "core": "#fdf1e8",      # the core disc
        "ring": "#ffffff",      # core ring + center dot
        "blue_soft": "#78a5d7", # the one steel-blue planet
    },
    "dark": {
        # Plain dark mode (2026-08-03, Ron's ask): the cream flower's own pink
        # and blue, brightened to read on a neutral near-black -- dark REGULAR,
        # not the hotel look.
        "bg": "#16181c",
        "petal": "#ee5f96",
        "halo": "#8a4a63",
        "blue": "#6d9bd3",
        "glint": "#a9ccff",
        "violet": "#8b7fd6",
        "core": "#f5e9dd",
        "ring": "#ffffff",
        "blue_soft": "#7395bd",
    },
    "midnight": {
        "bg": "#101218",
        "petal": "#d4ab5e",
        "halo": "#9c8148",
        "blue": "#6d9bd3",
        "glint": "#a9ccff",
        "violet": "#8b7fd6",
        "core": "#f2e7cd",
        "ring": "#fff7e0",
        "blue_soft": "#7395bd",
    },
}
BG = PALETTES["cream"]["bg"]   # default bg for callers that pass none

PETALS = [
    {"ang": 280, "L": 94,  "delta": 0.48},
    {"ang": 342, "L": 87,  "delta": 0.54},
    {"ang": 55,  "L": 102, "delta": 0.57},
    {"ang": 116, "L": 94,  "delta": 0.54},
    {"ang": 188, "L": 83,  "delta": 0.52},
]
GAPS = [311, 18, 85, 152, 234]

# Geometry carries palette ROLE names, not colors: the same seeded layout is
# shared by every theme and _draw resolves the role through the active palette.
_rng = random.Random(63)
PLANETS = [
    {"ang0": _rng.uniform(0, 2 * math.pi), "rest_d": _rng.uniform(20, 36),
     "open_d": od, "size": sz, "color": col, "speed": sp,
     "tw": _rng.uniform(0, 2 * math.pi)}
    for od, sz, col, sp in (
        (112, 2.6, "petal", 1), (119, 2.0, "violet", -1), (125, 3.0, "violet", 1),
        (115, 1.8, "petal", -2), (128, 2.3, "blue_soft", 2),
    )
]
DUST = [{"ang": _rng.uniform(0, 2 * math.pi), "dist": _rng.uniform(19, 40),
         "size": _rng.uniform(1.6, 3.0),
         "color": "petal" if i % 2 else "violet",
         "tw": _rng.uniform(0, 2 * math.pi)}
        for i in range(6)]
SPARKS = [(math.radians(g + _rng.uniform(-8, 8)), _rng.uniform(0.7, 1.0),
           "petal" if i % 2 else "blue") for i, g in enumerate(GAPS * 2)]

TICK_MS = 55
BREATH_TICKS = 24.0      # one breath

def _smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)

def _lerp(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class ThinkingStar(tk.Canvas):
    def __init__(self, parent, size=64, bg=None, theme="cream"):
        self.pal = PALETTES[theme]
        if bg is None:
            bg = self.pal["bg"]
        tk.Canvas.__init__(self, parent, width=size, height=size,
                           bg=bg, highlightthickness=0)
        self.size = size
        self.k = size / REF                 # geometry scale
        self.cx = self.cy = size / 2.0
        self.bgc = bg
        self.f = 0                          # tick counter (drives orbits/breath)
        self.grow = 0.0                     # 0 = rest, 1 = fully open
        self.target = 0.0
        self.spark_t = None                 # None, or 0..1 while sparks fly
        self._after = None
        self._alive = False

    # ---- public API -------------------------------------------------------
    def start(self):
        if not self._alive:
            self._alive = True
            self._tick()

    def stop(self):
        self._alive = False
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def set_busy(self, busy):
        was = self.target
        self.target = 1.0 if busy else 0.0
        if was >= 0.5 and not busy and self.grow > 0.5:
            self.spark_t = 0.0              # fire the settle sparks once

    def set_theme(self, theme, bg=None):
        """Recolor the flower in place -- the window's live theme switch calls
        this. Geometry and animation state are untouched; the next tick draws
        in the new palette."""
        self.pal = PALETTES[theme]
        if bg is None:
            bg = self.pal["bg"]
        self.bgc = bg
        self.configure(bg=bg)

    # ---- animation --------------------------------------------------------
    def _tick(self):
        if not self._alive:
            return
        # ease grow toward its target; blooming is a touch slower than settling
        step = 0.07 if self.target > self.grow else 0.09
        if abs(self.target - self.grow) <= step:
            self.grow = self.target
        else:
            self.grow += step if self.target > self.grow else -step
        if self.spark_t is not None:
            self.spark_t += 1.0 / BREATH_TICKS
            if self.spark_t >= 1.0:
                self.spark_t = None
        self._draw()
        self.f += 1
        self._after = self.after(TICK_MS, self._tick)

    def _draw(self):
        k, cx, cy = self.k, self.cx, self.cy
        self.delete("all")
        f = self.f
        t_orbit = f / (72.0 * 4)            # slow planet clock (period ~16 s)
        breath_theta = 2 * math.pi * f / BREATH_TICKS
        grow = _smooth(self.grow)
        grow_deep = _smooth((self.grow - 0.8) / 0.2)
        speck_vis = 1.0 - grow
        breathe = 1.0 + (0.045 + 0.045 * grow_deep) * math.sin(breath_theta)

        # bloom halo, lagging the breath
        halo_breathe = 1.0 + (0.03 + 0.05 * grow_deep) * math.sin(breath_theta - 0.6)
        bloomR = (70 + 48 * grow) * halo_breathe * k
        strength_base = 0.62 - 0.14 * grow
        rr = bloomR
        shell = max(2, int(4 * k) or 2)
        while rr > 6 * k:
            s = (1 - rr / bloomR) ** 1.3 * strength_base
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                             fill=_lerp(self.bgc, self.pal["halo"], max(0.0, s)),
                             outline="")
            rr -= shell

        # core: warm disc + bright ring + heartbeat thump when fully open
        R = ((16 - 6 * grow) + 1.6 * math.sin(breath_theta)
             + 1.2 * grow_deep * max(0.0, math.sin(2 * breath_theta + 0.9)) ** 3) * k
        self.create_oval(cx - R, cy - R, cx + R, cy + R, fill=self.pal["core"], outline="")
        ring = R * 0.62
        self.create_oval(cx - ring, cy - ring, cx + ring, cy + ring,
                         outline=self.pal["ring"], width=max(1, int(R * 0.28)))
        rc = R * 0.22
        self.create_oval(cx - rc, cy - rc, cx + rc, cy + rc, fill=self.pal["ring"], outline="")

        # planets: close orbit at rest, wide orbit around the open flower
        for pl in PLANETS:
            a = pl["ang0"] + pl["speed"] * 2 * math.pi * t_orbit
            dist = (pl["rest_d"] + (pl["open_d"] - pl["rest_d"]) * grow) * k
            tw = 0.78 + 0.22 * math.sin(t_orbit * 4 * math.pi + pl["tw"])
            col = _lerp(self.bgc, self.pal[pl["color"]], tw)
            x, y = cx + dist * math.cos(a), cy + dist * math.sin(a)
            r = max(1.0, pl["size"] * (0.85 + 0.15 * tw) * k * 1.6)
            self.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="")

        # petals, with the traveling attention wave + blue glint when open
        if grow > 0.04:
            for i, p in enumerate(PETALS):
                wave = math.sin(breath_theta - i * 2 * math.pi / 5)
                own = 1.0 + (0.03 + 0.06 * grow_deep) * wave
                L = p["L"] * breathe * own * grow * k
                ang = p["ang"] + (1.6 + 2.4 * grow_deep) * math.sin(
                    breath_theta - i * 2 * math.pi / 5 + 1.0)
                fi = max(0.0, wave) ** 6 * grow_deep
                blue_now = _lerp(self.pal["blue"], self.pal["glint"], 0.55 * fi)
                ws = min(1.0, grow * 1.35)
                outer = self._petal(ang, L, p["delta"])
                inner = self._petal(ang, L * 0.82, p["delta"] * 0.76)
                self.create_line(*outer, *outer[:2], fill=self.pal["petal"],
                                 width=max(1, int(11 * ws * k * 1.4)),
                                 smooth=True, capstyle="round", joinstyle="round")
                self.create_line(*inner, *inner[:2], fill=blue_now,
                                 width=max(1, int((5 + 2 * fi) * ws * k * 1.4)),
                                 smooth=True, capstyle="round", joinstyle="round")
            # one mote of thought per breath, escaping between two petals
            if grow_deep > 0.5:
                breath_idx = int(f // BREATH_TICKS)
                gap_ang = math.radians(GAPS[breath_idx % 5])
                prog = (f % BREATH_TICKS) / BREATH_TICKS
                dist = (18 + 52 * prog) * k
                glow_m = math.sin(prog * math.pi) * grow_deep
                col = _lerp(self.bgc,
                            self.pal["petal" if breath_idx % 2 else "violet"], glow_m)
                mr = max(1.0, (1.6 + 0.6 * glow_m) * k * 1.6)
                self.create_oval(cx + dist * math.cos(gap_ang) - mr,
                                 cy + dist * math.sin(gap_ang) - mr,
                                 cx + dist * math.cos(gap_ang) + mr,
                                 cy + dist * math.sin(gap_ang) + mr,
                                 fill=col, outline="")

        # static dust: the resting reference dots, twinkling only
        if speck_vis > 0.02:
            for sp in DUST:
                tw = 0.75 + 0.25 * math.sin(t_orbit * 8 * math.pi + sp["tw"])
                col = _lerp(self.bgc, self.pal[sp["color"]], speck_vis * tw)
                x = cx + sp["dist"] * k * math.cos(sp["ang"])
                y = cy + sp["dist"] * k * math.sin(sp["ang"])
                r = max(1.0, sp["size"] * (0.7 + 0.3 * speck_vis) * k * 1.6)
                self.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="")

        # settle sparks: fired once when busy ends, while petals fold back in
        if self.spark_t is not None:
            u = self.spark_t
            for ang, spd, color in SPARKS:
                dist = (30 + 55 * (u ** 0.7) * spd) * k
                fade = max(0.0, 1.0 - u * 1.25)
                r = max(1.0, (3 * (1 - u) + 1) * k * 1.4)
                col = _lerp(self.bgc, self.pal[color], fade)
                self.create_oval(cx + dist * math.cos(ang) - r,
                                 cy + dist * math.sin(ang) - r,
                                 cx + dist * math.cos(ang) + r,
                                 cy + dist * math.sin(ang) + r,
                                 fill=col, outline="")

    def _petal(self, ang, L, delta, k_shape=0.62, steps=24):
        a0 = math.radians(ang)
        pts = []
        for i in range(steps + 1):
            s = i / steps
            r = L * (math.sin(math.pi * s) ** k_shape)
            a = a0 + delta * (2 * s - 1)
            pts.extend((self.cx + r * math.cos(a), self.cy + r * math.sin(a)))
        return pts


def _selftest():
    # Every palette gets the same 90-tick drive incl. one busy cycle, so a
    # theme with a missing role or a bad hex dies here, not in the live window.
    for theme in sorted(PALETTES):
        root = tk.Tk()
        root.title("thinking_star selftest (%s)" % theme)
        star = ThinkingStar(root, size=64, theme=theme)
        star.pack()
        star.start()
        state = {"n": 0}

        def drive():
            state["n"] += 1
            if state["n"] == 20:
                star.set_busy(True)         # bloom
            elif state["n"] == 60:
                star.set_busy(False)        # retract + sparks
            if state["n"] >= 90:
                star.stop()
                root.destroy()
            else:
                root.after(5, drive)

        root.after(5, drive)
        root.mainloop()
    print("THINKING STAR SELFTEST OK - 90 ticks incl. one busy cycle per theme "
          "(%s)" % ", ".join(sorted(PALETTES)))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        theme = "cream"
        if "--theme" in sys.argv:
            try:
                theme = sys.argv[sys.argv.index("--theme") + 1]
            except IndexError:
                pass
            if theme not in PALETTES:
                sys.exit("no such theme: %s (themes: %s)" % (theme, ", ".join(sorted(PALETTES))))
        root = tk.Tk()
        root.title("thinking_star -- standalone preview (%s)" % theme)
        root.configure(bg=PALETTES[theme]["bg"])
        s = ThinkingStar(root, size=180, theme=theme)
        s.pack(padx=20, pady=20)
        s.start()
        root.after(2500, lambda: s.set_busy(True))
        root.after(9000, lambda: s.set_busy(False))
        root.mainloop()
