#!/bin/bash
# Records the demo GIF. Run from the repository root:
#
#     bash demo/record.sh
#
# Everything happens against a throwaway home directory, so the recording can
# never show real projects, and re-running produces the same session.
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEMO_HOME="/tmp/pb-demo-home"
CAST="$REPO/demo/pb.cast"
GIF="$REPO/demo/pb.gif"

for tool in asciinema agg; do
    command -v "$tool" >/dev/null || { echo "Missing $tool (brew install $tool)"; exit 1; }
done

bash "$REPO/demo/setup.sh" "$DEMO_HOME"

rm -f "$CAST"
HOME="$DEMO_HOME" PATH="$DEMO_HOME/bin:$PATH" TERM=xterm-256color \
    asciinema rec --window-size 100x24 --overwrite \
    -c "bash $REPO/demo/session.sh" "$CAST"

agg --font-size 22 --theme dracula --speed 1 --idle-time-limit 2 "$CAST" "$GIF"
echo "Wrote $GIF ($(du -h "$GIF" | cut -f1))"
