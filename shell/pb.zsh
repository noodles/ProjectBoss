# The pb shell function.
#
# pb itself cannot change your shell's directory: a child process never can.
# This wrapper asks pb where to go and does the `cd` on its behalf, which is
# what makes `pb open` and the offer at the end of `pb new` work.
#
# Sourced by install.sh (which copies it into ~/.zshrc) and by the Homebrew
# formula (which leaves it in place for you to source). One copy, either way.
#
#   source /path/to/pb.zsh

pb() {
    # PB_SHELL_WRAPPER tells pb it can hand a directory back to be changed into.
    if [[ "$1" == "open" && "$2" != "--help" && "$2" != "-h" ]]; then
        local target
        target=$(PB_SHELL_WRAPPER=1 command pb open "${@:2}" --path-only 2>/dev/null)
        if [[ $? -eq 0 && -n "$target" && -d "$target" ]]; then
            cd "$target" && echo "Opened: $target"
        else
            PB_SHELL_WRAPPER=1 command pb open "${@:2}"
        fi
    else
        PB_SHELL_WRAPPER=1 command pb "$@"
    fi

    # `pb new` leaves the new project's path here when you ask to cd into it.
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
