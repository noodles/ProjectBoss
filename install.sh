#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PB_PY="$SCRIPT_DIR/pb.py"
BIN_DIR="$HOME/bin"
SYMLINK="$BIN_DIR/pb.py"
PB_DIR="$HOME/.pb"
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
    echo "Updating symlink: $SYMLINK → $PB_PY"
    rm "$SYMLINK"
elif [ -e "$SYMLINK" ]; then
    echo "Warning: $SYMLINK exists and is not a symlink. Backing up..."
    mv "$SYMLINK" "$SYMLINK.bak"
fi
ln -s "$PB_PY" "$SYMLINK"
echo "Symlinked: $SYMLINK → $PB_PY"

# 3. Make executable
chmod +x "$PB_PY"

# 4. Bootstrap ~/.pb/
#    Give pb.py a chance to move ~/.proj across FIRST. Creating the directory
#    here would make the migration refuse, correctly, and leave the data behind.
python3 "$PB_PY" config show >/dev/null 2>&1 || true
if [ ! -d "$PB_DIR" ]; then
    echo "Creating $PB_DIR..."
    mkdir -p "$PB_DIR"
fi

# 5. Init config if it doesn't exist
if [ ! -f "$PB_DIR/config.json" ]; then
    echo "Initializing config..."
    python3 "$PB_PY" config init
fi

# 5b. Clean up the previous name. The tool used to be `proj`, and leaving its
#     symlink and shell function behind means a broken `proj` command forever.
LEGACY_LINK="$BIN_DIR/proj.py"
if [ -L "$LEGACY_LINK" ]; then
    rm "$LEGACY_LINK"
    echo "Removed the old symlink: $LEGACY_LINK"
fi
LEGACY_START="# >>> proj shell function >>>"
LEGACY_END="# <<< proj shell function <<<"
if grep -q "$LEGACY_START" "$ZSHRC" 2>/dev/null; then
    cp "$ZSHRC" "$ZSHRC.pb-backup"
    awk -v s="$LEGACY_START" -v e="$LEGACY_END" '
        $0 == s { skip = 1 }
        skip != 1 { print }
        $0 == e { skip = 0 }
    ' "$ZSHRC.pb-backup" > "$ZSHRC"
    echo "Removed the old proj shell function from $ZSHRC"
fi

# 6. Add (or refresh) shell function in .zshrc
START_MARKER="# >>> pb shell function >>>"
END_MARKER="# <<< pb shell function <<<"
if grep -q "$START_MARKER" "$ZSHRC" 2>/dev/null; then
    echo "Refreshing shell function in $ZSHRC..."
    cp "$ZSHRC" "$ZSHRC.pb-backup"
    # Strip the existing block (inclusive of both markers) before re-adding it,
    # so installs always ship the current function body.
    awk -v s="$START_MARKER" -v e="$END_MARKER" '
        $0 == s { skip = 1 }
        skip != 1 { print }
        $0 == e { skip = 0 }
    ' "$ZSHRC.pb-backup" > "$ZSHRC"
else
    echo "Adding shell function to $ZSHRC..."
fi

cat >> "$ZSHRC" << 'SHELL_FUNC'

# >>> pb shell function >>>
pb() {
    # PB_SHELL_WRAPPER lets pb.py know it can hand back a directory to cd into.
    if [[ "$1" == "open" && "$2" != "--help" && "$2" != "-h" ]]; then
        local target
        target=$(PB_SHELL_WRAPPER=1 command python3 ~/bin/pb.py open "${@:2}" --path-only 2>/dev/null)
        if [[ $? -eq 0 && -n "$target" && -d "$target" ]]; then
            cd "$target" && echo "Opened: $target"
        else
            PB_SHELL_WRAPPER=1 command python3 ~/bin/pb.py open "${@:2}"
        fi
    else
        PB_SHELL_WRAPPER=1 command python3 ~/bin/pb.py "$@"
    fi
    # Handle cd-target signal from pb new
    local cd_target="$HOME/.pb/.cd_target"
    if [[ -f "$cd_target" ]]; then
        local dest
        dest=$(<"$cd_target")
        rm -f "$cd_target"
        if [[ -n "$dest" && -d "$dest" ]]; then
            cd "$dest"
        fi
    fi
}
# <<< pb shell function <<<
SHELL_FUNC
echo "Shell function installed."

# 7. Offer the Claude Code skill. Opt-in: a project CLI has no business writing
#    into an agent's config directory unless the user asks for it.
SKILL_SRC="$SCRIPT_DIR/skills/pb/SKILL.md"
SKILL_DIR="$HOME/.claude/skills/pb"
if [ -f "$SKILL_SRC" ]; then
    echo
    echo "Optional: a Claude Code skill so agents can look up your projects with pb."
    echo "It installs one markdown file to $SKILL_DIR/SKILL.md."
    REPLY=""
    if [ -t 0 ]; then
        printf "Install it? [y/N]: "
        read -r REPLY
    else
        echo "(no terminal to ask on, skipping)"
    fi
    case "$REPLY" in
        [Yy]*)
            mkdir -p "$SKILL_DIR"
            ln -sf "$SKILL_SRC" "$SKILL_DIR/SKILL.md"
            echo "Skill linked: $SKILL_DIR/SKILL.md"
            ;;
        *)
            echo "Skipped. Link it later with:"
            echo "  mkdir -p $SKILL_DIR && ln -s $SKILL_SRC $SKILL_DIR/SKILL.md"
            ;;
    esac
fi

echo
echo "=== Installation complete ==="
echo
echo "Next steps:"
echo "  1. source ~/.zshrc      (or open a new terminal)"
echo "  2. pb config show     (verify config)"
echo "  3. pb new             (create your first project)"
