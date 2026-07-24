"""
Repository-hygiene regression tests (v15.0-rc.1).

These encode the RC cleanup as automated guards so it cannot silently
regress: every relative Markdown link must resolve, and the tracked runtime
artifacts removed during the RC (process stdout/stderr, lock files) must not
creep back in. Offline and fast -- pure filesystem, no Telegram/AI/network.
"""
import os
import re
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _tracked(*globs):
    """git-tracked files matching the globs, or [] if git is unavailable
    (so the suite still runs from a source tarball)."""
    try:
        out = subprocess.check_output(
            ["git", "ls-files", *globs], cwd=REPO_ROOT, text=True,
            stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []
    return [p for p in out.splitlines() if p.strip()]


def test_no_broken_markdown_links():
    """Every relative file link in tracked Markdown resolves to a real path
    (external URLs, mailto:, and pure #anchors are ignored). Guards Part 10
    of the RC audit: 'No broken links.'"""
    mds = _tracked("*.md")
    if not mds:
        pytest.skip("git not available; cannot enumerate tracked docs")
    broken = []
    for md in mds:
        d = os.path.dirname(md)
        text = open(os.path.join(REPO_ROOT, md), encoding="utf-8").read()
        for m in _LINK_RE.finditer(text):
            target = m.group(1).split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            # only assert on things that look like repo file links
            if not (target.endswith(".md") or "/" in target):
                continue
            resolved = os.path.normpath(os.path.join(REPO_ROOT, d, target))
            if not os.path.exists(resolved):
                broken.append(f"{md} -> {target}")
    assert not broken, "Broken markdown links:\n  " + "\n  ".join(broken)


def test_no_tracked_runtime_artifacts():
    """The runtime artifacts removed in rc.1 (supervisor stdout/stderr, the
    process lock) stay untracked. Guards Part 10: 'No temporary files.'"""
    tracked = set(_tracked())
    if not tracked:
        pytest.skip("git not available")
    offenders = [
        p for p in tracked
        if re.search(r"(^|/)planner\d*\.(out|err)$", p)
        or p.endswith(".lock")
        or p.endswith(".pyc")
    ]
    assert not offenders, f"Runtime artifacts should not be tracked: {offenders}"
