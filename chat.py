#!/usr/bin/env python3
"""
chat.py - your own private, local AI. One file, no server, no cloud.

Runs on your machine and talks ONLY to your own Ollama at 127.0.0.1:11434. It is not
a server: it opens no port and listens for nothing, so it can only be used from the
machine itself. The only network hop it makes is the loopback call to your own Ollama.

This is the FREE, chat-only edition: the model can talk, plan, and write code in the
chat, but it has NO tools. It cannot run code, read your files, or change anything on
disk. What it says is all it can do.

Usage:
  python chat.py                       interactive chat
  python chat.py --once "hello"        one prompt, print the reply, exit
  python chat.py --model llama3.2      pick any model you have pulled in Ollama

In chat:  /help   /model NAME   /reset   /save   /exit
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    import msvcrt  # Windows: lets us capture a multi-line paste as ONE message
except ImportError:
    msvcrt = None  # non-Windows: pastes still work, they just arrive line by line

HERE = os.path.dirname(os.path.abspath(__file__))
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

# A proxy-free opener. urllib's default opener honors HTTP_PROXY / HTTPS_PROXY from the
# environment, which would route even a 127.0.0.1 request out through a proxy host --
# quietly sending your prompts off the machine while the banner still says loopback-only.
# An explicit empty ProxyHandler disables that, so a loopback request truly stays local.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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
    """POST to Ollama /api/chat with stream=true.

    Yields ("text", chunk) as content arrives, and returns the assembled assistant
    message via a final ("done", message) yield. Raises on transport error OR on an
    in-stream Ollama error line, so the caller's except-path can show it and roll back.
    """
    payload = {"model": model, "messages": messages, "stream": True}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA + "/api/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    content = []
    with _OPENER.open(req, timeout=600) as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line.decode("utf-8"))
            # Ollama can emit {"error": "..."} mid-stream after a 200 (a runner crash or
            # OOM). Without this, the loop would end with an empty reply and silently append
            # a blank assistant turn to history. Raise so the caller prints the real reason.
            if obj.get("error"):
                raise RuntimeError(obj["error"])
            msg = obj.get("message") or {}
            chunk = msg.get("content") or ""
            if chunk:
                content.append(chunk)
                yield ("text", chunk)
            if obj.get("done"):
                break
    yield ("done", {"role": "assistant", "content": "".join(content)})


def turn(model, messages):
    """One user turn: stream the reply to the screen, append it to history."""
    assistant = None
    for kind, payload in stream_chat(model, messages):
        if kind == "text":
            sys.stdout.write(payload)
            sys.stdout.flush()
        else:
            assistant = payload
    messages.append(assistant)
    print()


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
    messages = [{"role": "system", "content": load_persona()},
                {"role": "user", "content": prompt}]
    try:
        turn(model, messages)
    except Exception as e:
        # A documented scripting mode must fail with a clean message and a nonzero exit,
        # not a raw traceback, when Ollama is down or the model isn't pulled.
        print("[error] " + _friendly_error(e), file=sys.stderr)
        sys.exit(1)


# Leading BOM / zero-width chars, built from code points so no invisible byte lives
# in this source. Stripped off user input so a pasted "/cmd" stays a command.
_LEAD_INVIS = "".join(chr(c) for c in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060))

# The flags that actually exist on the launch command line. Only these get the
# "that's a launch flag" nudge; anything else starting with "-" (a Markdown "---"
# rule, "--anyway, ...") is a normal message and goes to the model.
_LAUNCH_FLAGS = {"--model", "--once", "--help", "-h"}


def _read_message():
    """Read one user message. A slash-command on the first line returns right away.
    Otherwise grab any extra lines still buffered from a paste (Windows msvcrt), so a
    multi-line prompt arrives as ONE message instead of fragmenting into many turns."""
    first = input("you > ").lstrip(_LEAD_INVIS)
    if first.strip().startswith("/"):
        return first.strip()
    lines = [first]
    if msvcrt is not None:
        while msvcrt.kbhit():
            lines.append(sys.stdin.readline().rstrip("\n"))
    return "\n".join(lines).strip()


def save_transcript(messages):
    """Write the visible conversation (not the system prompt) to a text file HERE.
    This is a command YOU typed, not something the model can do: the model has no
    tools in this edition and cannot write files."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join(HERE, "chat_%s.txt" % stamp)
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
    print("  /exit          quit")
    print()
    print("  Everything else is just chat. The AI has NO tools in this edition:")
    print("  it cannot run code, read files, or change anything on disk.")
    print()


def interactive(model):
    persona = load_persona()
    messages = [{"role": "system", "content": persona}]
    print("=== your private local AI ===  model: %s" % model)
    # Claim exactly what is enforced, nothing more: the check proves the HOST is
    # loopback. It does not prove what is listening there, and it is not a promise
    # that your machine as a whole is secure.
    print("talking to: %s   (this client refuses any host but loopback)" % OLLAMA)
    print("commands  : /help   /model NAME   /reset   /save   /exit\n")
    while True:
        try:
            user = _read_message()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
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
        print()


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
