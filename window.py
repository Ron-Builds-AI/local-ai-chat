#!/usr/bin/env python3
"""window.py - the free/education edition in a real window instead of a terminal.

This file is a WINDOW, not a second AI. It imports chat.py and reuses its
harness: the loopback-only transport, the crisis reflex, the session cache, and
the `wrap` lifecycle verb. Nothing here relaxes anything there, and nothing here
adds a capability chat.py does not already have.

  - The crisis reflex fires FIRST, before the model, exactly as in the terminal
    client. It is not skippable by a persona, a model, or a setting.
  - `wrap` and `wrap logs` work by typing them, same grammar as the terminal.
    Closing the window asks the same question the verb answers: keep this
    conversation's log, or delete it. Delete is the default.
  - The model's streamed text lands in the transcript pane verbatim, so the
    window shows what the terminal would have shown.

This edition is CHAT ONLY. There are no file tools, so there is no folder to
choose, no mode to switch, and nothing to approve -- which is why this window is
smaller than it might look like it should be. A control that does nothing is
worse than no control, so the ones with nothing behind them are simply absent.

Usage:
  python window.py                  window, default model
  python window.py --model NAME     pick an Ollama model
  python window.py --theme dark     launch palette: cream | dark | midnight
                                    (the Theme dropdown in the footer switches live)
  python window.py --selftest       build the window, verify wiring, close, exit 0

ASCII-only on purpose: non-ASCII in scripts has come back as mojibake under
Windows PowerShell more than once.
"""
import argparse
import os
import queue
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chat  # noqa: E402  -- the harness; this file only presents it

import tkinter as tk                      # noqa: E402
from tkinter import messagebox            # noqa: E402

import thinking_star                      # noqa: E402  -- the breathing flower
import ui                                 # noqa: E402  -- the window layer

UI_QUEUE = queue.Queue()


class QueueWriter:
    """Stands in for stdout/stderr so chat.turn()'s prints land in the window.
    Under pythonw.exe the real stdout is None, so this also keeps turn() alive."""

    def write(self, s):
        if s:
            UI_QUEUE.put(("text", s))
        return len(s)

    def flush(self):
        pass


class App:
    def __init__(self, win, model, theme=ui.DEFAULT_THEME):
        self.win = win
        self.model = model
        self.busy = False
        self.messages = [{"role": "system", "content": chat.load_persona()}]

        win.title("your private local AI (nothing leaves this PC)")
        win.geometry("860x620")
        win.minsize(600, 440)

        # EVERY WIDGET IS BUILT THROUGH self.ui, which paints it now and
        # remembers it for the next theme switch. Geometry, fonts, and commands
        # belong here; color never does.
        self.ui = ui.UI(theme)
        self.ui.window(win)

        top = self.ui.frame(win)
        top.pack(fill="x", padx=10, pady=(8, 0))
        # Rest = a quiet idle drift; bloom + breathe = the model is working. It
        # is the only "is it thinking" cue in the window, which matters more here
        # than in a terminal: there is no cursor sitting there blinking.
        self.star = thinking_star.ThinkingStar(top, size=64, theme=theme)
        self.star.pack(side="left", padx=(0, 10))
        self.ui.track(self.star,
                      painter=lambda w, pal: w.set_theme(self.ui.theme, pal["bg"]))

        # The model is a free-text field, not a dropdown: this edition has no
        # curated model list, and `ollama list` on this box is the only honest
        # source of what is actually installed. Same as the terminal's /model.
        picker = self.ui.frame(top)
        picker.pack(side="right", padx=(0, 2))
        self.ui.label(picker, "Model:", font=("Segoe UI", 9)).pack(side="left")
        self.model_entry = self.ui.entry(picker, font=("Segoe UI", 9), width=18)
        self.model_entry.insert(0, model)
        self.model_entry.pack(side="left", padx=(4, 4))
        self.ui.soft_button(picker, "Use", self.on_model_change,
                            font=("Segoe UI", 9), width=5).pack(side="left")

        self.txt = self.ui.transcript(win, font=("Consolas", 10))
        self.txt.pack(fill="both", expand=True, padx=10, pady=8)

        bottom = self.ui.frame(win)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        self.entry = self.ui.input_box(bottom, font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="both", expand=True)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<Shift-Return>", lambda e: None)  # plain newline
        btns = self.ui.frame(bottom)
        btns.pack(side="right", fill="y", padx=(6, 0))
        self.send_btn = self.ui.primary_button(btns, "Send", self.on_send,
                                               width=12,
                                               font=("Segoe UI", 10, "bold"))
        self.send_btn.pack(fill="x", ipady=2)
        for text, cmd in (("Save a copy", self.on_save),
                          ("Finish chat", self.on_close)):
            self.ui.soft_button(btns, text, cmd, width=12,
                                font=("Segoe UI", 9)).pack(fill="x", pady=(4, 0))

        self._strip = self.ui.strip(win)
        self._strip.pack(fill="x", side="bottom")
        self.theme_var = tk.StringVar(value=theme)
        self._theme_menu = self.ui.option_menu(self._strip, self.theme_var,
                                               ui.THEMES,
                                               command=self.on_theme_change,
                                               font=("Segoe UI", 8))
        self._theme_menu.pack(side="right", padx=(0, 8), pady=1)
        self.ui.strip_label(self._strip, "Theme:",
                            font=("Segoe UI", 8)).pack(side="right")
        self.status = self.ui.strip_label(self._strip, anchor="w", justify="left",
                                          font=("Segoe UI", 9), padx=10, pady=3)
        self.status.pack(side="left", fill="x", expand=True)

        win.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_status()
        self.entry.focus_set()
        self.star.start()

        # Same startup narration as the terminal client, same honesty about where
        # the traffic goes: the check proves the HOST is loopback. It does not
        # prove what is listening there.
        print("=== your private local AI ===  model: %s" % model)
        print("talking to: %s   (this client refuses any host but loopback)" % chat.OLLAMA)
        print("session   : %s" % chat.SESSION_CACHE)
        print("done?     : type  wrap  to finish and DELETE the cache, wrap logs to keep it,")
        print("            or use the Finish chat button.\n")
        chat._orphan_sweep()
        win.after(50, self.poll)

    # ---- GUI-thread plumbing ---------------------------------------------------

    def apply_theme(self, name):
        """Recolor the whole window, live. STYLING ONLY -- no rule or behavior
        changes. Every widget registered itself when it was built, so this is one
        call and there is no list to keep in sync."""
        self.ui.retheme(name)
        self.theme_var.set(name)

    def on_theme_change(self, choice):
        if choice == self.ui.theme:
            return
        self.apply_theme(choice)
        self.append("(theme -> %s)\n" % choice, "note")

    def refresh_status(self):
        self.status.config(text="model: %s     talking to: %s     chat only "
                                "(no file access)" % (self.model, chat.OLLAMA))

    def append(self, s, tag=None):
        self.txt.configure(state="normal")
        if tag:
            self.txt.insert("end", s, tag)
        else:
            self.txt.insert("end", s)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def poll(self):
        try:
            while True:
                item = UI_QUEUE.get_nowait()
                if item[0] == "text":
                    self.append(item[1])
                elif item[0] == "enable":
                    self.busy = False
                    self.send_btn.config(state="normal")
                    self.star.set_busy(False)
        except queue.Empty:
            pass
        self.win.after(50, self.poll)

    # ---- events ----------------------------------------------------------------

    def on_enter(self, _event):
        self.on_send()
        return "break"

    def on_model_change(self):
        want = self.model_entry.get().strip()
        if not want or want == self.model:
            self.model_entry.delete(0, "end")
            self.model_entry.insert(0, self.model)
            return
        if self.busy:
            self.model_entry.delete(0, "end")
            self.model_entry.insert(0, self.model)
            self.append("(wait for the current reply to finish before switching "
                        "model)\n", "note")
            return
        self.model = want
        chat._cache_append("--- model -> %s ---" % want)
        self.refresh_status()
        self.append("(model is now %s -- if it is not installed the next reply "
                    "will say so, and nothing is lost. The first reply after a "
                    "switch may pause while Ollama loads it.)\n\n" % want, "note")

    def on_save(self):
        try:
            path = chat.save_transcript(self.messages)
            self.append("(saved: %s)\n\n" % path, "note")
        except OSError as e:
            self.append("(could not save: %s)\n\n" % e, "note")

    def on_send(self):
        if self.busy:
            return
        user = self.entry.get("1.0", "end").strip()
        if not user:
            return
        self.entry.delete("1.0", "end")

        # REFLEX first, same order as the terminal client: crisis, then
        # lifecycle, then commands, then the model.
        if chat.crisis_hit(user):
            self.append("you > %s\n" % user, "you")
            self.append(chat._CRISIS_REPLY + "\n\n", "crisis")
            return
        wrap = chat._wrap_match(user)
        if wrap is not None:
            chat._cache_resolve(keep=(wrap == "keep"))
            self.win.destroy()
            return
        self.append("you > %s\n" % user, "you")
        if user == "/exit":
            self.on_close()
            return
        if user == "/reset":
            self.messages = [{"role": "system", "content": chat.load_persona()}]
            chat._cache_append("--- context reset ---")
            self.append("(context cleared)\n\n", "note")
            return
        if user == "/save":
            self.on_save()
            return
        if user == "/help":
            chat.print_help()
            return
        if user.startswith("/model"):
            self.append("(use the Model box at the top right)\n\n", "note")
            return
        # A launch flag typed into the chat would otherwise sail to the model as
        # a prompt, which answers nothing and costs a turn.
        first = user.split(None, 1)[0]
        if "\n" not in user and first in chat._LAUNCH_FLAGS:
            self.append("(%s is a launch flag, not a chat command. Nothing was "
                        "sent.)\n\n" % first, "note")
            return
        if user.startswith("/"):
            self.append("(no command needed -- just say what you want. Commands: "
                        "/help, /reset, /save, /exit.)\n\n", "note")
            return
        self.run_turn(user)

    # ---- model turns (worker thread) -------------------------------------------

    def run_turn(self, user):
        self.busy = True
        self.send_btn.config(state="disabled")
        self.star.set_busy(True)

        def work():
            chat._cache_append("you > %s" % user)
            self.messages.append({"role": "user", "content": user})
            print("ai  > ", end="", flush=True)
            try:
                chat.turn(self.model, self.messages)
                if self.messages and self.messages[-1]["role"] == "assistant":
                    chat._cache_append("ai > %s"
                                       % self.messages[-1].get("content", ""))
                print()
            except Exception as e:
                # Same friendly text the terminal prints, and the same rollback:
                # a failed exchange is dropped so a retry starts clean.
                print("\n[error] " + chat._friendly_error(e) + "\n")
                chat._rollback(self.messages)
            finally:
                UI_QUEUE.put(("enable",))
        threading.Thread(target=work, daemon=True).start()

    # ---- lifecycle -------------------------------------------------------------

    def on_close(self):
        """The wrap gate, made visible. Yes = keep the transcript, No = delete it
        (the default privacy stance), Cancel = keep chatting."""
        ans = messagebox.askyesnocancel(
            "Finish this chat?",
            "Keep this chat's log?\n\nYes  = keep it as a chat_<stamp>.txt file\n"
            "No   = delete it (nothing kept -- the default)\nCancel = keep chatting")
        if ans is None:
            return
        chat._cache_resolve(keep=bool(ans))
        self.win.destroy()


def main():
    ap = argparse.ArgumentParser(
        description="your private local AI -- the window (chat only)")
    ap.add_argument("--model", default=chat.DEFAULT_MODEL, help="Ollama model name")
    ap.add_argument("--theme", choices=list(ui.THEMES), default=ui.DEFAULT_THEME,
                    help="launch palette: cream (the default), dark, or midnight. "
                         "The Theme dropdown in the footer switches live.")
    ap.add_argument("--selftest", action="store_true",
                    help="build the window, verify wiring, close, exit 0")
    args = ap.parse_args()

    if not os.path.isdir(chat.SESSION_DIR):
        sys.exit("[refused] session directory does not exist: %s" % chat.SESSION_DIR)

    sys.stdout = QueueWriter()
    sys.stderr = QueueWriter()

    win = tk.Tk()
    app = App(win, args.model, theme=args.theme)

    if args.selftest:
        tracked = app.ui.tracked_count()
        ok = (isinstance(sys.stdout, QueueWriter)
              and app.messages[0]["role"] == "system"
              and app.messages[0]["content"].strip() != ""
              and app.model_entry.get() == args.model
              and hasattr(app, "star") and app.star.winfo_exists()
              and app.theme_var.get() == args.theme
              and tracked >= 12
              # This edition must not have grown a file-tool surface. If a
              # future edit wires one in, the absence check fails here rather
              # than shipping a control with a gate behind it that does not
              # exist in this harness.
              and not hasattr(chat, "HANDS")
              and not hasattr(chat, "CONSENT_FUNC"))
        # Live-switch smoke: walk EVERY theme and land back on the launch one.
        for t_name in list(ui.THEMES) + [args.theme]:
            app.apply_theme(t_name)
        ok = (ok and app.ui.pal is ui.PALETTES[args.theme]
              and app.ui.theme == args.theme
              and app.star.pal is thinking_star.PALETTES[args.theme]
              and app.ui.tracked_count() == tracked)
        win.after(200, win.destroy)
        win.mainloop()
        sys.__stdout__.write("WINDOW SELFTEST %s\n" % ("OK" if ok else "FAILED"))
        sys.exit(0 if ok else 1)

    win.mainloop()


if __name__ == "__main__":
    main()
