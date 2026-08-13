"""Bounded, deterministic repository file walk shared by DB detection + extraction.

Skips VCS/build/vendor directories and oversized/binary files so scanning a repository
is cheap and never wanders into ``node_modules`` or ``.venv``. Results are sorted so
extraction is reproducible across runs (a prerequisite for stable ids).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

#: Directories never worth scanning for source or schema.
IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        ".knowledge",
        "graphify-out",
        ".tox",
        ".gradle",
    }
)

#: Skip files larger than this when reading text (bytes).
MAX_FILE_BYTES = 2_000_000
#: Never walk more than this many files (runaway-repo backstop).
MAX_FILES = 50_000


@dataclass(frozen=True)
class RepoFile:
    """A file discovered in the repository."""

    #: POSIX-style path relative to the repo root (stable across platforms).
    rel: str
    path: Path


def iter_files(repo_path: Path) -> Iterator[RepoFile]:
    """Yield every non-ignored file under ``repo_path`` in a deterministic order."""
    root = Path(repo_path)
    for count, path in enumerate(sorted(_walk(root))):
        if count >= MAX_FILES:
            return
        yield RepoFile(rel=path.relative_to(root).as_posix(), path=path)


def _walk(root: Path) -> Iterator[Path]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in IGNORED_DIRS:
                    stack.append(entry)
            elif entry.is_file():
                yield entry


def read_text(path: Path) -> str | None:
    """Read a text file, or ``None`` if missing, too large, or undecodable."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
