"""AgentsDocPass — write/update ``AGENTS.md`` + ``CLAUDE.md`` so agents use ``knowledge.kb``.

An agent won't discover the compiled knowledge base on its own. This pass drops a short,
auto-managed section into the repo's agent-instruction files (``AGENTS.md`` for Cursor and
AGENTS.md-aware tools, ``CLAUDE.md`` for Claude Code), created if absent, telling any coding
agent to consult ``knowledge.kb`` first. The section is delimited by marker comments so
re-running ``knowledge build`` updates *only* our block and never clobbers the user's own
content.
"""

from __future__ import annotations

import os
from pathlib import Path

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass

#: Agent-instruction files we manage, in order.
MANAGED_FILES = ("AGENTS.md", "CLAUDE.md")
BEGIN = "<!-- BEGIN knowledge.kb (auto-managed by `knowledge build`) -->"
END = "<!-- END knowledge.kb -->"


class AgentsDocPass(CompilerPass):
    """Create or update the ``knowledge.kb`` section of ``AGENTS.md`` and ``CLAUDE.md``."""

    name = "agents-doc"

    def run(self, context: CompilationContext) -> None:
        cfg = context.config
        if not cfg.write_agents_doc:
            return

        kb_rel = _relpath(cfg.resolved_output_path, cfg.repo_path)
        block = render_block(kb_rel)
        results: dict[str, str] = {}
        for filename in MANAGED_FILES:
            path = cfg.repo_path / filename
            try:
                results[filename] = upsert_agents_doc(path, block)
            except OSError as exc:
                context.warning(self.name, f"could not write {filename}: {exc}")

        if results:
            context.stats["agents_doc"] = results
            context.info(self.name, "wrote agent docs", files=results)


def render_block(kb_rel: str) -> str:
    """Render the auto-managed agent-docs section (between the marker comments)."""
    return (
        f"{BEGIN}\n"
        "## Repository knowledge (knowledge.kb)\n\n"
        "Prefer querying the compiled knowledge base over reading source — it is far "
        "cheaper. For ANY question about this codebase's architecture, modules, or how "
        "something works, use it FIRST:\n\n"
        f"1. If `{kb_rel}` is missing (it is gitignored / per-machine), build it once:\n"
        "   `knowledge build .`  (needs the `knowledge` CLI installed).\n"
        "2. Query it:\n"
        f'    - Detailed (map + exact code): `knowledge ask {kb_rel} "<question>" --repo .`\n'
        f'    - Overview (cheapest, no code): `knowledge context {kb_rel} "<question>"`\n'
        f'    - Find entities: `knowledge query {kb_rel} "<terms>"`\n\n'
        "Rebuild after significant changes: `knowledge build . --rebuild`. "
        "If the KB cannot answer, fall back to reading source.\n"
        f"{END}"
    )


def upsert_agents_doc(path: Path, block: str) -> str:
    """Create ``path`` with ``block``, or replace/append the managed block in place.

    Returns ``"created"`` or ``"updated"``.
    """
    if not path.exists():
        path.write_text(block + "\n", encoding="utf-8")
        return "created"

    text = path.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        pre = text[: text.index(BEGIN)]
        post = text[text.index(END) + len(END) :]
        path.write_text(pre + block + post, encoding="utf-8")
    else:
        separator = "" if text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
        path.write_text(text + separator + block + "\n", encoding="utf-8")
    return "updated"


def _relpath(target: Path, base: Path) -> str:
    try:
        return os.path.relpath(target, base)
    except ValueError:  # pragma: no cover - different drives on Windows
        return str(target)
