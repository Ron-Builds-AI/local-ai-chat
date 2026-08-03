#!/usr/bin/env python3
"""myai_core.py - the shared plumbing both my_ai editions run on.

VENDORED BYTE-IDENTICALLY in the full client and in the free chat-only
edition (which ships standalone and therefore carries its own copy of this
file). The canonical copy lives with the full client; check_core_sync.py
fails the standing probe gate the moment the copies drift. History: the two
chat.py files duplicated this exact plumbing and every fix had to be
hand-ported between them -- the 2026-08-03 blank-turn fix was ported by hand
the same day this file was extracted to make that labor structurally
impossible.

Design rules for this file:
  - PURE functions over module state: callers own their paths and pass them in,
    so the two editions can never fall out of sync through a global.
  - Nothing edition-specific: no tools opinions, no persona, no crisis list
    (each edition keeps its own crisis surface deliberately), nothing that
    names one edition's features to the other.
  - Standard library only.
"""
import datetime
import json
import os
import re
import time
import urllib.request

try:
    import msvcrt  # Windows: lets us capture a multi-line paste as ONE message
except ImportError:
    msvcrt = None  # elsewhere: pastes still work, they just arrive line by line

import sys

# Leading BOM / zero-width chars, built from code points so no invisible byte
# lives in this source. Stripped off user input so a pasted "/cmd" stays a
# command (a doc-pasted BOM once made "/help" sail to the model as prose).
LEAD_INVIS = "".join(chr(c) for c in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060))

# A proxy-free opener, used for every model request. urllib's default opener
# honors HTTP_PROXY / HTTPS_PROXY from the environment, which would route even
# a 127.0.0.1 request out through a proxy host -- quietly sending prompts off
# the machine while the banner still says loopback-only. An explicit empty
# ProxyHandler disables that, so a loopback request truly stays local.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

ORPHAN_MIN_AGE_S = 30 * 60   # younger .inprogress files may belong to a LIVE chat


def wrap_match(user):
    """None = not a wrap. 'keep' / 'delete' otherwise. Deterministic: fires only
    when the FIRST word of the typed line is `wrap` (so 'how do I wrap a burrito'
    is chat, 'wrap it up' resolves); `logs`/`log` anywhere in the same line =
    keep. Slash lines ('/wrap') stay in the command lane and never fire the
    verb. The model is never asked: retention is a typed human verb, full stop."""
    if user.lstrip().startswith("/"):
        return None
    words = re.findall(r"[a-z]+", user.lower())
    if not words or words[0] != "wrap":
        return None
    return "keep" if ("logs" in words or "log" in words) else "delete"


def session_paths(directory, stamp):
    """The session's two files: the prose cache and the structured TURN-LOG
    sidecar (one JSON metadata line per model round; never message content).
    Same stamp, same lifecycle: both die on `wrap`, both survive as
    chat_<stamp>.* on `wrap logs`. The sidecar keeps .inprogress.txt in its
    name ON PURPOSE so the orphan sweep's one pattern covers it."""
    cache = os.path.join(directory, "chat_session_%s.inprogress.txt" % stamp)
    tlog = os.path.join(directory, "chat_session_%s.turns.inprogress.txt" % stamp)
    return cache, tlog


def cache_append(path, text):
    """Append one block to the live session cache. Open/close per write so no
    handle is held (the file must stay deletable at any moment). Never raises."""
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n\n")
    except OSError:
        pass


def turnlog_append(path, rec):
    """One JSON line of turn METADATA to the sidecar -- model, counts, lengths,
    verb names; never message content (even metadata obeys the wrap lifecycle,
    and content already lives in the prose cache). This is the file that turns
    the next 'weird turn' from a multi-trial reproduction into a one-line read.
    Never raises."""
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def cache_resolve(session_dir, stamp, cache, turnlog, keep):
    """The wrap action. keep=False deletes the cache AND the turn-log sidecar;
    keep=True renames both to the chat_<stamp>.* shapes. Prints what happened."""
    if not os.path.exists(cache) and not os.path.exists(turnlog):
        print("(wrapped -- nothing was cached this session)")
        return
    try:
        if keep:
            kept = os.path.join(session_dir, "chat_%s.txt" % stamp)
            if os.path.exists(cache):
                os.replace(cache, kept)
            if os.path.exists(turnlog):
                os.replace(turnlog,
                           os.path.join(session_dir, "chat_%s.turns.jsonl" % stamp))
            print("(wrapped -- session log KEPT: %s, plus its .turns.jsonl sidecar)" % kept)
        else:
            for path in (cache, turnlog):
                if os.path.exists(path):
                    os.remove(path)
            print("(wrapped -- session cache deleted, nothing kept)")
    except OSError as e:
        print("(wrap could not finish: %s -- the cache file is %s)" % (e, cache))


def orphan_sweep(session_dir, live_paths, min_age_s=ORPHAN_MIN_AGE_S):
    """Delete .inprogress session files a crashed/quit session left behind.
    Age-gated so a second chat window running RIGHT NOW keeps its live files.
    Says what it did."""
    now = time.time()
    for path in sorted(os.listdir(session_dir)):
        if not (path.startswith("chat_session_") and path.endswith(".inprogress.txt")):
            continue
        full = os.path.join(session_dir, path)
        if full in live_paths:
            continue
        try:
            if now - os.path.getmtime(full) > min_age_s:
                os.remove(full)
                print("(cleaned up an unresolved session cache from a previous run: %s)" % path)
            else:
                print("(note: %s looks like ANOTHER live session's cache; left alone)" % path)
        except OSError:
            pass


def read_message(prompt="you > "):
    """Read one user message. A slash-command on the first line returns right
    away. Otherwise grab any extra lines still buffered from a paste (Windows
    msvcrt), so a multi-line prompt arrives as ONE message instead of
    fragmenting into many turns. A leading BOM/zero-width char is stripped so a
    pasted command stays a command."""
    first = input(prompt).lstrip(LEAD_INVIS)
    if first.strip().startswith("/"):
        return first.strip()
    lines = [first]
    if msvcrt is not None:
        while msvcrt.kbhit():
            lines.append(sys.stdin.readline().rstrip("\n"))
    return "\n".join(lines).strip()


def stream_chat(base_url, model, messages, tools=None, options=None,
                opener=None, timeout=600):
    """POST to Ollama /api/chat with stream=true.

    Yields ("text", chunk) as content arrives, and returns the assembled
    assistant message (content + any tool_calls) via a final ("done", message)
    yield. Raises on transport error OR on an in-stream Ollama error line (a
    runner crash or OOM after the 200), so the caller can show the real reason
    instead of a silent blank turn.

    A THINKING model streams `message.thinking` before content, and a
    degenerate turn can leave the WHOLE reply there with content empty
    (measured live 2026-08-03: the thinking held the correct answer and the
    turn stopped without one content byte). The channel is collected and rides
    the done message under the private "_thinking" key -- the caller pops it
    before the message enters history, states the blank turn plainly, and never
    echoes thinking as an answer. Stream metadata (done_reason, token counts)
    rides under "_meta" the same way, for the turn log.
    """
    payload = {"model": model, "messages": messages, "stream": True}
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/api/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    content, thinking, tool_calls = [], [], []
    done_obj = {}
    with (opener or _OPENER).open(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line.decode("utf-8"))
            if obj.get("error"):
                raise RuntimeError(obj["error"])
            msg = obj.get("message") or {}
            chunk = msg.get("content") or ""
            if chunk:
                content.append(chunk)
                yield ("text", chunk)
            tchunk = msg.get("thinking") or ""
            if tchunk:
                thinking.append(tchunk)
            for tc in (msg.get("tool_calls") or []):
                tool_calls.append(tc)
            if obj.get("done"):
                done_obj = obj
                break
    out = {"role": "assistant", "content": "".join(content)}
    if tool_calls:
        out["tool_calls"] = tool_calls
    if thinking:
        out["_thinking"] = "".join(thinking)
    out["_meta"] = {k: done_obj.get(k) for k in
                    ("done_reason", "eval_count", "prompt_eval_count", "total_duration")}
    yield ("done", out)


def now_stamp():
    """The session stamp format both editions use for file names."""
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
