<!--
The brief this tool was built from, written 2026-02-22 before any code existed.
Kept as provenance: it records what was asked for, which is usually more useful
than a description written afterwards.

Two things have changed since. The command shipped as `pb`, not `proj`, because
`proj` is already taken by PROJ, the cartographic projections library; the
command names below have been updated so nobody follows a wrong one. And plenty
was built that this brief never asked for: decision logs, GitHub repo creation,
discovery and review. See the README for what the tool actually does.
-->

# I want to establish a better way of creating and maintaining all of the projects I'm working on.

At the moment, I tend to create a new folder in whichever folder I think it appropriate. Then inside that I create a folder called docs and then inside that I create a file called {project_name}_initial_prompt.md

I think I'd like a terminal script to automate this process and help me name, place and organise new projects. I'd also like create and automatically update an index document that keeps track of all my projects names, where they are located, a one sentence summary, where to find a detailed summary or readme file for the project, when it was create and when it was last edited (worked on). It should also have automatically updating statuses like active, stale (2 weeks since changes made), archived (3 months since marked stale).

This all need to run locally and be easily maintained.

Write a prompt for Claude Code to build this for me. Focus on the user experience and

Acting as an experience product manager, flesh out these ideas into a detailed prompt ready for Claude Code to build. You do not have to architect it or do the technical design, just focus on the product requirements.

You want a local, CLI-first “project initializer + indexer” that standardizes how you create, name, place, and track projects, with a good UX and without over‑engineering. Here is a product‑requirements style prompt you can paste directly into Claude Code.

***

You are an experienced CLI tool and automation engineer.

Design and implement a small, local-only command line tool that helps me create and maintain software and non‑software “projects” in a consistent way on macOS. The primary goal is to improve the **user** experience of starting, finding, and revisiting projects, not to over‑engineer the internals.

Do not worry about perfect architecture; prioritize a clean UX, clear data model, and maintainability. Use simple, well‑documented code and avoid heavy dependencies.

## Overall concept

I want a “project initializer and indexer” I can run from the terminal to:

- Create new projects with a consistent folder and file structure.
- Capture a short description and initial prompt/notes at creation time.
- Maintain a single, automatically updated “projects index” file with key metadata.
- Track “status” (active vs stale vs archived) based on time since last work.
- Make it easy to list, filter, search, and jump into projects from the CLI.

Assume I’m comfortable with the terminal and git, but I want something that “just works” and is easy to adjust later.

## Scope and constraints

- Runs locally only (no network calls, no cloud).
- macOS‑friendly; POSIX shell paths and tools.
- No daemon or background service; everything is run on demand from commands.
- Use plain text formats (Markdown, JSON or YAML) for data so I can inspect and edit by hand.
- Prefer one self‑contained script or a very small CLI tool, plus config and data files.
- I will run this from the terminal, e.g. `pb new`, `pb list`, etc.

If you need to assume a language, choose one that is easy to run on macOS with no extra friction (for example Python or a POSIX shell script).

***

## User experience and commands

Design the UX around a single CLI entrypoint, referred to here as `pb` (actual name can be configurable).

Support at least these top‑level commands:

1. `pb new`
2. `pb list`
3. `pb info`
4. `pb edit`
5. `pb open`
6. `pb rescan` (optional but desirable)
7. `pb config` (basic config management)

### 1) `pb new`: create a project

Goal: Make it pleasant and fast to create a new project with consistent structure and metadata, while still allowing me to think for a moment about naming and intent.

Flow:

- If I just type `pb new`, guide me through an interactive prompt flow:
  - Ask for a **project name** (free text, e.g. “ClientX booking integration”).
    - Internally create a “slugified” folder name (e.g. `clientx-booking-integration`).
    - Support defaulting to the slug as the project ID.
  - Ask me to pick a **project category** (configurable list, e.g. `personal`, `client`, `company`, `experiment`).
    - Allow a default category to be configured.
  - Ask for a **one‑sentence summary** of the project (short description).
  - Ask for an optional **detailed description / initial notes**:
    - Allow either multi-line input right in the terminal (ended by some delimiter) OR open my default editor if that’s simpler.
  - Ask for a **base directory** if I have multiple base locations (e.g. `~/Projects`, `~/Clients`, external drive paths), or default to the configured base path.
    - Ideally, pre‑populate choices from config (e.g. `[^1] ~/Projects`, `[^2] ~/Clients/Active`, `[^3] /Volumes/External/Projects`).
- The tool creates the project folder structure, for example:
  - `{base_dir}/{category}/{project_slug}/`
    - `docs/`
      - `{project_slug}_initial_prompt.md` (or a configurable file name pattern)
      - A main readme, e.g. `README.md`.
- The initial docs should be pre‑templated with:
  - A small frontmatter section (YAML or similar) that stores metadata like:
    - `id`, `name`, `category`, `summary`, `created_at`, `updated_at`, `status` (initially `active`).
  - A clear section heading for “Initial Prompt / Notes” where the captured text goes.
- After creation:
  - Update the global project index file (see below).
  - Show me a concise confirmation, plus a short “next actions” message, e.g.:
    - “Project created at: /full/path/to/project”
    - “Docs: /full/path/to/project/docs/{project_slug}_initial_prompt.md”
    - Offer a one‑key shortcut to open the project folder or the initial prompt file in my editor if feasible (e.g. ask “Open now? [y/N]”).

Also support a non‑interactive mode, like:

```bash
pb new --name "ClientX booking integration" \
         --category client \
         --summary "Migrate booking flows to new API" \
         --base ~/Clients \
         --no-notes
```


### 2) `pb list`: view and filter projects

Goal: Give me a “control panel” style view of all projects without leaving the terminal, with sensible defaults and filters.

Behavior:

- By default (`pb list` with no args), show a table including:
  - Project ID or short name
  - Human-readable name
  - Status (`active`, `stale`, `archived`)
  - Category
  - Created date
  - Last worked date (derived from index; see below)
  - One‑line summary
- Provide useful sorting and filtering flags, for example:
  - `--status active|stale|archived|any`
  - `--category personal|client|company|experiment|…`
  - `--limit N`
  - `--sort created|updated|name|status` (with ascending/descending)
- Consider a short mode (`pb list --short`) that prints a minimal view, suitable for piping into other tools.
- Ensure the output formatting is readable in a standard terminal (fixed width columns, truncation for long summaries, etc.).


### 3) `pb info`: show project details

Goal: Quickly see all key metadata and links for a single project.

Behavior:

- `pb info <project_id_or_name>`
  - Allow resolving by:
    - Exact ID / slug.
    - Partial match on name (if ambiguous, list choices).
- Output:
  - All metadata stored in the index (name, category, paths, summary, created, last updated, status).
  - Paths:
    - Project root folder.
    - Main docs folder.
    - Initial prompt file path.
    - Optional: location of readme / main design doc.
  - Show status and how it was computed (e.g. “stale: last updated 19 days ago”).
- Optionally allow a `--json` flag to output machine‑readable data.


### 4) `pb edit`: update metadata

Goal: Let me adjust the one‑sentence summary, category, or other metadata after creation, in a safe and simple way.

Behavior:

- `pb edit <project_id>`:
  - Interactively ask which fields to update: summary, category, maybe name (but be careful about renaming folders; see below).
  - For non‑destructive metadata fields (summary, category, tags), just update index + frontmatter.
  - If name changes, decide how to handle the folder:
    - For MVP, you can choose to not rename the folder, but allow a “display name” distinct from the slug.
    - Document this clearly.
- Ensure the index stays consistent with any changes.
- Optionally support a non‑interactive form with flags.


### 5) `pb open`: jump into a project

Goal: Make it easy to get back into a project with one command.

Behavior:

- `pb open <project_id>`
  - By default:
    - Change directory to the project folder (for shells that support it) OR print the path so I can `cd` manually.
    - Optionally open the project folder in Finder or VS Code if a flag is provided (e.g. `--code`, `--finder`).
  - `pb open --docs <project_id>` could open the docs folder or the initial prompt file in my configured editor.

You can implement `pb open` in a way that prints clearly usable commands if direct directory changing is not straightforward (e.g. `cd /path/...`).

### 6) `pb rescan`: reconcile timestamps and statuses

Goal: Keep the index in sync with reality when files are edited directly.

Behavior:

- The index should track:
  - `created_at`: timestamp when project was first created.
  - `last_worked_at`: last time the project was considered “worked on.”
- For `last_worked_at`, make a reasonable and maintainable design:
  - MVP: update `last_worked_at` whenever a `pb` command touches the project (e.g. `pb new`, `pb edit`, maybe `pb open` with a flag).
  - Optional: provide `pb rescan` which:
    - Walks all project folders listed in the index.
    - Computes the last modification time of any file in each project.
    - Updates `last_worked_at` accordingly.
- Status rules (configurable but default as):
  - `active`: last_worked_at < 14 days ago.
  - `stale`: last_worked_at >= 14 days ago and < 90 days ago.
  - `archived`: last_worked_at >= 90 days ago OR explicitly marked archived.
- Implement status as derived rather than manually set where possible:
  - Either recompute on each command or during `pb rescan`.
- Provide a way to explicitly mark a project as archived:

```
- `pb edit <id> --archive` or `pb archive <id>` (if you prefer a separate command).
```

    - Once archived, treat it as archived even if files change, unless explicitly unarchived.


### 7) `pb config`: configuration

Goal: Give me a single place to configure paths, categories, thresholds, and defaults.

Behavior:

- Store a config file in my home directory, e.g. `~/.projconfig.yml` (or similar).
- Config options should include at least:
  - `base_directories`: list of root paths, each with:
    - `id` or `name` (e.g. `default`, `clients`, `experiments`)
    - `path`
  - `default_base_directory`
  - `categories`: list of known categories.
  - `status_thresholds`:
    - `stale_after_days` (e.g. 14)
    - `archived_after_days` (e.g. 90)
  - Format for project folder naming (e.g. slug from project name).
  - Template paths/names for:
    - Initial prompt document name.
    - Readme or main summary file.
- Provide simple subcommands to:
  - `pb config show` (print current config).
  - `pb config edit` (open config file in editor).
- Ensure there are safe defaults if no config exists (e.g. create `~/Projects` by default).

***

## Project index file

Key requirement: Maintain an index document that tracks all projects and is automatically updated.

Design goals:

- Single source of truth.
- Easy to read and diff in git.
- Easy to programmatically update.

Implementation preferences:

- Use JSON, YAML, or a single Markdown file with a structured table. YAML or JSON is likely easiest for reliable updates.
- Default location example: `~/.proj_index.json` or `~/.pb/index.yml`.

For each project, store at least:

- `id` (slug or unique ID).
- `name` (human readable).
- `category`.
- `summary` (one sentence).
- `project_root_path`.
- `docs_path`.
- `initial_prompt_path`.
- `created_at`.
- `last_worked_at`.
- `status` (either derived on read or stored and recomputed).
- Optional:
  - `tags`: list of strings.
  - `archived_reason` or notes.

When a project is created or edited, update the index immediately. Make index updates robust and safe (e.g. write to a temp file then move, to avoid corruption).

Also generate or maintain a human‑friendly Markdown index alongside the structured index (optional but desirable), for example:

- `~/Projects/PROJECTS_INDEX.md`

This Markdown file could contain a table (one row per project) with:

- Name (linked to folder path if possible)
- Status
- Category
- Created
- Last worked
- Summary

Whenever the index changes, regenerate this Markdown file from the structured index.

***

## File and folder conventions

Use sensible defaults but keep them configurable.

Example default structure:

- Base directories:
  - `~/Projects`
  - `~/Clients`
- New project path pattern:
  - `{base_dir}/{category}/{project_slug}/`
- Under each project:
  - `docs/`
    - `{project_slug}_initial_prompt.md`
    - `README.md`
  - (Leave space for me to add `/src`, `/data`, etc.; do not enforce code structure.)

Initial prompt file content:

- Include frontmatter (YAML or similar) that mirrors key index fields.
- Example:

```yaml
---
id: clientx-booking-integration
name: ClientX booking integration
category: client
summary: Migrate booking flows to new API.
created_at: 2026-02-22T12:34:56+10:00
updated_at: 2026-02-22T12:34:56+10:00
status: active
---
```

Then a heading and the captured initial prompt / notes below.

***

## Status logic and “stale/archived”

Clear expectations for status:

- Status should reflect **time since last meaningful work**, not just time since creation.
- Default thresholds:
  - `active`: last worked under 14 days ago.
  - `stale`: 14 to 90 days.
  - `archived`: 90+ days OR explicitly archived.

User experience details:

- Whenever I run `pb list`, I should see up‑to‑date statuses.
- If you recompute on every command, that’s fine for a modest number of projects.
- If you rely on `pb rescan`, make that obvious in the documentation and provide a friendly message if the data might be out of date.
- If the tool explicitly archives a project, status should remain `archived` unless I deliberately unarchive it.

***

## Implementation/maintenance considerations

- Prefer minimal, readable code. No heavy frameworks.
- Include:
  - Clear comments.
  - A short README explaining how to install, configure, and use the tool.
- Handle errors gracefully:
  - Missing base directory.
  - Invalid project ID.
  - Index file corrupted or missing.
- Support dry‑run mode where it makes sense for destructive operations (e.g. if you ever add cleanup/archive moves later).
- Make it easy to extend later (e.g. adding tags, priorities, or integration with git), but do not implement those now unless trivial.

***

## Deliverables

Produce:

1. The main CLI script or small codebase implementing:
   - `pb new`, `pb list`, `pb info`, `pb edit`, `pb open`, `pb rescan`, `pb config`.
2. A default config file example.
3. An example index file and example generated project structure.
4. A short README explaining:
   - How to install and invoke the tool.
   - How to configure base directories and categories.
   - How statuses work and how to interpret “stale” and “archived”.
   - A couple of example workflows:
     - Creating a new client project.
     - Listing stale projects and opening one.

Focus on making the day‑to‑day UX of starting and revisiting projects feel smooth and consistent, while keeping the internal design simple and maintainable.
