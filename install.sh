#!/bin/bash
# =============================================================================
# Dispatch — Setup Installer (TUI)
# KLM Axiva Finvest — MIS Email Dispatch System
# =============================================================================
# Usage: chmod +x install.sh && ./install.sh
# Run as: ./install.sh   (no sudo needed for user-space install)
# =============================================================================

set -e

# ── Colours ──────────────────────────────────────────────────────────────────
BOLD="\033[1m"
GREEN="\033[92m"
YELLOW="\033[93m"
RED="\033[91m"
CYAN="\033[96m"
MAGENTA="\033[95m"
BLUE="\033[94m"
RESET="\033[0m"
DIM="\033[2m"

# ── Detect real user home (sudo preserving) ───────────────────────────────────
REAL_HOME="$HOME"
if [ -n "$SUDO_USER" ]; then
    REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
fi

# ── Defaults ─────────────────────────────────────────────────────────────────
INSTALL_DIR="$REAL_HOME/Dispatch"
PORT=5000
PYTHON_CMD=""
PYTHON_VER=""

# ── Banner ─────────────────────────────────────────────────────────────────────
banner() {
    clear
    echo -e "${BOLD}${CYAN}"
    echo "  ██████╗ ██████╗ ███████╗██████╗  ██████╗ ███╗   ███╗███████╗"
    echo "  ██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔═══██╗████╗ ████║██╔════╝"
    echo "  ██████╔╝██████╔╝███████╗██████╔╝██║   ██║██╔████╔██║█████╗  "
    echo "  ██╔═══╝ ██╔══██╗╚════██║██╔═══╝ ██║   ██║██║╚██╔╝██║██╔══╝  "
    echo "  ██║     ██║  ██║███████║██║     ╚██████╔╝██║ ╚═╝ ██║███████╗"
    echo "  ╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚═╝     ╚═╝╚══════╝"
    echo -e "${RESET}"
    echo -e "${BOLD}${MAGENTA}          KLM Axiva Finvest — MIS Email Dispatch System${RESET}"
    echo -e "${DIM}                    Version 1.0.0 — TUI Installer${RESET}"
    echo ""
}

# ── Spinner ───────────────────────────────────────────────────────────────────
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    while kill -0 $pid 2>/dev/null; do
        printf "\r  ${CYAN}%c${RESET} ${spinstr:$i:1}" "${spinstr:$i:1}"
        i=$(( (i+1) % ${#spinstr} ))
        sleep $delay
    done
    printf "\r"
    wait $pid
    return $?
}

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo -e "  ${BLUE}[INFO]${RESET}    $1"; }
ok()      { echo -e "  ${GREEN}[OK]${RESET}     $1"; }
warn()    { echo -e "  ${YELLOW}[WARN]${RESET}   $1"; }
error()   { echo -e "  ${RED}[ERROR]${RESET} $1"; }
section() { echo ""; echo -e "${BOLD}${CYAN}── $1 ──${RESET}"; }
prompt()  { echo -en "  ${BOLD}➜${RESET} $1 "; }

# ── Wait key ───────────────────────────────────────────────────────────────────
wait_key() {
    echo ""
    echo -e "  ${DIM}Press ENTER to continue...${RESET}"
    read
}

# ── Check root ──────────────────────────────────────────────────────────────────
check_root() {
    if [ "$(id -u)" -eq 0 ]; then
        warn "Running as root. This installer handles user-space setup."
        warn "sudo is only used when strictly required."
        echo ""
    fi
}

# ── Check prerequisites ─────────────────────────────────────────────────────────
check_prereqs() {
    section "Prerequisites Check"

    # Python 3
    PYTHON_CMD=""
    for cmd in python3 python python3.12 python3.11 python3.10; do
        if command -v $cmd &>/dev/null; then
            VER=$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            MAJOR=$(echo $VER | cut -d. -f1)
            MINOR=$(echo $VER | cut -d. -f2)
            if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 8 ]; then
                PYTHON_CMD=$cmd
                PYTHON_VER=$VER
                break
            fi
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        error "Python 3.8+ not found. Please install Python 3.8 or higher."
        echo "  Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
        echo "  Fedora/RHEL:    sudo dnf install python3 python3-pip"
        echo "  Arch:           sudo pacman -S python python-pip"
        exit 1
    fi
    ok "Python $PYTHON_VER found: $PYTHON_CMD"

    # pip
    PIP_CMD=""
    for cmd in pip3 pip python3 -m pip; do
        if $cmd --version &>/dev/null 2>&1; then
            PIP_CMD="$cmd"
            break
        fi
    done
    if [ -z "$PIP_CMD" ]; then
        error "pip not found. Install python3-pip package for your distribution."
        exit 1
    fi
    ok "pip found: $PIP_CMD"

    # Internet check
    if curl -s --max-time 5 https://pypi.org &>/dev/null; then
        ok "Internet connection active"
    else
        warn "No internet detected. Package installation may fail."
    fi

    wait_key
}

# ── Get install location ────────────────────────────────────────────────────────
get_install_dir() {
    section "Install Location"
    echo "  Dispatch will be installed to:"
    echo ""
    echo -e "    ${BOLD}$INSTALL_DIR${RESET}"
    echo ""
    prompt "Enter a custom path or press ENTER to accept default: "
    read -r input
    if [ -n "$input" ]; then
        # Resolve tilde
        INPUT_DIR="${input/#\~/$REAL_HOME}"
        if [[ "$INPUT_DIR" = /* ]]; then
            INSTALL_DIR="$INPUT_DIR"
        else
            INSTALL_DIR="$REAL_HOME/$INPUT_DIR"
        fi
    fi

    if [ -d "$INSTALL_DIR" ]; then
        warn "Directory already exists: $INSTALL_DIR"
        prompt "Files may be overwritten. Continue? [y/N]: "
        read -r confirm
        if [ "${confirm,,}" != "y" ]; then
            info "Aborted."
            exit 0
        fi
    fi
}

# ── Create directories ───────────────────────────────────────────────────────────
create_dirs() {
    mkdir -p "$INSTALL_DIR"/{core,db,static,templates,uploads}
    ok "Directory structure created: $INSTALL_DIR/"
}

# ── Detect platform ─────────────────────────────────────────────────────────────
detect_platform() {
    section "Platform Detection"
    OS=$(uname -s)
    KERNEL=$(uname -r)
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO="$NAME ($VERSION_ID)"
    elif [ -f /etc/redhat-release ]; then
        DISTRO=$(cat /etc/redhat-release)
    elif [ -f /etc/debian_version ]; then
        DISTRO="Debian-based"
    else
        DISTRO="$OS $KERNEL"
    fi
    ok "OS: $DISTRO"
    ok "Kernel: $KERNEL"
    wait_key
}

# ── Install system packages ─────────────────────────────────────────────────────
install_system_packages() {
    section "System Packages"

    if command -v apt-get &>/dev/null; then
        PKG_MGR="apt"
        echo "  Package manager: ${BOLD}apt${RESET}"
        echo ""
        info "The following will be installed if missing:"
        echo "    ${CYAN}python3 python3-venv python3-pip${RESET}"
        echo ""
        prompt "Proceed with apt install? [Y/n]: "
        read -r confirm
        if [ "${confirm,,}" != "n" ]; then
            (
                set -x
                sudo apt-get update -qq
                sudo apt-get install -y -qq python3 python3-venv python3-pip curl
            ) &>/dev/null &
            spinner $!
            if [ $? -eq 0 ]; then
                ok "System packages installed"
            else
                error "Failed to install system packages. Try manually:"
                echo "  sudo apt install python3 python3-venv python3-pip curl"
            fi
        fi
    elif command -v dnf &>/dev/null; then
        PKG_MGR="dnf"
        echo "  Package manager: ${BOLD}dnf${RESET}"
        (
            set -x
            sudo dnf install -y python3 python3-pip curl
        ) &>/dev/null &
        spinner $!
        ok "System packages installed"
    elif command -v pacman &>/dev/null; then
        PKG_MGR="pacman"
        echo "  Package manager: ${BOLD}pacman${RESET}"
        (
            set -x
            sudo pacman -Sy --noconfirm python python-pip curl
        ) &>/dev/null &
        spinner $!
        ok "System packages installed"
    else
        warn "No supported package manager found."
        warn "Please install Python 3.8+ and pip manually."
    fi

    wait_key
}

# ── Copy application files ───────────────────────────────────────────────────────
copy_app_files() {
    section "Copy Application Files"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    echo "  Copying from: $SCRIPT_DIR"
    echo "  Installing to: $INSTALL_DIR"
    echo ""

    # Files to copy (skip venv, .git, build, dist, this script)
    FILES=(
        app.py
        requirements-windows.txt
        requirements.txt
        icon.ico
        ARCHITECTURE.md
        README.md
    )

    DIRS=(core db static templates uploads)

    for item in "${FILES[@]}"; do
        if [ -f "$SCRIPT_DIR/$item" ]; then
            cp "$SCRIPT_DIR/$item" "$INSTALL_DIR/"
            ok "Copied: $item"
        fi
    done

    for dir in "${DIRS[@]}"; do
        if [ -d "$SCRIPT_DIR/$dir" ]; then
            rm -rf "$INSTALL_DIR/$dir"
            cp -r "$SCRIPT_DIR/$dir" "$INSTALL_DIR/"
            ok "Copied: $dir/"
        fi
    done

    wait_key
}

# ── Create Python virtual environment ───────────────────────────────────────────
create_venv() {
    section "Python Virtual Environment"

    if [ -d "$INSTALL_DIR/.venv" ]; then
        warn "Existing virtual environment found at $INSTALL_DIR/.venv"
        prompt "Recreate it? [y/N]: "
        read -r confirm
        if [ "${confirm,,}" = "y" ]; then
            info "Removing old venv..."
            rm -rf "$INSTALL_DIR/.venv"
        fi
    fi

    if [ ! -d "$INSTALL_DIR/.venv" ]; then
        info "Creating Python virtual environment..."
        (cd "$INSTALL_DIR" && $PYTHON_CMD -m venv .venv) &>/dev/null &
        spinner $!
        if [ $? -eq 0 ]; then
            ok "Virtual environment created"
        else
            error "Failed to create virtual environment."
            exit 1
        fi
    fi

    wait_key
}

# ── Install Python dependencies ─────────────────────────────────────────────────
install_deps() {
    section "Python Dependencies"
    info "Installing packages from requirements.txt..."
    echo ""

    PIP="$INSTALL_DIR/.venv/bin/pip"
    PY="$INSTALL_DIR/.venv/bin/python"

    # Upgrade pip first
    (cd "$INSTALL_DIR" && $PIP install --upgrade pip -q) &>/dev/null &
    spinner $!
    ok "pip upgraded"

    # Install packages in background with spinner
    (cd "$INSTALL_DIR" && $PIP install -r requirements-windows.txt -q) &>/dev/null &
    spinner $!
    if [ $? -eq 0 ]; then
        ok "Python packages installed"
    else
        error "Some packages failed to install. Check log above."
    fi

    wait_key
}

# ── Port selection ──────────────────────────────────────────────────────────────
select_port() {
    section "Network Configuration"
    echo "  Dispatch runs as a local web app."
    echo ""
    echo -e "  ${BOLD}Default port: ${CYAN}$PORT${RESET}"
    echo ""
    prompt "Enter port number or press ENTER to use $PORT: "
    read -r input
    if [ -n "$input" ]; then
        if [[ "$input" =~ ^[0-9]+$ ]] && [ "$input" -gt 1024 ] && [ "$input" -lt 65535 ]; then
            PORT=$input
            ok "Port set to: $PORT"
        else
            warn "Invalid port. Using default: $PORT"
        fi
    fi
    wait_key
}

# ── Create launcher scripts ─────────────────────────────────────────────────────
create_launchers() {
    section "Launcher Scripts"

    # Main start script
    cat > "$INSTALL_DIR/start.sh" << 'LAUNCHER'
#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Dispatch — Start Server
# Run this script to launch the Dispatch web interface.
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Find an open port
PORT="${PORT:-5000}"
if lsof -i ":$PORT" &>/dev/null; then
    echo "[WARN] Port $PORT is in use. Searching for free port..."
    for p in $(seq 5001 5010); do
        if ! lsof -i ":$p" &>/dev/null; then
            PORT=$p
            break
        fi
    done
fi

echo "Starting Dispatch on port $PORT..."
exec .venv/bin/python app.py
LAUNCHER
    chmod +x "$INSTALL_DIR/start.sh"
    ok "Created: start.sh"

    # Quick-start script
    cat > "$INSTALL_DIR/dispatch.sh" << 'LAUNCHER'
#!/bin/bash
# Dispatch — Quick start (runs in background)
cd "$(dirname "${BASH_SOURCE[0]}")"
./start.sh &>/dev/null &
echo "Dispatch started. Check start.sh log for port."
LAUNCHER
    chmod +x "$INSTALL_DIR/dispatch.sh"
    ok "Created: dispatch.sh"

    wait_key
}

# ── Systemd service (optional) ──────────────────────────────────────────────────
install_systemd() {
    section "Systemd Service (Optional)"
    echo "  Register a user-level systemd service for auto-start on boot."
    echo "  Requires systemd (most Linux desktops)."
    echo ""
    prompt "Install systemd service? [y/N]: "
    read -r confirm
    if [ "${confirm,,}" = "y" ]; then
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
        ok "Service installed: ~/.config/systemd/user/dispatch.service"
        info "Enable with: systemctl --user enable dispatch.service"
        info "Start with:  systemctl --user start dispatch.service"
    fi
    wait_key
}

# ── Verify installation ─────────────────────────────────────────────────────────
verify() {
    section "Verification"
    PY="$INSTALL_DIR/.venv/bin/python"

    info "Checking Python environment..."
    if $PY -c "import flask, pandas, openpyxl, werkzeug" 2>/dev/null; then
        ok "All Python packages importable"
    else
        error "Some packages failed to import. Run manually:"
        echo "  cd $INSTALL_DIR && .venv/bin/pip install -r requirements-windows.txt"
    fi

    info "Checking app structure..."
    MISSING=""
    for f in app.py core/engine.py core/parser.py core/mailer.py core/exporter.py db/database.py db/address_book.py; do
        if [ ! -f "$INSTALL_DIR/$f" ]; then
            MISSING="$MISSING $f"
        fi
    done
    if [ -z "$MISSING" ]; then
        ok "All core files present"
    else
        error "Missing files:$MISSING"
    fi

    wait_key
}

# ── Final summary ───────────────────────────────────────────────────────────────
summary() {
    banner
    echo -e "${BOLD}${GREEN}═════════════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}               ✓  Installation Complete!${RESET}"
    echo -e "${BOLD}${GREEN}═════════════════════════════════════════════════════════════${RESET}"
    echo ""
    echo -e "  ${BOLD}Install location:${RESET}  $INSTALL_DIR"
    echo -e "  ${BOLD}Port:${RESET}             $PORT"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────┐"
    echo "  │  HOW TO START DISPATCH                                   │"
    echo "  │                                                         │"
    echo "  │  Option 1 — Direct:                                     │"
    echo "  │    cd $INSTALL_DIR"
    echo "  │    ./start.sh                                           │"
    echo "  │                                                         │"
    echo "  │  Option 2 — Background:                                 │"
    echo "  │    cd $INSTALL_DIR"
    echo "  │    ./dispatch.sh                                        │"
    echo "  │                                                         │"
    echo "  │  Option 3 — Python directly:                            │"
    echo "  │    cd $INSTALL_DIR"
    echo "  │    .venv/bin/python app.py                              │"
    echo "  │                                                         │"
    echo "  │  Then open:  http://localhost:$PORT                      │"
    echo "  └─────────────────────────────────────────────────────────┘"
    echo ""
    echo -e "  ${DIM}Stop server:  pkill -f 'python app.py'${RESET}"
    echo -e "  ${DIM}Logs:         tail -f $INSTALL_DIR/app.log${RESET}"
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────────
main() {
    banner
    check_root
    check_prereqs
    detect_platform
    get_install_dir
    create_dirs
    install_system_packages
    copy_app_files
    create_venv
    install_deps
    select_port
    create_launchers

    if command -v systemctl &>/dev/null; then
        install_systemd
    fi

    verify
    summary
}

main "$@"