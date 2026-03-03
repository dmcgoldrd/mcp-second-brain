"""Metadata extraction from memory content.

Extracts structured metadata from raw text content. This runs server-side
but uses simple heuristics — LLM-powered extraction is delegated to the client
via MCP tool descriptions that instruct the AI to provide structured input.
"""

from __future__ import annotations

import re
from datetime import datetime


def extract_metadata(content: str) -> dict:
    """Extract basic metadata from memory content using heuristics.

    For richer extraction (entities, topics, sentiment), the MCP tool
    descriptions instruct the AI client to provide these in the metadata
    field when creating memories.
    """
    metadata: dict = {}

    # Word count
    words = content.split()
    metadata["word_count"] = len(words)

    # Detect URLs
    urls = re.findall(r"https?://[^\s<>\"']+", content)
    if urls:
        metadata["urls"] = urls

    # Detect @mentions
    mentions = re.findall(r"@(\w+)", content)
    if mentions:
        metadata["mentions"] = mentions

    # Detect dates in content
    date_patterns = re.findall(
        r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        content,
    )
    if date_patterns:
        metadata["referenced_dates"] = date_patterns

    # Timestamp
    metadata["indexed_at"] = datetime.utcnow().isoformat()

    return metadata


def classify_memory_type(content: str) -> str:
    """Simple heuristic classification of memory type.

    The AI client can override this by providing memory_type explicitly.
    """
    lower = content.lower()

    if any(kw in lower for kw in ["todo", "task", "need to", "should", "must", "deadline"]):
        return "task"
    if any(kw in lower for kw in ["idea:", "what if", "maybe we", "concept:", "brainstorm"]):
        return "idea"
    if any(kw in lower for kw in ["http://", "https://", "reference:", "link:", "source:"]):
        return "reference"
    if any(kw in lower for kw in ["decided", "decision:", "chose", "going with", "picked"]):
        return "decision"
    if any(kw in lower for kw in ["prefer", "always", "never", "i like", "i hate", "i want"]):
        return "preference"
    if any(
        kw in lower
        for kw in ["met with", "spoke to", "talked to", "said that", "person:"]
    ):
        return "person_note"

    return "observation"
