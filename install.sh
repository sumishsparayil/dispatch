#!/bin/bash
# =============================================================================
# Dispatch — Professional TUI Installer
# Dispatch — MIS Email Dispatch System
# =============================================================================
# Run interactively:  ./install.sh
# Run unattended:     ./install.sh --unattended [--port NNNN] [--dir PATH]
# =============================================================================

set -e

# ── Identity ─────────────────────────────────────────────────────────────────────
APP_NAME="Dispatch"
APP_FULL="Dispatch MIS"
ORG="Dispatch MIS"
VERSION="1.0.0"
REPO="https://github.com/sumishsparayil/dispatch.git"

# ── Paths ─────────────────────────────────────────────────────────────────────
REAL_HOME="${HOME}"
[ -n "$SUDO_USER" ] && REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
INSTALL_DIR="$REAL_HOME/Dispatch"
UPLOADS_DIR=""
PORT=5000

# ── Installer source directory (where this script lives) ────────────────────────
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Colours ────────────────────────────────────────────────────────────────────────
C_RESET="\033[0m"; C_BOLD="\033[1m"; C_DIM="\033[2m"
C_RED="\033[91m";   C_GREEN="\033[92m"; C_YELLOW="\033[93m"
C_BLUE="\033[94m";  C_CYAN="\033[96m";  C_MAGENTA="\033[95m"
C_WHITE="\033[97m"

# ── State ──────────────────────────────────────────────────────────────────────
STEP=0; TOTAL_STEPS=8
UNATTENDED=false
SKIP_PROMPTS=false
CUSTOM_PORT=false
CUSTOM_DIR=false
PKG_MGR=""

# ── Output helpers ──────────────────────────────────────────────────────────────
log_info()  { echo -e "  ${C_CYAN}[INFO]${C_RESET}  $1"; }
log_ok()    { echo -e "  ${C_GREEN}[✓]${C_RESET}    $1"; }
log_warn()  { echo -e "  ${C_YELLOW}[WARN]${C_RESET}  $1"; }
log_fail()  { echo -e "  ${C_RED}[FAIL]${C_RESET}  $1"; }
log_step()  { echo -e "\n  ${C_BOLD}${C_MAGENTA}▶ Step $((++STEP)) of $TOTAL_STEPS${C_RESET} — ${C_BOLD}$1${C_RESET}"; }
log_sub()   { echo -e "    ${C_DIM}$1${C_RESET}"; }
prompt()    { echo -en "\n  ${C_BOLD}➜${C_RESET} $1 "; }
wait_key()  { echo -e "\n  ${C_DIM}Press ENTER to continue...${C_RESET}"; read; }

# ── Parse CLI args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --unattended|-y) UNATTENDED=true; SKIP_PROMPTS=true ;;
        --port|--port=*)
            [[ "$1" == "--port"* ]] && { CUSTOM_PORT=true; PORT="${1#*=}"; } 2>/dev/null
            [[ -z "$PORT" ]] && { PORT="$2"; shift; } 2>/dev/null
            ;;
        --dir|--dir=*)
            CUSTOM_DIR=true
            [[ "$1" == "--dir="* ]] && INSTALL_DIR="${1#*=}" || { INSTALL_DIR="$2"; shift; }
            ;;
        --help|-h) echo "Usage: $0 [--unattended] [--port NNNN] [--dir PATH]"; exit 0 ;;
    esac
    shift
done

# ── Banner ───────────────────────────────────────────────────────────────────────
banner() {
    clear
    echo -e "${C_BOLD}${C_CYAN}"
    echo "   ██████╗ ██████╗ ███████╗██████╗  ██████╗ ███╗   ███╗███████╗"
    echo "   ██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔═══██╗████╗ ████║██╔════╝"
    echo "   ██████╔╝██████╔╝███████╗██████╔╝██║   ██║██╔████╔██║█████╗  "
    echo "   ██╔═══╝ ██╔══██╗╚════██║██╔═══╝ ██║   ██║██║╚██╔╝██║██╔══╝  "
    echo "   ██║     ██║  ██║███████║██║     ╚██████╔╝██║ ╚═╝ ██║███████╗"
    echo "   ╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚═╝     ╚═╝╚══════╝"
    echo -e "${C_RESET}"
    echo -e "  ${C_BOLD}${C_MAGENTA}Dispatch MIS${C_RESET}  ·  ${C_WHITE}MIS Email Dispatch System${C_RESET}"
    echo -e "  ${C_DIM}Version $VERSION  ·  Professional Installer${C_RESET}"
    echo ""
}

# ── Spinner ────────────────────────────────────────────────────────────────────
spin_pid=""; spin_char=0
spin_chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
spin_start() { spin_pid=$!; spin_char=0; }
spin_stop() {
    [ -n "$spin_pid" ] && kill $spin_pid 2>/dev/null && wait $spin_pid 2>/dev/null
    printf "\r                   \r"
}
spinner() {
    local cmd="$1"; local label="${2:-}"; local tmp
    printf "  ${C_CYAN}%c${C_RESET} ${label:-Processing...}  " "${spin_chars:0:1}"
    spin_start
    eval "$cmd" &>/dev/null &
    while kill -0 $spin_pid 2>/dev/null; do
        printf "\b\b%c\b\b" "${spin_chars:((spin_char++ % ${#spin_chars})):1}"
        sleep 0.1
    done
    spin_stop
    tmp=$?
    [ $tmp -eq 0 ] && log_ok "$label" || log_fail "$label (exit $tmp)"
    return $tmp
}

# ── Checks ─────────────────────────────────────────────────────────────────────
check_internet() {
    curl -s --max-time 5 https://github.com -o /dev/null 2>&1
}

check_git()    { command -v git &>/dev/null; }
check_python() {
    local cmd; for cmd in python3 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
        if command -v $cmd &>/dev/null 2>&1; then
            local ver=$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
            [ -n "$ver" ] && [ ${ver%%.*} -eq 3 ] && [ ${ver#*.} -ge 8 ] && PYTHON_CMD=$cmd && PYTHON_VER=$ver && return 0
        fi
    done
    return 1
}

detect_os() {
    OS=$(uname -s); KERNEL=$(uname -r)
    if [ -f /etc/os-release ]; then
        . /etc/os-release; DISTRO="$NAME ($VERSION_ID)"
    elif [ -f /etc/redhat-release ]; then
        DISTRO=$(cat /etc/redhat-release)
    elif [ -f /etc/debian_version ]; then
        DISTRO="Debian-based"
    else
        DISTRO="$OS $KERNEL"
    fi
    if command -v apt-get &>/dev/null; then PKG_MGR="apt"
    elif command -v dnf &>/dev/null; then PKG_MGR="dnf"
    elif command -v pacman &>/dev/null; then PKG_MGR="pacman"
    elif command -v zypper &>/dev/null; then PKG_MGR="zypper"
    fi
}

# ── Dependency installer ───────────────────────────────────────────────────────
install_deps() {
    log_info "System package manager detected: ${C_BOLD}$PKG_MGR${C_RESET}"
    case "$PKG_MGR" in
        apt)
            (set -x; sudo apt-get update -qq) 2>/dev/null
            (set -x; sudo apt-get install -y -qq python3 python3-venv python3-pip git curl) 2>/dev/null
            ;;
        dnf)
            (set -x; sudo dnf install -y python3 python3-pip git curl) 2>/dev/null
            ;;
        pacman)
            (set -x; sudo pacman -Sy --noconfirm python python-pip git curl) 2>/dev/null
            ;;
        zypper)
            (set -x; sudo zypper install -y python3 python3-pip git curl) 2>/dev/null
            ;;
        *)
            log_warn "No supported package manager found. Please install Python 3.8+ and git manually."
            return 1
            ;;
    esac
}

# ── Copy files ─────────────────────────────────────────────────────────────────
copy_files() {
    local src="$SRC_DIR"; local dst="$INSTALL_DIR"
    log_info "Source: $src"
    log_info "Destination: $dst"
    mkdir -p "$dst"/{core,db,static,templates,uploads}

    local files=(
        app.py:app.py
        requirements-windows.txt:requirements.txt
        install.sh:install.sh
        setup.sh:setup.sh
        icon.ico:icon.ico
        ARCHITECTURE.md:ARCHITECTURE.md
    )
    local dirs=(core db static templates uploads)

    for item in "${files[@]}"; do
        local src_f="${item%%:*}"; local dst_f="${item#*:}"
        [ -f "$src/$src_f" ] && cp "$src/$src_f" "$dst/$dst_f" && log_ok "Copied: $dst_f"
    done
    for dir in "${dirs[@]}"; do
        [ -d "$src/$dir" ] && { rm -rf "$dst/$dir"; cp -r "$src/$dir" "$dst/"; log_ok "Copied: $dir/"; }
    done
}

# ── Build Python venv ───────────────────────────────────────────────────────────
build_venv() {
    local py="$INSTALL_DIR/.venv/bin/python"
    if [ -d "$INSTALL_DIR/.venv" ]; then
        log_warn "Virtual environment already exists — skipping creation"
    else
        log_info "Creating Python virtual environment..."
        $PYTHON_CMD -m venv "$INSTALL_DIR/.venv" 2>/dev/null && log_ok "Virtual environment created" || { log_fail "venv creation failed"; return 1; }
    fi
    $py -m pip install --upgrade pip -q 2>/dev/null && log_ok "pip upgraded"
}

# ── Install Python packages ────────────────────────────────────────────────────
install_packages() {
    local pip="$INSTALL_DIR/.venv/bin/pip"
    log_info "Installing Python packages (Flask, pandas, openpyxl, etc.)..."
    $pip install -r "$INSTALL_DIR/requirements.txt" -q 2>&1 | grep -v "^$" || true
    $pip show flask &>/dev/null && log_ok "Python packages installed" || log_warn "Some packages may have failed — check with: $pip show flask"
}

# ── Create launcher scripts ─────────────────────────────────────────────────────
create_scripts() {
    cat > "$INSTALL_DIR/start.sh" << 'SCRIPT'
#!/bin/bash
# Dispatch — Start Server
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source .venv/bin/activate
exec .venv/bin/python app.py --port $PORT
SCRIPT
    chmod +x "$INSTALL_DIR/start.sh"
    log_ok "Created: start.sh"

    cat > "$INSTALL_DIR/dispatch.sh" << 'SCRIPT'
#!/bin/bash
# Dispatch — Quick start (background)
cd "$(dirname "${BASH_SOURCE[0]}")"
./start.sh &>/dev/null &
echo "Dispatch started. View logs: tail -f ~/Dispatch/app.log"
SCRIPT
    chmod +x "$INSTALL_DIR/dispatch.sh"
    log_ok "Created: dispatch.sh"
}

# ── Systemd service ───────────────────────────────────────────────────────────────
create_service() {
    mkdir -p "$REAL_HOME/.config/systemd/user"
    cat > "$REAL_HOME/.config/systemd/user/dispatch.service" << EOF
[Unit]
Description=Dispatch MIS Email System
Documentation=https://github.com/sumishsparayil/dispatch
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/app.py --port $PORT
Restart=on-failure
RestartSec=10
Environment=PORT=$PORT

# Logging
StandardOutput=append:$INSTALL_DIR/app.log
StandardError=append:$INSTALL_DIR/app.log

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable dispatch.service 2>/dev/null || true
    log_ok "Systemd service installed and enabled"
}

# ── Final verification ─────────────────────────────────────────────────────────
verify() {
    local py="$INSTALL_DIR/.venv/bin/python"; local ok=0
    log_info "Verifying Python packages..."
    for pkg in flask werkzeug pandas openpyxl waitress; do
        $py -c "import $pkg" 2>/dev/null && log_ok "$pkg" || { log_fail "$pkg"; ok=1; }
    done
    [ $ok -eq 0 ] && log_ok "All packages verified" || log_warn "Some packages failed — run manually: $INSTALL_DIR/.venv/bin/pip install -r $INSTALL_DIR/requirements.txt"
    return $ok
}

# ── Start app ───────────────────────────────────────────────────────────────────
start_app() {
    log_info "Starting Dispatch on port ${C_BOLD}$PORT${C_RESET}..."
    if systemctl --user start dispatch.service 2>/dev/null; then
        log_ok "Service started (systemd)"
    else
        nohup "$INSTALL_DIR/start.sh" > "$INSTALL_DIR/app.log" 2>&1 &
        sleep 2
        log_ok "Process started (background)"
    fi
    sleep 2
    local code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$PORT/ 2>/dev/null || echo "000")
    [ "$code" = "200" ] && log_ok "Web app responding on http://localhost:$PORT" || log_warn "App may still be starting — check: curl http://localhost:$PORT"
}

# ── Unattended flow ─────────────────────────────────────────────────────────────
unattended_flow() {
    banner
    echo -e "  ${C_BOLD}Unattended install${C_RESET}  ·  Install dir: ${C_CYAN}$INSTALL_DIR${C_RESET}  ·  Port: ${C_CYAN}$PORT${C_RESET}"
    echo ""

    detect_os
    install_deps

    log_info "Cloning Dispatch repository..."
    mkdir -p "$INSTALL_DIR"
    git clone --depth=1 "$REPO" "$INSTALL_DIR" 2>/dev/null || git -C "$INSTALL_DIR" pull origin main 2>/dev/null || true
    copy_files
    build_venv
    install_packages
    create_scripts
    create_service
    start_app
    verify

    echo ""
    echo -e "${C_GREEN}══════════════════════════════════════════════════════${C_RESET}"
    echo -e "${C_GREEN}  ✓  Dispatch installed successfully!${C_RESET}"
    echo -e "${C_GREEN}══════════════════════════════════════════════${C_RESET}"
    echo ""
    echo -e "  ${C_BOLD}URL:${C_RESET}        ${C_CYAN}http://localhost:$PORT${C_RESET}"
    echo -e "  ${C_BOLD}Start:${C_RESET}      systemctl --user start dispatch"
    echo -e "  ${C_BOLD}Logs:${C_RESET}       tail -f $INSTALL_DIR/app.log"
    echo ""
}

# ── Interactive flow ────────────────────────────────────────────────────────────
welcome() {
    banner
    echo -e "  ${C_BOLD}This installer will:${C_RESET}"
    echo ""
    echo -e "  ${C_CYAN} 1${C_RESET}  Detect your OS and install Python 3.8+ if needed"
    echo -e "  ${C_CYAN} 2${C_RESET}  Clone Dispatch from GitHub to your home folder"
    echo -e "  ${C_CYAN} 3${C_RESET}  Set up a Python virtual environment"
    echo -e "  ${C_CYAN} 4${C_RESET}  Install Flask, pandas, openpyxl, and other dependencies"
    echo -e "  ${C_CYAN} 5${C_RESET}  Create launcher scripts (start.sh, dispatch.sh)"
    echo -e "  ${C_CYAN} 6${C_RESET}  Install a systemd service (auto-starts on boot)"
    echo -e "  ${C_CYAN} 7${C_RESET}  Verify everything and start the web app"
    echo ""
    echo -e "  ${C_YELLOW}NOTE: You need an internet connection for this installer to work.${C_RESET}"
    echo ""
    prompt "Press ENTER to begin... "; read; echo ""
}

step_prereqs() {
    log_step "System Prerequisites"
    detect_os
    log_info "Operating system: ${C_BOLD}$DISTRO${C_RESET}"
    log_info "Kernel: ${C_BOLD}$KERNEL${C_RESET}"
    log_info "Package manager: ${C_BOLD}${PKG_MGR:-none}${C_RESET}"
    echo ""

    if check_python; then
        log_ok "Python $PYTHON_VER found: ${C_BOLD}$PYTHON_CMD${C_RESET}"
    else
        log_warn "Python 3.8+ not found. Will install via package manager."
        [ -z "$PKG_MGR" ] && { log_fail "No supported package manager. Please install Python 3.8+ manually."; exit 1; }
    fi

    if check_git; then
        log_ok "git found"
    else
        log_warn "git not found. Will install via package manager."
    fi

    if check_internet; then
        log_ok "Internet connection active"
    else
        log_fail "No internet connection detected. Please check your network and try again."
        exit 1
    fi

    [ "$UNATTENDED" = false ] && wait_key
}

step_install_packages() {
    log_step "System Packages"
    if check_python && check_git; then
        log_info "All required tools present — skipping system package install."
    else
        log_info "Installing system packages..."
        install_deps
    fi
    [ "$UNATTENDED" = false ] && wait_key
}

step_clone() {
    log_step "Clone Repository"
    [ "$CUSTOM_DIR" = false ] && {
        echo "  Dispatch will be installed to:"
        echo -e "    ${C_BOLD}$INSTALL_DIR${C_RESET}"
        echo ""
        prompt "Enter a custom path or press ENTER to accept: "
        read -r input
        [ -n "$input" ] && INSTALL_DIR="${input/#\~/$REAL_HOME}"
    }

    mkdir -p "$INSTALL_DIR"

    if [ -d "$INSTALL_DIR/.git" ]; then
        log_ok "Repository already present — pulling latest..."
        git -C "$INSTALL_DIR" pull origin main 2>/dev/null || log_warn "Could not pull — using existing files"
    else
        log_info "Cloning Dispatch from GitHub..."
        git clone --depth=1 "$REPO" "$INSTALL_DIR" 2>/dev/null || { log_fail "Clone failed. Check internet and try again."; exit 1; }
        log_ok "Repository cloned"
    fi

    copy_files
    [ "$UNATTENDED" = false ] && wait_key
}

step_venv() {
    log_step "Python Virtual Environment"
    build_venv
    [ "$UNATTENDED" = false ] && wait_key
}

step_packages() {
    log_step "Python Dependencies"
    install_packages
    [ "$UNATTENDED" = false ] && wait_key
}

step_scripts() {
    log_step "Launcher Scripts"
    create_scripts
    echo ""
    echo -e "  ${C_BOLD}What these do:${C_RESET}"
    echo -e "  ${C_CYAN}start.sh${C_RESET}    — Starts the web app (normal use)"
    echo -e "  ${C_CYAN}dispatch.sh${C_RESET}  — Starts the web app in background (silent)"
    [ "$UNATTENDED" = false ] && wait_key
}

step_service() {
    log_step "Systemd Service (Auto-Start)"
    echo "  This registers a user-level systemd service that:"
    echo -e "    ${C_GREEN}✓${C_RESET}  Starts automatically on every system reboot"
    echo -e "    ${C_GREEN}✓${C_RESET}  Restarts automatically if it crashes"
    echo -e "    ${C_GREEN}✓${C_RESET}  Runs in the background without a terminal"
    echo ""
    [ "$UNATTENDED" = false ] && {
        prompt "Install systemd service? [Y/n]: "; read -r confirm
        [ "${confirm,,}" = "n" ] && { log_info "Skipped — you can run ./start.sh manually instead."; return; }
    }
    create_service
    [ "$UNATTENDED" = false ] && wait_key
}

step_port() {
    log_step "Network Configuration"
    echo "  Dispatch runs as a local web app on a port of your choosing."
    echo "  Choose a port that is not used by another application."
    echo ""
    echo -e "  Suggestions:  ${C_DIM}5000 (default)  ·  5100  ·  8080  ·  3000${C_RESET}"
    echo -e "  Avoid:        ${C_DIM}80  ·  443  ·  22  (system ports below 1024)${C_RESET}"
    echo ""
    [ "$CUSTOM_PORT" = false ] && {
        prompt "Enter port number or press ENTER for default (5000): "
        read -r input
        if [ -n "$input" ]; then
            if [[ "$input" =~ ^[0-9]+$ ]] && [ "$input" -gt 1024 ] && [ "$input" -lt 65535 ]; then
                PORT=$input; log_ok "Port set to $PORT"
            else
                log_fail "Invalid port. Must be 1025–65535. Using default 5000."
                PORT=5000
            fi
        else
            log_ok "Using default port: 5000"
        fi
    }
    [ "$UNATTENDED" = false ] && wait_key
}

step_start() {
    log_step "Start Dispatch"
    verify
    start_app
    [ "$UNATTENDED" = false ] && wait_key
}

# ── Summary ─────────────────────────────────────────────────────────────────────
summary() {
    banner
    echo -e "${C_GREEN}═══════════════════════════════════════════════════════════════${C_RESET}"
    echo -e "${C_GREEN}        ✓  Installation Complete!${C_RESET}"
    echo -e "${C_GREEN}═══════════════════════════════════════════════════════════════${C_RESET}"
    echo ""
    echo -e "  ${C_BOLD}URL:${C_RESET}        ${C_CYAN}http://localhost:$PORT${C_RESET}"
    echo -e "  ${C_BOLD}Location:${C_RESET}  ${C_CYAN}$INSTALL_DIR${C_RESET}"
    echo -e "  ${C_BOLD}Port:${C_RESET}      ${C_CYAN}$PORT${C_RESET}"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────┐"
    echo "  │  HOW TO USE                                             │"
    echo "  │                                                         │"
    echo "  │  Web app:   ${C_CYAN}http://localhost:$PORT${C_RESET}                  │"
    echo "  │                                                         │"
    echo "  │  Start:     systemctl --user start dispatch            │"
    echo "  │  Stop:      systemctl --user stop dispatch             │"
    echo "  │  Restart:   systemctl --user restart dispatch          │"
    echo "  │  Status:    systemctl --user status dispatch          │"
    echo "  │  Logs:      tail -f $INSTALL_DIR/app.log                │"
    echo "  │                                                         │"
    echo "  │  Manual:    cd $INSTALL_DIR && ./start.sh              │"
    echo "  └─────────────────────────────────────────────────────────┘"
    echo ""
    echo -e "  ${C_DIM}To change port:  edit ~/.config/systemd/user/dispatch.service${C_RESET}"
    echo -e "  ${C_DIM}and set Environment=PORT=<new_port>, then:\n                systemctl --user daemon-reload && systemctl --user restart dispatch${C_RESET}"
    echo ""
    echo -e "  ${C_DIM}To uninstall:  systemctl --user stop dispatch && \\"
    echo "                 systemctl --user disable dispatch && \\"
    echo "                 rm -rf $INSTALL_DIR${C_RESET}"
    echo ""
}

# ── Main ───────────────────────────────────────────────────────────────────────
main() {
    if [ "$UNATTENDED" = true ]; then
        unattended_flow
        return
    fi

    welcome
    step_prereqs
    step_install_packages
    step_clone
    step_venv
    step_packages
    step_scripts
    step_service
    step_port
    step_start
    summary
}

main "$@"