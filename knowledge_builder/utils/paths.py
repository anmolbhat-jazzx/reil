"""Path-based heuristics shared by the classify and module passes.

These derive human-readable capability names and package keys from ``source_file``
paths, and detect architectural roles (service/controller/route) from path segments.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# Directories that name a technical layer rather than a business capability.
ROLE_DIRS: frozenset[str] = frozenset(
    {
        "services",
        "service",
        "controllers",
        "controller",
        "routes",
        "route",
        "api",
        "apis",
        "handlers",
        "handler",
        "views",
        "view",
        "urls",
        "endpoints",
        "resources",
    }
)

# Generic top-level source roots skipped when deriving a package/capability name.
ROOT_DIRS: frozenset[str] = frozenset(
    {"src", "lib", "app", "pkg", "internal", "source", "sources", "main", "cmd"}
)


def package_key(source_file: str | None) -> str:
    """Return a stable grouping key: the file's directory, or ``"<root>"``."""
    if not source_file:
        return "<root>"
    parent = PurePosixPath(source_file).parent
    return str(parent) if str(parent) not in ("", ".") else "<root>"


def capability_base(source_file: str | None) -> str | None:
    """Derive a business-capability base name from a source-file path.

    Prefers the nearest meaningful directory; if that directory only names a technical
    role (``services``/``controllers``/…) or a generic root, falls back to the file stem.
    """
    if not source_file:
        return None
    path = PurePosixPath(source_file)
    stem = path.stem
    for part in reversed(path.parent.parts):
        lowered = part.lower()
        if lowered in ROLE_DIRS or lowered in ROOT_DIRS:
            continue
        return part
    # Every directory was generic; fall back to the file stem (minus role suffixes).
    cleaned = re.sub(r"[_-]?(service|controller|routes?|handler|view|api)$", "", stem, flags=re.I)
    return cleaned or stem


def title_case(name: str) -> str:
    """Convert ``snake_case``/``kebab-case``/``dotted`` names to ``TitleCase`` words."""
    words = re.split(r"[_\-.\s]+", name.strip())
    return "".join(word[:1].upper() + word[1:] for word in words if word)
