#!/usr/bin/env python3
"""proj — local CLI for creating, finding, and managing projects."""

import argparse
import copy
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import termios
import textwrap
import tty
import uuid

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJ_DIR = os.path.expanduser("~/.proj")
CONFIG_PATH = os.path.join(PROJ_DIR, "config.json")
INDEX_PATH = os.path.join(PROJ_DIR, "index.json")
IGNORED_PATH = os.path.join(PROJ_DIR, "ignored.json")

DEFAULT_CONFIG = {
    "base_directories": [
        {"name": "default", "path": "~/Documents/01_Projects"}
    ],
    "default_base_directory": "default",
    "categories": [
        "Noodle", "Shopify", "NVE", "Hypnosis",
        "Julia", "Nooduino", "NoosaQueen", "STAT",
    ],
    "default_category": "Noodle",
    "status_thresholds": {
        "stale_after_days": 14,
        "archived_after_days": 90,
    },
    "project_editor": "Zed",
    "prompt_editor": "Typora",
    "templates": {
        "initial_prompt_name": "{slug}_initial_prompt.md",
        "readme_name": "README.md",
    },
}

VERSION = "0.1.0"

# ANSI color support — disabled when piped or when NO_COLOR is set.
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

BOLD = "\033[1m" if _USE_COLOR else ""
DIM = "\033[2m" if _USE_COLOR else ""
RESET = "\033[0m" if _USE_COLOR else ""
CYAN = "\033[36m" if _USE_COLOR else ""
GREEN = "\033[32m" if _USE_COLOR else ""
YELLOW = "\033[33m" if _USE_COLOR else ""
MAGENTA = "\033[35m" if _USE_COLOR else ""
BOLD_CYAN = "\033[1;36m" if _USE_COLOR else ""
BOLD_GREEN = "\033[1;32m" if _USE_COLOR else ""
BOLD_MAGENTA = "\033[1;35m" if _USE_COLOR else ""

_LOGO_LINES = [
    r" ____            _           _     ____",
    r"|  _ \ _ __ ___ (_) ___  ___| |_  | __ )  ___  ___ ___",
    r"| |_) | '__/ _ \| |/ _ \/ __| __| |  _ \ / _ \/ __/ __|",
    "|  __/| | | (_) | |  __/ (__| |_  | |_) | (_) \\__ \\__ \\",
    r"|_|   |_|  \___/|_|\___|\___|\__| |____/ \___/|___/___/",
]
_LOGO_COLORS = [BOLD_CYAN, BOLD_CYAN, CYAN, BOLD_GREEN, GREEN]

# ---------------------------------------------------------------------------
# Helpers — filesystem / atomic writes
# ---------------------------------------------------------------------------


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def atomic_write_json(path, data):
    """Write JSON atomically via temp file + rename."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Helpers — slugify
# ---------------------------------------------------------------------------


def slugify(name):
    """Turn a project name into a filesystem-safe slug."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# Helpers — status computation
# ---------------------------------------------------------------------------


def compute_status(entry, config):
    """Derive status from last_worked_at and archived flag."""
    if entry.get("archived"):
        return "archived"
    thresholds = config.get("status_thresholds", DEFAULT_CONFIG["status_thresholds"])
    stale_days = thresholds["stale_after_days"]
    archive_days = thresholds["archived_after_days"]
    last = entry.get("last_worked_at")
    if not last:
        return "active"
    try:
        last_dt = datetime.datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return "active"
    now = datetime.datetime.now(datetime.timezone.utc)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
    delta = (now - last_dt).days
    if delta >= archive_days:
        return "archived"
    if delta >= stale_days:
        return "stale"
    return "active"


def status_explanation(entry, config):
    """Human-readable status string with reason."""
    status = compute_status(entry, config)
    if entry.get("archived"):
        return "archived (manually)"
    last = entry.get("last_worked_at")
    if not last:
        return f"{status}"
    try:
        last_dt = datetime.datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return status
    now = datetime.datetime.now(datetime.timezone.utc)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
    delta = (now - last_dt).days
    if delta == 0:
        age = "today"
    elif delta == 1:
        age = "1 day ago"
    else:
        age = f"{delta} days ago"
    return f"{status}: last worked {age}"


# ---------------------------------------------------------------------------
# Helpers — YAML-ish frontmatter (minimal, no PyYAML dependency)
# ---------------------------------------------------------------------------


def parse_frontmatter(text):
    """Return (metadata_dict, body_string) from text with optional --- fences."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw = parts[1].strip()
    meta = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip('"').strip("'")
        # Handle list values (simple single-line [a, b, c] format)
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
        meta[key.strip()] = val
    body = parts[2]
    if body.startswith("\n"):
        body = body[1:]
    return meta, body


def build_frontmatter(meta):
    """Render a metadata dict as YAML-ish frontmatter block."""
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(i) for i in v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def update_frontmatter_in_file(filepath, updates):
    """Read file, update frontmatter keys, write back."""
    if not os.path.isfile(filepath):
        return
    with open(filepath) as f:
        text = f.read()
    meta, body = parse_frontmatter(text)
    meta.update(updates)
    with open(filepath, "w") as f:
        f.write(build_frontmatter(meta) + "\n" + body)


# ---------------------------------------------------------------------------
# Helpers — interactive prompts
# ---------------------------------------------------------------------------


def read_key():
    """Read a single keypress from stdin without waiting for Enter."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def open_in_app(app, path):
    """Open a file or directory in a macOS app via `open -a`."""
    try:
        subprocess.run(
            ["open", "-a", app, path],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        print(f"  Could not open {app}.")


def prompt_text(label, default=None):
    """Prompt for a text value, with optional default."""
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val if val else default


def prompt_choice(label, choices, default=None):
    """Prompt user to pick from a numbered list."""
    print(f"\n{label}:")
    for i, c in enumerate(choices, 1):
        marker = " *" if c == default else ""
        print(f"  {i}. {c}{marker}")
    while True:
        raw = input(f"Choice [1-{len(choices)}]: ").strip()
        if not raw and default:
            return default
        try:
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        except ValueError:
            # Allow typing the name directly
            matches = [c for c in choices if c.lower() == raw.lower()]
            if matches:
                return matches[0]
        print("  Invalid choice, try again.")


def prompt_confirm(label, default=True):
    """Yes/no prompt."""
    hint = "Y/n" if default else "y/N"
    raw = input(f"{label} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


# ---------------------------------------------------------------------------
# Helpers — table formatting
# ---------------------------------------------------------------------------


def format_table(headers, rows, max_width=None):
    """Render a simple ASCII table that fits the terminal."""
    if max_width is None:
        max_width = shutil.get_terminal_size((80, 24)).columns

    if not rows:
        return "  (no results)"

    # Calculate column widths from content
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    # Shrink last column if table is too wide
    total = sum(col_widths) + 3 * (len(headers) - 1)  # 3 chars padding between cols
    if total > max_width and len(headers) > 1:
        excess = total - max_width
        col_widths[-1] = max(10, col_widths[-1] - excess)

    def fmt_row(cells):
        parts = []
        for i, cell in enumerate(cells):
            s = str(cell)
            w = col_widths[i]
            if len(s) > w:
                s = s[: w - 1] + "…"
            parts.append(s.ljust(w))
        return "   ".join(parts)

    lines = [fmt_row(headers), fmt_row(["─" * w for w in col_widths])]
    for row in rows:
        lines.append(fmt_row(row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers — welcome screen
# ---------------------------------------------------------------------------


def _colorize_logo():
    """Apply a cyan-to-green gradient across the ASCII logo lines."""
    return "\n".join(
        f"{color}{line}{RESET}"
        for color, line in zip(_LOGO_COLORS, _LOGO_LINES)
    )


def _format_box(lines, width):
    """Render *lines* inside a Unicode rounded-corner box of *width* chars."""
    top = f"  {DIM}╭{'─' * (width + 2)}╮{RESET}"
    bot = f"  {DIM}╰{'─' * (width + 2)}╯{RESET}"
    rows = []
    for line in lines:
        # Pad the visible text to *width*, preserving any ANSI codes.
        visible_len = len(re.sub(r"\033\[[0-9;]*m", "", line))
        padding = max(0, width - visible_len)
        rows.append(f"  {DIM}│{RESET} {line}{' ' * padding} {DIM}│{RESET}")
    return "\n".join([top, *rows, bot])


def print_welcome():
    """Print the full welcome screen with logo, stats, and tips."""
    out = []

    # Logo
    out.append(_colorize_logo())
    out.append("")

    # Tagline
    out.append(f"  {BOLD}Welcome to {BOLD_MAGENTA}Project Boss{RESET}{BOLD} v{VERSION}{RESET}")

    # Dynamic stats
    index = load_index()
    total = len(index)
    if total:
        config = load_config()
        active = sum(1 for e in index if compute_status(e, config) == "active")
        out.append(f"  {DIM}Tracking {total} project{'s' if total != 1 else ''}"
                   f" ({active} active){RESET}")
    else:
        out.append(f"  {DIM}No projects tracked yet — run {GREEN}proj new{RESET}"
                   f"{DIM} to get started.{RESET}")
    out.append("")

    # Quick-start commands
    out.append(f"  {BOLD}Quick Start:{RESET}")
    cmds = [
        ("proj new",         "Create a new project"),
        ("proj list",        "List all tracked projects"),
        ("proj open <name>", "Open a project directory"),
        ("proj info <name>", "Show project details"),
        ("proj rescan",      "Discover unindexed projects"),
    ]
    for cmd, desc in cmds:
        out.append(f"    {GREEN}{cmd:<20}{RESET}{DIM}{desc}{RESET}")
    out.append("")

    # Tips box
    box_lines = [
        f"Run {GREEN}proj help <command>{RESET} for detailed usage.",
        f"Use {GREEN}proj --version{RESET} to check your version.",
    ]
    box_width = 54
    out.append(_format_box(box_lines, box_width))

    print("\n".join(out))


# ---------------------------------------------------------------------------
# Helpers — date formatting
# ---------------------------------------------------------------------------


def format_date(iso_str, short=False):
    """Format an ISO date string for display."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        if short:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str


def now_iso():
    """Current time as ISO string with timezone."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Helpers — git remote detection
# ---------------------------------------------------------------------------


def get_repo_url(project_root):
    """Detect a GitHub/Bitbucket repo URL from the git remote origin."""
    if not os.path.isdir(project_root):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _remote_to_web_url(raw)


def _remote_to_web_url(raw):
    """Convert a git remote URL to a web URL for GitHub/Bitbucket."""
    # SSH: git@github.com:user/repo.git
    m = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", raw)
    if m:
        host, path = m.group(1), m.group(2)
        return f"https://{host}/{path}"

    # HTTPS: https://github.com/user/repo.git
    m = re.match(r"^https?://([^/]+)/(.+?)(?:\.git)?$", raw)
    if m:
        host, path = m.group(1), m.group(2)
        return f"https://{host}/{path}"

    return None


# ---------------------------------------------------------------------------
# Config management
# ---------------------------------------------------------------------------


def load_config():
    """Load config, falling back to defaults for missing keys."""
    if not os.path.isfile(CONFIG_PATH):
        return copy.deepcopy(DEFAULT_CONFIG)
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    # Merge defaults for any missing keys
    merged = copy.deepcopy(DEFAULT_CONFIG)
    merged.update(cfg)
    return merged


def save_config(cfg):
    ensure_dir(PROJ_DIR)
    atomic_write_json(CONFIG_PATH, cfg)


def resolve_base_dir(cfg, name=None):
    """Resolve a base directory name to its expanded path."""
    name = name or cfg.get("default_base_directory", "default")
    for bd in cfg["base_directories"]:
        if bd["name"] == name:
            return os.path.expanduser(bd["path"])
    # Fallback: first entry
    return os.path.expanduser(cfg["base_directories"][0]["path"])


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------


def load_index():
    if not os.path.isfile(INDEX_PATH):
        return []
    with open(INDEX_PATH) as f:
        return json.load(f)


def save_index(entries):
    ensure_dir(PROJ_DIR)
    atomic_write_json(INDEX_PATH, entries)


def load_ignored():
    if not os.path.isfile(IGNORED_PATH):
        return []
    with open(IGNORED_PATH) as f:
        return json.load(f)


def save_ignored(paths):
    ensure_dir(PROJ_DIR)
    atomic_write_json(IGNORED_PATH, sorted(set(paths)))


def is_ignored(proj_path, ignored):
    """Check if a path (or its realpath) is in the ignored list."""
    # Use normcase for case-insensitive filesystems (macOS)
    nc = os.path.normcase
    proj_norm = nc(proj_path)
    real_norm = nc(os.path.realpath(proj_path))
    ignored_norm = {nc(p) for p in ignored}
    return proj_norm in ignored_norm or real_norm in ignored_norm


def next_id(entries):
    """Return the next sequential integer ID as a string."""
    if not entries:
        return "1"
    max_id = max(int(e["id"]) for e in entries if e.get("id", "").isdigit())
    return str(max_id + 1)


def find_entry(entries, query):
    """Resolve a query to a single index entry (by ID, prefix, or name substring)."""
    if not query:
        return None
    q = query.strip().lower()

    # Exact ID match
    for e in entries:
        if e.get("id") == query:
            return e

    # ID prefix match
    id_matches = [e for e in entries if e.get("id", "").startswith(query)]
    if len(id_matches) == 1:
        return id_matches[0]

    # Name substring (case-insensitive)
    name_matches = [e for e in entries if q in e.get("name", "").lower()]
    if len(name_matches) == 1:
        return name_matches[0]

    # Slug match
    slug_matches = [e for e in entries if q in slugify(e.get("name", "")).lower()]
    if len(slug_matches) == 1:
        return slug_matches[0]

    # Ambiguous
    all_matches = list({id(e): e for e in id_matches + name_matches + slug_matches}.values())
    if len(all_matches) > 1:
        print(f"Ambiguous query '{query}'. Matches:")
        for e in all_matches:
            print(f"  {e['id']}: {e['name']}")
        return None

    return None


# ---------------------------------------------------------------------------
# PROJECTS_INDEX.md generation
# ---------------------------------------------------------------------------


def generate_projects_index(entries, config):
    """Write a PROJECTS_INDEX.md at the base directory root."""
    for bd in config["base_directories"]:
        base = os.path.expanduser(bd["path"])
        if not os.path.isdir(base):
            continue
        # Filter entries belonging to this base
        bd_entries = [e for e in entries if e.get("base_directory") == bd["name"]]
        if not bd_entries:
            continue

        lines = ["# Projects Index", "", f"*Auto-generated by proj — {datetime.date.today()}*", ""]

        # Group by category
        by_cat = {}
        for e in bd_entries:
            cat = e.get("category", "Uncategorised")
            by_cat.setdefault(cat, []).append(e)

        for cat in sorted(by_cat.keys()):
            lines.append(f"## {cat}")
            lines.append("")
            for e in sorted(by_cat[cat], key=lambda x: x.get("last_worked_at", ""), reverse=True):
                status = compute_status(e, config)
                tag = f" `{status}`" if status != "active" else ""
                summary = e.get("summary", "")
                summary_part = f" — {summary}" if summary else ""
                lines.append(f"- **{e['name']}**{tag}{summary_part}")
            lines.append("")

        path = os.path.join(base, "PROJECTS_INDEX.md")
        with open(path, "w") as f:
            f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Template: initial prompt
# ---------------------------------------------------------------------------


def create_initial_prompt(path, meta, brief=""):
    """Create the initial prompt markdown file."""
    fm = build_frontmatter({
        "project": meta["name"],
        "category": meta["category"],
        "created": meta["created_at"][:10],
        "summary": meta.get("summary", ""),
        "tags": meta.get("tags", []),
    })
    body = f"\n# {meta['name']}\n\n"
    if meta.get("summary"):
        body += f"{meta['summary']}\n\n"
    body += "## Initial Project Prompt\n\n"
    if brief:
        body += brief + "\n"
    with open(path, "w") as f:
        f.write(fm + "\n" + body)


# ---------------------------------------------------------------------------
# Template: README
# ---------------------------------------------------------------------------


def create_readme(path, meta):
    """Create a basic project README."""
    content = f"# {meta['name']}\n\n"
    if meta.get("summary"):
        content += f"{meta['summary']}\n\n"
    content += f"Category: {meta.get('category', '—')}\n"
    content += f"Created: {meta['created_at'][:10]}\n"
    with open(path, "w") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Command: config
# ---------------------------------------------------------------------------


def cmd_config(args):
    action = args.action or "show"

    if action == "init":
        if os.path.isfile(CONFIG_PATH):
            if not prompt_confirm("Config already exists. Overwrite?", default=False):
                print("Aborted.")
                return
        save_config(DEFAULT_CONFIG)
        print(f"Config created at {CONFIG_PATH}")
        return

    if action == "show":
        cfg = load_config()
        print(json.dumps(cfg, indent=2))
        return

    if action == "edit":
        cfg = load_config()
        editor = cfg.get("project_editor", "Zed")
        if not os.path.isfile(CONFIG_PATH):
            save_config(cfg)
        open_in_app(editor, CONFIG_PATH)
        return

    if action == "set":
        if not args.key or args.value is None:
            print("Usage: proj config set <key> <value>")
            return
        cfg = load_config()
        key = args.key
        val = args.value
        # Try to parse JSON values
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            pass
        # Support dot notation for nested keys
        parts = key.split(".")
        target = cfg
        for p in parts[:-1]:
            if p not in target or not isinstance(target[p], dict):
                target[p] = {}
            target = target[p]
        target[parts[-1]] = val
        save_config(cfg)
        print(f"Set {key} = {json.dumps(val)}")
        return

    print(f"Unknown config action: {action}")


# ---------------------------------------------------------------------------
# Command: new
# ---------------------------------------------------------------------------


def cmd_new(args):
    cfg = load_config()
    entries = load_index()

    # 1. Name
    name = args.name or prompt_text("Project name")
    if not name:
        print("Name is required.")
        return
    slug = slugify(name)

    # 2. Category
    categories = cfg.get("categories", [])
    default_cat = cfg.get("default_category")
    if args.category:
        category = args.category
    elif categories:
        category = prompt_choice("Category", categories, default=default_cat)
    else:
        category = prompt_text("Category", default=default_cat) or "General"

    # 3. Summary
    summary = args.summary or prompt_text("Summary (optional, one line)", default="")

    # 4. Base directory
    bases = cfg.get("base_directories", [])
    if args.base:
        base_name = args.base
    elif len(bases) > 1:
        base_name = prompt_choice(
            "Base directory",
            [b["name"] for b in bases],
            default=cfg.get("default_base_directory"),
        )
    else:
        base_name = bases[0]["name"] if bases else "default"

    base_path = resolve_base_dir(cfg, base_name)

    # 5. Build paths
    project_root = os.path.join(base_path, category, slug)
    docs_path = os.path.join(project_root, "docs")

    if os.path.exists(project_root):
        print(f"Directory already exists: {project_root}")
        if not prompt_confirm("Continue anyway?", default=False):
            return

    # 6. Initial project prompt
    brief = ""
    if not args.no_notes:
        print("\nInitial project prompt (optional):")
        print("  \\ = paste clipboard | Enter = skip")
        brief_lines = []

        # Intercept first keypress for instant \ and Enter handling
        first = read_key()
        if first == "\\":
            try:
                result = subprocess.run(
                    ["pbpaste"], capture_output=True, text=True, timeout=5,
                )
                clipboard = result.stdout.strip() if result.returncode == 0 else ""
            except (OSError, subprocess.TimeoutExpired):
                clipboard = ""
            if clipboard:
                line_count = clipboard.count("\n") + 1
                brief_lines.append(clipboard)
                print(f"  Pasted ({line_count} line{'s' if line_count != 1 else ''}). Add more or Enter to finish.")
            else:
                print("  Clipboard is empty.")
        elif first in ("\r", "\n"):
            pass  # skip
        elif first == "\x03":
            raise KeyboardInterrupt
        else:
            # User started typing — collect the rest of the first line
            sys.stdout.write(first)
            sys.stdout.flush()
            rest = input()
            brief_lines.append(first + rest)

        # Continue collecting lines if we have content or user started typing
        if brief_lines:
            while True:
                line = input()
                if line == "":
                    break
                brief_lines.append(line)

        brief = "\n".join(brief_lines)

    # 7. Create directories + files
    ensure_dir(docs_path)

    created_at = now_iso()
    entry_id = next_id(entries)

    templates = cfg.get("templates", DEFAULT_CONFIG["templates"])
    prompt_filename = templates.get("initial_prompt_name", "{slug}_initial_prompt.md").format(slug=slug)
    readme_filename = templates.get("readme_name", "README.md")

    initial_prompt_path = os.path.join(docs_path, prompt_filename)
    readme_path = os.path.join(project_root, readme_filename)

    meta = {
        "name": name,
        "category": category,
        "summary": summary,
        "created_at": created_at,
        "tags": [],
    }

    create_initial_prompt(initial_prompt_path, meta, brief)
    create_readme(readme_path, meta)

    # 8. Initialise git repository
    git_ok = False
    if prompt_confirm("Initialise git repository?", default=True):
        try:
            subprocess.run(
                ["git", "init"],
                cwd=project_root,
                check=True, capture_output=True,
            )
            git_ok = True
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"  Warning: could not initialise git repo: {exc}")

    # 9. Add to index
    entry = {
        "id": entry_id,
        "name": name,
        "category": category,
        "summary": summary,
        "project_root": project_root,
        "docs_path": docs_path,
        "initial_prompt_path": initial_prompt_path,
        "base_directory": base_name,
        "created_at": created_at,
        "last_worked_at": created_at,
        "archived": False,
        "tags": [],
    }
    entries.append(entry)
    save_index(entries)

    # 10. Regenerate PROJECTS_INDEX.md
    generate_projects_index(entries, cfg)

    print(f"\nCreated project: {name}")
    print(f"  ID:       {entry_id}")
    print(f"  Path:     {project_root}")
    print(f"  Category: {category}")
    if summary:
        print(f"  Summary:  {summary}")
    if git_ok:
        print(f"  Git:      initialised")

    # 11. Offer to open in editor(s)
    if not args.no_notes:
        project_editor = cfg.get("project_editor", "Zed")
        prompt_editor = cfg.get("prompt_editor", "Typora")
        choice = prompt_choice("What next?", [
            f"Open project in {project_editor}",
            f"Edit prompt in {prompt_editor}",
            "Both 1 & 2",
            "Skip",
        ], default="Skip")
        if choice.startswith("Open project"):
            open_in_app(project_editor, project_root)
        elif choice.startswith("Edit prompt"):
            open_in_app(prompt_editor, initial_prompt_path)
        elif choice == "Both 1 & 2":
            open_in_app(project_editor, project_root)
            open_in_app(prompt_editor, initial_prompt_path)


# ---------------------------------------------------------------------------
# Command: list
# ---------------------------------------------------------------------------


def cmd_list(args):
    cfg = load_config()
    entries = load_index()

    if not entries:
        print("No projects indexed. Run `proj new` to create one.")
        return

    # Filter by status
    status_filter = args.status
    if status_filter:
        filtered = [e for e in entries if compute_status(e, cfg) == status_filter]
    else:
        # Default: non-archived
        filtered = [e for e in entries if compute_status(e, cfg) != "archived"]

    # Filter by category
    if args.category:
        filtered = [e for e in filtered if e.get("category", "").lower() == args.category.lower()]

    # Sort
    sort_key = args.sort or "last_worked_at"
    reverse = not args.reverse  # default is desc (most recent first)
    if sort_key == "name":
        filtered.sort(key=lambda e: e.get("name", "").lower(), reverse=args.reverse)
    elif sort_key == "category":
        filtered.sort(key=lambda e: e.get("category", "").lower(), reverse=args.reverse)
    elif sort_key == "created":
        filtered.sort(key=lambda e: e.get("created_at", ""), reverse=reverse)
    else:  # last_worked_at
        filtered.sort(key=lambda e: e.get("last_worked_at", ""), reverse=reverse)

    # Limit
    if args.limit:
        filtered = filtered[: args.limit]

    if not filtered:
        print("No matching projects.")
        return

    if args.short:
        for e in filtered:
            status = compute_status(e, cfg)
            tag = f" [{status}]" if status != "active" else ""
            print(f"  {e['id']:>3}  {e['name']}{tag}")
        return

    # Full table
    headers = ["ID", "Name", "Status", "Category", "Last Worked", "Summary"]
    rows = []
    for e in filtered:
        status = compute_status(e, cfg)
        rows.append([
            e["id"],
            e["name"],
            status,
            e.get("category", ""),
            format_date(e.get("last_worked_at"), short=True),
            e.get("summary", ""),
        ])

    print(format_table(headers, rows))


# ---------------------------------------------------------------------------
# Command: info
# ---------------------------------------------------------------------------


def cmd_info(args):
    cfg = load_config()
    entries = load_index()
    entry = find_entry(entries, args.query)

    if not entry:
        print(f"No project found for '{args.query}'")
        return

    repo_url = get_repo_url(entry.get("project_root", ""))

    if args.json:
        out = dict(entry)
        out["status"] = compute_status(entry, cfg)
        if repo_url:
            out["repo_url"] = repo_url
        print(json.dumps(out, indent=2))
        return

    print(f"\n  Name:          {entry['name']}")
    print(f"  ID:            {entry['id']}")
    print(f"  Status:        {status_explanation(entry, cfg)}")
    print(f"  Category:      {entry.get('category', '—')}")
    print(f"  Summary:       {entry.get('summary', '—')}")
    print(f"  Tags:          {', '.join(entry.get('tags', [])) or '—'}")
    print(f"  Project Root:  {entry.get('project_root', '—')}")
    print(f"  Docs:          {entry.get('docs_path', '—')}")
    if repo_url:
        print(f"  Repo:          {repo_url}")
    print(f"  Base Dir:      {entry.get('base_directory', '—')}")
    print(f"  Created:       {format_date(entry.get('created_at'))}")
    print(f"  Last Worked:   {format_date(entry.get('last_worked_at'))}")
    print(f"  Archived:      {entry.get('archived', False)}")
    print()


# ---------------------------------------------------------------------------
# Command: edit
# ---------------------------------------------------------------------------


def cmd_edit(args):
    cfg = load_config()
    entries = load_index()
    entry = find_entry(entries, args.query)

    if not entry:
        print(f"No project found for '{args.query}'")
        return

    changed = False

    # Flag-based edits
    if args.summary is not None:
        entry["summary"] = args.summary
        changed = True

    if args.category is not None:
        entry["category"] = args.category
        changed = True

    if args.name is not None:
        entry["name"] = args.name
        changed = True

    if args.archive:
        entry["archived"] = True
        changed = True

    if args.unarchive:
        entry["archived"] = False
        changed = True

    if args.tag:
        tags = entry.get("tags", [])
        for t in args.tag:
            if t not in tags:
                tags.append(t)
        entry["tags"] = tags
        changed = True

    if args.untag:
        tags = entry.get("tags", [])
        for t in args.untag:
            if t in tags:
                tags.remove(t)
        entry["tags"] = tags
        changed = True

    # Interactive mode if no flags given
    if not changed:
        print(f"\nEditing: {entry['name']} (ID {entry['id']})")
        new_name = prompt_text("Name", default=entry["name"])
        if new_name != entry["name"]:
            entry["name"] = new_name
            changed = True

        categories = cfg.get("categories", [])
        if categories:
            new_cat = prompt_choice("Category", categories, default=entry.get("category"))
        else:
            new_cat = prompt_text("Category", default=entry.get("category", ""))
        if new_cat != entry.get("category"):
            entry["category"] = new_cat
            changed = True

        new_summary = prompt_text("Summary", default=entry.get("summary", ""))
        if new_summary != entry.get("summary"):
            entry["summary"] = new_summary
            changed = True

        new_tags = prompt_text("Tags (comma-separated)", default=", ".join(entry.get("tags", [])))
        if new_tags is not None:
            parsed = [t.strip() for t in new_tags.split(",") if t.strip()] if new_tags else []
            if parsed != entry.get("tags", []):
                entry["tags"] = parsed
                changed = True

    if not changed:
        print("No changes made.")
        return

    # Update index
    for i, e in enumerate(entries):
        if e["id"] == entry["id"]:
            entries[i] = entry
            break
    save_index(entries)

    # Update frontmatter in initial prompt if it exists
    ip_path = entry.get("initial_prompt_path", "")
    if ip_path and os.path.isfile(ip_path):
        update_frontmatter_in_file(ip_path, {
            "project": entry["name"],
            "category": entry.get("category", ""),
            "summary": entry.get("summary", ""),
            "tags": entry.get("tags", []),
        })

    generate_projects_index(entries, cfg)
    print(f"Updated: {entry['name']}")


# ---------------------------------------------------------------------------
# Command: open
# ---------------------------------------------------------------------------


def cmd_open(args):
    cfg = load_config()
    entries = load_index()
    entry = find_entry(entries, args.query)

    if not entry:
        print(f"No project found for '{args.query}'", file=sys.stderr)
        sys.exit(1)

    root = entry.get("project_root", "")

    if not os.path.isdir(root):
        print(f"Project directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    # Update last_worked_at
    entry["last_worked_at"] = now_iso()
    for i, e in enumerate(entries):
        if e["id"] == entry["id"]:
            entries[i] = entry
            break
    save_index(entries)

    target = entry.get("docs_path", root) if args.docs else root

    if args.path_only:
        print(target)
        return

    if args.editor:
        editor = cfg.get("project_editor", "Zed")
        open_in_app(editor, target)
        return

    if args.finder:
        subprocess.run(["open", target])
        return

    # Default: print path (shell function will cd)
    print(target)


# ---------------------------------------------------------------------------
# Command: rescan
# ---------------------------------------------------------------------------


def _walk_latest_mtime(root):
    """Walk a project tree and return the latest file mtime. Follows symlinks."""
    latest = 0
    seen_real = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        # Cycle protection for symlinks
        real = os.path.realpath(dirpath)
        if real in seen_real:
            dirnames.clear()
            continue
        seen_real.add(real)
        # Skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                mt = os.path.getmtime(fp)
                if mt > latest:
                    latest = mt
            except OSError:
                pass
    return latest


def cmd_rescan(args):
    cfg = load_config()
    entries = load_index()
    updated = 0

    # Update last_worked_at from filesystem mtimes
    for entry in entries:
        root = entry.get("project_root", "")
        if not os.path.isdir(root):
            if args.verbose:
                print(f"  MISSING: {entry['name']} ({root})")
            continue

        latest_mtime = _walk_latest_mtime(root)

        if latest_mtime > 0:
            new_ts = datetime.datetime.fromtimestamp(latest_mtime, tz=datetime.timezone.utc).isoformat()
            old_ts = entry.get("last_worked_at", "")
            if new_ts > old_ts:
                entry["last_worked_at"] = new_ts
                updated += 1
                if args.verbose:
                    print(f"  UPDATED: {entry['name']} → {format_date(new_ts, short=True)}")
            elif args.verbose:
                print(f"  OK:      {entry['name']}")

    # Discover unindexed projects
    if args.discover:
        ignored = load_ignored()
        # Match by both symlink path and resolved real path to avoid duplicates
        indexed_real = set()
        for e in entries:
            p = e.get("project_root", "")
            indexed_real.add(p)
            if os.path.isdir(p):
                indexed_real.add(os.path.realpath(p))

        discovered = 0
        skipped = 0
        for bd in cfg.get("base_directories", []):
            base = os.path.expanduser(bd["path"])
            if not os.path.isdir(base):
                continue
            for cat_name in sorted(os.listdir(base)):
                cat_path = os.path.join(base, cat_name)
                if not os.path.isdir(cat_path) or cat_name.startswith("."):
                    continue
                for proj_name in sorted(os.listdir(cat_path)):
                    proj_path = os.path.join(cat_path, proj_name)
                    if not os.path.isdir(proj_path) or proj_name.startswith("."):
                        continue
                    real_path = os.path.realpath(proj_path)
                    if proj_path in indexed_real or real_path in indexed_real:
                        continue
                    if is_ignored(proj_path, ignored):
                        skipped += 1
                        if args.verbose:
                            print(f"  IGNORED: {proj_name} ({cat_name})")
                        continue
                    # Found an unindexed project
                    is_link = os.path.islink(proj_path)
                    discovered += 1
                    link_note = " (symlink)" if is_link else ""
                    if args.verbose:
                        print(f"  FOUND:   {proj_name} ({cat_name}){link_note} at {proj_path}")

                    docs_path = os.path.join(proj_path, "docs")
                    if not os.path.isdir(docs_path):
                        docs_path = proj_path

                    # Derive last_worked_at from filesystem
                    mtime = _walk_latest_mtime(proj_path)
                    if mtime > 0:
                        last_worked = datetime.datetime.fromtimestamp(
                            mtime, tz=datetime.timezone.utc
                        ).isoformat()
                    else:
                        last_worked = now_iso()

                    new_entry = {
                        "id": next_id(entries),
                        "name": proj_name.replace("-", " ").title(),
                        "category": cat_name,
                        "summary": "",
                        "project_root": proj_path,
                        "docs_path": docs_path,
                        "initial_prompt_path": "",
                        "base_directory": bd["name"],
                        "created_at": now_iso(),
                        "last_worked_at": last_worked,
                        "archived": False,
                        "tags": [],
                    }
                    entries.append(new_entry)
                    indexed_real.add(proj_path)
                    indexed_real.add(real_path)

        if discovered:
            print(f"Discovered {discovered} new project(s).")
        if skipped and args.verbose:
            print(f"Skipped {skipped} ignored path(s).")

    save_index(entries)
    generate_projects_index(entries, cfg)
    print(f"Rescan complete. Updated {updated} timestamp(s).")


# ---------------------------------------------------------------------------
# Command: ignore
# ---------------------------------------------------------------------------


def cmd_ignore(args):
    cfg = load_config()
    entries = load_index()
    ignored = load_ignored()

    if args.list_ignored:
        if not ignored:
            print("No ignored paths.")
            return
        print("Ignored paths:")
        for p in sorted(ignored):
            print(f"  {p}")
        return

    if args.remove:
        removed = []
        for pattern in args.remove:
            matches = [p for p in ignored if pattern in p]
            removed.extend(matches)
        if not removed:
            print(f"No ignored paths matching '{args.remove}'")
            return
        for p in removed:
            ignored.remove(p)
        save_ignored(ignored)
        for p in removed:
            print(f"Un-ignored: {p}")
        return

    # Default: ignore by query (ID, name, path)
    query = args.query
    if not query:
        print("Usage: proj ignore <query>  or  proj ignore --list")
        return

    entry = find_entry(entries, query)
    if entry:
        path = entry["project_root"]
        # Remove from index
        entries = [e for e in entries if e["id"] != entry["id"]]
        save_index(entries)
        # Add to ignored
        ignored.append(path)
        save_ignored(ignored)
        generate_projects_index(entries, cfg)
        print(f"Ignored: {entry['name']} ({path})")
        print("  Removed from index and won't be re-discovered.")
        return

    # Maybe it's a raw path
    path = os.path.abspath(os.path.expanduser(query))
    if os.path.isdir(path):
        # Remove from index if present
        removed_name = None
        for e in entries:
            if e.get("project_root") == path or os.path.realpath(e.get("project_root", "")) == os.path.realpath(path):
                removed_name = e["name"]
                entries = [x for x in entries if x["id"] != e["id"]]
                break
        save_index(entries)
        ignored.append(path)
        save_ignored(ignored)
        generate_projects_index(entries, cfg)
        if removed_name:
            print(f"Ignored: {removed_name} ({path})")
        else:
            print(f"Ignored: {path}")
        print("  Won't be discovered by rescan.")
        return

    print(f"No project or directory found for '{query}'")


# ---------------------------------------------------------------------------
# Argparse setup
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="proj",
        description="Local CLI for creating, finding, and managing projects.",
    )
    parser.add_argument("--version", action="version", version=f"proj {VERSION}")
    sub = parser.add_subparsers(dest="command")

    # config
    p_cfg = sub.add_parser("config", help="Manage configuration")
    p_cfg.add_argument("action", nargs="?", choices=["show", "edit", "set", "init"],
                       default="show", help="Config action")
    p_cfg.add_argument("key", nargs="?", help="Config key (for set)")
    p_cfg.add_argument("value", nargs="?", help="Config value (for set)")

    # new
    p_new = sub.add_parser("new", help="Create a new project")
    p_new.add_argument("--name", "-n", help="Project name")
    p_new.add_argument("--category", "-c", help="Category")
    p_new.add_argument("--summary", "-s", help="One-line summary")
    p_new.add_argument("--base", "-b", help="Base directory name")
    p_new.add_argument("--no-notes", action="store_true", help="Skip prompts (non-interactive)")

    # list
    p_list = sub.add_parser("list", aliases=["ls"], help="List projects")
    p_list.add_argument("--status", choices=["active", "stale", "archived"])
    p_list.add_argument("--category", "-c")
    p_list.add_argument("--limit", "-l", type=int)
    p_list.add_argument("--sort", choices=["name", "last_worked_at", "created", "category"],
                        default="last_worked_at")
    p_list.add_argument("--reverse", "-r", action="store_true",
                        help="Reverse sort order (default is desc by last_worked)")
    p_list.add_argument("--short", action="store_true", help="Compact output")

    # info
    p_info = sub.add_parser("info", help="Show project details")
    p_info.add_argument("query", help="Project ID, name, or slug")
    p_info.add_argument("--json", action="store_true", help="Output as JSON")

    # edit
    p_edit = sub.add_parser("edit", help="Edit project metadata")
    p_edit.add_argument("query", help="Project ID, name, or slug")
    p_edit.add_argument("--summary", "-s")
    p_edit.add_argument("--category", "-c")
    p_edit.add_argument("--name", "-n")
    p_edit.add_argument("--archive", action="store_true")
    p_edit.add_argument("--unarchive", action="store_true")
    p_edit.add_argument("--tag", action="append", help="Add tag(s)")
    p_edit.add_argument("--untag", action="append", help="Remove tag(s)")

    # open
    p_open = sub.add_parser("open", help="Open a project")
    p_open.add_argument("query", help="Project ID, name, or slug")
    p_open.add_argument("--docs", "-d", action="store_true", help="Open docs dir")
    p_open.add_argument("--editor", "-e", action="store_true", help="Open in editor")
    p_open.add_argument("--finder", "-f", action="store_true", help="Open in Finder")
    p_open.add_argument("--path-only", action="store_true", help="Print path only")

    # rescan
    p_rescan = sub.add_parser("rescan", help="Rescan project directories")
    p_rescan.add_argument("--discover", action="store_true",
                          help="Find unindexed projects in base dirs")
    p_rescan.add_argument("--verbose", "-v", action="store_true")

    # ignore
    p_ignore = sub.add_parser("ignore", help="Ignore folders that aren't projects")
    p_ignore.add_argument("query", nargs="?", help="Project ID, name, or path to ignore")
    p_ignore.add_argument("--list", "-l", dest="list_ignored", action="store_true",
                          help="List all ignored paths")
    p_ignore.add_argument("--remove", "-r", action="append",
                          help="Un-ignore a path (substring match)")

    # help
    p_help = sub.add_parser("help", help="Show help for a command")
    p_help.add_argument("topic", nargs="?", help="Command to get help for")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        print_welcome()
        return

    if args.command == "help":
        topic = getattr(args, "topic", None)
        if topic:
            parser.parse_args([topic, "--help"])
        else:
            print_welcome()
        return

    commands = {
        "config": cmd_config,
        "new": cmd_new,
        "list": cmd_list,
        "ls": cmd_list,
        "info": cmd_info,
        "edit": cmd_edit,
        "open": cmd_open,
        "rescan": cmd_rescan,
        "ignore": cmd_ignore,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
