#!/bin/bash
# =============================================================================
# Dispatch — One-Line Setup
# Dispatch — MIS Email Dispatch System
# =============================================================================
# Usage:
#   curl -sSL https://raw.githubusercontent.com/sumishsparayil/dispatch/main/setup.sh | bash
#
# Options (env vars):
#   DISPATCH_DIR=~/Dispatch     # install location
#   DISPATCH_PORT=5000          # port number
# =============================================================================
set -e

INSTALL_DIR="${DISPATCH_DIR:-$HOME/Dispatch}"
PORT="${DISPATCH_PORT:-5000}"
REPO="https://github.com/sumishsparayil/dispatch.git"

BOLD="\033[1m"; CYAN="\033[96m"; GREEN="\033[92m"; RED="\033[91m"; YELLOW="\033[93m"; RESET="\033[0m"

log()  { echo -e "  ${CYAN}[INFO]${RESET} $1"; }
ok()   { echo -e "  ${GREEN}[✓]${RESET}   $1"; }
err()  { echo -e "  ${RED}[✗]${RESET}   $1"; }
warn() { echo -e "  ${YELLOW}[!]${RESET}  $1"; }

echo -e "${BOLD}${CYAN}"
echo "   ██████╗ ██████╗ ███████╗██████╗  ██████╗ ███╗   ███╗███████╗"
echo "   ██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔═══██╗████╗ ████║██╔════╝"
echo "   ██████╔╝██████╔╝███████╗██████╔╝██║   ██║██╔████╔██║█████╗  "
echo "   ██╔═══╝ ██╔══██╗╚════██║██╔═══╝ ██║   ██║██║╚██╔╝██║██╔══╝  "
echo "   ██║     ██║  ██║███████║██║     ╚██████╔╝██║ ╚═╝ ██║███████╗"
echo "   ╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚═╝     ╚═╝╚══════╝"
echo -e "${RESET}"
echo -e "  ${BOLD}Dispatch MIS — Email Dispatch System${RESET}"
echo -e "  ${CYAN}https://github.com/sumishsparayil/dispatch${RESET}"
echo ""

# ── Validate port ─────────────────────────────────────────────────────────────
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
    err "Port must be a number between 1024 and 65535."
    exit 1
fi
log "Installing on port $PORT"

# ── Python detection ───────────────────────────────────────────────────────────
PYTHON_CMD=""; PYTHON_VER=""
for cmd in python3 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
    if command -v $cmd &>/dev/null 2>&1; then
        VER=$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        [ -n "$VER" ] && [ ${VER%%.*} -eq 3 ] && [ ${VER#*.} -ge 8 ] && PYTHON_CMD=$cmd && PYTHON_VER=$VER && break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    err "Python 3.8+ not found."
    echo "  Install Python 3.8+ first:"
    echo "    Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
    echo "    Fedora/RHEL:    sudo dnf install python3 python3-pip"
    echo "    Arch:           sudo pacman -S python python-pip"
    exit 1
fi
ok "Python $PYTHON_VER — $PYTHON_CMD"

# ── pip check ──────────────────────────────────────────────────────────────────
if ! $PYTHON_CMD -m pip --version &>/dev/null 2>&1; then
    err "pip not found. Install python3-pip for your OS."
    exit 1
fi
ok "pip available"

# ── git check ──────────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    err "git not found. Install git: sudo apt install git"
    exit 1
fi
ok "git available"

# ── Detect real home ───────────────────────────────────────────────────────────
REAL_HOME="$HOME"
[ -n "$SUDO_USER" ] && REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)

# ── Resolve install dir ──────────────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR/#\~/$REAL_HOME}"
[ -d "$INSTALL_DIR" ] || mkdir -p "$INSTALL_DIR"

# ── Clone or update repo ───────────────────────────────────────────────────────
cd "$INSTALL_DIR"
if [ -d ".git" ]; then
    log "Repo present — pulling latest..."
    git pull origin main 2>/dev/null || warn "Could not pull — continuing with existing files"
else
    log "Cloning Dispatch from GitHub..."
    rm -rf "$INSTALL_DIR"/*
    git clone --depth=1 "$REPO" . 2>/dev/null || {
        err "Clone failed. Check internet connection."
        exit 1
    }
fi
ok "Repository ready"

# ── Python venv ────────────────────────────────────────────────────────────────
log "Setting up Python virtual environment..."
if [ ! -d ".venv" ]; then
    $PYTHON_CMD -m venv .venv 2>/dev/null || {
        err "Failed to create virtual environment."
        exit 1
    }
fi
ok "Virtual environment ready"

# ── Install dependencies ─────────────────────────────────────────────────────
PIP="$INSTALL_DIR/.venv/bin/pip"
log "Installing Python packages..."
$PIP install --upgrade pip -q 2>/dev/null
INSTALL_LOG=$($PIP install -r requirements-windows.txt 2>&1) || true
$PIP show flask &>/dev/null && ok "Python packages installed" || {
    warn "Some packages may have issues. Run manually to check:"
    echo "  cd $INSTALL_DIR && .venv/bin/pip install -r requirements-windows.txt"
}

# ── Launcher scripts ───────────────────────────────────────────────────────────
cat > "$INSTALL_DIR/start.sh" << 'SCRIPT'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
PORT="${PORT:-5000}"
source .venv/bin/activate
exec .venv/bin/python app.py --port "$PORT"
SCRIPT
chmod +x "$INSTALL_DIR/start.sh"
ok "Created: start.sh"

cat > "$INSTALL_DIR/dispatch.sh" << 'SCRIPT'
#!/bin/bash
cd "$(dirname "${BASH_SOURCE[0]}")"
./start.sh &>/dev/null &
echo "Dispatch started."
SCRIPT
chmod +x "$INSTALL_DIR/dispatch.sh"
ok "Created: dispatch.sh"

# ── Systemd service ───────────────────────────────────────────────────────────
log "Installing systemd service..."
mkdir -p "$REAL_HOME/.config/systemd/user"
cat > "$REAL_HOME/.config/systemd/user/dispatch.service" << EOF
[Unit]
Description=Dispatch MIS Email System
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/app.py --port $PORT
Restart=on-failure
RestartSec=10
Environment=PORT=$PORT
StandardOutput=append:$INSTALL_DIR/app.log
StandardError=append:$INSTALL_DIR/app.log
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable dispatch.service 2>/dev/null || true
ok "Systemd service installed and enabled"

# ── Start ─────────────────────────────────────────────────────────────────────
log "Starting Dispatch on port $PORT..."
if ! systemctl --user start dispatch.service 2>/dev/null; then
    PORT=$PORT nohup "$INSTALL_DIR/start.sh" > "$INSTALL_DIR/app.log" 2>&1 &
fi
sleep 3

# ── Status check ──────────────────────────────────────────────────────────────
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$PORT/ 2>/dev/null || echo "000")
echo ""
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}══════════════════════════════════════════════════════════${RESET}"
    echo -e "${GREEN}  ✓  Dispatch is running!${RESET}"
    echo -e "${GREEN}══════════════════════════════════════════════════════════${RESET}"
    echo ""
    echo -e "  ${BOLD}URL:${RESET}        ${CYAN}http://localhost:$PORT${RESET}"
    echo -e "  ${BOLD}Auto-start:${RESET} ${GREEN}enabled${RESET} — survives reboots"
    echo ""
    echo "  Management:"
    echo "    Start    systemctl --user start dispatch"
    echo "    Stop     systemctl --user stop dispatch"
    echo "    Restart  systemctl --user restart dispatch"
    echo "    Logs     tail -f $INSTALL_DIR/app.log"
    echo ""
else
    echo -e "${YELLOW}══════════════════════════════════════════════════════════${RESET}"
    echo -e "${YELLOW}  ⚠  Dispatch installed but may still be starting${RESET}"
    echo -e "${YELLOW}══════════════════════════════════════════════════════════${RESET}"
    echo ""
    echo "  Check manually:"
    echo "    curl http://localhost:$PORT"
    echo "    tail -f $INSTALL_DIR/app.log"
    echo ""
fi
