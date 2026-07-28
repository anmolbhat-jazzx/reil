"""Compiler framework: pluggable passes, pipeline, context, and artifact."""

from __future__ import annotations

from knowledge_builder.compiler.artifact import KnowledgeArtifact
from knowledge_builder.compiler.compiler import Compiler
from knowledge_builder.compiler.config import CompilerConfig
from knowledge_builder.compiler.context import CompilationContext, Diagnostic, Severity
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.compiler.pipeline import CompilationPipeline

__all__ = [
    "CompilationContext",
    "CompilationPipeline",
    "Compiler",
    "CompilerConfig",
    "CompilerPass",
    "Diagnostic",
    "KnowledgeArtifact",
    "Severity",
]
