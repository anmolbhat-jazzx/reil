"""Read precise source slices for symbols, using the KB as a line index.

graphify records only a symbol's **start** line (e.g. ``L107``), not its end. So a
symbol's slice is taken from its start line up to just before the next symbol's start
line in the same file (capped at ``max_lines``). Explicit ranges (``L10-L30``) are
honored when present. This reconstructs tight, function-sized snippets without a parser
or the whole file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from knowledge_builder.models.symbol import Symbol

_LOC = re.compile(r"L?(\d+)(?:\s*-\s*L?(\d+))?")


@dataclass(frozen=True)
class SourceSnippet:
    """A slice of source read for one symbol."""

    file: str
    start: int
    end: int
    symbol: str
    code: str


def parse_location(location: str | None) -> tuple[int, int | None] | None:
    """Parse ``L107`` / ``L10-L30`` / ``10`` → (start, end|None); ``None`` if unparseable."""
    if not location:
        return None
    match = _LOC.search(location)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else None
    return start, end


class SnippetReader:
    """Reads exact source slices for symbols from a checked-out repository."""

    def __init__(self, repo_path: Path, *, max_lines: int = 60) -> None:
        self._repo = Path(repo_path)
        self._max_lines = max_lines

    def read_for_symbols(
        self, targets: list[Symbol], boundary_symbols: tuple[Symbol, ...]
    ) -> list[SourceSnippet]:
        """Read slices for ``targets``; ``boundary_symbols`` supply next-symbol line bounds."""
        file_starts: dict[str, list[int]] = {}
        for sym in boundary_symbols:
            loc = parse_location(sym.source_location)
            if sym.source_file and loc:
                file_starts.setdefault(sym.source_file, []).append(loc[0])
        for starts in file_starts.values():
            starts.sort()

        cache: dict[str, list[str] | None] = {}
        snippets: list[SourceSnippet] = []
        for sym in targets:
            if not sym.source_file:
                continue
            loc = parse_location(sym.source_location)
            if loc is None:
                continue
            start, explicit_end = loc
            next_start = next((s for s in file_starts.get(sym.source_file, []) if s > start), None)
            end = explicit_end or (next_start - 1 if next_start else start + self._max_lines - 1)
            end = min(end, start + self._max_lines - 1)

            lines = self._lines(sym.source_file, cache)
            if lines is None or start < 1 or start > len(lines):
                continue
            end = min(end, len(lines))
            code = "\n".join(lines[start - 1 : end]).rstrip()
            if code.strip():
                snippets.append(
                    SourceSnippet(
                        file=sym.source_file, start=start, end=end, symbol=sym.label, code=code
                    )
                )
        return snippets

    def _lines(self, rel: str, cache: dict[str, list[str] | None]) -> list[str] | None:
        if rel not in cache:
            path = self._repo / rel
            try:
                content = path.read_text(errors="ignore") if path.is_file() else None
                cache[rel] = content.splitlines() if content is not None else None
            except OSError:
                cache[rel] = None
        return cache[rel]
