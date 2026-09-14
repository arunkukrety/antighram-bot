# agy-server

A small FastAPI wrapper that exposes your local Antigravity CLI (`agy`) as an
HTTP API, so you can drive it from your phone (or curl, or anything) while
your laptop acts as the server.

## Why it's a job queue, not one blocking call

`agy -p "..."` can take anywhere from a few seconds to several minutes.
Blocking an HTTP request for that long is fragile on mobile networks, so:

1. `POST /jobs` starts the run in a background thread and returns a `job_id`
   immediately.
2. `GET /jobs/{job_id}` polls for the result.

## Why `pexpect` instead of `subprocess.run`

`agy -p` has a documented bug: when stdout isn't a real terminal (which is
always true for `subprocess`), it either hangs or silently returns nothing
(see antigravity-cli issues #76 and #318). `pexpect` allocates a
pseudo-terminal so `agy` behaves like it's talking to an interactive shell.

This works on **Linux and macOS**. It does not work the same way on native
Windows. If your laptop is Windows, run this whole server inside **WSL**
(agy runs fine there too), or swap `pexpect` for `pywinpty` — ping me if you
want that version.

## Setup

```bash
cd agy-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Make sure agy itself works first, outside this wrapper:
agy --version
agy models

# Pick a random shared secret -- this is what your phone will send as
# X-API-Key on every request.
export AGY_SERVER_API_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
echo "Save this key: $AGY_SERVER_API_KEY"

# Optional: where agy runs by default, if a request doesn't specify one.
export AGY_DEFAULT_WORKSPACE=~/agy-server-workspace

python3 server.py
# -> listening on 0.0.0.0:8787
```

## Using it

Start a job:

```bash
curl -s -X POST http://localhost:8787/jobs \
  -H "X-API-Key: $AGY_SERVER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "prompt": "List all TODOs in this codebase",
        "model": "Gemini 3.5 Flash (High)",
        "workspace": "/home/you/some-project"
      }'
# -> {"job_id": "...", "status": "queued", ...}
```

Poll it:

```bash
curl -s http://localhost:8787/jobs/<job_id> -H "X-API-Key: $AGY_SERVER_API_KEY"
```

List available models (from `agy models`):

```bash
curl -s http://localhost:8787/models -H "X-API-Key: $AGY_SERVER_API_KEY"
```

See what agy changed, if the workspace is a git repo:

```bash
curl -s http://localhost:8787/jobs/<job_id>/diff -H "X-API-Key: $AGY_SERVER_API_KEY"
```

Continue the same conversation across requests (so follow-up prompts have
context):

```bash
curl -s -X POST http://localhost:8787/jobs \
  -H "X-API-Key: $AGY_SERVER_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt": "Now add tests for that", "continue_last": true}'
```

or pin to a specific `--conversation <id>` returned in a previous job's
`raw_json`.

## Getting to your phone

Don't port-forward this straight to the open internet — `agy` can write
files and run shell commands on your machine, and the `X-API-Key` header is
a shared secret, not real auth (no rate limiting, no TLS by default). Two
reasonable options:

- **Tailscale** (or another WireGuard-based mesh VPN): install it on your
  laptop and phone, then hit `http://<laptop-tailscale-ip>:8787` from the
  phone. This is the option I'd start with — no exposed port at all.
- **Cloudflare Tunnel / ngrok** with the API key still required: gives you
  a public HTTPS URL without opening a port, but the URL is internet-facing,
  so keep the API key secret and consider IP allowlisting if the tool
  supports it.

Either way, run `uvicorn` behind HTTPS if you go past your own LAN — plain
`X-API-Key` over HTTP means anyone on the network path can read it.

## About `--dangerously-skip-permissions`

By default `agy` pauses to ask permission before writing files or running
shell commands, and in `-p` mode without this flag it just won't perform
those actions non-interactively. The server refuses to pass this flag
unless you explicitly set:

```bash
export AGY_ALLOW_SKIP_PERMISSIONS=true
```

...and also pass `"skip_permissions": true` in the individual request. Only
turn this on for workspaces you don't mind an agent modifying autonomously,
ideally under version control so you can always `git diff` / `git checkout`
your way out.

## Telegram bot with live permission approval (`telegram_agy_bot.py`)

This is a separate, standalone script from `server.py` -- it doesn't need
the FastAPI server running at all. It runs `agy` in full **interactive**
mode (not `-p`) inside a pty, uses `pyte` to render its TUI output into
plain text, and bridges it to a Telegram chat:

- Every message you send in the chat is forwarded as a keystroke into agy.
- When agy shows a permission prompt ("Do you want to proceed?" with
  numbered options), the bot parses it and sends you inline buttons.
  Tapping one sends that option number back into agy.
- Anything else agy prints, once it's been quiet for ~1.5s, gets sent to
  you as a message. This also covers first-run prompts like the
  "trust this folder?" question and the color-theme picker -- you just
  reply normally, no special-casing needed for those.

### Setup

```bash
pip install -r requirements.txt   # now includes python-telegram-bot + pyte

# Create a bot with @BotFather on Telegram, copy the token it gives you.
export TELEGRAM_BOT_TOKEN="123456:ABC-your-token"

# Find your own numeric Telegram chat id (message @userinfobot, or check
# the bot logs on first message) and lock the bot down to just you:
export TELEGRAM_ALLOWED_CHAT_IDS="111111111"

export AGY_DEFAULT_WORKSPACE="$HOME/agy-server-workspace"

python3 telegram_agy_bot.py
```

No inbound port needs opening -- Telegram bots use long polling *outbound*
from your laptop to Telegram's servers, so this sidesteps the whole
"how do I expose this to my phone safely" problem from before.

### Usage

- `/start [workspace] [model]` -- launch an agy session, e.g.
  `/start /home/you/some-project "Claude Opus 4.6 (Thinking)"`
- Just type normally -- it goes straight into agy as if you'd typed it in
  the terminal.
- `/models` -- list available models (`agy models`).
- `/debug` -- dump the raw current terminal screen agy is showing. Use this
  if a permission prompt didn't trigger buttons, to see the exact text so
  you can adjust `PERMISSION_RE` / `OPTION_LINE_RE` in the script.
- `/stop` -- end the session.

### Honest limitations

- **Screen-scraping, not a documented API.** The bot recognizes agy's
  current prompt wording ("Requesting permission for:", "Do you want to
  proceed?", numbered options). If a future `agy` version changes that
  wording or menu layout, matching breaks silently -- `/debug` is there so
  you can see what changed and fix the regex.
- **Only one active session per chat.** Concurrent approvals across
  multiple simultaneous jobs aren't handled -- this assumes one
  conversation at a time, matching how the interactive TUI itself works.
- **`QUIET_SECONDS` (1.5s) is a guess** at how long to wait before deciding
  agy has finished a turn. If replies arrive split into multiple Telegram
  messages, or feel delayed, tune that constant.
- **Restart = lost session state.** If the bot process restarts, the pty
  and the running `agy` conversation are gone; you'll need `/start` again
  (agy's own `--conversation <id>` / `--continue` can resume the underlying
  conversation content once you're back in interactive mode, but this
  script doesn't wire that up yet).

## Roadmap notes (for the "full phone agent" version)

- **Diffs**: already wired up via `/jobs/{id}/diff` (`git diff HEAD`). Good
  enough as long as workspaces are git repos.
- **Screenshots**: `agy` itself doesn't take screenshots in headless mode —
  that's a GUI/Antigravity-2.0-app feature, not something the CLI exposes
  over `-p`. To get screenshots from a phone client, the cleanest path is a
  companion step: after a job finishes, if it started a local dev server,
  run a small Playwright script against `http://127.0.0.1:<port>` and save
  a PNG the phone can fetch via a new `/jobs/{id}/screenshot` endpoint. I
  didn't build this yet since it depends on what each project actually
  serves — happy to add it once you tell me the shape (e.g. "always
  screenshot localhost:5000 if the job started a Flask app").
- **Auth**: swap the shared-secret header for per-device tokens once you
  have more than one phone/client talking to it.
- **Persistence**: `JOBS` is in-memory and resets on restart — move to
  SQLite if you want job history to survive a reboot.
