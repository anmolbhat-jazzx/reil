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
from knowledge_builder.models import DbTable, Symbol
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

#: Conventional location of the compiled artifact, relative to the current directory.
DEFAULT_KB = Path(".knowledge/knowledge.kb")


def _resolve_kb(kb: Path | None) -> Path:
    """Return the KB path (default ``.knowledge/knowledge.kb``), or fail with guidance."""
    path = kb or DEFAULT_KB
    if not path.is_file():
        err_console.print(f"[bold red]✗ no knowledge base at {path}[/bold red]")
        err_console.print(
            "  Run [bold]reil build .[/bold] to create it, or pass [bold]--kb <path>[/bold]."
        )
        raise typer.Exit(1)
    return path


# Map each pass to the Definition-of-Done stage line it belongs to.
_STAGE_LABELS: dict[str, str] = {
    "graph-build": "Building Graphify graph",
    "load": "Loading Graphify graph",
    "symbols": "Extracting deterministic knowledge",
    "symbol-enrich": "Extracting deterministic knowledge",
    "callgraph": "Extracting deterministic knowledge",
    "dependencies": "Extracting deterministic knowledge",
    "classify": "Extracting deterministic knowledge",
    "openapi": "Extracting deterministic knowledge",
    "database": "Extracting deterministic knowledge",
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
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
) -> None:
    """Validate an existing knowledge.kb and print a report."""
    artifact = _resolve_kb(kb)
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
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
) -> None:
    """Show metadata, counts, and modules of a knowledge.kb."""
    artifact = _resolve_kb(kb)
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


#: Entity kinds grouped under the ``database`` query filter.
_DATABASE_KINDS: tuple[str, ...] = ("db_table", "db_migration", "db_technology")


@app.command()
def symbols(
    name: str | None = typer.Argument(None, help="Show symbols matching this name."),
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
    kind: str | None = typer.Option(None, "--kind", help="Filter by kind: function, class, ..."),
    limit: int = typer.Option(25, "--limit", "-n", help="Max rows."),
    coverage: bool = typer.Option(
        False, "--coverage", help="Report enrichment coverage instead of listing symbols."
    ),
) -> None:
    """Inspect code symbols: identity keys plus source-derived detail."""
    artifact = _resolve_kb(kb)
    with KnowledgeReader(artifact) as reader:
        all_symbols = reader.symbols()

    if coverage:
        _print_symbol_coverage(all_symbols)
        return

    matches = [
        s
        for s in all_symbols
        if (name is None or name.lower() in (s.name or "").lower())
        and (kind is None or s.kind == kind)
    ]
    if not matches:
        console.print("[dim]no matching symbols[/dim]")
        return

    if name is not None and len(matches) <= 5:
        for symbol in matches:
            _print_symbol_detail(symbol)
        return

    table = Table(title=f"Symbols ({len(matches)} matched, showing {min(limit, len(matches))})")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Signature")
    table.add_column("Location")
    for symbol in sorted(matches, key=lambda s: (s.source_file or "", s.start_line or 0))[:limit]:
        where = f"{symbol.source_file or '?'}:{symbol.start_line or '?'}"
        table.add_row(symbol.name, symbol.kind or "", symbol.signature or "", where)
    console.print(table)
    console.print("[dim]tip: [bold]reil symbols <name>[/bold] for full detail[/dim]")


def _print_symbol_detail(symbol: Symbol) -> None:
    console.print(
        f"[bold]{symbol.qualified_name or symbol.name}[/bold]  [dim]{symbol.kind or ''}[/dim]"
    )
    console.print(
        f"  location : {symbol.source_file or '?'}:{symbol.start_line or '?'}"
        f"-{symbol.end_line or '?'}   [dim](federation join key)[/dim]"
    )
    if symbol.signature:
        console.print(f"  signature: {symbol.signature}", markup=False, highlight=False)
    if symbol.docstring:
        first = symbol.docstring.splitlines()[0]
        console.print(f"  docstring: {first}", markup=False, highlight=False)
    if symbol.decorators:
        console.print(f"  decorators: {', '.join(symbol.decorators)}", markup=False)
    flags = [
        f
        for f, on in (
            ("async", symbol.is_async),
            ("static", symbol.is_static),
            ("abstract", symbol.is_abstract),
        )
        if on
    ]
    if flags or symbol.visibility:
        console.print(f"  modifiers: {', '.join([*flags, symbol.visibility or ''])}".rstrip(", "))
    console.print()


def _print_symbol_coverage(all_symbols: tuple[Symbol, ...]) -> None:
    """How much of each field the extractors actually filled, per language."""
    by_language: dict[str, list[Symbol]] = {}
    for symbol in all_symbols:
        by_language.setdefault(symbol.language or "unknown", []).append(symbol)

    table = Table(title=f"Symbol enrichment coverage ({len(all_symbols)} symbols)")
    table.add_column("Language")
    table.add_column("Total", justify="right")
    for column in ("name", "start_line", "kind", "qualified", "signature", "docstring"):
        table.add_column(column, justify="right")
    for language, group in sorted(by_language.items(), key=lambda kv: -len(kv[1])):
        total = len(group)

        def pct(n: int, total: int = total) -> str:
            return f"{n} ({round(100 * n / total)}%)" if total else "0"

        table.add_row(
            language,
            str(total),
            pct(sum(1 for s in group if s.name)),
            pct(sum(1 for s in group if s.start_line is not None)),
            pct(sum(1 for s in group if s.kind)),
            pct(sum(1 for s in group if s.qualified_name)),
            pct(sum(1 for s in group if s.signature)),
            pct(sum(1 for s in group if s.docstring)),
        )
    console.print(table)


@app.command()
def query(
    text: str = typer.Argument(..., help="Search text."),
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results."),
    kind: str | None = typer.Option(
        None, "--kind", help="Restrict to a kind: database, module, symbol, api, ..."
    ),
) -> None:
    """Retrieve entities matching TEXT (deterministic keyword search)."""
    kinds = _DATABASE_KINDS if kind == "database" else ((kind,) if kind else None)
    with KnowledgeBase(_resolve_kb(kb)) as base:
        results = base.query(text, limit=limit, kinds=kinds)

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
    text: str = typer.Argument(..., help="The question to build context for."),
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
    limit: int = typer.Option(8, "--limit", "-n", help="Max entities to include."),
    kind: str | None = typer.Option(
        None, "--kind", help="Restrict to a kind: database, module, symbol, api, ..."
    ),
    show: bool = typer.Option(False, "--show", help="Print the assembled context text."),
) -> None:
    """Assemble the LLM-ready context for a question and report its exact token cost."""
    kinds = _DATABASE_KINDS if kind == "database" else ((kind,) if kind else None)
    with KnowledgeBase(_resolve_kb(kb)) as base:
        result = base.build_context(text, limit=limit, kinds=kinds)
    if show:
        # Print the assembled context verbatim (it is data, not Rich markup).
        console.print(result.text, markup=False, highlight=False)
        console.print()
    console.print(
        f"[bold]{result.tokens:,} tokens[/bold] "
        f"([dim]{len(result.hits)} entities, tokenizer={result.tokenizer}[/dim])"
    )


@app.command()
def ask(
    text: str = typer.Argument(..., help="The question."),
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
    repo: Path = typer.Option(
        Path("."), "--repo", "-r", exists=True, file_okay=False, help="Repo checkout for code."
    ),
    limit: int = typer.Option(8, "--limit", "-n", help="Max entities in the KB map."),
    hops: int = typer.Option(1, "--hops", help="Graph expansion hops from seed matches."),
    max_symbols: int = typer.Option(40, "--max-symbols", help="Max candidate functions."),
    max_lines: int = typer.Option(60, "--max-lines", help="Max lines per function slice."),
    code_budget: int = typer.Option(2000, "--code-budget", help="Max code tokens to read."),
    show: bool = typer.Option(False, "--show", help="Print the assembled hybrid context."),
) -> None:
    """Hybrid context: KB map + graph-selected source slices, with a token breakdown."""
    with KnowledgeBase(_resolve_kb(kb)) as base:
        result = base.build_hybrid_context(
            text,
            repo,
            limit=limit,
            hops=hops,
            max_symbols=max_symbols,
            max_lines=max_lines,
            code_token_budget=code_budget,
        )
    if show:
        console.print(result.text, markup=False, highlight=False)
        console.print()
    console.print(
        f"[bold]{result.tokens:,} tokens[/bold] = "
        f"{result.kb_tokens:,} KB map + {result.code_tokens:,} code  "
        f"([dim]{len(result.snippets)} snippets from {len(result.hits)} entities, "
        f"tokenizer={result.tokenizer}[/dim])"
    )


@app.command()
def stats(
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
) -> None:
    """Print summary statistics for a knowledge.kb."""
    with KnowledgeBase(_resolve_kb(kb)) as base:
        data = base.stats()
    console.print(f"[bold]{data['repo_name']}[/bold] (schema v{data['schema_version']})")
    table = Table()
    table.add_column("Entity")
    table.add_column("Count", justify="right")
    for name, count in data["counts"].items():
        table.add_row(name, str(count))
    console.print(table)


@app.command()
def api(
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
    controller: bool = typer.Option(
        False, "--controllers", help="Group endpoints by controller instead of listing flat."
    ),
) -> None:
    """List every HTTP endpoint / route derived from the codebase."""
    artifact = _resolve_kb(kb)
    with KnowledgeReader(artifact) as reader:
        apis = reader.apis()
        controllers = {c.id: c for c in reader.controllers()}

    if not apis:
        console.print("[dim]no APIs detected in this repository[/dim]")
        return

    table = Table(title=f"APIs ({len(apis)})")
    table.add_column("Method")
    table.add_column("Path / Name")
    if controller:
        table.add_column("Controller")
    table.add_column("Source")
    for a in sorted(apis, key=lambda a: (a.path or a.name or "", a.method or "")):
        row = [a.method or "-", a.path or a.name]
        if controller:
            ctrl = controllers.get(a.controller_id or "")
            row.append(ctrl.name if ctrl else "")
        row.append(a.source_file or "")
        table.add_row(*row)
    console.print(table)


@app.command()
def db(
    table: str | None = typer.Argument(None, help="Show one table in detail (by name)."),
    kb: Path | None = typer.Option(None, "--kb", "-k", help="knowledge.kb path."),
) -> None:
    """Show the extracted database layer: detected stack, tables, columns, and evidence."""
    with KnowledgeBase(_resolve_kb(kb)) as base:
        technologies = base.db_technologies()
        tables = base.db_tables()
        migrations = base.db_migrations()

    if table is not None:
        matches = [t for t in tables if t.name.lower() == table.lower()]
        if not matches:
            err_console.print(f"[yellow]no table named {table!r}[/yellow]")
            raise typer.Exit(1)
        for match in matches:
            _print_db_table(match)
        return

    if not technologies and not tables:
        console.print("[dim]no database layer extracted for this repository[/dim]")
        return

    if technologies:
        tech_table = Table(title="Detected database technologies")
        tech_table.add_column("Technology")
        tech_table.add_column("Category")
        tech_table.add_column("Confidence")
        tech_table.add_column("Evidence")
        for tech in sorted(technologies, key=lambda t: (t.category, t.id)):
            tech_table.add_row(
                tech.name, tech.category, tech.confidence.value, ", ".join(tech.evidence)
            )
        console.print(tech_table)

    if tables:
        overview = Table(title=f"Tables ({len(tables)})")
        overview.add_column("Table")
        overview.add_column("Cols", justify="right")
        overview.add_column("Stack")
        overview.add_column("Source")
        for tbl in sorted(tables, key=lambda t: t.name):
            where = tbl.source_file or "?"
            if tbl.source_location:
                where = f"{where}:{tbl.source_location}"
            overview.add_row(tbl.name, str(len(tbl.columns)), tbl.technology or "", where)
        console.print(overview)
        console.print("[dim]tip: [bold]reil db <table>[/bold] for column-level detail[/dim]")

    if migrations:
        console.print(f"[dim]{len(migrations)} migration(s) extracted[/dim]")


def _print_db_table(tbl: DbTable) -> None:
    where = tbl.source_file or "?"
    if tbl.source_location:
        where = f"{where}:{tbl.source_location}"
    console.print(
        f"[bold]{tbl.name}[/bold]  "
        f"([dim]{tbl.technology or 'unknown'}, {tbl.confidence.value}, {where}[/dim])"
    )
    col_table = Table()
    col_table.add_column("Column")
    col_table.add_column("Type")
    col_table.add_column("Attributes")
    for col in tbl.columns:
        flags = []
        if col.primary_key:
            flags.append("PK")
        if col.unique:
            flags.append("unique")
        if col.nullable is False:
            flags.append("not null")
        if col.default:
            flags.append(f"default {col.default}")
        if col.references_table:
            target = col.references_table
            if col.references_column:
                target += f".{col.references_column}"
            flags.append(f"FK→{target}")
        col_table.add_row(col.name, col.data_type or "?", ", ".join(flags))
    console.print(col_table)
    for con in tbl.constraints:
        target = ""
        if con.references_table:
            target = f" → {con.references_table}({', '.join(con.references_columns)})"
        console.print(f"  [dim]constraint[/dim] {con.kind}({', '.join(con.columns)}){target}")
    for idx in tbl.indexes:
        kind = "unique index" if idx.unique else "index"
        console.print(f"  [dim]{kind}[/dim] {idx.name or ''} ({', '.join(idx.columns)})")


def _print_counts(artifact: KnowledgeArtifact) -> None:
    repo = artifact.repository
    console.print(
        f"  modules={len(repo.modules)} services={len(repo.services)} "
        f"concepts={len(repo.concepts)} workflows={len(repo.workflows)} "
        f"symbols={len(repo.symbols)} nodes={repo.metadata.node_count}"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
