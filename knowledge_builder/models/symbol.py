"""Symbol: a code entity (function/class/method/file) projected from a ``code`` node.

The ``code`` node comes from graphify (which supplies only ``label`` + ``source_location``);
the richer fields — ``name``, ``kind``, ``qualified_name``, ``signature``, ``docstring``,
exact ``start_line``/``end_line``, and the modifier flags — are filled by
:mod:`knowledge_builder.parser.symbols` (stdlib ``ast`` today, tree-sitter for other
languages later). Anything that cannot be determined deterministically is left ``None``.

``(name, source_file, start_line)`` is the stable identity tuple external indexers join
on. By convention ``start_line`` is the 1-based line of the ``def``/``class`` keyword
(decorators excluded), taken from the source parser when available.
"""

from __future__ import annotations

from knowledge_builder.models.base import IRModel

#: Kinds that *refer* to something defined elsewhere rather than defining it here.
#:
#: These have no definition site in this repo, so they carry no ``start_line``, never name
#: a module, and are not expected to belong to one. Every consumer must agree on the set —
#: a second copy that drifts turns "expected absence" into a spurious warning.
REFERENCE_KINDS: frozenset[str] = frozenset({"import", "external", "file", "module", "variable"})


class Symbol(IRModel):
    """A code symbol with its source-derived identity and metadata."""

    id: str
    label: str
    #: Clean identifier (``clean_revision``), free of parens / leading dots / file paths.
    name: str = ""
    #: function | method | class | file | module | ... (``None`` if undetermined).
    kind: str | None = None
    #: Dotted path: module path + nesting, e.g. ``app.collection.models.Collection.save``.
    qualified_name: str | None = None
    source_file: str | None = None
    #: Original graphify location string (e.g. ``L10-L30``); kept for provenance.
    source_location: str | None = None
    #: 1-based line of the ``def``/``class`` keyword (the identity/join key).
    start_line: int | None = None
    end_line: int | None = None
    start_col: int | None = None
    end_col: int | None = None
    language: str | None = None
    signature: str | None = None
    docstring: str | None = None
    decorators: tuple[str, ...] = ()
    is_async: bool = False
    is_static: bool = False
    is_abstract: bool = False
    #: public | protected | private (``None`` if not expressible in the language).
    visibility: str | None = None
    module_id: str | None = None
    rationale: str | None = None
