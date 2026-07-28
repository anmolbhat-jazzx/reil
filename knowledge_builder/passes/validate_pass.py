"""ValidatePass (Phase 8) — verify IR integrity and record a report.

Runs :func:`validate_repository`, stashes the report in ``context.artifacts``, emits a
diagnostic per issue, and — when ``config.strict`` is set — raises
:class:`ValidationError` if any errors are found.
"""

from __future__ import annotations

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.utils.errors import ValidationError
from knowledge_builder.validation import validate_repository

VALIDATION_REPORT = "validation_report"


class ValidatePass(CompilerPass):
    """Validate the compiled IR and (optionally) fail the build on errors."""

    name = "validate"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        report = validate_repository(ir)
        context.artifacts[VALIDATION_REPORT] = report
        context.stats["validation"] = {
            "errors": len(report.errors),
            "warnings": len(report.warnings),
        }

        for issue in report.warnings:
            context.warning(self.name, issue.message, code=issue.code)
        for issue in report.errors:
            context.error(self.name, issue.message, code=issue.code)

        if report.ok:
            context.info(self.name, "artifact validated", warnings=len(report.warnings))
        elif context.config.strict:
            summary = "; ".join(f"{i.code}: {i.message}" for i in report.errors[:5])
            count = len(report.errors)
            raise ValidationError(f"validation failed with {count} error(s): {summary}")
        else:
            context.info(self.name, "validation found errors", errors=len(report.errors))
