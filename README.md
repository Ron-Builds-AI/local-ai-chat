# Your Private Local AI (free, chat-only)

A private AI in two short Python files — the chat client (`chat.py`) and the shared
plumbing it runs on (`myai_core.py`). It runs on your machine, talks only to your own
[Ollama](https://ollama.com), and has no network door: it opens no port and listens
for nothing, so it can only be used from the machine itself. This client never sends
your prompts anywhere but your own loopback Ollama.

No account. No API key. No telemetry. No cloud. Read the source — two short files,
written to be read.

## What you need

1. **Python 3.8+** — [python.org/downloads](https://www.python.org/downloads/)
2. **Ollama** — [ollama.com/download](https://ollama.com/download), then pull a model:

```bash
ollama pull llama3.2
```

Any local model you have pulled works (`ollama list` shows them). Bigger models
generally give better answers and run slower; `llama3.2` is a small, fast starting
point.

## Run it

```bash
python chat.py
```

One-shot mode (useful for scripts and testing):

```bash
python chat.py --once "hello"
```

## In the chat

| command | what it does |
|---|---|
| `/help` | show the commands |
| `/model NAME` | switch model (e.g. `/model llama3.2`) |
| `/reset` | clear the conversation |
| `/save` | write the conversation to a text file next to `chat.py` |
| `/exit` | quit |

## Make it yours

**persona.txt** is the system prompt — plain text, no code. Edit it to change how your
AI talks and works. The one that ships is a "direct, honest teammate" baseline: it
*tells* the model to lead with the answer, push back when a plan looks off, and say
"I'm not sure" instead of guessing. How closely the model follows those instructions
depends on which model you pick — a system prompt is guidance, not a guarantee.

## Honest limits (read this part)

- **Chat-only.** The AI has no tools. It cannot run code, read your files, browse the
  web, or change anything on disk. What it says is all it can do.
- **Loopback-locked — with one exception you control.** This client refuses to talk to
  any host but your own machine (`127.0.0.1`), and it ignores proxy environment
  variables so a loopback request truly stays local. But it can't control what your
  Ollama does once it has the prompt: Ollama's **`-cloud` models** (names ending in
  `-cloud`) run on Ollama's servers, so with those, your prompts **do** leave the
  machine. Stick to local models and everything stays on your box.
- **`/save` writes a plain text file** next to `chat.py`. If you keep this folder inside
  a cloud-synced location (OneDrive, Dropbox, iCloud), your saved transcripts sync too.
  Keep it out of synced folders if that matters to you.
- **A local model is still a language model.** It can be wrong, confidently. The persona
  tells it to say "I'm not sure" — but verify anything that matters.

## Why local?

Because your first AI shouldn't require a subscription, an account, or sending your
thoughts to someone else's computer. This is the free edition of a line of local AI
tools built by [VetTech Homefront](https://vettechhomefront.com), a veteran-owned
business in Ohio. A paid edition that can *do* things — read and organize files in one
consent-gated folder, with a typed YES before anything changes on disk — is in the
works. This free one is complete as it is, and stays free.
