#!/usr/bin/env bash
# =============================================================================
# install.sh — Antigravity Telegram Bot Desktop App Installer (Linux)
# =============================================================================
# Usage:
#   bash install.sh
#
# What it does:
#   1. Creates a Python virtual environment inside the project
#   2. Installs all bot + GUI dependencies
#   3. Prompts for Telegram credentials if .env is missing
#   4. Creates a ~/.local/share/applications launcher (.desktop file)
#   5. Creates ~/.local/bin/agy-bot shortcut command
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

GREEN='\033[0;32m'
AMBER='\033[0;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

banner() {
  echo ""
  echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║     Antigravity Telegram Bot Installer       ║${NC}"
  echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
  echo ""
}

step() { echo -e "\n${BLUE}==> ${NC}$1"; }
ok()   { echo -e "    ${GREEN}✔${NC}  $1"; }
warn() { echo -e "    ${AMBER}⚠${NC}  $1"; }
err()  { echo -e "    ${RED}✗${NC}  $1"; exit 1; }

banner

# ── 1. Check Python ────────────────────────────────────────────────────────
step "Checking Python 3..."
if ! command -v python3 &>/dev/null; then
  err "Python 3 is required but not found. Install it and re-run."
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "Found Python $PY_VER"

# ── 2. Virtual environment ─────────────────────────────────────────────────
step "Setting up virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  ok "Created .venv"
else
  ok ".venv already exists — skipping"
fi
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ── 3. Install dependencies ────────────────────────────────────────────────
step "Installing bot dependencies..."
"$PIP" install --upgrade pip --quiet
"$PIP" install -r "$SCRIPT_DIR/requirements.txt" --quiet
ok "Bot dependencies installed"

step "Installing GUI dependencies..."
"$PIP" install -r "$SCRIPT_DIR/requirements-gui.txt" --quiet
ok "GUI dependencies installed"

# ── 4. Configure .env ──────────────────────────────────────────────────────
step "Configuring environment..."
ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo ""
  echo -e "  ${AMBER}No .env file found. Let's set it up now.${NC}"
  echo ""
  read -rp "  Telegram Bot Token (from @BotFather): " BOT_TOKEN
  read -rp "  Allowed Chat IDs (comma-separated, leave blank to skip): " CHAT_IDS

  cat > "$ENV_FILE" <<ENVEOF
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
TELEGRAM_ALLOWED_CHAT_IDS=$CHAT_IDS
AGY_BIN=agy
AGY_DEFAULT_WORKSPACE=$HOME/agy-server-workspace
AGY_PRINT_TIMEOUT=300
ENVEOF
  ok ".env created"
else
  ok ".env already exists — skipping"
fi

# ── 5. Desktop launcher ────────────────────────────────────────────────────
step "Creating application launcher..."
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/agy-bot.desktop" <<DESKTOPEOF
[Desktop Entry]
Name=Antigravity Bot
GenericName=Telegram Bot Server
Comment=Control the Antigravity Telegram Bot server
Exec=$PYTHON $SCRIPT_DIR/gui_app.py
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=Network;Utility;
Keywords=telegram;bot;antigravity;
StartupNotify=true
DESKTOPEOF
chmod +x "$DESKTOP_DIR/agy-bot.desktop"
ok "Created ~/.local/share/applications/agy-bot.desktop"

# Update desktop database if available
if command -v update-desktop-database &>/dev/null; then
  update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

# ── 6. Global command alias ────────────────────────────────────────────────
step "Installing 'agy-bot' command..."
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/agy-bot" <<CMDEOF
#!/usr/bin/env bash
# Antigravity Bot Desktop GUI launcher
exec "$PYTHON" "$SCRIPT_DIR/gui_app.py" "\$@"
CMDEOF
chmod +x "$BIN_DIR/agy-bot"
ok "Installed: agy-bot"

# Ensure ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  warn "~/.local/bin is not in your PATH."
  echo "     Add this line to your ~/.bashrc or ~/.zshrc:"
  echo ""
  echo -e "     ${GREEN}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
  echo ""
fi

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       Installation complete!  🎉             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "  Launch the control panel with any of these:"
echo ""
echo -e "  ${BLUE}agy-bot${NC}                   (command line)"
echo -e "  ${BLUE}python gui_app.py${NC}          (from project directory)"
echo -e "  ${BLUE}App Menu → Antigravity Bot${NC} (desktop launcher)"
echo ""
echo "  The app will appear in your system tray."
echo "  Left-click the tray icon to open the control panel."
echo ""
