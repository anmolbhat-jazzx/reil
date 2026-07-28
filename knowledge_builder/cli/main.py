"""``knowledge`` — the production CLI.

Commands: build, validate, inspect, query, stats. Human-facing output uses ``rich``;
structured logs go to stderr (quieted to warnings by default, ``--verbose`` for info).
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from knowledge_builder.build import build_knowledge
from knowledge_builder.compiler.artifact import KnowledgeArtifact
from knowledge_builder.compiler.config import CompilerConfig
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.query import KnowledgeBase
from knowledge_builder.serializer.reader import KnowledgeReader
from knowledge_builder.utils.errors import KnowledgeBuilderError
from knowledge_builder.utils.logging import configure_logging
from knowledge_builder.validation import validate_repository

app = typer.Typer(
    add_completion=False,
    help="Compile a repository's graphify output into a portable knowledge.kb artifact.",
)
console = Console()
err_console = Console(stderr=True)

# Map each pass to the Definition-of-Done stage line it belongs to.
_STAGE_LABELS: dict[str, str] = {
    "graph-build": "Building Graphify graph",
    "load": "Loading Graphify graph",
    "symbols": "Extracting deterministic knowledge",
    "callgraph": "Extracting deterministic knowledge",
    "dependencies": "Extracting deterministic knowledge",
    "classify": "Extracting deterministic knowledge",
    "modules": "Extracting deterministic knowledge",
    "concepts": "Harvesting semantic knowledge",
    "workflows": "Harvesting semantic knowledge",
    "summaries": "Harvesting semantic knowledge",
    "optimize": "Optimizing knowledge",
    "serialize": "Writing knowledge.kb",
    "agents-doc": "Updating AGENTS.md",
    "validate": "Validating artifact",
}


@app.command()
def build(
    repository: Path = typer.Argument(..., exists=True, file_okay=False, help="Repo root."),
    output: Path | None = typer.Option(None, "--output", "-o", help="knowledge.kb path."),
    workspace: Path | None = typer.Option(
        None, "--workspace", "-w", help="Output folder for graph files + knowledge.kb."
    ),
    graphify_out: Path | None = typer.Option(
        None, "--graphify-out", help="Use an existing graphify-out dir (skip running graphify)."
    ),
    no_build_graph: bool = typer.Option(
        False, "--no-build-graph", help="Do not run graphify; reuse existing graph files."
    ),
    rebuild: bool = typer.Option(False, "--rebuild", help="Force re-running graphify."),
    no_agents_doc: bool = typer.Option(
        False, "--no-agents-doc", help="Do not write/update AGENTS.md in the repo."
    ),
    strict: bool = typer.Option(False, "--strict", help="Fail the build on validation errors."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Emit info-level logs."),
) -> None:
    """Compile REPOSITORY into knowledge.kb (runs graphify end-to-end by default)."""
    configure_logging(level=logging.INFO if verbose else logging.WARNING)
    config = CompilerConfig(
        repo_path=repository,
        output_path=output,
        workspace=workspace,
        graphify_out=graphify_out,
        build_graph=not no_build_graph,
        rebuild_graph=rebuild,
        write_agents_doc=not no_agents_doc,
        strict=strict,
    )

    console.print("Scanning repository...")
    printed: set[str] = set()

    def progress(stage: CompilerPass) -> None:
        label = _STAGE_LABELS.get(stage.name)
        if label and label not in printed:
            printed.add(label)
            console.print(f"{label}...")

    try:
        artifact = build_knowledge(config, progress)
    except KnowledgeBuilderError as exc:
        err_console.print(f"[bold red]✗ build failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc

    for warning in artifact.warnings:
        console.print(f"  [yellow]warning[/yellow] {warning.message}")

    path = artifact.stats.get("artifact_path", str(config.resolved_output_path))
    console.print()
    console.print(f"[bold green]✓ knowledge.kb generated successfully[/bold green] → {path}")
    _print_counts(artifact)
    agents = artifact.stats.get("agents_doc")
    if agents:
        console.print(f"  [dim]wrote {', '.join(agents)} so agents consult the KB[/dim]")
    console.print(
        f"  [dim]tip: add [bold]{config.resolved_workspace.name}/[/bold] to .gitignore[/dim]"
    )


@app.command()
def validate(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, help="knowledge.kb path."),
) -> None:
    """Validate an existing knowledge.kb and print a report."""
    with KnowledgeReader(artifact) as reader:
        report = validate_repository(reader.load_repository())

    for issue in report.warnings:
        console.print(f"[yellow]warning[/yellow] [{issue.code}] {issue.message}")
    for issue in report.errors:
        console.print(f"[red]error[/red] [{issue.code}] {issue.message}")

    if report.ok:
        console.print(f"[bold green]✓ valid[/bold green] ({len(report.warnings)} warning(s))")
    else:
        console.print(f"[bold red]✗ {len(report.errors)} error(s)[/bold red]")
        raise typer.Exit(1)


@app.command()
def inspect(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, help="knowledge.kb path."),
) -> None:
    """Show metadata, counts, and modules of a knowledge.kb."""
    with KnowledgeReader(artifact) as reader:
        meta = reader.metadata()
        counts = reader.counts()
        modules = reader.modules()
        summaries = {s.module_id: s for s in reader.summaries()}

    console.print(f"[bold]{meta.repo_name}[/bold]  (schema v{meta.schema_version})")
    console.print(f"graphify: {meta.graphify_version or 'unknown'}  |  nodes: {meta.node_count}")

    table = Table(title="Modules")
    table.add_column("Name")
    table.add_column("Origin")
    table.add_column("Symbols", justify="right")
    table.add_column("Concepts")
    for module in sorted(modules, key=lambda m: m.name):
        summary = summaries.get(module.id)
        concepts = ", ".join(summary.concepts) if summary else ""
        table.add_row(module.name, module.origin.value, str(len(module.symbol_ids)), concepts)
    console.print(table)

    counts_table = Table(title="Counts")
    counts_table.add_column("Entity")
    counts_table.add_column("Count", justify="right")
    for name, count in counts.items():
        counts_table.add_row(name, str(count))
    console.print(counts_table)


@app.command()
def query(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, help="knowledge.kb path."),
    text: str = typer.Argument(..., help="Search text."),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results."),
) -> None:
    """Retrieve entities matching TEXT (deterministic keyword search)."""
    with KnowledgeBase(artifact) as kb:
        results = kb.query(text, limit=limit)

    if not results:
        console.print("[dim]no matches[/dim]")
        return
    table = Table(title=f"Results for {text!r}")
    table.add_column("Kind")
    table.add_column("Name")
    table.add_column("Score", justify="right")
    for result in results:
        table.add_row(result.kind, result.name, f"{result.score:g}")
    console.print(table)


@app.command()
def context(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, help="knowledge.kb path."),
    text: str = typer.Argument(..., help="The question to build context for."),
    limit: int = typer.Option(8, "--limit", "-n", help="Max entities to include."),
    show: bool = typer.Option(False, "--show", help="Print the assembled context text."),
) -> None:
    """Assemble the LLM-ready context for a question and report its exact token cost."""
    with KnowledgeBase(artifact) as kb:
        result = kb.build_context(text, limit=limit)
    if show:
        console.print(result.text)
        console.print()
    console.print(
        f"[bold]{result.tokens:,} tokens[/bold] "
        f"([dim]{len(result.hits)} entities, tokenizer={result.tokenizer}[/dim])"
    )


@app.command()
def ask(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, help="knowledge.kb path."),
    text: str = typer.Argument(..., help="The question."),
    repo: Path = typer.Option(
        ..., "--repo", "-r", exists=True, file_okay=False, help="Repo checkout to read code from."
    ),
    limit: int = typer.Option(8, "--limit", "-n", help="Max entities in the KB map."),
    hops: int = typer.Option(1, "--hops", help="Graph expansion hops from seed matches."),
    max_symbols: int = typer.Option(40, "--max-symbols", help="Max candidate functions."),
    max_lines: int = typer.Option(60, "--max-lines", help="Max lines per function slice."),
    code_budget: int = typer.Option(2000, "--code-budget", help="Max code tokens to read."),
    show: bool = typer.Option(False, "--show", help="Print the assembled hybrid context."),
) -> None:
    """Hybrid context: KB map + graph-selected source slices, with a token breakdown."""
    with KnowledgeBase(artifact) as kb:
        result = kb.build_hybrid_context(
            text,
            repo,
            limit=limit,
            hops=hops,
            max_symbols=max_symbols,
            max_lines=max_lines,
            code_token_budget=code_budget,
        )
    if show:
        console.print(result.text)
        console.print()
    console.print(
        f"[bold]{result.tokens:,} tokens[/bold] = "
        f"{result.kb_tokens:,} KB map + {result.code_tokens:,} code  "
        f"([dim]{len(result.snippets)} snippets from {len(result.hits)} entities, "
        f"tokenizer={result.tokenizer}[/dim])"
    )


@app.command()
def stats(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, help="knowledge.kb path."),
) -> None:
    """Print summary statistics for a knowledge.kb."""
    with KnowledgeBase(artifact) as kb:
        data = kb.stats()
    console.print(f"[bold]{data['repo_name']}[/bold] (schema v{data['schema_version']})")
    table = Table()
    table.add_column("Entity")
    table.add_column("Count", justify="right")
    for name, count in data["counts"].items():
        table.add_row(name, str(count))
    console.print(table)


def _print_counts(artifact: KnowledgeArtifact) -> None:
    repo = artifact.repository
    console.print(
        f"  modules={len(repo.modules)} services={len(repo.services)} "
        f"concepts={len(repo.concepts)} workflows={len(repo.workflows)} "
        f"symbols={len(repo.symbols)} nodes={repo.metadata.node_count}"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
