#!/usr/bin/env bash
#
# install.sh -- Install ClaudePanes to a user-local PATH directory.
#
# Copies claude_panes.py to $INSTALL_PATH (default: $HOME/.local/bin) and
# creates a `claude-panes` shell wrapper so the tool can be invoked by name.
# Also creates $HOME/.config/claude-panes/layouts/ if it does not exist.
#
# The script is conservative: it does NOT modify your shell rc files or PATH.
# If the install directory is not on PATH, it prints the export line for you
# to copy-paste into your shell's rc file.
#
# Usage:
#     ./install.sh                       # install to ~/.local/bin
#     ./install.sh -p /opt/bin           # install to /opt/bin
#     INSTALL_PATH=/opt/bin ./install.sh # install to /opt/bin (env var)

set -euo pipefail

# --- Parse args ---------------------------------------------------------------

INSTALL_PATH="${INSTALL_PATH:-$HOME/.local/bin}"

while [ $# -gt 0 ]; do
    case "$1" in
        -p)
            if [ $# -lt 2 ]; then
                echo "Error: -p requires a path argument" >&2
                exit 1
            fi
            INSTALL_PATH="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-p <install-path>]"
            echo "  -p <path>   Install directory (default: \$HOME/.local/bin)"
            echo "  Or set INSTALL_PATH=<path> in the environment."
            exit 0
            ;;
        *)
            echo "Error: unknown argument '$1'" >&2
            exit 1
            ;;
    esac
done

# --- 1. Python 3.11+ check ----------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found on PATH. Install Python 3.11+ and try again." >&2
    exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
    detected="$(python3 --version 2>&1 || true)"
    echo "Error: Python 3.11+ is required. Detected: $detected" >&2
    exit 1
fi

echo "Found $(python3 --version 2>&1)"

# --- 2. Resolve source script -------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_SCRIPT="$SCRIPT_DIR/claude_panes.py"

if [ ! -f "$SOURCE_SCRIPT" ]; then
    echo "Error: claude_panes.py not found next to install.sh (expected: $SOURCE_SCRIPT)" >&2
    exit 1
fi

# --- 3. Ensure install directory exists ---------------------------------------

if [ ! -d "$INSTALL_PATH" ]; then
    echo "Creating install directory: $INSTALL_PATH"
    mkdir -p "$INSTALL_PATH"
fi

# --- 4. Copy script + create wrapper ------------------------------------------

TARGET_SCRIPT="$INSTALL_PATH/claude_panes.py"
TARGET_WRAPPER="$INSTALL_PATH/claude-panes"

cp "$SOURCE_SCRIPT" "$TARGET_SCRIPT"
echo "Installed: $TARGET_SCRIPT"

# The wrapper resolves its own directory so it works regardless of how the
# user invokes it (full path, via PATH lookup, symlink, etc.).
cat > "$TARGET_WRAPPER" <<'EOF'
#!/usr/bin/env bash
exec python3 "$(dirname "$0")/claude_panes.py" "$@"
EOF
chmod 755 "$TARGET_WRAPPER"
echo "Installed: $TARGET_WRAPPER"

# --- 5. PATH advisory (never mutate rc files) ---------------------------------

case ":$PATH:" in
    *":$INSTALL_PATH:"*)
        on_path=1
        ;;
    *)
        on_path=0
        ;;
esac

if [ "$on_path" -eq 0 ]; then
    # Detect the user's shell to suggest the right rc file. SHELL may be unset
    # in some environments (cron, containers); fall back to a generic message.
    user_shell="$(basename "${SHELL:-}")"
    case "$user_shell" in
        zsh)  rc_file="$HOME/.zshrc" ;;
        bash) rc_file="$HOME/.bashrc" ;;
        fish) rc_file="$HOME/.config/fish/config.fish" ;;
        *)    rc_file="your shell's rc file" ;;
    esac

    echo ""
    echo "NOTE: $INSTALL_PATH is not on your PATH."
    if [ "$user_shell" = "fish" ]; then
        echo "Add this line to $rc_file:"
        echo ""
        echo "    set -gx PATH \"$INSTALL_PATH\" \$PATH"
    else
        echo "Add this line to $rc_file:"
        echo ""
        echo "    export PATH=\"$INSTALL_PATH:\$PATH\""
    fi
    echo ""
    echo "Then open a new shell or 'source' the file."
fi

# --- 6. Layouts config directory ----------------------------------------------

LAYOUTS_DIR="$HOME/.config/claude-panes/layouts"
if [ ! -d "$LAYOUTS_DIR" ]; then
    mkdir -p "$LAYOUTS_DIR"
    echo "Created layouts directory: $LAYOUTS_DIR"
else
    echo "Layouts directory already exists: $LAYOUTS_DIR"
fi

# --- 7. Success summary -------------------------------------------------------

echo ""
echo "ClaudePanes installed successfully."
echo "  Script:   $TARGET_SCRIPT"
echo "  Wrapper:  $TARGET_WRAPPER"
echo "  Layouts:  $LAYOUTS_DIR"
echo ""
echo "Smoke test (after PATH is set):"
echo "    claude-panes --help"
