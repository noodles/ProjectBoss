#!/bin/bash
# Builds the throwaway home directory the demo recording runs against, so the
# recording never touches real data and can be regenerated identically.
set -e

DEMO_HOME="${1:-/tmp/pb-demo-home}"
PB="$(cd "$(dirname "$0")/.." && pwd)/pb.py"

rm -rf "$DEMO_HOME"
mkdir -p "$DEMO_HOME/.pb"

cat > "$DEMO_HOME/.pb/config.json" <<'JSON'
{
  "base_directories": [{"name": "default", "path": "~/Projects"}],
  "default_base_directory": "default",
  "categories": ["Work", "Clients", "Personal"],
  "default_category": "Work",
  "github_orgs": ["your-username"],
  "default_github_org": "your-username",
  "status_thresholds": {"stale_after_days": 14, "archived_after_days": 90},
  "project_editor": "",
  "prompt_editor": "",
  "templates": {
    "initial_prompt_name": "{slug}_initial_prompt.md",
    "readme_name": "README.md"
  }
}
JSON

make_project() {
    HOME="$DEMO_HOME" python3 "$PB" new --name "$1" -c "$2" -s "$3" \
        --no-notes --no-remote --no-adr >/dev/null
}
make_project "Invoice Chaser"  Work     "Chases overdue invoices over email"
make_project "Site Redesign"   Clients  "Marketing site rebuild for Halcyon"
make_project "Recipe Box"      Personal "Somewhere to keep recipes"

# Stagger the timestamps so the demo shows all three statuses.
HOME="$DEMO_HOME" python3 - "$DEMO_HOME" <<'PY'
import datetime, json, os, sys
path = os.path.join(sys.argv[1], ".pb", "index.json")
entries = json.load(open(path))
def ago(days):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days)).isoformat()
for entry, days in zip(entries, (1, 34, 21)):
    entry["last_worked_at"] = ago(days)
json.dump(entries, open(path, "w"), indent=2)
PY

# A `pb` on PATH, so the tape needs no absolute paths of its own.
mkdir -p "$DEMO_HOME/bin"
cat > "$DEMO_HOME/bin/pb" <<SHIM
#!/bin/bash
exec python3 "$PB" "\$@"
SHIM
chmod +x "$DEMO_HOME/bin/pb"

echo "Demo home ready at $DEMO_HOME"
