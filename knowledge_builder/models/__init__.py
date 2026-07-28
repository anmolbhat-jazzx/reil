"""Repository IR — the stable abstraction every compilation stage operates on."""

from __future__ import annotations

from knowledge_builder.models.api import Api
from knowledge_builder.models.base import (
    ComponentKind,
    Confidence,
    FileType,
    HyperedgeRelation,
    IRModel,
    ModuleOrigin,
    RelationType,
)
from knowledge_builder.models.concept import Concept
from knowledge_builder.models.controller import Controller
from knowledge_builder.models.dependency import Dependency
from knowledge_builder.models.graph import GraphNode, Relationship
from knowledge_builder.models.metadata import SCHEMA_VERSION, Metadata
from knowledge_builder.models.module import Module
from knowledge_builder.models.repository import Repository
from knowledge_builder.models.service import Service
from knowledge_builder.models.summary import Summary
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.models.workflow import Workflow

__all__ = [
    "SCHEMA_VERSION",
    "Api",
    "ComponentKind",
    "Concept",
    "Confidence",
    "Controller",
    "Dependency",
    "FileType",
    "GraphNode",
    "HyperedgeRelation",
    "IRModel",
    "Metadata",
    "Module",
    "ModuleOrigin",
    "RelationType",
    "Relationship",
    "Repository",
    "Service",
    "Summary",
    "Symbol",
    "Workflow",
]
