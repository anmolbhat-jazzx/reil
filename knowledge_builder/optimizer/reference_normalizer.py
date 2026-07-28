"""Reference normalization — drop dangling cross-links so every id resolves.

After deduplication (and in case graphify emitted edges to nodes it never declared),
some id references may point at entities that no longer exist. This pass filters every
cross-reference down to ids that resolve, keeping the IR internally consistent before
serialization.
"""

from __future__ import annotations

from knowledge_builder.models.repository import Repository


def normalize_references(repo: Repository) -> Repository:
    """Return a copy of ``repo`` with all dangling references removed."""
    nodes = {n.id for n in repo.graph_nodes}
    symbols = {s.id for s in repo.symbols}
    modules = {m.id for m in repo.modules}
    concepts = {c.id for c in repo.concepts}
    services = {s.id for s in repo.services}
    controllers = {c.id for c in repo.controllers}
    apis = {a.id for a in repo.apis}
    workflows = {w.id for w in repo.workflows}
    summaries = {s.id for s in repo.summaries}

    new_modules = tuple(
        module.model_copy(
            update={
                "symbol_ids": _keep(module.symbol_ids, symbols),
                "related_module_ids": _keep(module.related_module_ids, modules - {module.id}),
                "concept_ids": _keep(module.concept_ids, concepts),
                "service_ids": _keep(module.service_ids, services),
                "controller_ids": _keep(module.controller_ids, controllers),
                "api_ids": _keep(module.api_ids, apis),
                "workflow_ids": _keep(module.workflow_ids, workflows),
                "summary_id": module.summary_id if module.summary_id in summaries else None,
            }
        )
        for module in repo.modules
    )
    new_concepts = tuple(
        concept.model_copy(update={"related_ids": _keep(concept.related_ids, nodes)})
        for concept in repo.concepts
    )
    new_apis = tuple(
        api.model_copy(
            update={
                "handler_symbol_id": (
                    api.handler_symbol_id if api.handler_symbol_id in symbols else None
                ),
                "controller_id": api.controller_id if api.controller_id in controllers else None,
            }
        )
        for api in repo.apis
    )
    new_relationships = tuple(
        rel for rel in repo.relationships if rel.source_id in nodes and rel.target_id in nodes
    )
    new_dependencies = tuple(dep for dep in repo.dependencies if dep.source_id in nodes)

    return repo.evolve(
        modules=new_modules,
        concepts=new_concepts,
        apis=new_apis,
        relationships=new_relationships,
        dependencies=new_dependencies,
    )


def _keep(ids: tuple[str, ...], valid: set[str]) -> tuple[str, ...]:
    return tuple(sorted({i for i in ids if i in valid}))
