<p align="center">
  <img src="https://antigrham.vercel.app/assets/telegram-antigravity-logo-D1hdGmSE.svg" alt="Antighram Bot logo" width="160">
</p>

<h1 align="center">Antighram Bot</h1>

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-v21+-blue?logo=telegram)](https://core.telegram.org/bots/api)
[![Antigravity CLI](https://img.shields.io/badge/Antigravity-CLI%20Compatible-green)](https://github.com/google-deepmind)

A powerful, feature-rich Telegram bridge and remote-control interface for **Google DeepMind's Antigravity CLI (`agy`)**. 

Control your local AI coding agent directly from your phone or any device with Telegram. Run coding prompts, browse and switch project workspaces, approve interactive terminal permissions with one tap, track AI model quotas with live progress bars, execute shell commands, and receive generated image artifacts—all without opening ports or configuring network port forwarding.

---

## Table of Contents

- [Why This Project Exists](#why-this-project-exists)
- [Key Features](#key-features)
  - [Dual Execution Modes](#dual-execution-modes)
  - [Rich Output & Media Rendering](#rich-output--media-rendering)
  - [Visual Directory Browser & Volume Mounts](#visual-directory-browser--volume-mounts)
  - [Workspace & Conversation Persistence](#workspace--conversation-persistence)
  - [Interactive Model Selection & Live Quotas](#interactive-model-selection--live-quotas)
  - [Remote Shell & System Power Controls](#remote-shell--system-power-controls)
  - [Security & Access Control](#security--access-control)
- [Project Architecture](#project-architecture)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Configuration Reference](#configuration-reference)
- [Running as a System Service (systemd)](#running-as-a-system-service-systemd)
- [Command Reference](#command-reference)
- [Troubleshooting & FAQ](#troubleshooting--faq)
- [Contributing](#contributing)
- [License](#license)

---

## Why This Project Exists

Running autonomous coding agents like Antigravity on your local machine or workstation provides access to full compute, local files, compilers, and test suites. However, leaving your workstation often means pausing your workflow.

Traditional approaches like web servers or SSH require public IP addresses, dynamic DNS, complex firewall routing, or VPN clients. 

**Antighram Bot** eliminates these hurdles:
- **Outbound Long Polling**: The bot connects *outward* to Telegram's HTTPS servers. It works seamlessly behind home NATs, mobile hotspots, firewalls, and university/corporate networks without exposing any local ports.
- **PTY Terminal Emulation**: Avoids known CLI subprocess hanging bugs by allocating pseudo-terminals — `pexpect` on Linux/macOS and native ConPTY (`pywinpty`) on Windows — ensuring `agy` behaves exactly as it would in an interactive terminal.
- **Mobile-First UX**: Complex terminal flows—such as permission approvals, model selections, workspace switching, and file browsing—are converted into interactive Telegram buttons and formatted messages.

---

## Key Features

### Dual Execution Modes

1. **Print / Streaming Mode (`/plain`) [Default]**
   - Runs `agy` via `--output-format stream-json`.
   - **Live Progress Updates**: Provides real-time status messages showing exactly what tool `agy` is running:
     - ⚡ `Running: git status`
     - 📖 `Reading: config.py`
     - ✏️ `Editing: main.py`
     - 🔍 `Searching: query`
   - **Streaming Quote Preview**: Displays a live, collapsible blockquote preview of the streamed response text as it is generated.
   - **Rate-Limited Edits**: Throttles Telegram message updates to 1.0-second intervals to avoid Telegram API rate limits.
   - **Clean Teardown**: Automatically cleans up temporary status messages when the final response is delivered.

2. **Interactive PTY Mode (`/interactive`)**
   - Runs `agy` in full interactive mode inside an emulated pseudo-terminal (`pexpect` + `pyte` on POSIX, ConPTY via `pywinpty` + `pyte` on Windows).
   - **Smart Permission Interception**: Detects interactive prompts (e.g. `Do you want to proceed? Requesting permission for: ...`) and renders inline action buttons (`1. Allow`, `2. Reject`, etc.). Tapping an inline button instantly writes the response back to the PTY.
   - **Quiet-Screen Detection**: Intelligently buffers and forwards terminal output once the agent has been quiet for 1.5 seconds.
   - **Direct Input**: Regular text messages sent in chat are passed directly to the interactive session.

---

### Rich Output & Media Rendering

- **Telegram-Safe Markdown Parsing**: Converts LLM markdown (fenced code blocks with language labels, inline code, bold, italics, bullets, links) into sanitized Telegram HTML.
- **Plain Text Fallback**: If Telegram rejects malformed HTML markup, the bot automatically falls back to raw plain text delivery, ensuring you never miss a response.
- **Automatic Message Splitting**: Long responses exceeding Telegram's 4096-character limit are automatically chunked cleanly without breaking formatting.
- **Artifact & Image Auto-Detection**: Automatically detects generated or modified images (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`) in the workspace or conversation brain directory, deduplicates them by MD5 content hash, and sends them directly to your chat as photos or uncompressed documents.
- **Execution Footer**: Displays the active AI model and execution duration in seconds on every completed run.

---

### Visual Directory Browser & Volume Mounts

- **Interactive Directory Browser (`/browse [path]`)**:
  - Browse your workstation's filesystem using inline buttons.
  - Navigate directories: `⬆️ Up`, `⬇️ Prev` (with navigation history), or click subfolders in a 2-column layout.
  - One-tap actions: `🎯 Set Active`, `🚀 Launch agy`, and `⭐ Set Default`.
- **System Volume & External Storage Detection (`/volumes`)**:
  - Automatically queries `lsblk -J` and checks `/run/media/$USER/*`, `/media/*`, and `/mnt/*`.
  - Discovers external SSDs, USB flash drives, and secondary OS partitions (NTFS, FAT32, ext4).
  - One-click buttons to browse mounted volumes or mount & open unmounted partitions.

---

### Workspace & Conversation Persistence

- **Smart Workspace Resolution (`/cd <path>`)**:
  - Resolves absolute paths, user-expanded paths (`~/...`), paths relative to the current workspace, paths relative to `$HOME`, or fuzzy matches against recent directory names.
- **Persistent Defaults (`/default`, `/set_default <path>`)**:
  - View or permanently save your default workspace across restarts in `~/.antighram-config.json`.
- **Recent Workspaces (`/workspaces`)**:
  - View and switch between your most recently used workspaces with quick-select buttons.
- **Conversation Resumption (`/conversations` or `/history`)**:
  - Lists past conversations with prompt previews, timestamps, and workspace badges.
  - One-click buttons to resume previous conversations (`--continue` or `--conversation <id>`).
  - Automatically scans local Antigravity brain transcript logs (`~/.gemini/antigravity-ide/brain/`) to discover historical sessions on disk.
- **Context Reset (`/new` or `/newchat`)**:
  - Resets conversation context and starts a fresh thread immediately.

---

### Interactive Model Selection & Live Quotas

- **Hierarchical Model Selector (`/models`)**:
  - Dynamically queries `agy models` and groups models by family (Gemini, Claude, GPT, etc.).
  - Select reasoning effort (High, Medium, Low, Thinking, Standard) using inline buttons.
  - Or switch models directly via `/model <name>`.
- **Live Quota & Usage Monitor (`/usage`)**:
  - Queries `agy -p /usage --output-format stream-json`.
  - Renders ASCII visual progress bars (`[████████░░]`), remaining percentages, and color-coded status badges (🟢 🟡 🔴).
  - Shows exact reset countdown timers (e.g. `Refreshes in 3h 12m`).

---

### Remote Shell & System Power Controls

- **Desktop Shell Execution (`/sh <cmd>`)**:
  - Run terminal commands (e.g., `/sh git status`, `/sh docker ps`, `/sh npm test`) directly inside your active workspace.
  - Enforces a 60-second execution timeout and provides clean, monospaced output formatting.
- **Session Interruption (`/stop`)**:
  - Interrupts running `agy` processes or cancels the active session.
- **Remote Laptop Sleep (`/sleep`)**:
  - Suspends the host laptop (`systemctl suspend` on Linux, `SetSuspendState` on Windows) directly from Telegram when you step away, with clear safety and wake-up guidance.
- **Diagnostic Screen Dump (`/debug`)**:
  - Dumps the raw PTY screen buffer to verify what the terminal is displaying.
- **Native Telegram Command Menu**:
  - Registers all commands with Telegram via `set_my_commands` so typing `/` or clicking the `[/]` button auto-populates the command list.

---

### Security & Access Control

- **Strict Chat ID Whitelist**:
  - The `TELEGRAM_ALLOWED_CHAT_IDS` environment variable restricts access exclusively to authorized Telegram user IDs or group chats.
  - Unauthenticated requests are silently ignored, preventing unauthorized access to your machine.

---

## Project Architecture

The codebase is organized into modular packages:

```text
antighram-bot/
├── agy_bot/                         # Core bot package (server)
│   ├── agy/                         # agy process runners
│   │   ├── interactive_mode.py      # PTY spawner, pyte screen, quiet handler, permissions
│   │   ├── print_mode.py            # stream-json runner, live quote preview, rate-limiting
│   │   └── status.py                # Stream event to status text & tool indicator mapping
│   ├── handlers/                    # Telegram command & callback handlers (by feature)
│   │   ├── session_cmds.py          # /start /new /stop /sleep + text router
│   │   ├── workspace.py             # /workspaces /pwd /cd /default /set_default
│   │   ├── browse.py                # /browse /volumes + br:* callbacks
│   │   ├── shell.py                 # /sh desktop shell execution
│   │   ├── modes.py                 # /help /interactive /plain /debug + permission buttons
│   │   ├── models.py                # /model /models + model pickers
│   │   ├── usage.py                 # /usage quota panel
│   │   ├── conversations.py         # /conversations + resume
│   │   └── routing.py               # callback router + global error handler
│   ├── browse/                      # File browser components
│   │   └── markup.py                # Interactive directory browser inline keyboard builder
│   ├── conversation/                # Conversation state & tracking
│   │   └── history.py               # JSON persistence & Antigravity brain log discovery
│   ├── models/                      # Model management
│   │   └── models.py                # Model grouping, reasoning effort, inline selector
│   ├── rendering/                   # Output formatting & media
│   │   ├── images.py                # Image/artifact detector, MD5 deduplication, sender
│   │   ├── markdown.py              # Markdown to Telegram-safe HTML parser & footers
│   │   └── text.py                  # ANSI stripper & 4096-char chunk splitter
│   ├── usage/                       # Quota & metrics
│   │   └── usage.py                 # stream-json quota parser & ASCII progress bar renderer
│   ├── workspace/                   # Workspace & filesystem tools
│   │   ├── browse_token.py          # Ephemeral token mapping for long path callback data
│   │   ├── history.py               # Workspace history tracking
│   │   ├── resolver.py              # Fuzzy path resolution & default workspace config
│   │   └── volumes.py               # External drive & partition detection via lsblk
│   ├── config.py                    # Environment variables, logging, constants
│   ├── main.py                      # Application entrypoint & handler registration
│   ├── process_manager.py           # Cross-platform bot subprocess lifecycle (GUI mode)
│   ├── pty_compat.py                # Cross-platform PTY spawn (pexpect POSIX / ConPTY Windows)
│   ├── session.py                   # ChatSession and InteractiveState dataclasses
│   └── state.py                     # Shared startup state (default workspace)
├── gui/                             # Desktop control-center package (CustomTkinter)
│   ├── app_window.py                # AgyBotApp: tray icon, status/config/logs tabs
│   ├── setup_wizard.py              # First-run credential wizard
│   ├── constants.py                 # Palette, geometry, app metadata
│   ├── env_store.py                 # .env read/write helpers
│   ├── paths.py                     # Frozen (exe) vs dev path resolution
│   ├── startup.py                   # Start-on-login (registry / XDG autostart)
│   └── tray_image.py                # Programmatic tray icon rendering
├── gui_app.py                       # Desktop app entrypoint (GUI or --run-bot headless)
├── antighram_bot.spec               # PyInstaller build spec
├── build.py                         # One-file executable build script
├── install.sh / install.bat         # Dev installers (Linux / Windows)
├── .github/workflows/build.yml      # CI: builds & publishes release binaries
├── requirements.txt                 # Bot dependencies
├── requirements-gui.txt             # Desktop app dependencies
├── .env.example                     # Environment template file
└── README.md                        # Project documentation
```

---

## Prerequisites

1. **Linux, macOS, or native Windows 10 (1809+) / 11**
   *On Windows, pseudo-terminals are provided natively via ConPTY (`pywinpty`) — no WSL required (WSL2 also works if you prefer it).*
2. **Python 3.10+**
3. **Antigravity CLI (`agy`)** installed and authenticated on the host machine:
   ```bash
   agy --version
   agy models
   ```
4. A **Telegram Account**

---

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/arunkukrety/antighram-bot.git
cd antighram-bot
```

### 2. Create a Virtual Environment & Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts to choose a name and username.
3. Copy the HTTP API **Bot Token** provided (e.g. `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).

### 4. Find Your Telegram Chat ID

1. Open Telegram and message [@userinfobot](https://t.me/userinfobot).
2. Note your numeric **Id** (e.g. `123456789`).

### 5. Configure Environment Variables

Create a `.env` file from the provided template:

```bash
cp .env.example .env
```

Edit `.env` with your preferred editor:

```env
# Required: Bot token from @BotFather
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"

# Recommended: Your numeric Telegram chat ID (comma-separated if multiple)
TELEGRAM_ALLOWED_CHAT_IDS="123456789"

# Optional: Path to agy binary (default: 'agy')
AGY_BIN="agy"

# Optional: Default workspace directory
AGY_DEFAULT_WORKSPACE="~/agy-server-workspace"

# Optional: Print mode timeout in seconds (default: 300)
AGY_PRINT_TIMEOUT=300
```

### 6. Run the Bot

Launch the bot directly:

```bash
python -m agy_bot.main
```

Open your bot in Telegram and send `/start` or `/help`!

---

## Desktop Control Center (Tray App)

A cross-platform system-tray app manages the bot server as a subprocess —
power toggle, live logs, config editor, first-run setup wizard, and
start-on-login — no terminal needed.

```bash
pip install -r requirements.txt -r requirements-gui.txt
python gui_app.py
```

The window starts hidden: look for the ✦ icon in the system tray
(left-click = open panel, right-click = menu).

| Platform | Config (.env) location |
| :--- | :--- |
| Windows | `%APPDATA%\AntighramBot\.env` |
| Linux/macOS | `~/.config/antighram-bot/.env` |

### Building a standalone executable

```bash
python build.py          # → dist/AntighramBot.exe (Windows)
```

Uses PyInstaller (single-file). Pushing a `v*.*.*` tag triggers the
GitHub Actions workflow, which builds and uploads Windows & Linux
binaries to GitHub Releases.

---

## Configuration Reference

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | String | **Required** | Telegram bot token obtained from `@BotFather`. |
| `TELEGRAM_ALLOWED_CHAT_IDS`| String | `""` (Open) | Comma-separated list of allowed user/chat IDs. Highly recommended. |
| `AGY_BIN` | String | `agy` | Command or absolute path to the `agy` binary. |
| `AGY_DEFAULT_WORKSPACE` | String | `~/agy-server-workspace` | Default directory where `agy` runs if no workspace is active. |
| `AGY_PRINT_TIMEOUT` | Integer| `300` | Timeout in seconds for `--output-format stream-json` runs. |

Persistent runtime settings are saved to:
- Bot configuration: `~/.antighram-config.json`
- Recent workspaces: `~/.antighram-workspaces.json`
- Conversation history: `~/.antighram-conversations.json`

---

## Running as a System Service (systemd)

To keep the bot running 24/7 as a background service on your Linux host:

### 1. Create a systemd Service File

Create `/etc/systemd/system/antighram.service` (replace `arun` and paths with your username and repo location):

```ini
[Unit]
Description=Antighram Bot
After=network.target

[Service]
Type=simple
User=arun
WorkingDirectory=/home/arun/agy-server
EnvironmentFile=/home/arun/agy-server/.env
ExecStart=/home/arun/agy-server/.venv/bin/python -m agy_bot.main
Restart=always
RestartSec=5

# Ensure user PATH includes user-installed binaries (like agy)
Environment="PATH=/home/arun/.local/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
```

### 2. Enable and Start the Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable antighram.service
sudo systemctl start antighram.service
```

### 3. Manage and Check Logs

```bash
# Check service status
sudo systemctl status antighram.service

# View live streaming logs
journalctl -u antighram.service -f
```

---

## Command Reference

| Command | Syntax | Description |
| :--- | :--- | :--- |
| `/new` | `/new` or `/newchat` | Reset conversation context and start a fresh session. |
| `/conversations` | `/conversations` or `/history` | View recent conversations with prompt previews and resume buttons. |
| `/pwd` | `/pwd` | Display the current active workspace and default workspace. |
| `/cd` | `/cd <path>` | Switch workspace (supports absolute, relative, `~`, and recent folder names). |
| `/default` | `/default [path]` | Display or set the permanent default workspace. |
| `/set_default` | `/set_default <path>` | Save the specified path as the permanent default workspace. |
| `/browse` | `/browse [path]` | Open the interactive visual directory browser with navigation buttons. |
| `/volumes` | `/volumes` | Scan and list connected secondary drives, external USBs, and partitions. |
| `/workspaces` | `/workspaces` | Display recent workspaces with one-tap switching buttons. |
| `/sh` | `/sh <command>` | Execute a shell command (bash on POSIX, default shell on Windows) in the current workspace (60s timeout). |
| `/models` | `/models` | Open the interactive model selector with reasoning effort options. |
| `/model` | `/model <name>` | Switch the active AI model directly (e.g. `/model Claude 3.7 Sonnet`). |
| `/usage` | `/usage` | Display live quota progress bars, percentages, and reset timers. |
| `/interactive` | `/interactive` | Switch to live PTY interactive mode with inline permission approvals. |
| `/plain` | `/plain` | Switch back to the default streaming print mode (`stream-json`). |
| `/stop` | `/stop` | Interrupt active commands or abort running `agy` processes. |
| `/sleep` | `/sleep` | Put the host computer to sleep (`systemctl suspend`). |
| `/help` | `/help` | Display the interactive command guide with quick-action buttons. |
| `/debug` | `/debug` | Dump the raw terminal screen buffer for diagnostic inspection. |

---

## Troubleshooting & FAQ

#### Q: The bot reports that `agy` is not found.
Ensure `agy` is installed and in your system `PATH`. When running under systemd or cron, the `PATH` variable may differ. You can set the explicit binary location in `.env`:
```env
AGY_BIN="/home/arun/.local/bin/agy"
```

#### Q: Permission prompts are not showing buttons in Interactive Mode.
Send `/debug` to view the raw terminal screen. If your version of `agy` changed the wording of permission prompts, adjust the matching regex in [`agy_bot/agy/interactive_mode.py`](agy_bot/agy/interactive_mode.py).

#### Q: Does this require public ports or port forwarding?
**No.** Telegram bots use HTTP long-polling *outbound* to Telegram servers. No router ports, port forwarding, dynamic DNS, or public IPs are required.

#### Q: How can I run this on Windows?
It runs **natively** — the bot uses Windows ConPTY (via `pywinpty`) for pseudo-terminals, and `agy.exe` works out of the box. Alternatively, run everything inside WSL2 as before. Prebuilt desktop executables are published on the [Releases](../../releases) page.

---

## Contributing

Contributions, bug reports, and feature requests are welcome!

1. Fork the repository on GitHub.
2. Create a feature branch (`git checkout -b feature/amazing-feature`).
3. Commit your changes (`git commit -m "feat: add amazing feature"`).
4. Push to the branch (`git push origin feature/amazing-feature`).
5. Open a Pull Request.

Please ensure your code follows standard Python conventions (PEP 8) and maintains typing annotations.

---

## License

This project is licensed under the [MIT License](https://opensource.org/licenses/MIT).
