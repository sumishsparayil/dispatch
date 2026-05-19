#!/bin/bash
# =============================================================================
# Dispatch — One-Line Setup Installer
# KLM Axiva Finvest — MIS Email Dispatch System
# Usage: curl -sSL <raw-url> | bash
# =============================================================================
set -e

INSTALL_DIR="${DISPATCH_DIR:-$HOME/Dispatch}"
PORT="${DISPATCH_PORT:-5000}"
PYTHON_CMD=""
REPO_URL="https://github.com/sumishsparayil/dispatch.git"

# ── Colours ──────────────────────────────────────────────────────────────────
BOLD="\033[1m"; GREEN="\033[92m"; RED="\033[91m"; CYAN="\033[96m"; RESET="\033[0m"; DIM="\033[2m"

# ── Helpers ──────────────────────────────────────────────────────────────────
log()  { echo -e "  ${CYAN}[INFO]${RESET} $1"; }
ok()  { echo -e "  ${GREEN}[OK]${RESET} $1"; }
err() { echo -e "  ${RED}[ERR]${RESET} $1"; }

# ── Banner ───────────────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}"
echo "  ██████╗ ██████╗ ███████╗██████╗  ██████╗ ███╗   ███╗███████╗"
echo "  ██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔═══██╗████╗ ████║██╔════╝"
echo "  ██████╔╝██████╔╝███████╗██████╔╝██║   ██║██╔████╔██║█████╗  "
echo "  ██╔═══╝ ██╔══██╗╚════██║██╔═══╝ ██║   ██║██║╚██╔╝██║██╔══╝  "
echo "  ██║     ██║  ██║███████║██║     ╚██████╔╝██║ ╚═╝ ██║███████╗"
echo "  ╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚═╝     ╚═╝╚══════╝"
echo -e "${RESET}"
echo -e "${BOLD}    KLM Axiva Finvest — MIS Email Dispatch System${RESET}"
echo -e "${DIM}                         v1.0.0${RESET}"
echo ""

# ── Detect Python ─────────────────────────────────────────────────────────────
log "Detecting Python 3.8+..."
for cmd in python3 python python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v $cmd &>/dev/null 2>&1; then
        VER=$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        if [ -n "$VER" ]; then
            MAJOR=$(echo $VER | cut -d. -f1)
            MINOR=$(echo $VER | cut -d. -f2)
            if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 8 ]; then
                PYTHON_CMD=$cmd
                PYTHON_VER=$VER
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    err "Python 3.8+ not found. Install Python 3.8+ first:"
    echo "  Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora/RHEL:    sudo dnf install python3 python3-pip"
    exit 1
fi
ok "Python $PYTHON_VER found"

# ── Detect pip ────────────────────────────────────────────────────────────────
PIP="$PYTHON_CMD -m pip"
if ! $PIP --version &>/dev/null 2>&1; then
    err "pip not found. Install python3-pip for your OS."
    exit 1
fi
ok "pip available"

# ── Create install dir ────────────────────────────────────────────────────────
log "Creating install directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# ── Clone repo ────────────────────────────────────────────────────────────────
if [ -d ".git" ]; then
    log "Repo already present — pulling latest..."
    git pull origin main 2>/dev/null || true
else
    log "Cloning Dispatch repository..."
    if ! command -v git &>/dev/null; then
        err "git not found. Install git first: sudo apt install git"
        exit 1
    fi
    git clone --depth=1 "$REPO_URL" . 2>/dev/null || {
        err "Failed to clone. Check internet connection."
        exit 1
    }
fi

# ── Create venv ───────────────────────────────────────────────────────────────
log "Creating Python virtual environment..."
if [ -d ".venv" ]; then
    ok "Virtual environment already exists"
else
    $PYTHON_CMD -m venv .venv
    ok "Virtual environment created"
fi

# ── Install dependencies ───────────────────────────────────────────────────────
log "Installing Python dependencies..."
PIP_BIN="$INSTALL_DIR/.venv/bin/pip"
$PIP_BIN install --upgrade pip -q 2>/dev/null
$PIP_BIN install -r requirements-windows.txt -q 2>&1 | tail -3

if $PIP_BIN show flask &>/dev/null; then
    ok "Python packages installed"
else
    err "Package installation may have failed. Run manually:"
    echo "  cd $INSTALL_DIR && .venv/bin/pip install -r requirements-windows.txt"
fi

# ── Create start scripts ──────────────────────────────────────────────────────
cat > "$INSTALL_DIR/start.sh" << 'SCRIPT'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source .venv/bin/activate
PORT="${PORT:-5000}"
exec .venv/bin/python app.py
SCRIPT
chmod +x "$INSTALL_DIR/start.sh"

cat > "$INSTALL_DIR/dispatch.sh" << 'SCRIPT'
#!/bin/bash
cd "$(dirname "${BASH_SOURCE[0]}")"
./start.sh &>/dev/null &
echo "Dispatch started on port ${PORT:-5000}"
SCRIPT
chmod +x "$INSTALL_DIR/dispatch.sh"
ok "Launcher scripts created"

# ── Systemd service ───────────────────────────────────────────────────────────
REAL_HOME="${HOME:-/root}"
if [ -n "$SUDO_USER" ]; then
    REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
fi

log "Installing systemd service..."
mkdir -p "$REAL_HOME/.config/systemd/user"
cat > "$REAL_HOME/.config/systemd/user/dispatch.service" << EOF
[Unit]
Description=Dispatch MIS Email System
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/app.py
Restart=on-failure
RestartSec=10
Environment=PORT=$PORT

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable dispatch.service 2>/dev/null || true
ok "Systemd service installed and enabled"

# ── Start the app ─────────────────────────────────────────────────────────────
log "Starting Dispatch..."
systemctl --user start dispatch.service 2>/dev/null || {
    nohup "$INSTALL_DIR/start.sh" > "$INSTALL_DIR/app.log" 2>&1 &
}
sleep 2

# ── Done ─────────────────────────────────────────────────────────────────────
PORT_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${PORT}/ 2>/dev/null || echo "000")
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  ✓  Dispatch is running!${RESET}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "  ${BOLD}URL:${RESET}       http://localhost:${PORT}"
echo -e "  ${BOLD}Service:${RESET}   systemctl --user {'start|stop|restart'} dispatch"
echo -e "  ${BOLD}Log:${RESET}       tail -f $INSTALL_DIR/app.log"
echo -e "  ${BOLD}Auto-start:${RESET} enabled (survives reboot)"
echo ""