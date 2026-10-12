
"""A synthetic repository with five concurrent lanes, built from scratch.

The fixture mirrors the real failure shape this tool exists for: one base branch,
several lanes on branches, and several more lanes sitting uncommitted in a single
working tree. mtimes are set explicitly so clustering is deterministic instead of
dependent on how fast the machine writes files.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

REPO = "/home/rk/Projects/muster"
if REPO + "/src" not in sys.path:
    sys.path.insert(0, REPO + "/src")

from muster.gitio import Git  # noqa: E402
from muster.store import Ledger  # noqa: E402


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, check=check,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}).stdout.decode()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(text, (bytes, bytearray)) else "w"
    with open(path, mode) as fh:
        fh.write(text)


def touch_at(path, epoch):
    os.utime(path, (epoch, epoch))


BASE_TIME = time.time() - 10 * 86400  # lanes are laid out backwards from "now"


def H(hours_ago):
    """Epoch for a file last touched `hours_ago`."""
    return BASE_TIME - hours_ago * 3600


@pytest.fixture
def repo(tmp_path):
    """Five lanes: three on branches, two uncommitted in the shared tree."""
    root = str(tmp_path / "project")
    os.makedirs(root)
    git(root, "init", "-q")
    # `git init -b` needs git >= 2.28; the symbolic-ref form works everywhere the
    # tool itself claims to work.
    git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    git(root, "config", "user.email", "owner@example.com")
    git(root, "config", "user.name", "Owner")
    git(root, "config", "commit.gpgsign", "false")

    write(os.path.join(root, "README.md"), "# Project\n\nThe original readme.\n")
    write(os.path.join(root, "app.py"),
          "\n".join("def handler_%d():\n    return %d\n" % (i, i) for i in range(40)))
    write(os.path.join(root, "util.py"), "def helper():\n    return 1\n")
    os.makedirs(os.path.join(root, "tests"))
    write(os.path.join(root, "tests", "test_app.py"), "def test_ok():\n    assert True\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "feat: initial project")

    # lane A: upload API, on a branch, clean
    git(root, "checkout", "-qb", "feature/upload-api")
    write(os.path.join(root, "app.py"),
          "\n".join("def handler_%d():\n    return %d\n" % (i, i) for i in range(40))
          + "\ndef upload():\n    return 'uploaded'\n")
    write(os.path.join(root, "tests", "test_upload.py"),
          "from app import upload\n\n\ndef test_upload():\n    assert upload() == 'uploaded'\n")
    write(os.path.join(root, "docs", "upload.md"), "# Upload API\n\nAccepts multipart posts.\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "feat(upload): multipart upload endpoint")
    git(root, "checkout", "-q", "main")

    # lane B: billing, on a branch, edits the same region of app.py as lane A
    git(root, "checkout", "-qb", "feature/billing")
    write(os.path.join(root, "app.py"),
          "\n".join("def handler_%d():\n    return %d\n" % (i, i) for i in range(40))
          + "\ndef charge():\n    return 'charged'\n")
    write(os.path.join(root, "billing.py"), "def invoice():\n    return 2\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "feat(billing): charge() and invoice")
    git(root, "checkout", "-q", "main")

    # lane C: already merged into main
    git(root, "checkout", "-qb", "chore/readme")
    write(os.path.join(root, "README.md"), "# Project\n\nThe original readme.\n\nSee docs/.\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "docs: point readme at docs/")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "chore/readme", "-m", "merge readme lane")

    # lane D: uncommitted marketing work sitting in the shared working tree.
    # It is committed once on the checked-out branch first, because git will not
    # let an uncommitted edit to a tracked file survive a branch switch - and that
    # refusal is itself one of the things agents trip over in a shared tree.
    git(root, "checkout", "-q", "feature/upload-api")
    os.makedirs(os.path.join(root, "site"))
    write(os.path.join(root, "site", "hero.jsx"), "export const Hero = () => <h1>Hi</h1>;\n")
    write(os.path.join(root, "site", "footer.jsx"), "export const Footer = () => <p>Bye</p>;\n")
    git(root, "add", "site")
    git(root, "commit", "-qm", "feat(site): hero and footer")
    write(os.path.join(root, "site", "hero.jsx"),
          "export const Hero = () => <h1>Ship faster</h1>;\n")
    write(os.path.join(root, "site", "pricing.jsx"), "export const Pricing = () => null;\n")
    os.remove(os.path.join(root, "site", "footer.jsx"))
    touch_at(os.path.join(root, "site", "hero.jsx"), H(2))
    touch_at(os.path.join(root, "site", "pricing.jsx"), H(2))

    # lane E: an entirely new directory, untracked, a sitting days earlier
    os.makedirs(os.path.join(root, "experiments", "notebooks"))
    write(os.path.join(root, "experiments", "run.py"), "print('experiment')\n")
    write(os.path.join(root, "experiments", "notebooks", "probe.py"), "x = 1\n")
    write(os.path.join(root, "experiments", "blob.bin"), b"\x00\x01\x02\x03" * 64)
    for name in ("run.py", "notebooks/probe.py", "blob.bin"):
        touch_at(os.path.join(root, "experiments", name), H(30))

    # a stray file nobody has touched in a long time
    write(os.path.join(root, "notes.txt"), "old scratch notes\n")
    touch_at(os.path.join(root, "notes.txt"), H(24 * 20))

    return root


@pytest.fixture
def ledger(repo):
    return Ledger(repo)


@pytest.fixture
def snapshot(repo):
    from muster.observe import build_snapshot
    snap, _led = build_snapshot(repo=repo, window=6 * 3600)
    return snap


@pytest.fixture
def two_clones(tmp_path):
    """A bare remote with two clones, for cross-machine sync tests."""
    remote = str(tmp_path / "remote.git")
    os.makedirs(remote)
    git(remote, "init", "-q", "--bare")
    a = str(tmp_path / "cloneA")
    git(str(tmp_path), "clone", "-q", remote, a)
    git(a, "config", "user.email", "a@example.com")
    git(a, "config", "user.name", "A")
    write(os.path.join(a, "a.txt"), "shared\n")
    git(a, "add", "-A")
    git(a, "commit", "-qm", "seed")
    git(a, "push", "-q", "origin", "HEAD:refs/heads/main")
    b = str(tmp_path / "cloneB")
    git(str(tmp_path), "clone", "-q", remote, b)
    git(b, "config", "user.email", "b@example.com")
    git(b, "config", "user.name", "B")
    return a, b, remote
