"""Pydantic models for MCP Brain core entities.

These models are the single source of truth for data shapes across all layers:
- DB layer returns model instances (from_row class methods)
- Tools layer operates on model instances
- Server/MCP layer serializes models to JSON (via .model_dump())
- Consolidation engine uses models for type-safe processing

Using Pydantic v2 for performance, validation, and future FastAPI/PydanticAI compatibility.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums — single source of truth for all valid string types
# ---------------------------------------------------------------------------


class MemoryType(StrEnum):
    OBSERVATION = "observation"
    TASK = "task"
    IDEA = "idea"
    REFERENCE = "reference"
    PERSON_NOTE = "person_note"
    DECISION = "decision"
    PREFERENCE = "preference"


class MemorySource(StrEnum):
    MCP = "mcp"
    SLACK = "slack"
    MANUAL = "manual"
    IMPORT = "import"


class EntityType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    PROJECT = "project"
    TOPIC = "topic"


class SubscriptionStatus(StrEnum):
    FREE = "free"
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"


class ConsolidationAction(StrEnum):
    UPDATE_SCORE = "update_score"
    MERGE = "merge"
    RESOLVE_CONFLICT = "resolve_conflict"
    EXTRACT_ENTITY = "extract_entity"
    ARCHIVE = "archive"


class ArchiveReason(StrEnum):
    DUPLICATE = "duplicate"
    CONFLICT_RESOLVED = "conflict_resolved"
    LOW_IMPORTANCE_DECAY = "low_importance_decay"


# ---------------------------------------------------------------------------
# Core entity models
# ---------------------------------------------------------------------------


class Memory(BaseModel):
    """A single memory stored in the user's brain."""

    id: UUID
    user_id: UUID
    bank_id: UUID
    content: str
    memory_type: MemoryType = MemoryType.OBSERVATION
    tags: list[str] = Field(default_factory=list)
    source: MemorySource = MemorySource.MCP
    metadata: dict[str, Any] = Field(default_factory=dict)
    access_count: int = 0
    last_accessed_at: datetime | None = None
    importance_score: float = 0.0
    archived_at: datetime | None = None
    archived_reason: str | None = None
    superseded_by: UUID | None = None
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    def is_archived(self) -> bool:
        return self.archived_at is not None

    def to_mcp_response(self, include_score: bool = False, score: float = 0.0) -> dict[str, Any]:
        """Serialize for MCP tool response."""
        result: dict[str, Any] = {
            "id": str(self.id),
            "content": self.content,
            "memory_type": self.memory_type.value,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_score:
            result["score"] = score
        return result


class MemoryCreate(BaseModel):
    """Input model for creating a new memory."""

    content: str = Field(min_length=1, max_length=50000)
    memory_type: MemoryType | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] | None = None
    source: MemorySource = MemorySource.MCP


class MemoryConflict(BaseModel):
    """A potential conflict detected during memory creation."""

    memory_id: UUID
    content: str
    similarity: float
    memory_type: MemoryType = MemoryType.OBSERVATION
    created_at: datetime | None = None


class MemorySearchResult(BaseModel):
    """A memory with a relevance score from search."""

    memory: Memory
    score: float = 0.0


class Bank(BaseModel):
    """A memory bank — an isolated namespace for organizing memories."""

    id: UUID
    user_id: UUID
    name: str
    slug: str
    is_default: bool = False
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class BankCreate(BaseModel):
    """Input model for creating a new bank."""

    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9-]*$")


class Profile(BaseModel):
    """User profile with subscription status and memory count."""

    id: UUID
    display_name: str | None = None
    stripe_customer_id: str | None = None
    subscription_status: SubscriptionStatus = SubscriptionStatus.FREE
    memory_count: int = 0
    last_consolidation_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @property
    def is_paid(self) -> bool:
        return self.subscription_status == SubscriptionStatus.ACTIVE


class Entity(BaseModel):
    """A named entity extracted from memories (person, org, place, etc.)."""

    id: UUID
    user_id: UUID
    bank_id: UUID
    entity_name: str
    entity_type: EntityType
    facts: list[dict[str, Any]] = Field(default_factory=list)
    memory_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    def to_mcp_response(self) -> dict[str, Any]:
        """Serialize for MCP tool response."""
        return {
            "id": str(self.id),
            "entity_name": self.entity_name,
            "entity_type": self.entity_type.value,
            "facts": self.facts,
            "memory_ids": [str(mid) for mid in self.memory_ids],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ConsolidationLogEntry(BaseModel):
    """A record of an action taken during consolidation."""

    id: UUID
    user_id: UUID
    bank_id: UUID
    action: ConsolidationAction
    memory_ids: list[UUID] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class Subscription(BaseModel):
    """Stripe subscription record."""

    id: UUID
    user_id: UUID
    stripe_subscription_id: str
    stripe_customer_id: str
    status: SubscriptionStatus
    price_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Import/Export models
# ---------------------------------------------------------------------------


class MemoryImportItem(BaseModel):
    """A single memory to import."""

    content: str = Field(min_length=1)
    memory_type: MemoryType | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class MemoryImportRequest(BaseModel):
    """Batch import request."""

    memories: list[MemoryImportItem] = Field(max_length=100)
    deduplicate: bool = True


class MemoryImportResult(BaseModel):
    """Result of a batch import."""

    status: str = "imported"
    created: int = 0
    skipped: int = 0
    memory_ids: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Consolidation summary
# ---------------------------------------------------------------------------


class ConsolidationSummary(BaseModel):
    """Summary of a consolidation run for one user+bank."""

    user_id: str
    bank_id: str
    started_at: str
    completed_at: str | None = None
    scores_updated: int = 0
    duplicates_merged: int = 0
    conflicts_resolved: int = 0
    entities_extracted: int = 0
    stale_archived: int = 0
    error: str | None = None
