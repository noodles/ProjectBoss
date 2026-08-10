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
IDEAS_PATH = os.path.join(PROJ_DIR, "ideas.json")
CD_TARGET_PATH = os.path.join(PROJ_DIR, ".cd_target")

IDEA_CATEGORIES = [
    ("bug",           "🐛", "Bug",           "errors, unexpected behavior"),
    ("feature",       "✨", "Feature",       "new features, functionality"),
    ("improvement",   "💡", "Improvement",   "suggestions, improvements, RFC"),
    ("documentation", "📝", "Documentation", "READMEs, docs"),
    ("performance",   "🔥", "Performance",   "optimizations, speed"),
    ("security",      "🔒", "Security",      "vulnerabilities, security patches"),
    ("test",          "🧪", "Test",          "adding, updating tests"),
    ("release",       "🎉", "Release",       "release-related"),
    ("refactor",      "🔧", "Refactor",      "refactoring without changing functionality"),
]

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

VERSION = "0.2.0"

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
    s = name.strip()
    # Insert hyphens at camelCase boundaries (e.g. "CalendarSync" → "Calendar-Sync")
    s = re.sub(r"([a-z])([A-Z])", r"\1-\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", s)
    s = s.lower()
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

    # Command reference
    out.append(f"  {BOLD}Commands:{RESET}")
    cmds = [
        ("proj new",            "Create a new project"),
        ("proj list",           "List all tracked projects"),
        ("proj open <query>",   "Open a project directory"),
        ("proj info <query>",   "Show project details"),
        ("proj edit <query>",   "Edit project metadata"),
        ("proj idea",           "Capture or list project ideas"),
        ("proj adr init",       "Scaffold an ADR decision log"),
        ("proj reflect",        "Review ReflectFlow findings"),
        ("proj delete <query>", "Remove a project from the index"),
        ("proj rescan",         "Update timestamps and detect missing projects"),
        ("proj ignore",         "Ignore folders that aren't projects"),
        ("proj config",         "Manage configuration"),
    ]
    for cmd, desc in cmds:
        out.append(f"    {GREEN}{cmd:<22}{RESET}{DIM}{desc}{RESET}")
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


def _gh_available():
    """Return True if the GitHub CLI is installed and authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _create_gh_issue(project_root, title, body, label):
    """Create a GitHub issue via `gh`. Returns {"url": ..., "number": ...} or None."""
    cmd = ["gh", "issue", "create", "--title", title]
    if body:
        cmd += ["--body", body]
    if label:
        cmd += ["--label", label]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, cwd=project_root,
        )
        if result.returncode != 0 and label:
            # Retry without label (label may not exist on repo)
            cmd = ["gh", "issue", "create", "--title", title]
            if body:
                cmd += ["--body", body]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, cwd=project_root,
            )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        # gh returns the issue URL, extract the number from the end
        number = url.rstrip("/").rsplit("/", 1)[-1] if url else None
        return {"url": url, "number": number}
    except (OSError, subprocess.TimeoutExpired):
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


def load_ideas():
    if not os.path.isfile(IDEAS_PATH):
        return []
    with open(IDEAS_PATH) as f:
        return json.load(f)


def save_ideas(ideas):
    ensure_dir(PROJ_DIR)
    atomic_write_json(IDEAS_PATH, ideas)


def _next_idea_id(ideas):
    """Return the next sequential integer ID for ideas."""
    if not ideas:
        return "1"
    max_id = max(int(i["id"]) for i in ideas if i.get("id", "").isdigit())
    return str(max_id + 1)


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

    # 9. Optional ADR decision log
    adr_ok = False
    if args.adr:
        adr_ok = scaffold_adr(project_root, name, quiet=True)

    # 10. Add to index
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

    # 11. Regenerate PROJECTS_INDEX.md
    generate_projects_index(entries, cfg)

    print(f"\nCreated project: {name}")
    print(f"  ID:       {entry_id}")
    print(f"  Path:     {project_root}")
    print(f"  Category: {category}")
    if summary:
        print(f"  Summary:  {summary}")
    if git_ok:
        print(f"  Git:      initialised")
    if adr_ok:
        adr_new_cmd, _ = _adr_commands(project_root)
        print(f"  ADR log:  docs/adr/ — add a record with `{adr_new_cmd}`")

    # 12. Offer to open in editor(s)
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

    # 13. Offer to cd into the new project directory
    if prompt_confirm("Change into the new project directory?", default=True):
        try:
            with open(CD_TARGET_PATH, "w") as f:
                f.write(project_root)
        except OSError:
            pass


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


_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".venv", "venv", ".env", "env",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".next", ".nuxt", ".output",
    "target", "Pods", ".dart_tool", ".pub-cache",
})


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
        # Skip hidden and heavy dependency/build directories
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in _SKIP_DIRS]
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


def _rename_project_dir(entry, new_dir_name):
    """Rename a project directory and update all index paths.

    Handles case-only renames on case-insensitive filesystems (macOS).
    Returns True on success, False if target already exists.
    """
    root = entry["project_root"]
    parent = os.path.dirname(root)
    new_root = os.path.join(parent, new_dir_name)

    if os.path.exists(new_root):
        try:
            if os.path.samefile(root, new_root):
                # Case-only rename — two-step via temp name
                tmp = new_root + "_reslug_tmp"
                os.rename(root, tmp)
                os.rename(tmp, new_root)
            else:
                return False
        except OSError:
            return False
    else:
        os.rename(root, new_root)

    # Update all paths in the entry
    for key in ("project_root", "docs_path", "initial_prompt_path"):
        val = entry.get(key, "")
        if val.startswith(root):
            entry[key] = new_root + val[len(root):]
    return True


def cmd_rescan(args):
    cfg = load_config()
    entries = load_index()
    updated = 0

    # Detect missing projects (directory no longer exists)
    missing = [e for e in entries if not os.path.isdir(e.get("project_root", ""))]
    if missing:
        if args.prune:
            for e in missing:
                print(f"  PRUNED:  {e['name']} ({e.get('project_root', '')})")
            entries = [e for e in entries if os.path.isdir(e.get("project_root", ""))]
            print(f"Removed {len(missing)} missing project(s) from index.")
        else:
            print(f"Found {len(missing)} project(s) whose directories no longer exist:")
            for e in missing:
                print(f"  {e['id']}: {e['name']} ({e.get('project_root', '')})")
            print("Run with --prune to remove them, or use 'proj delete <query>'.")

    # Reslug: rename project directories to match current slugify rules
    if args.reslug:
        reslug_count = 0
        reslug_skipped = 0
        for entry in entries:
            root = entry.get("project_root", "")
            if not os.path.isdir(root):
                continue
            old_dir_name = os.path.basename(root)
            new_dir_name = slugify(entry["name"])
            if old_dir_name == new_dir_name:
                continue
            if _rename_project_dir(entry, new_dir_name):
                print(f"  RENAME:  {old_dir_name} → {new_dir_name}")
                reslug_count += 1
            else:
                print(f"  SKIP:    {entry['name']} — target already exists")
                reslug_skipped += 1
        if reslug_count or reslug_skipped:
            print(f"Reslugged {reslug_count} project(s).")
            if reslug_skipped:
                print(f"Skipped {reslug_skipped} (target directory already exists).")
        else:
            print("All project directories already match current slug rules.")

    # Reslug check: interactive review of each project directory name
    if args.reslug_check:
        print("Reslug check — review each project directory name.")
        print("Enter=accept proposed, type a custom slug, or s=skip.\n")
        renames = []
        n = 0
        for entry in entries:
            root = entry.get("project_root", "")
            if not os.path.isdir(root):
                continue
            n += 1
            old_dir = os.path.basename(root)
            proposed = slugify(entry["name"])
            same = old_dir == proposed

            print(f"  [{n}] {entry['name']}")
            print(f"       Current:  {old_dir}")
            if same:
                print(f"       Proposed: {proposed} (no change)")
                hint = "keep"
            else:
                print(f"       Proposed: {proposed}")
                hint = "accept"

            response = input(f"       New slug [Enter={hint}, s=skip]: ").strip()

            if response.lower() == "s" or (not response and same):
                print()
                continue

            new_slug = response if response else proposed

            if new_slug == old_dir:
                print()
                continue

            renames.append((entry, old_dir, new_slug))
            print(f"       → {old_dir} → {new_slug}")
            print()

        if not renames:
            print("No changes to make.")
        else:
            print(f"\n{len(renames)} rename(s) queued:")
            for _, old, new in renames:
                print(f"  {old} → {new}")
            if prompt_confirm("\nApply all renames?", default=True):
                applied = 0
                for entry, old_dir, new_dir in renames:
                    if _rename_project_dir(entry, new_dir):
                        print(f"  RENAMED: {old_dir} → {new_dir}")
                        applied += 1
                    else:
                        print(f"  FAILED:  {old_dir} → {new_dir} (target exists)")
                save_index(entries)
                generate_projects_index(entries, cfg)
                print(f"Applied {applied} rename(s).")
            else:
                print("Cancelled.")
        return

    # Update last_worked_at from filesystem mtimes
    for entry in entries:
        root = entry.get("project_root", "")
        if not os.path.isdir(root):
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
# Command: delete
# ---------------------------------------------------------------------------


def cmd_delete(args):
    cfg = load_config()
    entries = load_index()

    query = args.query
    if not query:
        print("Usage: proj delete <query>")
        return

    entry = find_entry(entries, query)
    if not entry:
        print(f"No project found for '{query}'")
        return

    root = entry.get("project_root", "")
    dir_exists = os.path.isdir(root)

    print(f"Project: {entry['name']}")
    print(f"  ID:       {entry['id']}")
    print(f"  Category: {entry.get('category', '?')}")
    print(f"  Path:     {root}")
    print(f"  On disk:  {'yes' if dir_exists else 'no (already deleted)'}")
    print()

    if args.yes or prompt_confirm(f"Remove '{entry['name']}' from the project index?", default=False):
        entries = [e for e in entries if e["id"] != entry["id"]]
        save_index(entries)
        generate_projects_index(entries, cfg)
        print(f"Removed '{entry['name']}' from the index.")

        if dir_exists and not args.keep:
            if args.yes or prompt_confirm("Also delete the project directory from disk?", default=False):
                shutil.rmtree(root)
                print(f"Deleted: {root}")
            else:
                print(f"Directory kept: {root}")
    else:
        print("Cancelled.")


# ---------------------------------------------------------------------------
# Ideas — display helpers
# ---------------------------------------------------------------------------


def _idea_category_emoji(cat_key):
    """Return the emoji for a category key, or empty string."""
    if cat_key == "new_app":
        return "🚀"
    for key, emoji, _, _ in IDEA_CATEGORIES:
        if key == cat_key:
            return emoji
    return ""


def _idea_list(ideas, entries, project_filter=None):
    """Display open ideas grouped by project, with done count at end."""
    # Build project name lookup
    proj_names = {e["id"]: e["name"] for e in entries}

    filtered = ideas
    if project_filter:
        filtered = [i for i in ideas if i.get("project_id") == project_filter]

    open_ideas = [i for i in filtered if not i.get("done")]
    done_ideas = [i for i in filtered if i.get("done")]

    if not open_ideas and not done_ideas:
        print("No ideas recorded yet. Run `proj idea` to capture one.")
        return

    # Group open ideas by project
    by_project = {}
    for idea in open_ideas:
        pname = idea.get("project_name") or proj_names.get(idea.get("project_id")) or "New App Ideas"
        by_project.setdefault(pname, []).append(idea)

    if open_ideas:
        for pname in sorted(by_project):
            print(f"\n  {BOLD}{pname}{RESET}")
            for idea in by_project[pname]:
                emoji = _idea_category_emoji(idea.get("category", ""))
                iid = idea["id"]
                title = idea["title"]
                gh = ""
                if idea.get("gh_issue_number"):
                    gh = f"  {DIM}#{idea['gh_issue_number']}{RESET}"
                date = format_date(idea.get("created_at"), short=True)
                print(f"    {DIM}{iid:>3}{RESET}  {emoji}  {title}{gh}  {DIM}{date}{RESET}")
    else:
        print("\n  No open ideas.")

    # Done summary
    if done_ideas:
        print(f"\n  {DIM}Done ({len(done_ideas)}):{RESET}")
        for idea in done_ideas[-5:]:
            emoji = _idea_category_emoji(idea.get("category", ""))
            pname = idea.get("project_name") or proj_names.get(idea.get("project_id")) or "New App"
            print(f"    {DIM}{idea['id']:>3}  {emoji}  {idea['title']} ({pname}){RESET}")
        if len(done_ideas) > 5:
            print(f"    {DIM}... and {len(done_ideas) - 5} more{RESET}")
    print()


def _idea_mark_done(ideas, idea_id):
    """Find idea by ID, set done=True, save. Returns True on success."""
    for idea in ideas:
        if idea["id"] == idea_id:
            if idea.get("done"):
                print(f"Idea #{idea_id} is already done.")
                return True
            idea["done"] = True
            save_ideas(ideas)
            emoji = _idea_category_emoji(idea.get("category", ""))
            print(f"  {GREEN}Done:{RESET} {emoji}  {idea['title']}")
            return True
    print(f"No idea found with ID '{idea_id}'.")
    return False


def _idea_delete(ideas, idea_id):
    """Find idea by ID, confirm, remove from list, save. Returns True on success."""
    for i, idea in enumerate(ideas):
        if idea["id"] == idea_id:
            emoji = _idea_category_emoji(idea.get("category", ""))
            pname = idea.get("project_name") or "New App"
            print(f"  {emoji}  {idea['title']}  ({pname})")
            if prompt_confirm(f"Delete idea #{idea_id}?", default=False):
                ideas.pop(i)
                save_ideas(ideas)
                print(f"  {YELLOW}Deleted.{RESET}")
                return True
            print("  Cancelled.")
            return True
    print(f"No idea found with ID '{idea_id}'.")
    return False


# ---------------------------------------------------------------------------
# Command: idea
# ---------------------------------------------------------------------------


def cmd_idea(args):
    entries = load_index()
    ideas = load_ideas()

    # --list mode
    if args.list_ideas:
        project_id = None
        if args.project:
            entry = find_entry(entries, args.project)
            if not entry:
                print(f"No project found for '{args.project}'")
                return
            project_id = entry["id"]
        _idea_list(ideas, entries, project_filter=project_id)
        return

    # --done mode
    if args.done:
        _idea_mark_done(ideas, args.done)
        return

    # --delete mode
    if args.delete:
        _idea_delete(ideas, args.delete)
        return

    # Capture mode — pick type first
    cat_labels = [f"{emoji}  {name} — {desc}" for _, emoji, name, desc in IDEA_CATEGORIES]
    new_app_label = "🚀  New App — idea for a brand new project"
    all_labels = cat_labels + [new_app_label]
    chosen_label = prompt_choice("Type", all_labels)

    is_new_app = chosen_label == new_app_label
    if is_new_app:
        cat_key, cat_emoji = "new_app", "🚀"
    else:
        cat_idx = cat_labels.index(chosen_label)
        cat_key, cat_emoji, _, _ = IDEA_CATEGORIES[cat_idx]

    # Resolve project (skip for new app ideas)
    entry = None
    if not is_new_app:
        if args.project:
            entry = find_entry(entries, args.project)
            if not entry:
                print(f"No project found for '{args.project}'")
                return
        else:
            if not entries:
                print("No projects tracked. Run `proj new` first.")
                return
            cats = sorted({e.get("category", "") for e in entries if e.get("category")})
            if len(cats) > 1:
                group = prompt_choice("Project group", cats)
                pool = [e for e in entries if e.get("category") == group]
            else:
                pool = entries
            pool = sorted(pool, key=lambda e: e.get("last_worked_at", ""), reverse=True)
            names = [e["name"] for e in pool]
            chosen = prompt_choice("Select project", names)
            entry = next(e for e in pool if e["name"] == chosen)

    # Title
    title = args.title
    if not title:
        title = prompt_text("Title")
    if not title:
        print("Title is required.")
        return

    # Body (optional)
    body = args.body
    if not body and not args.quick:
        body = prompt_text("Description (optional)")

    # Save idea locally
    idea = {
        "id": _next_idea_id(ideas),
        "project_id": entry["id"] if entry else None,
        "project_name": entry["name"] if entry else None,
        "category": cat_key,
        "title": title,
        "body": body or "",
        "created_at": now_iso(),
        "gh_issue_url": None,
        "gh_issue_number": None,
        "done": False,
    }
    ideas.append(idea)
    save_ideas(ideas)
    print(f"\n  {GREEN}Saved:{RESET} {cat_emoji}  {title}")
    if entry:
        print(f"  {DIM}Idea #{idea['id']} for {entry['name']}{RESET}")
    else:
        print(f"  {DIM}Idea #{idea['id']} (new app){RESET}")

    # Offer to create GitHub issue if repo has a remote
    if entry:
        project_root = entry.get("project_root", "")
        repo_url = get_repo_url(project_root) if project_root else None
        if repo_url and _gh_available():
            if prompt_confirm("Create GitHub issue?"):
                gh_body = body or ""
                result = _create_gh_issue(project_root, title, gh_body, cat_key)
                if result:
                    idea["gh_issue_url"] = result["url"]
                    idea["gh_issue_number"] = result["number"]
                    save_ideas(ideas)
                    print(f"  {GREEN}Issue created:{RESET} {result['url']}")
                else:
                    print(f"  {YELLOW}Could not create issue (gh error).{RESET}")


# ---------------------------------------------------------------------------
# Command: reflect
# ---------------------------------------------------------------------------

REFLECTFLOW_STAGING = os.path.expanduser("~/.claude/reflectflow/staging")
REFLECTFLOW_ARCHIVE = os.path.expanduser("~/.claude/reflectflow/archive")

_REFLECT_TYPE_MAP = {
    "quick-scan": "Quick Scan",
    "feature-review": "Feature Review",
    "weekly-retro": "Weekly Retro",
    "decisions": "Decisions",
    "doc-update": "Doc Update",
}


def _reflect_finding_type(filename):
    """Derive finding type from filename prefix."""
    for prefix, label in _REFLECT_TYPE_MAP.items():
        if filename.startswith(prefix):
            return label
    return "Finding"


def _reflect_is_error(filepath):
    """Check if a finding file is just an error message."""
    try:
        size = os.path.getsize(filepath)
        if size >= 100:
            return False
        with open(filepath) as f:
            content = f.read()
        return "Error: Exceeded" in content
    except OSError:
        return False


def _reflect_archive(filepath):
    """Move a finding file to the archive directory."""
    ensure_dir(REFLECTFLOW_ARCHIVE)
    dest = os.path.join(REFLECTFLOW_ARCHIVE, os.path.basename(filepath))
    shutil.move(filepath, dest)


def _reflect_list_findings():
    """Return list of (filepath, filename, type_label) for pending findings."""
    if not os.path.isdir(REFLECTFLOW_STAGING):
        return []
    findings = []
    for name in sorted(os.listdir(REFLECTFLOW_STAGING)):
        if name.startswith(".") or not name.endswith(".md"):
            continue
        filepath = os.path.join(REFLECTFLOW_STAGING, name)
        if not os.path.isfile(filepath):
            continue
        findings.append((filepath, name, _reflect_finding_type(name)))
    return findings


def _reflect_dismiss_errors(findings):
    """Auto-archive error-only findings, return remaining findings."""
    errors = set()
    for f in findings:
        if _reflect_is_error(f[0]):
            errors.add(f[0])
    if errors:
        print(f"Found {len(errors)} error-only finding{'s' if len(errors) != 1 else ''}"
              f" — auto-dismissing.")
        for filepath in errors:
            _reflect_archive(filepath)
    return [f for f in findings if f[0] not in errors]


def _reflect_show_summary(findings):
    """Print count summary by type."""
    counts = {}
    for _, _, type_label in findings:
        counts[type_label] = counts.get(type_label, 0) + 1
    parts = ", ".join(f"{v} {k.lower()}{'s' if v != 1 else ''}" for k, v in counts.items())
    total = len(findings)
    print(f"\n{BOLD}{total} pending finding{'s' if total != 1 else ''}{RESET}"
          f" ({parts})")


def _reflect_apply(filepath, content):
    """Handle the Apply action — route finding to a destination."""
    destinations = [
        "Global rule (~/.claude/rules/)",
        "Project rule (.claude/rules/)",
        "Project CLAUDE.md",
        "Memory (~/.claude/projects/.../memory/)",
        "Manual (just print the path suggestion)",
    ]
    dest = prompt_choice("Route to", destinations)

    if dest.startswith("Manual"):
        print(f"\n  {DIM}Suggested locations:{RESET}")
        print(f"    Global rule:  ~/.claude/rules/<name>.md")
        print(f"    Project rule: .claude/rules/<name>.md")
        print(f"    CLAUDE.md:    append to project CLAUDE.md")
        _reflect_archive(filepath)
        print(f"  {GREEN}Archived.{RESET} Apply the content manually.")
        return

    # Determine target directory and prompt for filename
    if dest.startswith("Global"):
        target_dir = os.path.expanduser("~/.claude/rules")
    elif dest.startswith("Project rule"):
        target_dir = os.path.join(os.getcwd(), ".claude", "rules")
    elif dest.startswith("Project CLAUDE"):
        target_path = os.path.join(os.getcwd(), "CLAUDE.md")
        ensure_dir(os.path.dirname(target_path))
        mode = "a" if os.path.exists(target_path) else "w"
        with open(target_path, mode) as f:
            if mode == "a":
                f.write("\n\n")
            f.write(content)
        _reflect_archive(filepath)
        print(f"  {GREEN}Appended to {target_path} and archived.{RESET}")
        return
    elif dest.startswith("Memory"):
        target_dir = os.path.expanduser("~/.claude/projects")
        # Find the first memory directory that exists
        print(f"\n  {DIM}Memory directories are project-specific.")
        print(f"  Copy the content to the appropriate memory file manually.{RESET}")
        _reflect_archive(filepath)
        print(f"  {GREEN}Archived.{RESET} Apply the content manually.")
        return
    else:
        target_dir = os.path.expanduser("~/.claude/rules")

    # Suggest a filename based on the finding file
    basename = os.path.splitext(os.path.basename(filepath))[0]
    # Strip timestamp portion to get a cleaner suggestion
    suggested = re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", basename)
    suggested = re.sub(r"-\d{10,}$", "", suggested)
    if not suggested:
        suggested = basename
    suggested = suggested + ".md"

    filename = prompt_text("Filename", default=suggested)
    if not filename:
        print("  Cancelled.")
        return
    if not filename.endswith(".md"):
        filename += ".md"

    ensure_dir(target_dir)
    target_path = os.path.join(target_dir, filename)
    mode = "a" if os.path.exists(target_path) else "w"
    with open(target_path, mode) as f:
        if mode == "a":
            f.write("\n\n")
        f.write(content)
    _reflect_archive(filepath)
    print(f"  {GREEN}Written to {target_path} and archived.{RESET}")


def cmd_reflect(args):
    """Interactive review of ReflectFlow findings."""
    findings = _reflect_list_findings()

    if not findings:
        print("No pending ReflectFlow findings.")
        return

    # --list: non-interactive listing
    if getattr(args, "list_findings", False):
        _reflect_show_summary(findings)
        error_count = sum(1 for f in findings if _reflect_is_error(f[0]))
        if error_count:
            print(f"  {DIM}({error_count} are error-only — use --dismiss-errors to clean up){RESET}")
        print()
        for filepath, name, type_label in findings:
            is_err = _reflect_is_error(filepath)
            marker = f" {DIM}(error){RESET}" if is_err else ""
            print(f"  {CYAN}{type_label:<16}{RESET} {name}{marker}")
        return

    # --dismiss-errors: bulk dismiss errors only
    if getattr(args, "dismiss_errors", False):
        remaining = _reflect_dismiss_errors(findings)
        errcount = len(findings) - len(remaining)
        if errcount == 0:
            print("No error-only findings found.")
        else:
            print(f"Done. {len(remaining)} finding{'s' if len(remaining) != 1 else ''} remaining.")
        return

    # Interactive review
    # First auto-dismiss errors
    findings = _reflect_dismiss_errors(findings)

    if not findings:
        print("No findings to review after dismissing errors.")
        return

    _reflect_show_summary(findings)

    applied = 0
    dismissed = 0
    skipped = 0

    for filepath, name, type_label in findings:
        print(f"\n{'─' * 60}")
        print(f"  {BOLD}{type_label}{RESET}  {DIM}{name}{RESET}")
        print(f"{'─' * 60}")

        with open(filepath) as f:
            content = f.read()
        lines = content.splitlines()
        total_lines = len(lines)
        truncated = total_lines > 40

        if truncated:
            display = "\n".join(lines[:40])
            print(display)
            print(f"\n  {DIM}... truncated, showing 40/{total_lines} lines{RESET}")
        else:
            print(content)

        while True:
            action = prompt_choice("Action", ["Apply", "Dismiss", "Skip", "Show full"])

            if action == "Show full":
                if truncated:
                    print(f"\n{'─' * 40}")
                    print(content)
                    print(f"{'─' * 40}")
                else:
                    print(f"  {DIM}(already showing full content){RESET}")
                continue

            if action == "Apply":
                _reflect_apply(filepath, content)
                applied += 1
            elif action == "Dismiss":
                _reflect_archive(filepath)
                print(f"  {DIM}Archived.{RESET}")
                dismissed += 1
            else:  # Skip
                skipped += 1
            break

    print(f"\n{BOLD}Review complete:{RESET} "
          f"{GREEN}Applied: {applied}{RESET}, "
          f"Dismissed: {dismissed}, "
          f"Skipped: {skipped}")


# ---------------------------------------------------------------------------
# Command: adr — scaffold an Architecture Decision Record log
# ---------------------------------------------------------------------------

LOG4BRAINS_VERSION = "1.1.0"

ADR_TEMPLATE_MD = """\
# [short title of the decision — a noun phrase, e.g. "Trunk-based deploy via GitHub Actions"]

- Status: [draft | proposed | accepted | rejected | deprecated | superseded by [YYYYMMDD-xxx](yyyymmdd-xxx.md)]
- Deciders: [who made the call]
- Date: [YYYY-MM-DD when the decision was made or last updated]
- Tags: [space/comma separated — e.g. deploy, data, styling, payments, infra]

<!--
AGENT GUIDANCE — read before writing an ADR here:
- One decision per file. Two choices = two ADRs.
- ADRs are IMMUTABLE. Never rewrite an accepted one to reflect a new decision.
  Instead: create a new ADR and set this one's Status to "superseded by [link]",
  and the new one's Status to "accepted" with a "Supersedes [link]" in Links.
- Record the REJECTED options too (## Considered Options). The "why not" is the most
  valuable part for the next reader.
- Ground every claim in evidence: a commit SHA, a file:line, a release tag, or a doc.
  Do not invent rationale. If the "why" isn't recorded anywhere, say so.
- To create one, run `{{new_cmd}}` (auto-dates and numbers the file).
- Verify the decision actually shipped before recording it as accepted.
-->

## Context and Problem Statement

[Two or three sentences. What forced a decision? What was breaking, or what did we need?]

## Considered Options

- [option 1]
- [option 2]
- [option 3]

## Decision Outcome

Chosen option: "[option 1]", because [justification]. [Cite the commit / file:line / tag that
implements it, or mark it not-yet-shipped.]

### Consequences

- Good: [what this bought us]
- Bad / accepted trade-off: [what it cost, what we knowingly gave up]

## Pros and Cons of the Options <!-- optional -->

### [option 2]

- Good, because [...]
- Bad, because [why it was rejected]

## Links <!-- optional -->

- Supersedes [YYYYMMDD-xxx](yyyymmdd-xxx.md)
- Superseded by [YYYYMMDD-xxx](yyyymmdd-xxx.md)
- Related to [YYYYMMDD-xxx](yyyymmdd-xxx.md)
"""

ADR_README_MD = """\
# Architecture Decision Records

This is the decision log for **{{name}}**. Each file records one architecturally-significant
decision: the context, the options weighed, the choice, and its consequences.

## Creating and browsing

```bash
{{new_cmd}}       # create a new ADR (auto-dated + auto-numbered filename)
{{serve_cmd}}     # build the static site and serve it locally
```

These run [log4brains](https://github.com/thomvaill/log4brains) via `npx` (pinned to
{{l4b_version}}), so **nothing is added to this project's dependency tree**. Node is only needed
for browsing and for the auto-numbered filename — the records themselves are plain markdown you
can write by hand.

## The rules

- **One decision per file.** Two choices means two ADRs.
- **ADRs are immutable.** Never edit an accepted ADR to change the decision. Create a new one,
  set the old one's `Status:` to `superseded by [link]`, and add `Supersedes [link]` to the new
  one's `## Links`. Flipping the status and adding that link is the only edit an accepted ADR
  should ever get.
- **Record the rejected options and why.** The "why not" is the most valuable part.
- A decision that is **decided but not yet shipped** is a valid ADR — set `Status: proposed`.

See `template.md` for the full format.

## More information

- [Log4brains documentation](https://github.com/thomvaill/log4brains/tree/develop#readme)
- [ADR GitHub organization](https://adr.github.io/)

<!-- Scaffolded by `proj adr init`. -->
"""

ADR_INDEX_MD = """\
<!-- This file is the homepage of the Log4brains knowledge base. Edit freely. -->

# {{name}} — Architecture knowledge base

Welcome 👋 to the architecture decision log for **{{name}}**.

You'll find here the Architecture Decision Records (ADRs) that got this project to where it is
now — the reasoning behind the choices, including the ones that were reversed.

## Why this exists

An ADR captures one architecturally-significant decision: the context, the options weighed, the
choice, and its consequences. An ADR is **immutable** — once accepted you don't rewrite it, you
supersede it with a new one and link the two. Read the log in date order and you get the whole
story, including the reversals.

## How this is kept up to date

The ADRs are markdown files in `docs/adr/`, managed next to the code. Create one with
`{{new_cmd}}` and browse this knowledge base with `{{serve_cmd}}`.

Browse via the left menu or the search bar.

## More information

- [What is an ADR and why use them](https://github.com/thomvaill/log4brains/tree/develop#-what-is-an-adr-and-why-should-you-use-them)
- [ADR GitHub organization](https://adr.github.io/)
"""

ADR_SKILL_MD = """\
---
name: adr
description: Record or supersede an Architecture Decision Record (ADR) for {{name}}. Use whenever a significant, durable architectural decision is made, changed, or reversed.
---

# adr

The {{name}} decision log lives in `docs/adr/`. It is the project's memory of **why** things are
the way they are. Before changing anything architectural, read the relevant ADRs first — they
exist to stop a settled decision being silently re-litigated or reversed.

## When to invoke

When the user types `/adr`, or asks to "record a decision", "write an ADR", or "supersede an
ADR" — and whenever you (an agent) make an architecturally-significant, durable choice worth
recording.

## When to write one

Write an ADR when a choice is **architecturally significant and durable** — it constrains future
work, or a newcomer would otherwise re-argue it. Examples: the deploy model, the state/data/
styling standard, an auth or payments decision, a build-tooling choice, a reversal of a previous
approach. Do NOT write one for a routine feature or a bugfix.

Keep it scoped to **this repository**. Decisions belonging to another repo belong in that repo's
log.

## How to create one

```bash
{{new_cmd}}       # prompts for a title, then creates docs/adr/YYYYMMDD-slug.md
{{serve_cmd}}     # build + serve the knowledge base locally
```

These run log4brains via `npx` (pinned), so nothing is added to the project's dependency tree.

Fill in the MADR sections (see `docs/adr/template.md`): Context and Problem Statement, Considered
Options, Decision Outcome (start with `Chosen option: "..."`), Consequences.

- **Record the rejected options and why** — the "why not" is the most valuable part.
- **Ground every claim** in a commit SHA, `file:line`, a release tag, or a doc. Never invent
  rationale.
- **Verify it actually shipped** before recording it as `accepted`.

## Rules that must not be broken

- **One decision per ADR.** Two choices → two files.
- **ADRs are immutable.** Never rewrite an accepted ADR to reflect a new decision. Instead:
  1. Create a new ADR for the new decision (status `accepted`).
  2. In the new ADR's `## Links`, add `Supersedes [YYYYMMDD-old](YYYYMMDD-old.md)`.
  3. In the OLD ADR, change `Status:` to `superseded by [YYYYMMDD-new](YYYYMMDD-new.md)`.
  This is the ONLY edit you may make to an accepted ADR — flipping its status and adding the link.
- A decision that was **decided but not yet shipped** is a valid ADR — set `Status: proposed`.
"""

ADR_LOG4BRAINS_YML = """\
project:
  name: {{name}}
  tz: {{tz}}
  adrFolder: ./docs/adr
  packages: []
"""


def _render(template, **values):
    """Substitute {{key}} placeholders. Used instead of str.format so that
    markdown braces in the templates are never interpreted."""
    out = template
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", str(val))
    return out


def _detect_timezone():
    """Best-effort IANA timezone name (e.g. Australia/Sydney)."""
    try:
        path = os.path.realpath("/etc/localtime")
    except OSError:
        return "UTC"
    if "/zoneinfo/" in path:
        return path.split("/zoneinfo/", 1)[1]
    return "UTC"


def _detect_pkg_runner(project_root):
    """Return the script runner prefix for this project's lockfile, or None
    when the project has no package.json to hang scripts off."""
    if not os.path.isfile(os.path.join(project_root, "package.json")):
        return None
    if os.path.isfile(os.path.join(project_root, "pnpm-lock.yaml")):
        return "pnpm"
    if os.path.isfile(os.path.join(project_root, "yarn.lock")):
        return "yarn"
    return "npm run"


def _adr_commands(project_root):
    """Return (new_cmd, serve_cmd) — package scripts when the project has a
    package.json, raw pinned npx invocations otherwise."""
    runner = _detect_pkg_runner(project_root)
    if runner:
        return f"{runner} adr:new", f"{runner} adr:serve"
    npx = f"npx --yes log4brains@{LOG4BRAINS_VERSION}"
    return f"{npx} adr new", f"{npx} build && npx --yes serve .log4brains/out"


def _adr_write(path, content, force):
    """Write a scaffold file. Returns 'created', 'overwritten', or 'skipped'."""
    exists = os.path.exists(path)
    if exists and not force:
        return "skipped"
    ensure_dir(os.path.dirname(path))
    with open(path, "w") as f:
        f.write(content)
    return "overwritten" if exists else "created"


def _adr_add_gitignore(project_root):
    """Ensure /.log4brains is ignored. Returns 'created', 'appended', or 'skipped'."""
    path = os.path.join(project_root, ".gitignore")
    entry = "/.log4brains"
    existing = ""
    if os.path.isfile(path):
        try:
            with open(path) as f:
                existing = f.read()
        except OSError:
            return "skipped"
        if any(line.strip() == entry for line in existing.splitlines()):
            return "skipped"
    block = "# log4brains ADR knowledge-base build output (docs/adr)\n" + entry + "\n"
    if existing and not existing.endswith("\n"):
        block = "\n" + block
    elif existing:
        block = "\n" + block
    try:
        with open(path, "a") as f:
            f.write(block)
    except OSError:
        return "skipped"
    return "appended" if existing else "created"


def _adr_add_pkg_scripts(project_root):
    """Merge the adr:* scripts into package.json. Returns a list of added script
    names, or None when there is no package.json to merge into."""
    path = os.path.join(project_root, "package.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            pkg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    npx = f"npx --yes log4brains@{LOG4BRAINS_VERSION}"
    wanted = {
        "adr:new": f"{npx} adr new",
        "adr:preview": f"{npx} preview",
        "adr:build": f"{npx} build",
        "adr:serve": f"{npx} build && npx --yes serve .log4brains/out",
    }
    scripts = pkg.setdefault("scripts", {})
    added = [k for k, v in wanted.items() if k not in scripts]
    if not added:
        return []
    for key in added:
        scripts[key] = wanted[key]
    atomic_write_json(path, pkg)
    return added


def scaffold_adr(project_root, name, force=False, with_skill=True, quiet=False):
    """Create the ADR log scaffold in project_root. Returns True on success."""
    if not os.path.isdir(project_root):
        print(f"Project directory does not exist: {project_root}")
        return False

    adr_dir = os.path.join(project_root, "docs", "adr")
    new_cmd, serve_cmd = _adr_commands(project_root)
    subs = {
        "name": name,
        "tz": _detect_timezone(),
        "new_cmd": new_cmd,
        "serve_cmd": serve_cmd,
        "l4b_version": LOG4BRAINS_VERSION,
    }

    files = [
        (os.path.join(adr_dir, "template.md"), ADR_TEMPLATE_MD),
        (os.path.join(adr_dir, "README.md"), ADR_README_MD),
        (os.path.join(adr_dir, "index.md"), ADR_INDEX_MD),
        (os.path.join(project_root, ".log4brains.yml"), ADR_LOG4BRAINS_YML),
    ]
    if with_skill:
        files.append(
            (os.path.join(project_root, ".claude", "skills", "adr", "SKILL.md"), ADR_SKILL_MD)
        )

    results = []
    for path, template in files:
        outcome = _adr_write(path, _render(template, **subs), force)
        results.append((os.path.relpath(path, project_root), outcome))

    gitignore = _adr_add_gitignore(project_root)
    scripts_added = _adr_add_pkg_scripts(project_root)

    if quiet:
        return True

    print(f"\n{BOLD}ADR log scaffolded:{RESET} {project_root}")
    for rel, outcome in results:
        if outcome == "skipped":
            print(f"  {DIM}skipped   {rel} (already exists){RESET}")
        else:
            print(f"  {GREEN}{outcome:<9}{RESET} {rel}")
    if gitignore != "skipped":
        print(f"  {GREEN}{gitignore:<9}{RESET} .gitignore (/.log4brains)")
    if scripts_added:
        print(f"  {GREEN}added     {RESET} package.json scripts: {', '.join(scripts_added)}")

    if any(o == "skipped" for _, o in results) and not force:
        print(f"\n  {DIM}Re-run with --force to overwrite existing files.{RESET}")

    print(f"\n  Create a record:  {CYAN}{new_cmd}{RESET}")
    print(f"  Browse the log:   {CYAN}{serve_cmd}{RESET}")
    if scripts_added is None:
        print(f"  {DIM}No package.json found — the commands above run log4brains directly.{RESET}")
    return True


def cmd_adr(args):
    entries = load_index()

    entry = None
    if args.query:
        entry = find_entry(entries, args.query)
        if not entry:
            print(f"No project found for '{args.query}'")
            return
    else:
        # Fall back to whichever indexed project contains the working directory.
        cwd = os.path.realpath(os.getcwd())
        for e in entries:
            root = e.get("project_root", "")
            if not root:
                continue
            root = os.path.realpath(os.path.expanduser(root))
            if cwd == root or cwd.startswith(root + os.sep):
                entry = e
                break
        if not entry:
            print("Not inside a tracked project. Pass a project: proj adr init <id|name>")
            return

    scaffold_adr(
        os.path.expanduser(entry["project_root"]),
        entry["name"],
        force=args.force,
        with_skill=not args.no_skill,
    )


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
    p_new.add_argument("--adr", action="store_true",
                       help="Scaffold an ADR decision log in docs/adr/")

    # list
    p_list = sub.add_parser("list", aliases=["ls"], help="List projects")
    p_list.add_argument("--status", choices=["active", "stale", "archived"],
                        help="Filter by status")
    p_list.add_argument("--category", "-c", help="Filter by category")
    p_list.add_argument("--limit", "-l", type=int, help="Max projects to show")
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
    p_edit.add_argument("--summary", "-s", help="Set summary")
    p_edit.add_argument("--category", "-c", help="Set category")
    p_edit.add_argument("--name", "-n", help="Rename project")
    p_edit.add_argument("--archive", action="store_true", help="Archive the project")
    p_edit.add_argument("--unarchive", action="store_true", help="Unarchive the project")
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
    p_rescan.add_argument("--prune", action="store_true",
                          help="Remove projects whose directories no longer exist")
    p_rescan.add_argument("--reslug", action="store_true",
                          help="Rename project directories to match current slugify rules")
    p_rescan.add_argument("--reslug-check", action="store_true",
                          help="Interactively review and rename each project directory")
    p_rescan.add_argument("--verbose", "-v", action="store_true")

    # delete
    p_delete = sub.add_parser("delete", aliases=["rm"], help="Remove a project from the index")
    p_delete.add_argument("query", help="Project ID, name, or slug")
    p_delete.add_argument("--yes", "-y", action="store_true",
                          help="Skip confirmation prompts")
    p_delete.add_argument("--keep", "-k", action="store_true",
                          help="Only remove from index, never delete files from disk")

    # ignore
    p_ignore = sub.add_parser("ignore", help="Ignore folders that aren't projects")
    p_ignore.add_argument("query", nargs="?", help="Project ID, name, or path to ignore")
    p_ignore.add_argument("--list", "-l", dest="list_ignored", action="store_true",
                          help="List all ignored paths")
    p_ignore.add_argument("--remove", "-r", action="append",
                          help="Un-ignore a path (substring match)")

    # idea
    p_idea = sub.add_parser("idea", help="Capture or list project ideas")
    p_idea.add_argument("project", nargs="?", help="Project ID, name, or slug")
    p_idea.add_argument("--title", "-t", help="Idea title")
    p_idea.add_argument("--body", "-b", help="Longer description")
    p_idea.add_argument("--list", "-l", dest="list_ideas", action="store_true",
                        help="List open ideas")
    p_idea.add_argument("--done", "-d", metavar="ID", help="Mark idea as done")
    p_idea.add_argument("--delete", metavar="ID", help="Delete an idea")
    p_idea.add_argument("--quick", "-q", action="store_true",
                        help="Skip optional prompts")

    # adr
    p_adr = sub.add_parser("adr", help="Scaffold an ADR decision log in a project")
    p_adr.add_argument("action", nargs="?", choices=["init"], default="init",
                       help="ADR action (only 'init' for now)")
    p_adr.add_argument("query", nargs="?",
                       help="Project ID, name, or slug (defaults to the current directory)")
    p_adr.add_argument("--force", "-f", action="store_true",
                       help="Overwrite scaffold files that already exist")
    p_adr.add_argument("--no-skill", dest="no_skill", action="store_true",
                       help="Don't write .claude/skills/adr/SKILL.md")

    # reflect
    p_reflect = sub.add_parser("reflect", help="Review ReflectFlow findings")
    p_reflect.add_argument("--list", "-l", dest="list_findings", action="store_true",
                           help="List pending findings (non-interactive)")
    p_reflect.add_argument("--dismiss-errors", dest="dismiss_errors", action="store_true",
                           help="Auto-archive error-only findings")

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
        "delete": cmd_delete,
        "rm": cmd_delete,
        "ignore": cmd_ignore,
        "idea": cmd_idea,
        "adr": cmd_adr,
        "reflect": cmd_reflect,
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
