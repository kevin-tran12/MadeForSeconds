#!/usr/bin/env python3
"""Keep README.md's version/test-count inventory honest.

The README states counts and versions by hand (test counts, file counts,
Vite/Terraform/provider/Playwright/Docker/Actions versions) in specific,
grep-able locations. Every one of those numbers has drifted silently in the
past (296 -> 454 backend tests, 49 -> 95 frontend tests, Vite 6 -> 8,
20 -> 24 backend test files, 8 -> 13 frontend test files, all found the same
day this script was written).

Run in three modes, each independent so CI can call the one that fits the
job already doing the work (no duplicate test runs just to check a count):

  python scripts/check_inventory.py static
      No test execution. Cross-checks file counts (ls-based) and toolchain
      versions (regex over manifests) against README.md. Cheap -- just
      actions/checkout + actions/setup-python.

  python scripts/check_inventory.py backend-count --output <path>
      Parses a captured `pytest --cov=app ...` (or --collect-only) run's
      output for "N passed" / "N tests collected" and checks README's three
      backend test-count mentions against it. Run as a step appended to the
      existing Backend Tests CI job, right after pytest already ran -- no
      second invocation.

  python scripts/check_inventory.py frontend-count --output <path>
      Same idea for a captured `npm run test:unit` (vitest) run's "Tests  N
      passed (N)" line, checked against README's one frontend test-count
      mention. Appended to the existing Frontend Tests job.

  python scripts/check_inventory.py static --fix
      Rewrites the "Toolchain versions" table in README.md with freshly
      detected values instead of just reporting a mismatch. Does NOT fix
      test counts or file counts -- those should only ever be corrected by
      actually looking at what changed and why, not silently overwritten.

Exit code is nonzero on any mismatch (or on a parse failure -- a check that
can't run is not a check that passed).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


class Mismatch:
    def __init__(self, label: str, expected: str, found: str):
        self.label = label
        self.expected = expected
        self.found = found

    def __str__(self) -> str:
        return "  - {}: README says {!r}, actual is {!r}".format(
            self.label, self.found, self.expected
        )


def _read(path: Path) -> str:
    if not path.exists():
        raise SystemExit("check_inventory: missing file {}".format(path))
    return path.read_text(encoding="utf-8")


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    r"""Strip ANSI color/style escape codes.

    vitest colorizes its summary even when stdout is piped to `tee` in a
    GitHub Actions step (unlike pytest's plain-text summary, which is why
    this only bit the frontend-count parser in practice) -- the escape
    sequences land *inside* what looks like whitespace between words, e.g.
    "Tests \x1b[22m \x1b[1m\x1b[32m95 passed", silently breaking a `\s+`
    match. Applied to every captured-output read here, not just vitest's,
    so a future colorized pytest plugin doesn't reintroduce the same bug.
    """
    return _ANSI_RE.sub("", text)


def _count_files(pattern_dir: Path, glob: str) -> int:
    return len(list(pattern_dir.glob(glob)))


# --- static: file counts + toolchain versions --------------------------------


def check_static() -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    readme = _read(README)

    # Backend test file count (2 mentions: structure tree, Testing heading)
    backend_files = _count_files(ROOT / "backend" / "tests", "test_*.py")
    for label, pattern in [
        ("Structure tree - backend test file count",
         r"Pytest suite \(\d+ tests across (\d+) files\)"),
        ("Testing heading - backend test file count",
         r"### Backend — pytest \(\d+ tests, (\d+) files\)"),
    ]:
        m = re.search(pattern, readme)
        if not m:
            mismatches.append(Mismatch(label, str(backend_files), "<pattern not found>"))
            continue
        stated = int(m.group(1))
        if stated != backend_files:
            mismatches.append(Mismatch(label, str(backend_files), str(stated)))

    # Frontend test file count
    frontend_files = _count_files(ROOT / "src", "**/*.test.*")
    m = re.search(r"### Frontend unit — vitest \(\d+ tests, (\d+) files\)", readme)
    if not m:
        mismatches.append(Mismatch("Testing heading - frontend test file count",
                                    str(frontend_files), "<pattern not found>"))
    elif int(m.group(1)) != frontend_files:
        mismatches.append(Mismatch("Testing heading - frontend test file count",
                                    str(frontend_files), m.group(1)))

    # E2E spec file count
    e2e_files = _count_files(ROOT / "tests-e2e", "*.spec.ts")
    m = re.search(r"### E2E — Playwright \((\d+) spec files\)", readme)
    if not m:
        mismatches.append(Mismatch("Testing heading - E2E spec file count",
                                    str(e2e_files), "<pattern not found>"))
    elif int(m.group(1)) != e2e_files:
        mismatches.append(Mismatch("Testing heading - E2E spec file count",
                                    str(e2e_files), m.group(1)))

    # Vite major version
    package_json = _read(ROOT / "package.json")
    m = re.search(r'"vite":\s*"\^?(\d+)', package_json)
    if not m:
        mismatches.append(Mismatch("Stack table - Vite version", "?", "<not found in package.json>"))
    else:
        vite_major = m.group(1)
        rm = re.search(r"Vite (\d+)", readme)
        if not rm:
            mismatches.append(Mismatch("Stack table - Vite version", vite_major, "<pattern not found>"))
        elif rm.group(1) != vite_major:
            mismatches.append(Mismatch("Stack table - Vite version", vite_major, rm.group(1)))

    # Toolchain versions table
    detected = _detect_toolchain_versions()
    table_checks = [
        ("Terraform CLI", detected["terraform"],
         r"\| Terraform CLI \| ([^|]+?) \|"),
        ("google/google-beta provider", detected["google_provider"],
         r"\| `google` / `google-beta` provider \| ([^|]+?) \|"),
        ("Playwright", detected["playwright"],
         r"\| Playwright \| ([^|]+?) \|"),
        ("Backend base image", detected["docker_base"],
         r"\| Backend base image \| `([^`]+)` \|"),
        ("GitHub Actions", detected["actions"],
         r"\| GitHub Actions \| ([^|]+?) \|"),
    ]
    for label, actual, pattern in table_checks:
        if actual is None:
            mismatches.append(Mismatch("Toolchain table - " + label, "?", "<not detected>"))
            continue
        rm = re.search(pattern, readme)
        if not rm:
            mismatches.append(Mismatch("Toolchain table - " + label, actual, "<row not found>"))
        elif rm.group(1).strip() != actual.strip():
            mismatches.append(Mismatch("Toolchain table - " + label, actual, rm.group(1).strip()))

    return mismatches


def _detect_toolchain_versions() -> dict:
    result: dict = {
        "terraform": None,
        "google_provider": None,
        "playwright": None,
        "docker_base": None,
        "actions": None,
    }

    main_tf = ROOT / "terraform" / "main.tf"
    if main_tf.exists():
        m = re.search(r'required_version\s*=\s*"([^"]+)"', main_tf.read_text(encoding="utf-8"))
        if m:
            result["terraform"] = m.group(1)

    lock_hcl = ROOT / "terraform" / ".terraform.lock.hcl"
    if lock_hcl.exists():
        text = lock_hcl.read_text(encoding="utf-8")
        m = re.search(
            r'provider "registry\.terraform\.io/hashicorp/google"\s*\{\s*version\s*=\s*"([^"]+)"',
            text,
        )
        if m:
            result["google_provider"] = m.group(1)

    package_json = ROOT / "package.json"
    if package_json.exists():
        m = re.search(
            r'"@playwright/test":\s*"\^?([^"]+)"', package_json.read_text(encoding="utf-8")
        )
        if m:
            result["playwright"] = m.group(1)

    dockerfile = ROOT / "backend" / "Dockerfile"
    if dockerfile.exists():
        # Digest-pinned (`python:3.12-slim@sha256:...`, PR 21) -- the table
        # shows the human-readable tag, not the 64-char digest, so strip it
        # rather than teaching the README to display a hash.
        m = re.search(r"^FROM\s+([^\s@]+)", dockerfile.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            result["docker_base"] = m.group(1)

    # Every workflow file, not just ci.yml -- terraform-drift.yml (Epic 8,
    # PR 8) was the first to need this; more will follow (PR 9's staging
    # target, PR 10's promotion pipeline), and a check scoped to one
    # filename would silently stop covering the rest.
    workflows_dir = ROOT / ".github" / "workflows"
    if workflows_dir.exists():
        actions: set[str] = set()
        for workflow_file in sorted(workflows_dir.glob("*.yml")):
            for line in workflow_file.read_text(encoding="utf-8").splitlines():
                m = re.search(r"uses:\s*(\S+)@([0-9a-f]{40})(?:\s*#\s*(\S+))?", line)
                if m:
                    # Digest-pinned (PR 21) -- every pinned ref in this repo
                    # carries a trailing `# vX` comment specifically so
                    # tooling doesn't have to display the hash; fall back to
                    # the raw sha if a ref is ever pinned without one.
                    repo, sha, comment = m.groups()
                    actions.add(f"{repo}@{comment or sha}")
                    continue
                m = re.search(r"uses:\s*(\S+)", line)
                if m:
                    actions.add(m.group(1))
        if actions:
            result["actions"] = ", ".join("`" + a + "`" for a in sorted(actions))

    return result


def _table_row_value(label: str, value) -> str | None:
    """Format one Toolchain-table cell value for the given label."""
    if value is None:
        return None
    if label == "Backend base image":
        return "`" + value + "`"
    return value


def fix_toolchain_table() -> None:
    """Rewrite the Toolchain versions table's version column with detected values."""
    readme = _read(README)
    detected = _detect_toolchain_versions()

    rows = [
        ("Terraform CLI", detected["terraform"],
         r"(\| Terraform CLI \| )[^|]+?( \|)"),
        ("google/google-beta provider", detected["google_provider"],
         r"(\| `google` / `google-beta` provider \| )[^|]+?( \|)"),
        ("Playwright", detected["playwright"],
         r"(\| Playwright \| )[^|]+?( \|)"),
        ("Backend base image", detected["docker_base"],
         r"(\| Backend base image \| )`[^`]+`( \|)"),
        ("GitHub Actions", detected["actions"],
         r"(\| GitHub Actions \| )[^|]+?( \|)"),
    ]

    changed = False
    for label, raw_value, pattern in rows:
        formatted = _table_row_value(label, raw_value)
        if formatted is None:
            continue
        new_readme, n = re.subn(pattern, r"\g<1>" + formatted.replace("\\", "\\\\") + r"\g<2>", readme)
        if n:
            readme = new_readme
            changed = True

    if changed:
        README.write_text(readme, encoding="utf-8")
        print("check_inventory: README.md Toolchain versions table updated")
    else:
        print("check_inventory: nothing to fix (all rows already current, or none matched)")


# --- backend-count / frontend-count: live test totals -------------------------


def check_backend_count(output_path: Path) -> list[Mismatch]:
    text = _strip_ansi(_read(output_path))
    # pytest --cov ends with "N passed[, M warnings] in Ts"; --collect-only says
    # "N tests collected". Either satisfies this check.
    m = re.search(r"(\d+) passed", text) or re.search(r"(\d+) tests collected", text)
    if not m:
        raise SystemExit(
            "check_inventory: could not find a pytest pass/collect count in {}".format(output_path)
        )
    actual = m.group(1)
    readme = _read(README)
    mismatches: list[Mismatch] = []
    for label, pattern in [
        ("Structure tree - backend test count",
         r"Pytest suite \((\d+) tests across \d+ files\)"),
        ("test:backend npm-script comment - backend test count",
         r"# Pytest \((\d+) tests\)"),
        ("Testing heading - backend test count",
         r"### Backend — pytest \((\d+) tests, \d+ files\)"),
    ]:
        rm = re.search(pattern, readme)
        if not rm:
            mismatches.append(Mismatch(label, actual, "<pattern not found>"))
        elif rm.group(1) != actual:
            mismatches.append(Mismatch(label, actual, rm.group(1)))
    return mismatches


def check_frontend_count(output_path: Path) -> list[Mismatch]:
    text = _strip_ansi(_read(output_path))
    m = re.search(r"Tests\s+(\d+) passed", text)
    if not m:
        raise SystemExit(
            "check_inventory: could not find a vitest 'Tests  N passed' line in {}".format(output_path)
        )
    actual = m.group(1)
    readme = _read(README)
    mismatches: list[Mismatch] = []
    rm = re.search(r"### Frontend unit — vitest \((\d+) tests, \d+ files\)", readme)
    if not rm:
        mismatches.append(Mismatch("Testing heading - frontend test count", actual, "<pattern not found>"))
    elif rm.group(1) != actual:
        mismatches.append(Mismatch("Testing heading - frontend test count", actual, rm.group(1)))
    return mismatches


# --- entrypoint ---------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    static_p = sub.add_parser("static", help="File-count and toolchain-version checks (no test execution)")
    static_p.add_argument("--fix", action="store_true", help="Rewrite the Toolchain versions table instead of failing")

    backend_p = sub.add_parser("backend-count", help="Check README's backend test counts against a captured pytest run")
    backend_p.add_argument("--output", required=True, type=Path, help="Path to captured pytest stdout")

    frontend_p = sub.add_parser("frontend-count", help="Check README's frontend test count against a captured vitest run")
    frontend_p.add_argument("--output", required=True, type=Path, help="Path to captured vitest stdout")

    args = parser.parse_args()

    if args.mode == "static":
        if args.fix:
            fix_toolchain_table()
            # After fixing, re-check file counts and Vite version, which --fix
            # deliberately never touches -- those need a human to look at why.
            mismatches = [m for m in check_static() if not m.label.startswith("Toolchain table")]
        else:
            mismatches = check_static()
    elif args.mode == "backend-count":
        mismatches = check_backend_count(args.output)
    elif args.mode == "frontend-count":
        mismatches = check_frontend_count(args.output)
    else:  # pragma: no cover - argparse enforces choices
        raise SystemExit("unknown mode {!r}".format(args.mode))

    if mismatches:
        print("check_inventory ({}): {} mismatch(es) found:".format(args.mode, len(mismatches)), file=sys.stderr)
        for m in mismatches:
            print(m, file=sys.stderr)
        print(
            "\nUpdate README.md to match reality (or run "
            "`python scripts/check_inventory.py static --fix` for the toolchain "
            "table specifically). Test/file counts must be corrected by hand -- "
            "they're a signal something grew or shrank, not a rubber stamp.",
            file=sys.stderr,
        )
        return 1

    print("check_inventory ({}): README.md is consistent with the repo.".format(args.mode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
