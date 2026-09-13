#!/usr/bin/env python3
"""Tests for pb.

Run them with:

    python3 -m unittest discover -v

Stdlib only, matching the tool itself. Every test that touches disk works in a
temporary directory, and the data-layer tests repoint pb's module-level paths
at that directory, so a test run can never read or write the real ~/.pb.
"""

import datetime
import io
import json
import os
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout

import pb


def iso_days_ago(days):
    """An ISO timestamp *days* in the past, as the index stores them."""
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return when.isoformat()


def entry(**kw):
    """An index entry with sensible defaults, overridden by keyword."""
    base = {
        "id": "1",
        "name": "Test Project",
        "category": "Work",
        "summary": "",
        "project_root": "/nonexistent/work/test-project",
        "docs_path": "/nonexistent/work/test-project/docs",
        "initial_prompt_path": "",
        "base_directory": "default",
        "created_at": iso_days_ago(1),
        "last_worked_at": iso_days_ago(1),
        "archived": False,
        "tags": [],
    }
    base.update(kw)
    return base


class TempDirCase(unittest.TestCase):
    """Gives each test an empty directory that is removed afterwards."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pb-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def make(self, *parts, contents=None):
        """Create a file (with contents) or a directory, and return its path."""
        path = os.path.join(self.tmp, *parts)
        if contents is None:
            os.makedirs(path, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(contents)
        return path


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify(unittest.TestCase):

    def test_lowercases_and_hyphenates(self):
        self.assertEqual(pb.slugify("My Cool Project"), "my-cool-project")

    def test_splits_camel_case(self):
        self.assertEqual(pb.slugify("CalendarSync"), "calendar-sync")

    def test_splits_acronym_followed_by_word(self):
        self.assertEqual(pb.slugify("HTTPServer"), "http-server")

    def test_drops_punctuation(self):
        self.assertEqual(pb.slugify("Rich's App (v2)!"), "richs-app-v2")

    def test_collapses_separator_runs(self):
        self.assertEqual(pb.slugify("a __ b -- c"), "a-b-c")

    def test_trims_leading_and_trailing_separators(self):
        self.assertEqual(pb.slugify("  --Edges--  "), "edges")

    def test_is_idempotent(self):
        once = pb.slugify("Some Project Name")
        self.assertEqual(pb.slugify(once), once)


# ---------------------------------------------------------------------------
# compute_status
# ---------------------------------------------------------------------------


class TestComputeStatus(unittest.TestCase):

    def setUp(self):
        self.cfg = {"status_thresholds": {"stale_after_days": 14,
                                          "archived_after_days": 90}}

    def test_recent_is_active(self):
        self.assertEqual(pb.compute_status(entry(last_worked_at=iso_days_ago(3)),
                                             self.cfg), "active")

    def test_stale_threshold_is_inclusive(self):
        self.assertEqual(pb.compute_status(entry(last_worked_at=iso_days_ago(14)),
                                             self.cfg), "stale")

    def test_day_before_stale_is_still_active(self):
        self.assertEqual(pb.compute_status(entry(last_worked_at=iso_days_ago(13)),
                                             self.cfg), "active")

    def test_archived_threshold_is_inclusive(self):
        self.assertEqual(pb.compute_status(entry(last_worked_at=iso_days_ago(90)),
                                             self.cfg), "archived")

    def test_manual_archive_flag_wins_over_recent_work(self):
        e = entry(last_worked_at=iso_days_ago(0), archived=True)
        self.assertEqual(pb.compute_status(e, self.cfg), "archived")

    def test_missing_timestamp_is_active(self):
        self.assertEqual(pb.compute_status(entry(last_worked_at=None),
                                             self.cfg), "active")

    def test_unparseable_timestamp_is_active_not_an_error(self):
        self.assertEqual(pb.compute_status(entry(last_worked_at="not a date"),
                                             self.cfg), "active")

    def test_naive_timestamp_is_treated_as_utc(self):
        aware = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=20)
        naive = aware.replace(tzinfo=None).isoformat()
        self.assertEqual(pb.compute_status(entry(last_worked_at=naive),
                                             self.cfg), "stale")

    def test_thresholds_come_from_config(self):
        cfg = {"status_thresholds": {"stale_after_days": 2, "archived_after_days": 5}}
        self.assertEqual(pb.compute_status(entry(last_worked_at=iso_days_ago(3)),
                                             cfg), "stale")


# ---------------------------------------------------------------------------
# find_entry
# ---------------------------------------------------------------------------


class TestFindEntry(unittest.TestCase):

    def setUp(self):
        self.entries = [
            entry(id="1", name="Alpha Tool"),
            entry(id="2", name="Beta Service"),
            entry(id="12", name="Gamma Beta Widget"),
        ]

    def find(self, query):
        """find_entry prints on ambiguity; keep test output clean."""
        with redirect_stdout(io.StringIO()):
            return pb.find_entry(self.entries, query)

    def test_exact_id_beats_prefix(self):
        # "1" is also a prefix of "12", and the exact match must win.
        self.assertEqual(self.find("1")["name"], "Alpha Tool")

    def test_id_prefix_when_unambiguous(self):
        self.assertEqual(self.find("12")["name"], "Gamma Beta Widget")

    def test_name_substring_is_case_insensitive(self):
        self.assertEqual(self.find("alpha")["id"], "1")

    def test_slug_match(self):
        self.assertEqual(self.find("beta-service")["id"], "2")

    def test_ambiguous_name_returns_none(self):
        self.assertIsNone(self.find("Beta"))

    def test_no_match_returns_none(self):
        self.assertIsNone(self.find("nothing-like-this"))

    def test_empty_query_returns_none(self):
        self.assertIsNone(self.find(""))


# ---------------------------------------------------------------------------
# next_id
# ---------------------------------------------------------------------------


class TestNextId(unittest.TestCase):

    def test_first_id_is_one(self):
        self.assertEqual(pb.next_id([]), "1")

    def test_continues_from_the_highest(self):
        self.assertEqual(pb.next_id([entry(id="1"), entry(id="7")]), "8")

    def test_reuses_nothing_after_a_deletion(self):
        # 2 was deleted; the next id must not collide with the surviving 3.
        self.assertEqual(pb.next_id([entry(id="1"), entry(id="3")]), "4")

    def test_ignores_non_numeric_ids(self):
        self.assertEqual(pb.next_id([entry(id="1"), entry(id="legacy")]), "2")


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


class TestFrontmatter(unittest.TestCase):

    def test_parses_keys_and_body(self):
        meta, body = pb.parse_frontmatter("---\nname: Thing\n---\nBody here\n")
        self.assertEqual(meta["name"], "Thing")
        self.assertEqual(body, "Body here\n")

    def test_parses_inline_lists(self):
        meta, _ = pb.parse_frontmatter("---\ntags: [one, two]\n---\n")
        self.assertEqual(meta["tags"], ["one", "two"])

    def test_strips_quotes_from_values(self):
        meta, _ = pb.parse_frontmatter('---\nname: "Quoted"\n---\n')
        self.assertEqual(meta["name"], "Quoted")

    def test_text_without_fences_is_all_body(self):
        meta, body = pb.parse_frontmatter("Just text")
        self.assertEqual(meta, {})
        self.assertEqual(body, "Just text")

    def test_unterminated_fence_is_all_body(self):
        text = "---\nname: Thing\nno closing fence"
        meta, body = pb.parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_round_trip_preserves_values(self):
        meta = {"name": "Thing", "tags": ["a", "b"]}
        parsed, _ = pb.parse_frontmatter(pb.build_frontmatter(meta) + "\nbody")
        self.assertEqual(parsed["name"], "Thing")
        self.assertEqual(parsed["tags"], ["a", "b"])


# ---------------------------------------------------------------------------
# Git remote URLs
# ---------------------------------------------------------------------------


class TestRemoteToWebUrl(unittest.TestCase):

    def test_ssh_remote(self):
        self.assertEqual(pb._remote_to_web_url("git@github.com:owner/repo.git"),
                         "https://github.com/owner/repo")

    def test_https_remote(self):
        self.assertEqual(pb._remote_to_web_url("https://github.com/owner/repo.git"),
                         "https://github.com/owner/repo")

    def test_remote_without_git_suffix(self):
        self.assertEqual(pb._remote_to_web_url("https://github.com/owner/repo"),
                         "https://github.com/owner/repo")

    def test_non_github_host_is_kept(self):
        self.assertEqual(pb._remote_to_web_url("git@bitbucket.org:owner/repo.git"),
                         "https://bitbucket.org/owner/repo")

    def test_unrecognised_remote_returns_none(self):
        self.assertIsNone(pb._remote_to_web_url("file:///local/path"))


# ---------------------------------------------------------------------------
# Discovery classification
# ---------------------------------------------------------------------------


class TestClassifyDir(TempDirCase):

    def test_git_repo_is_strong(self):
        self.make("app", ".git")
        tier, _ = pb._classify_dir(os.path.join(self.tmp, "app"))
        self.assertEqual(tier, "strong")

    def test_manifest_is_strong(self):
        self.make("app", "package.json", contents="{}")
        tier, _ = pb._classify_dir(os.path.join(self.tmp, "app"))
        self.assertEqual(tier, "strong")

    def test_readme_alone_is_weak(self):
        self.make("notes", "README.md", contents="# hi")
        tier, reason = pb._classify_dir(os.path.join(self.tmp, "notes"))
        self.assertEqual(tier, "weak")
        self.assertIn("only", reason)

    def test_empty_directory_has_no_markers(self):
        self.make("empty")
        tier, _ = pb._classify_dir(os.path.join(self.tmp, "empty"))
        self.assertEqual(tier, "none")

    def test_unreadable_path_does_not_raise(self):
        tier, _ = pb._classify_dir(os.path.join(self.tmp, "does-not-exist"))
        self.assertEqual(tier, "none")

    def test_is_repo_follows_strong_markers_only(self):
        self.make("repo", ".git")
        self.make("docs-only", "README.md", contents="x")
        self.assertTrue(pb._is_repo(os.path.join(self.tmp, "repo")))
        self.assertFalse(pb._is_repo(os.path.join(self.tmp, "docs-only")))


# ---------------------------------------------------------------------------
# Reviewing what is already indexed
#
# This is the logic that let eight subfolders of one app sit in the index as
# eight separate projects, so it gets the most attention.
# ---------------------------------------------------------------------------


class TestFlagIndexedEntry(TempDirCase):

    def test_dependency_folder_is_flagged(self):
        root = self.make("app", "node_modules")
        self.assertEqual(pb._flag_indexed_entry(entry(project_root=root)),
                         "dependency or build folder")

    def test_subfolder_of_a_repo_is_flagged(self):
        self.make("app", ".git")
        root = self.make("app", "src")
        reason = pb._flag_indexed_entry(entry(project_root=root))
        self.assertEqual(reason, "part of app")

    def test_a_repo_itself_is_not_flagged(self):
        root = self.make("app", ".git")
        self.assertIsNone(pb._flag_indexed_entry(
            entry(project_root=os.path.dirname(root))))

    def test_project_created_by_proj_new_is_never_flagged(self):
        # An initial_prompt_path means the user made it deliberately.
        root = self.make("category", "node_modules")
        e = entry(project_root=root, initial_prompt_path=root + "/docs/p.md")
        self.assertIsNone(pb._flag_indexed_entry(e))

    def test_missing_directory_is_left_to_prune(self):
        e = entry(project_root=os.path.join(self.tmp, "gone"))
        self.assertIsNone(pb._flag_indexed_entry(e))

    def test_bare_folder_is_held_back_by_default(self):
        root = self.make("category", "just-a-folder")
        self.assertIsNone(pb._flag_indexed_entry(entry(project_root=root)))

    def test_bare_folder_is_reported_when_asked(self):
        root = self.make("category", "just-a-folder")
        self.assertEqual(
            pb._flag_indexed_entry(entry(project_root=root), include_unsure=True),
            "no project markers")


# ---------------------------------------------------------------------------
# is_ignored
# ---------------------------------------------------------------------------


class TestIsIgnored(TempDirCase):

    def test_exact_path_matches(self):
        path = self.make("skip-me")
        self.assertTrue(pb.is_ignored(path, [path]))

    def test_unlisted_path_does_not_match(self):
        self.assertFalse(pb.is_ignored(self.make("keep"), [self.make("skip")]))

    def test_symlink_matches_via_its_target(self):
        # realpath, because macOS temp dirs are themselves under a symlink.
        target = os.path.realpath(self.make("real"))
        link = os.path.join(self.tmp, "link")
        os.symlink(target, link)
        self.assertTrue(pb.is_ignored(link, [target]))

    def test_matching_is_case_insensitive(self):
        path = self.make("CaseFolder")
        self.assertTrue(pb.is_ignored(path, [path.lower()]))


# ---------------------------------------------------------------------------
# Data layer: every test here writes to a temp directory, never ~/.pb
# ---------------------------------------------------------------------------


class TestDataLayer(TempDirCase):

    def setUp(self):
        super().setUp()
        for name in ("CONFIG_PATH", "INDEX_PATH", "IGNORED_PATH", "IDEAS_PATH"):
            patched = os.path.join(self.tmp, name.split("_")[0].lower() + ".json")
            patcher = unittest.mock.patch.object(pb, name, patched)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_index_round_trip(self):
        pb.save_index([entry(id="1", name="Round Trip")])
        self.assertEqual(pb.load_index()[0]["name"], "Round Trip")

    def test_missing_index_loads_as_empty(self):
        self.assertEqual(pb.load_index(), [])

    def test_config_inherits_defaults_for_missing_keys(self):
        with open(pb.CONFIG_PATH, "w") as f:
            json.dump({"categories": ["Only This"]}, f)
        cfg = pb.load_config()
        self.assertEqual(cfg["categories"], ["Only This"])
        self.assertEqual(cfg["status_thresholds"]["stale_after_days"], 14)

    def test_default_config_carries_no_personal_data(self):
        # The tool ships to other people; their setup is theirs to state.
        self.assertEqual(pb.DEFAULT_CONFIG["categories"], [])
        self.assertEqual(pb.DEFAULT_CONFIG["github_orgs"], [])
        self.assertIsNone(pb.DEFAULT_CONFIG["default_category"])
        self.assertIsNone(pb.DEFAULT_CONFIG["default_github_org"])
        self.assertEqual(pb.DEFAULT_CONFIG["project_editor"], "")

    def test_ignored_round_trip(self):
        pb.save_ignored(["/a/path"])
        self.assertEqual(pb.load_ignored(), ["/a/path"])

    def test_atomic_write_leaves_no_temp_file_behind(self):
        path = os.path.join(self.tmp, "out.json")
        pb.atomic_write_json(path, {"a": 1})
        self.assertEqual(os.listdir(self.tmp), ["out.json"])

    def test_atomic_write_replaces_existing_content(self):
        path = os.path.join(self.tmp, "out.json")
        pb.atomic_write_json(path, {"first": True})
        pb.atomic_write_json(path, {"second": True})
        with open(path) as f:
            self.assertEqual(json.load(f), {"second": True})

    def test_resolve_base_dir_expands_the_home_shortcut(self):
        cfg = {"base_directories": [{"name": "default", "path": "~/Projects"}],
               "default_base_directory": "default"}
        self.assertEqual(pb.resolve_base_dir(cfg),
                         os.path.expanduser("~/Projects"))


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TestRender(unittest.TestCase):

    def test_substitutes_placeholders(self):
        self.assertEqual(pb._render("Hi {{name}}", name="there"), "Hi there")

    def test_leaves_markdown_braces_alone(self):
        # This is why _render exists instead of str.format.
        text = "```json\n{\"a\": 1}\n```  {{name}}"
        self.assertEqual(pb._render(text, name="x"), '```json\n{"a": 1}\n```  x')

    def test_repeats_a_placeholder(self):
        self.assertEqual(pb._render("{{a}}-{{a}}", a="z"), "z-z")


# ---------------------------------------------------------------------------
# ADR records
# ---------------------------------------------------------------------------


class TestAdrRecord(unittest.TestCase):

    def setUp(self):
        self.record = pb._adr_record(pb.ADR_TEMPLATE_MD,
                                       "Postgres over DynamoDB", "2026-09-13")

    def test_title_replaces_the_heading(self):
        self.assertTrue(self.record.startswith("# Postgres over DynamoDB\n"))

    def test_date_is_filled_in(self):
        self.assertIn("- Date: 2026-09-13\n", self.record)

    def test_agent_guidance_is_stripped(self):
        self.assertNotIn("AGENT GUIDANCE", self.record)

    def test_madr_sections_survive(self):
        for heading in ("## Context and Problem Statement", "## Considered Options",
                        "## Decision Outcome", "### Consequences"):
            self.assertIn(heading, self.record)

    def test_no_blank_line_pile_up_where_the_comment_was(self):
        self.assertNotIn("\n\n\n", self.record)


class TestAdrCommands(TempDirCase):

    def test_plain_log_points_at_pb_itself(self):
        new_cmd, serve_cmd = pb._adr_commands(self.tmp, site=False)
        self.assertIn("pb adr new", new_cmd)
        self.assertIsNone(serve_cmd)

    def test_site_without_package_json_uses_pinned_npx(self):
        new_cmd, serve_cmd = pb._adr_commands(self.tmp, site=True)
        self.assertIn(f"log4brains@{pb.LOG4BRAINS_VERSION}", new_cmd)
        self.assertIsNotNone(serve_cmd)

    def test_site_prefers_package_scripts(self):
        self.make("package.json", contents="{}")
        new_cmd, _ = pb._adr_commands(self.tmp, site=True)
        self.assertEqual(new_cmd, "npm run adr:new")

    def test_runner_follows_the_lockfile(self):
        self.make("package.json", contents="{}")
        self.make("pnpm-lock.yaml", contents="")
        new_cmd, _ = pb._adr_commands(self.tmp, site=True)
        self.assertEqual(new_cmd, "pnpm adr:new")


class TestScaffoldAdr(TempDirCase):

    def scaffold(self, **kw):
        with redirect_stdout(io.StringIO()):
            pb.scaffold_adr(self.tmp, "Test Project", quiet=True, **kw)

    def relpaths(self):
        found = set()
        for root, _, files in os.walk(self.tmp):
            for f in files:
                found.add(os.path.relpath(os.path.join(root, f), self.tmp))
        return found

    def test_plain_log_writes_no_log4brains_files(self):
        self.scaffold()
        self.assertEqual(self.relpaths(), {
            "docs/adr/template.md",
            "docs/adr/README.md",
            ".claude/skills/adr/SKILL.md",
        })

    def test_plain_log_prose_never_tells_you_to_run_npm(self):
        self.scaffold()
        with open(os.path.join(self.tmp, "docs/adr/README.md")) as f:
            readme = f.read()
        self.assertIn('pb adr new "<title>"', readme)
        self.assertNotIn("npx", readme)
        self.assertNotIn("npm run", readme)

    def test_no_placeholder_survives_rendering(self):
        self.scaffold()
        for rel in self.relpaths():
            with open(os.path.join(self.tmp, rel)) as f:
                self.assertNotIn("{{", f.read(), f"unrendered placeholder in {rel}")

    def test_site_adds_the_log4brains_files(self):
        self.scaffold(site=True)
        found = self.relpaths()
        self.assertIn("docs/adr/index.md", found)
        self.assertIn(".log4brains.yml", found)
        self.assertIn(".gitignore", found)

    def test_skill_can_be_skipped(self):
        self.scaffold(with_skill=False)
        self.assertNotIn(".claude/skills/adr/SKILL.md", self.relpaths())

    def test_rerunning_does_not_clobber_an_edited_file(self):
        self.scaffold()
        path = os.path.join(self.tmp, "docs/adr/README.md")
        with open(path, "w") as f:
            f.write("my own words")
        self.scaffold()
        with open(path) as f:
            self.assertEqual(f.read(), "my own words")

    def test_force_overwrites(self):
        self.scaffold()
        path = os.path.join(self.tmp, "docs/adr/README.md")
        with open(path, "w") as f:
            f.write("my own words")
        self.scaffold(force=True)
        with open(path) as f:
            self.assertNotEqual(f.read(), "my own words")

    def test_adding_the_site_later_keeps_existing_records(self):
        self.scaffold()
        record = os.path.join(self.tmp, "docs/adr/20260101-a-decision.md")
        with open(record, "w") as f:
            f.write("# A decision\n")
        self.scaffold(site=True, force=True)
        self.assertTrue(os.path.isfile(record))

    def test_gitignore_entry_is_not_duplicated(self):
        self.scaffold(site=True)
        self.scaffold(site=True, force=True)
        with open(os.path.join(self.tmp, ".gitignore")) as f:
            self.assertEqual(f.read().count("/.log4brains"), 1)


# ---------------------------------------------------------------------------
# PROJECTS_INDEX.md
# ---------------------------------------------------------------------------


class TestProjectsIndex(TempDirCase):

    def test_groups_projects_under_their_category(self):
        cfg = {"base_directories": [{"name": "default", "path": self.tmp}],
               "default_base_directory": "default",
               "status_thresholds": {"stale_after_days": 14,
                                     "archived_after_days": 90}}
        entries = [
            entry(id="1", name="Alpha", category="Work",
                  project_root=os.path.join(self.tmp, "Work/alpha")),
            entry(id="2", name="Beta", category="Personal",
                  project_root=os.path.join(self.tmp, "Personal/beta")),
        ]
        with redirect_stdout(io.StringIO()):
            pb.generate_projects_index(entries, cfg)
        with open(os.path.join(self.tmp, "PROJECTS_INDEX.md")) as f:
            text = f.read()
        self.assertIn("Work", text)
        self.assertIn("Personal", text)
        self.assertIn("Alpha", text)
        self.assertIn("Beta", text)


class TestDisplayPath(unittest.TestCase):

    def test_home_becomes_a_tilde(self):
        home = os.path.expanduser("~")
        self.assertEqual(pb.display_path(os.path.join(home, "Projects", "a")),
                         os.path.join("~", "Projects", "a"))

    def test_home_itself(self):
        self.assertEqual(pb.display_path(os.path.expanduser("~")), "~")

    def test_paths_outside_home_are_untouched(self):
        self.assertEqual(pb.display_path("/opt/thing"), "/opt/thing")

    def test_a_sibling_of_home_is_not_shortened(self):
        # "/Users/rich-old" must not become "~-old".
        self.assertEqual(pb.display_path(os.path.expanduser("~") + "-old"),
                         os.path.expanduser("~") + "-old")

    def test_empty_path_survives(self):
        self.assertEqual(pb.display_path(""), "")

    def test_json_keeps_the_absolute_path(self):
        cfg = {"status_thresholds": {"stale_after_days": 14,
                                     "archived_after_days": 90}}
        root = os.path.join(os.path.expanduser("~"), "Projects", "a")
        out = pb.entry_as_json(entry(project_root=root), cfg)
        self.assertEqual(out["project_root"], root)


# ---------------------------------------------------------------------------
# JSON output: a contract, once anything parses it
# ---------------------------------------------------------------------------


class TestJsonShape(unittest.TestCase):

    def setUp(self):
        self.cfg = {"status_thresholds": {"stale_after_days": 14,
                                          "archived_after_days": 90}}

    def test_carries_the_computed_status(self):
        # status is derived, not stored, so JSON consumers can't work it out.
        out = pb.entry_as_json(entry(last_worked_at=iso_days_ago(20)), self.cfg)
        self.assertEqual(out["status"], "stale")

    def test_keeps_every_stored_field(self):
        e = entry()
        out = pb.entry_as_json(e, self.cfg)
        self.assertTrue(set(e).issubset(set(out)))

    def test_repo_url_only_when_there_is_one(self):
        self.assertNotIn("repo_url", pb.entry_as_json(entry(), self.cfg))
        self.assertEqual(
            pb.entry_as_json(entry(), self.cfg, "https://example.com/a/b")["repo_url"],
            "https://example.com/a/b")

    def test_does_not_mutate_the_entry_it_is_given(self):
        e = entry()
        pb.entry_as_json(e, self.cfg)
        self.assertNotIn("status", e)


class TestSetupFallsBackWhenInputIsUnreadable(TempDirCase):
    """A terminal attached does not mean a terminal that can be read."""

    def run_list(self, stdin):
        env = dict(os.environ, HOME=self.tmp)
        return subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "pb.py"), "list", "--json"],
            stdin=stdin, capture_output=True, text=True, env=env, timeout=30)

    def test_closed_stdin_does_not_crash(self):
        with open(os.devnull) as devnull:
            out = self.run_list(devnull)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[]")

    def test_a_pty_with_nothing_to_read_does_not_crash(self):
        parent, child = pty.openpty()
        try:
            os.close(parent)  # nothing will ever be written: reads raise EIO
            out = self.run_list(child)
        finally:
            os.close(child)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[]")


class TestMigrationNoticeGoesToStderr(TempDirCase):
    """stdout has to stay parseable, so notices must not land in it."""

    def test_notice_is_not_on_stdout(self):
        legacy = os.path.join(self.tmp, ".proj")
        target = os.path.join(self.tmp, ".pb")
        os.makedirs(legacy)
        with unittest.mock.patch.object(pb, "LEGACY_DIR", legacy), \
             unittest.mock.patch.object(pb, "PB_DIR", target):
            buf = io.StringIO()
            with redirect_stdout(buf):
                moved = pb.migrate_legacy_dir()
        self.assertTrue(moved)
        self.assertEqual(buf.getvalue(), "")
        self.assertTrue(os.path.isdir(target))


# ---------------------------------------------------------------------------
# House style
# ---------------------------------------------------------------------------


class TestNoDashes(unittest.TestCase):
    """Em and en dashes are the clearest tell that text was machine-written.

    This guards what this repository produces, including the templates pb
    scaffolds into other people's projects. What they then write in those
    files is their business, not ours.
    """

    # Box-drawing characters are not dashes and are load-bearing in the table
    # output, so only the two punctuation dashes are banned.
    BANNED = {"\u2014": "em dash", "\u2013": "en dash"}

    def tracked_text_files(self):
        root = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(["git", "-C", root, "ls-files"],
                             capture_output=True, text=True)
        if out.returncode != 0:
            self.skipTest("not a git checkout")
        for rel in out.stdout.split():
            if os.path.splitext(rel)[1] in (".md", ".py", ".sh", ".yml", ".yaml"):
                yield rel, os.path.join(root, rel)

    def test_no_dashes_in_tracked_text_files(self):
        offenders = []
        for rel, path in self.tracked_text_files():
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    for char, name in self.BANNED.items():
                        if char in line:
                            offenders.append(f"{rel}:{n} contains an {name}")
        self.assertEqual(offenders, [], "\n" + "\n".join(offenders))

    def test_the_check_covers_something(self):
        # A guard that silently matches no files is worse than no guard.
        self.assertGreater(len(list(self.tracked_text_files())), 3)


if __name__ == "__main__":
    unittest.main()
