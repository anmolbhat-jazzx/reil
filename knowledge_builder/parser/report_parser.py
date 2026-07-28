"""ReportParser — extract human-readable insights from graphify's analysis/report.

The IR does not need these to be complete, but they enrich the artifact's metadata and
power the CLI ``inspect`` view: surprising cross-community connections and graphify's
suggested questions. Everything here is best-effort and degrades to empty.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from knowledge_builder.parser.loader import GraphifyBundle


class ReportInsights(BaseModel):
    """Non-structural insights carried alongside the graph."""

    model_config = ConfigDict(frozen=True)

    surprises: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()


class ReportParser:
    """Parses the analysis sidecar into :class:`ReportInsights`."""

    def parse(self, bundle: GraphifyBundle) -> ReportInsights:
        return ReportInsights(
            surprises=_string_tuple(bundle.analysis.get("surprises")),
            questions=_string_tuple(bundle.analysis.get("questions")),
        )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            text = item.get("text") or item.get("summary") or item.get("label")
            if isinstance(text, str) and text.strip():
                out.append(text.strip())
    return tuple(out)
