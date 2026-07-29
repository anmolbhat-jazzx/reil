"""Tests for AGENTS.md create/update behaviour."""

from __future__ import annotations

from pathlib import Path

from knowledge_builder.passes.agents_doc_pass import BEGIN, END, render_block, upsert_agents_doc


def test_creates_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    action = upsert_agents_doc(path, render_block(".knowledge/knowledge.kb"))
    assert action == "created"
    text = path.read_text()
    assert BEGIN in text and END in text
    assert 'reil ask "<question>"' in text
    # preflight tool check so agents fall back cleanly when the CLI is absent
    assert "command -v reil" in text
    assert "read source directly" in text


def test_appends_to_existing_without_markers(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("# My project rules\n\nBe nice.\n", encoding="utf-8")
    action = upsert_agents_doc(path, render_block(".knowledge/knowledge.kb"))
    assert action == "updated"
    text = path.read_text()
    assert "# My project rules" in text  # user content preserved
    assert text.count(BEGIN) == 1


def test_updates_managed_block_in_place(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("intro\n\n" + render_block("old/path.kb") + "\n\noutro\n", encoding="utf-8")
    upsert_agents_doc(path, render_block("new/path.kb"))
    text = path.read_text()
    assert "intro" in text and "outro" in text  # surrounding content kept
    assert "new/path.kb" in text
    assert "old/path.kb" not in text
    assert text.count(BEGIN) == 1  # no duplicate block


def test_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    block = render_block(".knowledge/knowledge.kb")
    upsert_agents_doc(path, block)
    first = path.read_text()
    upsert_agents_doc(path, block)
    assert path.read_text() == first
