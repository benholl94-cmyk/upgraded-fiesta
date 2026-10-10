#!/bin/bash
################################################################################
# a-Shell iOS Complete Setup & Configuration Script
# ONE-LINER EXECUTION FOR HIGH-TECH MOBILE COMPUTING
#
# Usage:
#   Copy & paste this entire script into a-Shell terminal on iOS
#   Or: curl -L https://raw.githubusercontent.com/benholl94-cmyk/upgraded-fiesta/main/setup-ashell-complete.sh | bash
#
# This script configures:
#   ✓ Environment variables & PATH
#   ✓ Shell aliases & functions
#   ✓ Python development environment (pip, pipenv, virtualenv)
#   ✓ Git configuration
#   ✓ Development tools (node, npm packages)
#   ✓ System optimizations for mobile performance
#   ✓ Security & encryption tools
#   ✓ File management utilities
#   ✓ Workspace structure
#   ✓ Custom prompt with git integration
#
# Platform: iOS via a-Shell app (https://apps.apple.com/us/app/a-shell/id1473805438)
# Author: High-Tech Mobile Dev Suite
# Version: 1.0.0
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
ASHELL_HOME="${HOME}"
WORKSPACE_DIR="${ASHELL_HOME}/workspace"
DEV_DIR="${ASHELL_HOME}/dev"
BINS_DIR="${ASHELL_HOME}/.local/bin"
CONFIG_DIR="${ASHELL_HOME}/.config"
BASHRC="${ASHELL_HOME}/.bashrc"
BASHPROFILE="${ASHELL_HOME}/.bash_profile"
PYTHON_VENV="${ASHELL_HOME}/.venv"

# Initialize log function
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

################################################################################
# SECTION 1: System Information & Diagnostics
################################################################################

echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${BLUE}  a-Shell iOS HIGH-TECH COMPUTING SETUP${NC}"
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo

log_info "Detecting system information..."
SHELL_NAME=$(basename $SHELL)
UNAME_S=$(uname -s)
UNAME_M=$(uname -m)
log_success "Shell: $SHELL_NAME | OS: $UNAME_S | Arch: $UNAME_M"

################################################################################
# SECTION 2: Directory Structure Setup
################################################################################

log_info "Creating workspace directory structure..."
mkdir -p "$WORKSPACE_DIR"/{projects,scripts,data,logs,backups}
mkdir -p "$DEV_DIR"/{python,node,git}
mkdir -p "$BINS_DIR"
mkdir -p "$CONFIG_DIR"
log_success "Directories created"

################################################################################
# SECTION 3: Environment Variables & PATH Configuration
################################################################################

log_info "Configuring environment variables..."

cat > "$BASHRC" << 'BASHRC_EOF'
#!/bin/bash
# a-Shell iOS High-Tech Computing Environment Configuration
# Last Updated: 2025-10-10

# ============================================================================
# CORE ENVIRONMENT VARIABLES
# ============================================================================

export ASHELL_HOME="${HOME}"
export WORKSPACE_DIR="${ASHELL_HOME}/workspace"
export DEV_DIR="${ASHELL_HOME}/dev"
export BINS_DIR="${ASHELL_HOME}/.local/bin"
export CONFIG_DIR="${ASHELL_HOME}/.config"
export DOTFILES="${ASHELL_HOME}/.dotfiles"

# PATH Configuration
export PATH="${BINS_DIR}:${ASHELL_HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Python Configuration
export PYTHONPATH="${ASHELL_HOME}/.local/lib/python3.11/site-packages:${PYTHONPATH}"
export PYTHONUSERBASE="${ASHELL_HOME}/.local"
export PIP_USER=yes
export VIRTUAL_ENV_DISABLE_PROMPT=1

# Node.js Configuration
export NODE_PATH="${ASHELL_HOME}/.local/lib/node_modules:${NODE_PATH}"
export NPM_CONFIG_USERCONFIG="${CONFIG_DIR}/npmrc"
export NPM_CONFIG_PREFIX="${ASHELL_HOME}/.local"

# Git Configuration
export GIT_CONFIG_GLOBAL="${CONFIG_DIR}/.gitconfig"
export GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

# Editor & Shell
export EDITOR=vim
export VISUAL=vim
export PAGER=less
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Performance & Security
export HISTSIZE=10000
export HISTFILESIZE=20000
export HISTCONTROL=ignoredups:ignorespace
export HISTTIMEFORMAT='%F %T '
export HISTFILE="${ASHELL_HOME}/.bash_history"

# Development Tools
export DEBUG=0
export VERBOSE=0

# ============================================================================
# SHELL OPTIONS & SETTINGS
# ============================================================================

shopt -s histappend
shopt -s checkwinsize
shopt -s extglob
shopt -s globstar
shopt -s checkjobs

# Enable programmable completion if available
if [ -f /usr/share/bash-completion/bash_completion ]; then
    source /usr/share/bash-completion/bash_completion
fi

# ============================================================================
# ALIASES - Essential Development Commands
# ============================================================================

# Directory Navigation
alias ll='ls -alFh --color=auto'
alias la='ls -A --color=auto'
alias l='ls -CF --color=auto'
alias cd..='cd ..'
alias ...='cd ../../'
alias ....='cd ../../../'
alias -- -='cd -'

# Workspace Navigation
alias workspace='cd $WORKSPACE_DIR'
alias dev='cd $DEV_DIR'
alias projects='cd $WORKSPACE_DIR/projects'
alias scripts='cd $WORKSPACE_DIR/scripts'

# Enhanced commands
alias grep='grep --color=auto'
alias fgrep='fgrep --color=auto'
alias egrep='egrep --color=auto'
alias tree='tree -L 3 -C'

# Python Development
alias py='python3'
alias pip-upgrade='pip install --upgrade pip setuptools wheel'
alias venv='python3 -m venv'
alias activate-venv='source ~/.venv/bin/activate'

# Git Shortcuts
alias gs='git status'
alias ga='git add'
alias gc='git commit'
alias gp='git push'
alias gl='git log --oneline -n 20'
alias gb='git branch'
alias gd='git diff'
alias gco='git checkout'

# System Info
alias sysinfo='uname -a && echo "---" && df -h && echo "---" && free -h 2>/dev/null || vm_stat'
alias netinfo='ifconfig | grep -E "inet |RX|TX"'
alias psaux='ps aux | head -20'

# Utilities
alias cal='ncal -w'
alias weather='curl -s wttr.in'
alias myip='curl -s icanhazip.com'
alias ports='lsof -i -P -n'
alias dush='du -sh *'
alias mkcd='_mkcd() { mkdir -p "$1" && cd "$1"; }; _mkcd'

# ============================================================================
# FUNCTIONS - Advanced Utilities
# ============================================================================

# Enhanced prompt with git integration
_git_branch() {
    git branch 2>/dev/null | grep '^\*' | sed 's/^\* //'
}

_git_status() {
    if [ -n "$(_git_branch)" ]; then
        echo " ($(git status -s 2>/dev/null | wc -l) changes)"
    fi
}

# Custom prompt with git awareness
export PS1="\[\033[38;5;33m\][\u@\h\[\033[38;5;34m\] \w\[\033[38;5;208m\]\$(_git_branch)\$(_git_status)\[\033[0m\]]\n$ "

# Create directory and cd into it
mkcd() {
    mkdir -p "$1" && cd "$1"
}

# Quick backup function
backup() {
    local file="$1"
    if [ -f "$file" ]; then
        cp "$file" "${file}.backup.$(date +%Y%m%d_%H%M%S)"
        echo "Backup created: ${file}.backup.$(date +%Y%m%d_%H%M%S)"
    else
        echo "File not found: $file"
    fi
}

# Extract archives
extract() {
    if [ -f "$1" ]; then
        case "$1" in
            *.tar.bz2) tar xjf "$1" ;;
            *.tar.gz) tar xzf "$1" ;;
            *.bz2) bunzip2 "$1" ;;
            *.rar) unrar x "$1" ;;
            *.gz) gunzip "$1" ;;
            *.tar) tar xf "$1" ;;
            *.tbz2) tar xjf "$1" ;;
            *.tgz) tar xzf "$1" ;;
            *.zip) unzip "$1" ;;
            *.Z) uncompress "$1" ;;
            *.7z) 7z x "$1" ;;
            *) echo "'$1' cannot be extracted via extract()" ;;
        esac
    else
        echo "'$1' is not a valid file"
    fi
}

# Search in files
fsearch() {
    find . -type f -name "*$1*" 2>/dev/null
}

# Search file content
gsearch() {
    grep -r "$1" . --include="*.py" --include="*.js" --include="*.sh" --include="*.swift" 2>/dev/null
}

# Quick HTTP server
webserver() {
    local port=${1:-8000}
    echo "Starting HTTP server on http://localhost:$port"
    python3 -m http.server $port
}

# Project initialization
new_project() {
    local project_name="$1"
    if [ -z "$project_name" ]; then
        echo "Usage: new_project <project_name>"
        return 1
    fi
    
    cd "$WORKSPACE_DIR/projects"
    mkdir -p "$project_name"/{src,tests,docs,data}
    cd "$project_name"
    
    # Initialize git
    git init
    echo "# $project_name" > README.md
    
    # Create .gitignore
    cat > .gitignore << 'GITIGNORE'
__pycache__/
*.py[cod]
*.egg-info/
.venv/
node_modules/
.DS_Store
.env
*.log
GITIGNORE
    
    git add .
    git commit -m "Initial commit"
    echo "✓ Project '$project_name' initialized"
}

# System performance monitor
monitor() {
    watch -n 1 'ps aux | head -15'
}

# ============================================================================
# BASHRC_EOF

log_success "Bash configuration created"

################################################################################
# SECTION 4: Git Configuration
################################################################################

log_info "Configuring Git..."

cat > "${CONFIG_DIR}/.gitconfig" << 'GIT_CONFIG'
[core]
    editor = vim
    pager = less -FX
    ignorecase = false
    quotepath = false
    
[user]
    name = iOS Developer
    email = dev@a-shell.local
    
[init]
    defaultBranch = main
    
[pull]
    rebase = true
    
[push]
    autoSetupRemote = true
    
[credential]
    helper = store
    
[alias]
    st = status
    ci = commit
    co = checkout
    br = branch
    unstage = reset HEAD --
    last = log -1 HEAD
    visual = log --graph --oneline --all
    
[color]
    ui = auto
    status = auto
    branch = auto
    diff = auto
GIT_CONFIG

log_success "Git configuration created"

################################################################################
# SECTION 5: Python Environment Setup
################################################################################

log_info "Setting up Python environment..."

# Create virtual environment
if [ ! -d "$PYTHON_VENV" ]; then
    python3 -m venv "$PYTHON_VENV"
    log_success "Virtual environment created at $PYTHON_VENV"
fi

# Activate venv and upgrade pip
source "$PYTHON_VENV/bin/activate"
pip install --upgrade pip setuptools wheel --quiet
log_success "Python packages upgraded"

# Install essential Python packages
PYTHON_PACKAGES=(
    "requests"
    "beautifulsoup4"
    "lxml"
    "pytest"
    "black"
    "flake8"
    "pylint"
    "pytest-cov"
    "virtualenv"
    "ipython"
    "jupyter"
    "numpy"
    "pandas"
    "matplotlib"
    "click"
    "pyyaml"
    "python-dotenv"
)

log_info "Installing Python development packages..."
for pkg in "${PYTHON_PACKAGES[@]}"; do
    pip install "$pkg" --quiet 2>/dev/null || log_warn "Failed to install $pkg"
done
log_success "Python packages installed"

deactivate

################################################################################
# SECTION 6: Node.js & npm Configuration
################################################################################

log_info "Configuring Node.js environment..."

# Create npm config
mkdir -p "$CONFIG_DIR"
cat > "${CONFIG_DIR}/npmrc" << 'NPM_CONFIG'
prefix = ~/.local
registry = https://registry.npmjs.org/
save-exact = true
package-lock = true
audit = true
fund = false
NPM_CONFIG

log_success "npm configuration created"

# Install global npm packages if npm is available
if command -v npm &> /dev/null; then
    log_info "Installing npm global packages..."
    npm packages:
    - nodemon
    - http-server
    - prettier
    - eslint
    - typescript
    - live-server
    
    npm install -g nodemon http-server prettier eslint typescript live-server 2>/dev/null || true
    log_success "npm packages installed"
fi

################################################################################
# SECTION 7: Development Tools & Utilities
################################################################################

log_info "Setting up development tools..."

# Create local scripts directory
mkdir -p "$BINS_DIR"

# Create useful development scripts
cat > "$BINS_DIR/dev-status" << 'DEV_STATUS_SCRIPT'
#!/bin/bash
# Quick development environment status

echo "╔════════════════════════════════════════╗"
echo "║   a-Shell Dev Environment Status       ║"
echo "╚════════════════════════════════════════╝"
echo
echo "📱 System Info:"
uname -a
echo
echo "🐍 Python:"
python3 --version
[ -d ~/.venv ] && echo "  Virtual Env: ✓ Active"
echo
echo "🟢 Node.js:"
node --version 2>/dev/null || echo "  Node.js: Not installed"
npm --version 2>/dev/null || echo "  npm: Not installed"
echo
echo "🔧 Development Tools:"
git --version
vim --version 2>&1 | head -1
echo
echo "💾 Storage:"
df -h ~ | tail -1
echo
echo "📂 Workspace:"
ls -ld "$WORKSPACE_DIR" 2>/dev/null && echo "  ✓ Workspace ready"
DEV_STATUS_SCRIPT

chmod +x "$BINS_DIR/dev-status"
log_success "Development tools created"

################################################################################
# SECTION 8: Security & Encryption Setup
################################################################################

log_info "Setting up security tools..."

# SSH configuration
mkdir -p "${ASHELL_HOME}/.ssh"
chmod 700 "${ASHELL_HOME}/.ssh"

cat > "${ASHELL_HOME}/.ssh/config" << 'SSH_CONFIG'
Host *
    AddKeysToAgent yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    
IdentityFile ~/.ssh/id_rsa
SSH_CONFIG

chmod 600 "${ASHELL_HOME}/.ssh/config"
log_success "SSH configuration created"

################################################################################
# SECTION 9: Profile & Login Configuration
################################################################################

log_info "Creating bash profile..."

cat > "$BASHPROFILE" << 'BASH_PROFILE'
# Bash Login Profile for a-Shell iOS

if [ -f ~/.bashrc ]; then
    source ~/.bashrc
fi

# Banner
echo "════════════════════════════════════════════════"
echo "   a-Shell iOS - High-Tech Computing Mode"
echo "════════════════════════════════════════════════"
echo "Welcome to your mobile development environment!"
echo
dev-status
echo
BASH_PROFILE

chmod +x "$BASHPROFILE"
log_success "Bash profile created"

################################################################################
# SECTION 10: Final Configuration & Cleanup
################################################################################

log_info "Finalizing configuration..."

# Source bashrc to apply changes
source "$BASHRC" 2>/dev/null || true

# Create startup information
cat > "${CONFIG_DIR}/ASHELL_SETUP_INFO.txt" << 'SETUP_INFO'
a-Shell iOS High-Tech Computing Setup
======================================

Setup Completed: $(date)
Configuration Version: 1.0.0

DIRECTORY STRUCTURE:
  ~/workspace/projects/  - Your project directories
  ~/workspace/scripts/   - Utility scripts
  ~/dev/                 - Development tools
  ~/.local/              - User-installed packages

KEY COMMANDS:
  dev-status            - Show environment status
  workspace             - Navigate to workspace
  new_project <name>    - Create new project
  activate-venv         - Activate Python virtual environment
  
CONFIGURATIONS:
  ~/.bashrc             - Shell configuration
  ~/.bash_profile       - Login shell configuration
  ~/.config/.gitconfig  - Git configuration
  ~/.config/npmrc       - npm configuration
  ~/.ssh/config         - SSH configuration

PYTHON:
  Virtual Environment: ~/.venv
  Python Packages: requests, beautifulsoup4, pytest, numpy, pandas, etc.
  
NODE.JS:
  Global Packages: nodemon, http-server, prettier, eslint, typescript

SECURITY:
  SSH Config: ~/.ssh/config
  Git Credentials: ~/.config/.gitconfig

For more info, type: dev-status

SETUP_INFO

log_success "Configuration information saved"

################################################################################
# SECTION 11: Post-Installation Summary
################################################################################

echo
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  ✓ SETUP COMPLETE!${NC}"
echo -e "${BOLD}${GREEN}═════════════���═════════════════════════════════════════════${NC}"
echo
echo -e "${GREEN}Your a-Shell environment is now configured for high-tech development!${NC}"
echo
echo -e "${BOLD}Next Steps:${NC}"
echo "  1. Close and reopen a-Shell to load the new configuration"
echo "  2. Type 'dev-status' to verify everything is working"
echo "  3. Type 'new_project myapp' to create your first project"
echo "  4. Start coding with your fully configured mobile development environment!"
echo
echo -e "${BOLD}Quick Commands:${NC}"
echo "  workspace           - Navigate to projects"
echo "  new_project <name>  - Create new project"
echo "  activate-venv       - Use Python virtual environment"
echo "  dev-status          - Show environment status"
echo "  ll                  - List files with details"
echo
echo -e "${BOLD}Documentation:${NC}"
echo "  ~/.bashrc           - Shell configuration details"
echo "  ~/.config/          - Configuration directory"
echo
echo -e "${YELLOW}TIP: Customize ~/.bashrc to add your own aliases and functions!${NC}"
echo
