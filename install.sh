#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ_PY="$SCRIPT_DIR/proj.py"
BIN_DIR="$HOME/bin"
SYMLINK="$BIN_DIR/proj.py"
PROJ_DIR="$HOME/.proj"
ZSHRC="$HOME/.zshrc"

echo "=== ProjectBoss Installer ==="
echo

# 1. Ensure ~/bin exists
if [ ! -d "$BIN_DIR" ]; then
    echo "Creating $BIN_DIR..."
    mkdir -p "$BIN_DIR"
fi

# 2. Create/update symlink
if [ -L "$SYMLINK" ]; then
    echo "Updating symlink: $SYMLINK → $PROJ_PY"
    rm "$SYMLINK"
elif [ -e "$SYMLINK" ]; then
    echo "Warning: $SYMLINK exists and is not a symlink. Backing up..."
    mv "$SYMLINK" "$SYMLINK.bak"
fi
ln -s "$PROJ_PY" "$SYMLINK"
echo "Symlinked: $SYMLINK → $PROJ_PY"

# 3. Make executable
chmod +x "$PROJ_PY"

# 4. Bootstrap ~/.proj/
if [ ! -d "$PROJ_DIR" ]; then
    echo "Creating $PROJ_DIR..."
    mkdir -p "$PROJ_DIR"
fi

# 5. Init config if it doesn't exist
if [ ! -f "$PROJ_DIR/config.json" ]; then
    echo "Initializing config..."
    python3 "$PROJ_PY" config init
fi

# 6. Add (or refresh) shell function in .zshrc
START_MARKER="# >>> proj shell function >>>"
END_MARKER="# <<< proj shell function <<<"
if grep -q "$START_MARKER" "$ZSHRC" 2>/dev/null; then
    echo "Refreshing shell function in $ZSHRC..."
    cp "$ZSHRC" "$ZSHRC.proj-backup"
    # Strip the existing block (inclusive of both markers) before re-adding it,
    # so installs always ship the current function body.
    awk -v s="$START_MARKER" -v e="$END_MARKER" '
        $0 == s { skip = 1 }
        skip != 1 { print }
        $0 == e { skip = 0 }
    ' "$ZSHRC.proj-backup" > "$ZSHRC"
else
    echo "Adding shell function to $ZSHRC..."
fi

cat >> "$ZSHRC" << 'SHELL_FUNC'

# >>> proj shell function >>>
proj() {
    # PROJ_SHELL_WRAPPER lets proj.py know it can hand back a directory to cd into.
    if [[ "$1" == "open" && "$2" != "--help" && "$2" != "-h" ]]; then
        local target
        target=$(PROJ_SHELL_WRAPPER=1 command python3 ~/bin/proj.py open "${@:2}" --path-only 2>/dev/null)
        if [[ $? -eq 0 && -n "$target" && -d "$target" ]]; then
            cd "$target" && echo "Opened: $target"
        else
            PROJ_SHELL_WRAPPER=1 command python3 ~/bin/proj.py open "${@:2}"
        fi
    else
        PROJ_SHELL_WRAPPER=1 command python3 ~/bin/proj.py "$@"
    fi
    # Handle cd-target signal from proj new
    local cd_target="$HOME/.proj/.cd_target"
    if [[ -f "$cd_target" ]]; then
        local dest
        dest=$(<"$cd_target")
        rm -f "$cd_target"
        if [[ -n "$dest" && -d "$dest" ]]; then
            cd "$dest"
        fi
    fi
}
# <<< proj shell function <<<
SHELL_FUNC
echo "Shell function installed."

echo
echo "=== Installation complete ==="
echo
echo "Next steps:"
echo "  1. source ~/.zshrc      (or open a new terminal)"
echo "  2. proj config show     (verify config)"
echo "  3. proj new             (create your first project)"
