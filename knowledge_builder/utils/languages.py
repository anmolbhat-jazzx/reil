"""Map source-file extensions to language names.

Mirrors the extension set graphify's AST extractor treats as code, so a symbol's
language can be inferred deterministically from its ``source_file``.
"""

from __future__ import annotations

from pathlib import PurePosixPath

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".scala": "scala",
    ".php": "php",
    ".lua": "lua",
    ".toc": "toc",
    ".f": "fortran",
    ".f90": "fortran",
    ".f95": "fortran",
    ".f03": "fortran",
    ".f08": "fortran",
}


def language_for_path(source_file: str | None) -> str | None:
    """Return the language name for a source-file path, or ``None`` if unknown."""
    if not source_file:
        return None
    suffix = PurePosixPath(source_file).suffix.lower()
    return _EXT_TO_LANGUAGE.get(suffix)
