#!/usr/bin/env python3
"""
chat.py - your own private, local AI. Two short files, no server, no cloud.

Runs on your machine and talks ONLY to your own Ollama at 127.0.0.1:11434. It is not
a server: it opens no port and listens for nothing, so it can only be used from the
machine itself. The only network hop it makes is the loopback call to your own Ollama.

This is the FREE, chat-only edition: the model can talk, plan, and write code in the
chat, but it has NO tools. It cannot run code, read your files, or change anything on
disk. What it says is all it can do. The plumbing it shares with the paid edition --
the streaming transport, the session-cache lifecycle, the paste-safe input reader --
lives in myai_core.py next to this file, the same file byte for byte.

Usage:
  python chat.py                       interactive chat
  python chat.py --once "hello"        one prompt, print the reply, exit
  python chat.py --model llama3.2      pick any model you have pulled in Ollama

In chat:  /help   /model NAME   /reset   /save   /exit
Done with a conversation? Type  wrap  -> the chat is over and this session's cache
files are DELETED (privacy by default: conversations do not accumulate on disk).
Type  wrap logs  (both words in the line) -> the chat is over and this one session's
transcript is KEPT as a chat_<stamp>.txt file next to chat.py, plus a small
chat_<stamp>.turns.jsonl sidecar of per-turn metadata (model name, token and
character counts -- never message content). That goodbye sentence is the ONLY
retention switch: no settings screen, no hidden flags. Quitting any other way
(/exit, Ctrl-C, a crash) leaves the cache files; the next start cleans such
leftovers up.
"""
import argparse
import datetime
import os
import re
import sys
import urllib.error
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
# The shared plumbing (transport, session lifecycle, the wrap verb's grammar,
# paste/BOM-safe input). myai_core.py ships NEXT TO this file and is the same
# file, byte for byte, the paid edition runs on -- read it too, it is short.
# The explicit path insert keeps `import myai_core` working however this file
# is loaded (script, importlib, embedded).
sys.path.insert(0, HERE)
import myai_core  # noqa: E402

PERSONA_PATH = os.path.join(HERE, "persona.txt")

# Pick any model you have pulled ("ollama list" shows them). Override per-run with
# --model, or set the MY_AI_MODEL environment variable to change the default.
DEFAULT_MODEL = os.environ.get("MY_AI_MODEL", "llama3.2")

# --- the one place prompts are allowed to go -------------------------------------
# MY_AI_URL is asserted to be loopback, always. If it were read from the environment
# unchecked, anything that set it could silently redirect every prompt you type to an
# arbitrary host while this file still claimed to be loopback-only. The resolved value
# is printed at startup so it is never a surprise.
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def resolve_ollama_url():
    raw = os.environ.get("MY_AI_URL", "http://127.0.0.1:11434").rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        sys.exit("[refused] MY_AI_URL must be http/https, got: %r" % raw)
    if (parsed.hostname or "") not in _ALLOWED_HOSTS:
        sys.exit(
            "[refused] MY_AI_URL points off this machine: %r\n"
            "This client only ever talks to your own loopback Ollama. Unset MY_AI_URL."
            % raw)
    return raw


OLLAMA = resolve_ollama_url()

# Every model request goes through myai_core's proxy-free opener: urllib's default
# opener honors HTTP_PROXY / HTTPS_PROXY from the environment, which would route
# even a 127.0.0.1 request out through a proxy host -- quietly sending your prompts
# off the machine while the banner still says loopback-only. The core disables that,
# so a loopback request truly stays local.

# --- crisis reflex (fires before the model, not disclaimer-able) -------------------
# HAND-KEPT MIRROR of dashboard\crisis_guard.py (the canonical single source on the
# development machine; this shipped file is one-file by design and cannot import it).
# Same rule as the Netlify crisis.mjs mirror noted there: any change to the canonical
# phrase list or reply text MUST be copied here in the same change. General-audience
# wording on purpose: this is the public free edition. Detection is deliberately
# UNAMBIGUOUS phrases only -- hyperbole is left to the model layer so the crisis line
# never cries wolf. A person in distress gets this line BEFORE any model call.
_CRISIS_REPLY = (
    "Call or text 988 now. The 988 Suicide and Crisis Lifeline is free, confidential, and "
    "open 24/7, and someone is there for you right now. If you are a Veteran, service member, "
    "National Guard or Reserve member, or someone supporting one, call 988 and press 1, or "
    "text 838255, to reach the Veterans Crisis Line. If you are in immediate danger, call 911.")

_CRISIS_PHRASES = (
    "suicide", "suicidal", "kill myself", "killing myself", "want to die", "wanna die",
    "end my life", "ending my life", "self harm", "hurt myself", "harming myself",
    "dont want to live", "no reason to live",
    "dont want to be alive", "no reason to be alive", "nothing to live for",
    "better off dead", "better off without me", "wish i was dead", "wish i were dead",
    "wish i wasnt here", "take my own life", "taking my own life", "want to overdose",
    "end it all", "cant go on",
    # ---- 2026-08-05 gap hunt (canonical: dashboard\crisis_guard.py) ---------------------
    # Mirrored in the same change. Verify with: python dashboard\probe_crisis_mirrors.py
    "sucide", "suicidle", "suicial", "sucidal", "kil myself",
    "kill my self", "killing my self", "hurt my self", "harm my self",
    "cutting myself", "cutting my self", "burn myself", "burning myself",
    "starve myself", "starving myself",
    "pills on purpose", "overdosed on purpose",
    "someone would kill me", "if i was dead", "if i were dead",
    "want to just die", "want to honestly die", "want to really die",
    "just want to die",
)


def _crisis_normalize(text):
    """Lowercase; fold apostrophes out ("don't" -> "dont"); fold expanded contractions to the
    same form ("do not" -> "dont"); dashes to spaces; collapse whitespace. Identical to the
    canonical _normalize so the surfaces can never drift.

    The expanded-contraction fold was added 2026-08-05 after a measured live miss: every
    phrase is stored apostrophe-stripped ("dont want to be alive"), so "I do not want to be
    alive anymore" matched nothing. Word boundaries are mandatory - without them "have not"
    would eat "have nothing" and BREAK an existing match."""
    t = (str(text).lower()
         .replace("’", "").replace("‘", "").replace("'", "")
         .replace("-", " "))
    t = re.sub(r"\b(do|ca|wo|is|did|was|are|have|could|should|would|ai)n\s+t\b", r"\1nt", t)
    t = re.sub(r"\bdo not\b", "dont", t)
    t = re.sub(r"\bcan ?not\b", "cant", t)
    return " ".join(t.split())


def crisis_hit(text):
    """True if the text contains an unambiguous distress phrase."""
    t = _crisis_normalize(text)
    return any(p in t for p in _CRISIS_PHRASES)


# --- the session cache + the "wrap" lifecycle verb ---------------------------------
# A personal AI deletes its chat cache when the chat RESOLVES, not before. While a
# chat runs, every exchange is appended to ONE plain-text session file next to this
# script, so the privacy promise is about a real file, testably deleted -- and a
# crash leaves a leftover the next start cleans up. Resolving is the typed verb
# `wrap` (first word of the line, plain string match -- the model is never asked):
# `wrap` deletes the cache; `wrap` with `logs` in the same line keeps it as
# chat_<stamp>.txt. That grammar is the ONLY retention switch: no hidden flags.
_SESSION_STAMP = myai_core.now_stamp()
# 2026-07-30: cache directory made settable, matching the paid edition. This edition
# has no hands, so it cannot READ a sensitive file and cannot hit the cross-volume leak
# that gate in the paid client exists to refuse -- but a person can still PASTE
# sensitive text into a chat, and the transcript of that has to be able to land
# somewhere other than the default drive. Env var only here; the free tier stays a
# one-knob product. An EMPTY env var is treated as unset: os.path.abspath("") resolves
# to the current working directory, so `set MY_AI_SESSION_DIR=` would have silently
# parked the transcript wherever the shell happened to be standing (audit finding on
# the paid edition, 2026-07-30; same fix here).
SESSION_DIR = os.path.abspath(os.environ.get("MY_AI_SESSION_DIR", "").strip() or HERE)
SESSION_CACHE, SESSION_TURNLOG = myai_core.session_paths(SESSION_DIR, _SESSION_STAMP)


# The bodies of the session-lifecycle helpers live in myai_core (the vendored,
# byte-identical shared core). These wrappers read the module globals at call
# time and keep the names the rest of this file uses.
def _cache_append(text):
    """Append one block to the live session cache; myai_core.cache_append."""
    myai_core.cache_append(SESSION_CACHE, text)


def _cache_resolve(keep):
    """The wrap action on this session's live files; myai_core.cache_resolve."""
    myai_core.cache_resolve(SESSION_DIR, _SESSION_STAMP, SESSION_CACHE,
                            SESSION_TURNLOG, keep)


def _orphan_sweep():
    """Sweep leftover .inprogress files, sparing this session's own two;
    myai_core.orphan_sweep (age-gated so a second live window keeps its files)."""
    myai_core.orphan_sweep(SESSION_DIR, (SESSION_CACHE, SESSION_TURNLOG))


# The wrap verb's grammar (typed human verb, never model-inferred) is
# myai_core.wrap_match -- one grammar, both editions.
_wrap_match = myai_core.wrap_match


def load_persona():
    """persona.txt is the system prompt. It is a plain text file: edit it, own it.

    Read as utf-8-sig so a Notepad-saved BOM is stripped instead of riding along at the
    head of the system prompt. If the file is missing OR saved in an encoding that is not
    UTF-8 (ANSI/cp1252 with curly quotes, UTF-16, ...), fall back to a built-in default
    rather than crashing at startup -- the README tells users to edit this file, so a bad
    save must be survivable."""
    try:
        return open(PERSONA_PATH, encoding="utf-8-sig").read().strip()
    except OSError:
        pass
    except UnicodeDecodeError:
        print("[warn] persona.txt is not valid UTF-8 (save it as UTF-8); using the built-in "
              "persona for now.", file=sys.stderr)
    return ("You are the user's private local AI. Be direct, accurate, and useful. "
            "Lead with the answer. If you are not sure, say so instead of guessing.")


def stream_chat(model, messages):
    """POST to Ollama /api/chat with stream=true; myai_core.stream_chat does the
    work. Its docstring carries the story: it raises on transport error OR on an
    in-stream Ollama error line (a runner crash or OOM after the 200) so the
    caller's except-path can show the real reason and roll back; a thinking
    model's private channel rides the done message under "_thinking" and stream
    metadata under "_meta". This edition sends no tools and no options -- chat
    only, Ollama's own defaults."""
    return myai_core.stream_chat(OLLAMA, model, messages)


def turn(model, messages):
    """One user turn: stream the reply to the screen, append it to history."""
    assistant = None
    for kind, payload in stream_chat(model, messages):
        if kind == "text":
            sys.stdout.write(payload)
            sys.stdout.flush()
        else:
            assistant = payload
    # The thinking channel never enters history and is never echoed as an answer;
    # it exists so a blank turn can be reported honestly instead of shown as silence.
    think = assistant.pop("_thinking", "")
    meta = assistant.pop("_meta", {})
    messages.append(assistant)
    # One metadata line per turn to the .turns sidecar -- model name, counts,
    # lengths, done_reason; NEVER message content. It obeys the same wrap
    # lifecycle as the prose cache, and it is what turns the next "weird turn"
    # from a many-trial reproduction into a one-line read.
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "model": model,
           "content_chars": len(assistant.get("content", "")),
           "thinking_chars": len(think)}
    rec.update(meta)
    myai_core.turnlog_append(SESSION_TURNLOG, rec)
    print()
    if not assistant.get("content", "").strip():
        if think.strip():
            shown = think.strip()
            print("(the model wrote no answer this turn -- all %d characters of its work "
                  "stayed in its private thinking channel. The thinking is shown below, "
                  "labeled: it is scratch work, NOT a vetted answer.)" % len(shown))
            if len(shown) > 800:
                shown = shown[:800] + " ...(thinking clipped)"
            for tline in shown.splitlines():
                print("  [thinking] %s" % tline)
            print("(ask again to get a real answer.)")
        else:
            print("(the model returned an empty reply this turn. Nothing was hidden by "
                  "this client; the model sent nothing. Ask again, or try another model.)")


def _friendly_error(exc):
    """Turn a request failure into a useful one-line diagnosis. An HTTP error (e.g. the
    model isn't pulled) carries Ollama's own JSON explanation in its body -- surface that
    instead of a generic 'is Ollama running?', which only fits a connection failure."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = exc.read().decode("utf-8", "replace").strip()
        except Exception:
            detail = ""
        return "Ollama returned HTTP %s%s" % (exc.code, (": " + detail) if detail else "")
    if isinstance(exc, urllib.error.URLError):
        return "could not reach Ollama at %s (%s). Is it running?  try:  ollama serve" % (OLLAMA, exc.reason)
    return "%s: %s" % (type(exc).__name__, exc)


def once(model, prompt):
    # REFLEX -- same gate as the interactive loop; --once is still a real entry point.
    if crisis_hit(prompt):
        print(_CRISIS_REPLY)
        return
    messages = [{"role": "system", "content": load_persona()},
                {"role": "user", "content": prompt}]
    try:
        turn(model, messages)
    except Exception as e:
        # A documented scripting mode must fail with a clean message and a nonzero exit,
        # not a raw traceback, when Ollama is down or the model isn't pulled.
        print("[error] " + _friendly_error(e), file=sys.stderr)
        sys.exit(1)
    finally:
        # --once has no `wrap` moment: the invocation IS the whole session and it
        # is over. Privacy by default, so the turn-log sidecar goes with it --
        # otherwise every scripted call would strand a .turns.inprogress.txt
        # next to chat.py until an interactive start swept it.
        try:
            os.remove(SESSION_TURNLOG)
        except OSError:
            pass


# The BOM/zero-width strip and the paste-capture both live in myai_core
# (LEAD_INVIS, read_message); the alias keeps the old name importable.
_LEAD_INVIS = myai_core.LEAD_INVIS

# The flags that actually exist on the launch command line. Only these get the
# "that's a launch flag" nudge; anything else starting with "-" (a Markdown "---"
# rule, "--anyway, ...") is a normal message and goes to the model.
_LAUNCH_FLAGS = {"--model", "--once", "--help", "-h"}


def _read_message():
    """Read one user message, paste-safe and BOM-safe; myai_core.read_message
    (a slash-command returns right away; a multi-line paste arrives as ONE
    message instead of fragmenting into many turns)."""
    return myai_core.read_message("you > ")


def save_transcript(messages):
    """Write the visible conversation (not the system prompt) to a text file HERE.
    This is a command YOU typed, not something the model can do: the model has no
    tools in this edition and cannot write files."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join(SESSION_DIR, "chat_%s.txt" % stamp)
    with open(path, "w", encoding="utf-8") as fh:
        for m in messages:
            if m["role"] == "system":
                continue
            fh.write("%s:\n%s\n\n" % (m["role"], m.get("content", "")))
    return path


def print_help():
    print()
    print("  /help          this help")
    print("  /model <name>  switch model, e.g.  /model llama3.2  (see: ollama list)")
    print("  /reset         clear the conversation and start fresh")
    print("  /save          write this conversation to a text file next to chat.py")
    print("  /exit          quit (leaves the session cache; next start cleans it up)")
    print()
    print("  Done for real? Type  wrap  -- the chat resolves and this session's cache")
    print("  files are DELETED. Type  wrap logs  -- resolves but KEEPS the transcript as")
    print("  chat_<stamp>.txt plus a .turns.jsonl sidecar of per-turn metadata (model")
    print("  name and counts, never message text). That sentence is the only retention switch.")
    print()
    print("  Everything else is just chat. The AI has NO tools in this edition:")
    print("  it cannot run code, read files, or change anything on disk.")
    print()


def interactive(model):
    persona = load_persona()
    messages = [{"role": "system", "content": persona}]
    _orphan_sweep()
    print("=== your private local AI ===  model: %s" % model)
    # Claim exactly what is enforced, nothing more: the check proves the HOST is
    # loopback. It does not prove what is listening there, and it is not a promise
    # that your machine as a whole is secure.
    print("talking to: %s   (this client refuses any host but loopback)" % OLLAMA)
    print("commands  : /help   /model NAME   /reset   /save   /exit")
    print("done?     : type  wrap  = finish + DELETE this session's cache   |   wrap logs  = finish + keep it\n")
    while True:
        try:
            user = _read_message()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        # REFLEX -- fires before anything else, including the model. A person in real
        # distress gets the crisis line immediately; this is not disclaimer-able and
        # not skippable by a persona or a model call. Mirror of dashboard\crisis_guard.py.
        if crisis_hit(user):
            print(_CRISIS_REPLY)
            print()
            continue
        # LIFECYCLE -- after the crisis reflex, before everything else. Deterministic
        # typed verb, never model-inferred (see _wrap_match for the exact grammar).
        _wrap = _wrap_match(user)
        if _wrap is not None:
            _cache_resolve(keep=(_wrap == "keep"))
            break
        # A launch flag typed into the chat ("--model llama3.2") would otherwise sail
        # straight to the model as a prompt, which answers nothing and costs a turn.
        # Only the real launch flags are intercepted; other "--" lines are normal chat.
        first_token = user.split(None, 1)[0]
        if "\n" not in user and first_token in _LAUNCH_FLAGS:
            rest = user.partition(" ")[2].strip()
            if first_token == "--model" and rest:
                print("(did you mean:  /model %s ?  --model only works on the launch "
                      "command line. Nothing was sent.)\n" % rest)
            else:
                print("(%s is a launch flag, not a chat command. Nothing was sent. "
                      "In chat, type /help.)\n" % first_token)
            continue
        if user == "/exit":
            break
        if user == "/help":
            print_help()
            continue
        if user == "/reset":
            messages = [{"role": "system", "content": persona}]
            _cache_append("--- context reset ---")
            print("(context cleared)\n")
            continue
        if user == "/save":
            try:
                path = save_transcript(messages)
                print("(saved: %s)\n" % path)
            except OSError as e:
                print("(could not save: %s)\n" % e)
            continue
        if user.startswith("/model"):
            parts = user.split(None, 1)
            if len(parts) == 2 and parts[1].strip():
                model = parts[1].strip()
                print("(model is now %s)\n" % model)
            else:
                print("(usage: /model <name> -- run 'ollama list' in another window to see them)\n")
            continue
        if user.startswith("/"):
            print("(unknown command. Type /help for the list, or just ask in plain English.)\n")
            continue

        _cache_append("you > %s" % user)
        messages.append({"role": "user", "content": user})
        print("ai  > ", end="", flush=True)
        try:
            turn(model, messages)
        except KeyboardInterrupt:
            # Ctrl+C during a streaming reply must not kill the app (and lose the whole
            # conversation). Note it, drop the interrupted exchange, keep chatting.
            print("\n(reply interrupted)\n")
            _rollback(messages)
            continue
        except Exception as e:
            print("\n[error] " + _friendly_error(e) + "\n")
            _rollback(messages)
            continue
        if messages and messages[-1]["role"] == "assistant":
            _cache_append("ai > %s" % messages[-1].get("content", ""))
        print()
    # Fell out of the loop some way other than `wrap` (wrap prints its own line and
    # deletes/keeps before breaking). Be explicit about what is left on disk.
    if os.path.exists(SESSION_CACHE):
        print("(session cache left at %s -- next start sweeps it. Type `wrap` to delete "
              "on the spot, `wrap logs` to keep.)" % os.path.basename(SESSION_CACHE))


def _rollback(messages):
    """Drop a failed/interrupted exchange so a retry starts clean: pop anything after the
    last user message, then that user message too."""
    while messages and messages[-1]["role"] != "user":
        messages.pop()
    if messages and messages[-1]["role"] == "user":
        messages.pop()


def main():
    # Force UTF-8 for the console streams. On Windows the default codepage crashes on
    # the first curly quote or emoji a model prints; replacing a glyph is cosmetic,
    # dying mid-reply is not.
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="your private local AI (chat-only)")
    ap.add_argument("--once", metavar="PROMPT", help="send one prompt and exit")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    args = ap.parse_args()

    if args.once is not None:
        once(args.model, args.once)
    else:
        interactive(args.model)


if __name__ == "__main__":
    main()
