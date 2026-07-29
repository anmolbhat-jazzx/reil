# Repository Intelligence Layer

Compile any software repository into a **portable, AI-native artifact** — `knowledge.kb`.

The guiding metaphor is a **compiler**: understanding a repository is a *build step*, not a
runtime activity. You compile a repo once into a single SQLite file that captures its
structural + semantic intelligence, then answer questions about it **offline and cheaply** —
thousands of times fewer tokens than reading source.

```text
Repository ──▶ graphify (AST) ──▶ Repository IR ──▶ Knowledge Compiler ──▶ knowledge.kb
```

- **Zero tokens to build.** The compiler never calls an LLM; graphify runs in AST-only mode.
- **Portable.** One SQLite file you can gitignore, ship, or query offline.
- **Graph-native retrieval.** Answers walk real code edges (calls/imports/contains), not text similarity.
- **Hybrid answers.** The KB is an index; when detail is needed it reads only the exact lines the graph points to — never whole files.

> 📄 **Full architecture, design rationale, tool comparison, and benchmark write-up:**
> [Notion — Repository Intelligence Layer: Problem, Approach & Results](https://app.notion.com/p/3aa2471607bf81e1ad01ebebb6f1c988)

---

## Requirements

- **Python ≥ 3.11**
- **graphify** on your `PATH` for the automatic graph build (`reil build` runs it for you, AST-only, no tokens). PyPI package `graphifyy` → `graphify` CLI (install below). If graphify isn't installed, point at an existing `graphify-out/` with `--no-build-graph`.
- All Python deps (`pydantic`, `typer`, `rich`, `structlog`, `tiktoken`) install automatically.

## Install

### Use it — install once with `pipx` (recommended, works on any machine)

`pipx` installs the `reil` CLI into its own isolated environment and puts it on your
`PATH` — no project-venv pollution, no dependency conflicts. This is the reproducible way
that works for everyone.

```bash
brew install pipx            # macOS  (Linux: python3 -m pip install --user pipx)
pipx ensurepath              # adds pipx's bin dir to PATH — then restart your shell

# Install the tool. The repo is private, so use an HTTPS token:
pipx install "git+https://<TOKEN>@github.com/anmolbhat-jazzx/reil.git"
# …or, if you already have the repo cloned locally (no token needed):
pipx install /path/to/reil
```

`graphify` comes bundled as a dependency, and `reil build` finds it automatically —
even though pipx exposes only the `reil` command. Pin a version with a ref, e.g.
`...reil.git@main`.

> **Using it from a coding agent (Claude Code / Cursor)?** After `pipx ensurepath`,
> **restart the agent/terminal** so it picks up the updated `PATH` — agents capture `PATH`
> at launch, so a freshly installed command won't appear until then.

### Develop it — clone

```bash
git clone git@github.com:anmolbhat-jazzx/reil.git && cd reil
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # adds ruff/black/mypy/pytest
```

Verify either install:

```bash
reil --help
```

To skip graphify and compile a repo that already has a `graphify-out/`, use
`reil build <repo> --no-build-graph`.

---

## Quickstart (end to end)

```bash
# Compile a repo into knowledge.kb (runs graphify for you, AST-only → 0 tokens)
reil build /path/to/repo
```

Output:

```text
Scanning repository...
Building Graphify graph...
Loading Graphify graph...
Extracting deterministic knowledge...
Harvesting semantic knowledge...
Optimizing knowledge...
Writing knowledge.kb...
Validating artifact...

✓ knowledge.kb generated successfully → /path/to/repo/.knowledge/knowledge.kb
  wrote AGENTS.md, CLAUDE.md so agents consult the KB
  tip: add .knowledge/ to .gitignore
```

Everything lands in one folder (`/path/to/repo/.knowledge/`): the imported graph files and
`knowledge.kb`. Add `.knowledge/` to your `.gitignore`.

**Agent integration.** Each build writes (or updates) both `AGENTS.md` (Cursor and other
AGENTS.md-aware tools) and `CLAUDE.md` (Claude Code) with a short auto-managed block telling
any coding agent to query `knowledge.kb` first. It only touches its own marker-delimited
section, so your existing content in those files is preserved. Pass `--no-agents-doc` to skip.

If the repo already has a `graphify-out/` (or graphify isn't installed):

```bash
reil build /path/to/repo --no-build-graph
```

## Commands

Run the query commands **from the repo root** — the KB path defaults to
`.knowledge/knowledge.kb` (override with `--kb <path>`), and `reil ask` reads code from `.`
by default (override with `--repo <path>`). If the KB is missing, the command fails and
tells you to run `reil build .`.

| Command | What it does |
| --- | --- |
| `reil build <repo>` | Compile a repo → `knowledge.kb`. Flags: `--workspace/-w`, `--no-build-graph`, `--rebuild`, `--strict`. |
| `reil ask "<q>"` | **Hybrid** answer context: KB map + exact source slices, with a token breakdown. |
| `reil context "<q>"` | KB-only context (no source needed) + token count. |
| `reil query "<text>"` | Ranked entity retrieval. |
| `reil inspect` | Metadata, modules, counts. |
| `reil validate` | Integrity report. |
| `reil stats` | Summary statistics. |

Hybrid tuning: `--code-budget` (default 2000 tokens), `--hops`, `--max-symbols`, `--max-lines`.

## Use from Python

```python
from knowledge_builder import KnowledgeBase

with KnowledgeBase("/path/to/repo/.knowledge/knowledge.kb") as kb:
    kb.get_module("Upload Pipeline")
    kb.get_service("UploadService")

    # KB-only context + exact token cost
    ctx = kb.build_context("explain the upload workflow")
    print(ctx.tokens, "tokens")

    # Hybrid: KB map + exact source slices (needs the repo checked out)
    hybrid = kb.build_hybrid_context("zip-upload architecture", "/path/to/repo")
    print(hybrid.tokens, "=", hybrid.kb_tokens, "map +", hybrid.code_tokens, "code")
```

Compile programmatically:

```python
from pathlib import Path
from knowledge_builder.build import build_knowledge
from knowledge_builder.compiler import CompilerConfig

artifact = build_knowledge(CompilerConfig(repo_path=Path("/path/to/repo")))
print(artifact.stats["artifact_path"])
```

---

## Results (measured on a real 3,430-file repo)

Compiling `knowledge_hub` (10,572 graph nodes / 21,129 edges) took **~0.6s, 0 LLM tokens**, producing
496 modules, 3,412 concepts, 6,354 symbols.

Answering *"summarize the zip-upload architecture"* — real `cl100k_base` token counts:

| Method | Tokens | Notes |
| --- | ---: | --- |
| Read whole source files | 11,920 | baseline; re-paid every question |
| **Hybrid `ask` (default budget 2,000)** | **3,147** | KB map + 4 exact function slices |
| **Hybrid `ask` (`--code-budget 3000`)** | **4,438** | adds confirm/CAS + concurrency (8 fns) |
| KB-only `context` | ~1,500–2,400 | overview, no code detail |

Whole-repo scale: raw source ≈ **7.9M tokens**; a full knowledge render ≈ **128K (62× smaller)**;
a scoped answer ≈ **1K (~7,000× smaller)**.

**Build once (0 tokens) → answer cheaply forever**, instead of re-reading source every question.

---

## Development

```bash
ruff check knowledge_builder tests
black --check knowledge_builder tests
mypy knowledge_builder            # strict mode
pytest                            # unit + integration
```

CI (`.github/workflows/ci.yml`) runs all four on Python 3.11 and 3.12. Pre-commit hooks are in
`.pre-commit-config.yaml` (`pre-commit install`).

## Project layout

```
knowledge_builder/   models · compiler · parser · passes · optimizer · serializer · query · cli · utils
tests/               unit/ + integration/ + fixtures/ (a tiny sample graphify-out)
pyproject.toml       package + tool config
```

## Notes / caveats

- **Deterministic V1.** No LLM at compile time. Module summaries capture structure + harvested
  concepts; richer prose (`purpose`, `business_rules`) is a future LLM-summary pass.
- **Hybrid slices are approximate.** graphify stores only a symbol's start line, so a slice runs
  start → next-symbol-start (capped by `--max-lines`).
- **Staleness.** If source changed since the graph was built, line markers can drift; `knowledge.kb`
  stores `file_hashes` to support a future staleness check — re-run `reil build --rebuild`.
- **Tokenizer.** `cl100k_base` (real BPE), within ~10% of other modern tokenizers.
