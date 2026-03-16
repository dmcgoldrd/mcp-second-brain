"""Nightly consolidation engine — the intelligence layer that runs per-user.

Implements a 5-phase pipeline inspired by human memory consolidation:
  Phase 1: Importance scoring (pure SQL)
  Phase 2: Near-duplicate detection + merge (SQL + embeddings)
  Phase 3: Conflict resolution (LLM for ambiguous pairs only)
  Phase 4: Entity extraction (LLM, batched)
  Phase 5: Archive stale memories (pure SQL)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from src.db.connection import get_pool
from src.db.utils import parse_uuid
from src.embeddings import get_openai_client

logger = logging.getLogger("mcp-brain")

# LLM model for cheap classification/extraction calls
_CLASSIFICATION_MODEL = "gpt-4o-mini"

# Consolidation thresholds
_DUPLICATE_SIMILARITY_THRESHOLD = 0.90
_CONFLICT_SIMILARITY_LOW = 0.80
_CONFLICT_SIMILARITY_HIGH = 0.90
_ARCHIVE_SCORE_THRESHOLD = 0.1
_ARCHIVE_AGE_DAYS = 90
_ENTITY_BATCH_SIZE = 10
_LLM_CONCURRENCY = 10  # max concurrent LLM calls
_USER_CONCURRENCY = 5  # max concurrent user consolidations


# ---------------------------------------------------------------------------
# Phase 1: Importance Scoring
# ---------------------------------------------------------------------------


async def _phase_importance_scoring(
    conn,
    user_uuid: uuid.UUID,
    bank_uuid: uuid.UUID,
) -> int:
    """Score all active memories using recency decay and access frequency.

    Formula: score = (1.0 / (1 + days_since_created)) * (1 + 0.1 * access_count)

    Returns the number of memories scored.
    """
    result = await conn.execute(
        """
        UPDATE memories
        SET importance_score = (
            1.0 / (1 + EXTRACT(EPOCH FROM (now() - created_at)) / 86400.0)
        ) * (1 + 0.1 * COALESCE(access_count, 0))
        WHERE user_id = $1::uuid
          AND bank_id = $2::uuid
          AND archived_at IS NULL
        """,
        user_uuid,
        bank_uuid,
    )
    count = int(result.split()[-1]) if result else 0

    if count > 0:
        await _log_action(
            conn,
            user_uuid,
            bank_uuid,
            action="update_score",
            memory_ids=[],
            details={"memories_scored": count},
        )

    return count


# ---------------------------------------------------------------------------
# Phase 2: Near-Duplicate Detection + Merge
# ---------------------------------------------------------------------------


async def _phase_duplicate_merge(
    conn,
    user_uuid: uuid.UUID,
    bank_uuid: uuid.UUID,
) -> int:
    """Find and merge near-duplicate memories (cosine similarity > 0.90).

    For each duplicate cluster, keep the memory with the highest importance_score
    and archive the rest with superseded_by pointing to the survivor.

    Returns the number of memories archived as duplicates.
    """
    # Find duplicate pairs — self-join on high cosine similarity.
    # We use (1 - cosine distance) > threshold.
    # Only compare each pair once (a.id < b.id) to avoid double-counting.
    rows = await conn.fetch(
        """
        SELECT
            a.id AS id_a,
            b.id AS id_b,
            a.importance_score AS score_a,
            b.importance_score AS score_b,
            1 - (a.embedding <=> b.embedding) AS similarity
        FROM memories a
        JOIN memories b
          ON a.user_id = b.user_id
         AND a.bank_id = b.bank_id
         AND a.id < b.id
        WHERE a.user_id = $1::uuid
          AND a.bank_id = $2::uuid
          AND a.archived_at IS NULL
          AND b.archived_at IS NULL
          AND a.embedding IS NOT NULL
          AND b.embedding IS NOT NULL
          AND 1 - (a.embedding <=> b.embedding) > $3
        ORDER BY similarity DESC
        LIMIT 500
        """,
        user_uuid,
        bank_uuid,
        _DUPLICATE_SIMILARITY_THRESHOLD,
    )

    if not rows:
        return 0

    # Build clusters: for each pair, the lower-scored memory gets archived.
    # Track which IDs are already archived so we don't archive a survivor.
    archived_ids: set[uuid.UUID] = set()
    merge_count = 0

    for row in rows:
        id_a = row["id_a"]
        id_b = row["id_b"]

        # Skip if either was already archived in this run
        if id_a in archived_ids or id_b in archived_ids:
            continue

        # Keep the higher-scored memory, archive the other
        if row["score_a"] >= row["score_b"]:
            survivor_id, loser_id = id_a, id_b
        else:
            survivor_id, loser_id = id_b, id_a

        await conn.execute(
            """
            UPDATE memories
            SET archived_at = now(),
                archived_reason = 'duplicate',
                superseded_by = $1
            WHERE id = $2
            """,
            survivor_id,
            loser_id,
        )

        archived_ids.add(loser_id)
        merge_count += 1

        await _log_action(
            conn,
            user_uuid,
            bank_uuid,
            action="merge",
            memory_ids=[survivor_id, loser_id],
            details={
                "survivor": str(survivor_id),
                "archived": str(loser_id),
                "similarity": float(row["similarity"]),
            },
        )

    return merge_count


# ---------------------------------------------------------------------------
# Phase 3: Conflict Resolution (LLM)
# ---------------------------------------------------------------------------


async def _phase_conflict_resolution(
    conn,
    user_uuid: uuid.UUID,
    bank_uuid: uuid.UUID,
) -> int:
    """Resolve ambiguous memory pairs using LLM classification.

    Targets pairs with cosine similarity 0.80-0.90 AND same memory_type.
    The LLM classifies each pair as UPDATE (newer wins) or KEEP_BOTH.

    Returns the number of conflicts resolved (archived).
    """
    rows = await conn.fetch(
        """
        SELECT
            a.id AS id_a, a.content AS content_a, a.created_at AS created_a,
            a.importance_score AS score_a, a.memory_type AS type_a,
            b.id AS id_b, b.content AS content_b, b.created_at AS created_b,
            b.importance_score AS score_b, b.memory_type AS type_b,
            1 - (a.embedding <=> b.embedding) AS similarity
        FROM memories a
        JOIN memories b
          ON a.user_id = b.user_id
         AND a.bank_id = b.bank_id
         AND a.id < b.id
        WHERE a.user_id = $1::uuid
          AND a.bank_id = $2::uuid
          AND a.archived_at IS NULL
          AND b.archived_at IS NULL
          AND a.embedding IS NOT NULL
          AND b.embedding IS NOT NULL
          AND a.memory_type = b.memory_type
          AND 1 - (a.embedding <=> b.embedding) > $3
          AND 1 - (a.embedding <=> b.embedding) <= $4
        ORDER BY similarity DESC
        LIMIT 100
        """,
        user_uuid,
        bank_uuid,
        _CONFLICT_SIMILARITY_LOW,
        _CONFLICT_SIMILARITY_HIGH,
    )

    if not rows:
        return 0

    client = get_openai_client()

    # Parallelize LLM calls with a semaphore to avoid overwhelming the API
    sem = asyncio.Semaphore(_LLM_CONCURRENCY)

    async def classify_one(row):
        async with sem:
            classification = await _classify_conflict(
                client,
                content_a=row["content_a"],
                content_b=row["content_b"],
                created_a=row["created_a"],
                created_b=row["created_b"],
            )
            return row, classification

    results = await asyncio.gather(*[classify_one(r) for r in rows])

    # Now apply the results sequentially (DB writes need ordered execution)
    resolved_count = 0
    for row, classification in results:
        if classification == "UPDATE":
            if row["created_a"] <= row["created_b"]:
                older_id, newer_id = row["id_a"], row["id_b"]
            else:
                older_id, newer_id = row["id_b"], row["id_a"]

            await conn.execute(
                """
                UPDATE memories
                SET archived_at = now(),
                    archived_reason = 'conflict_resolved',
                    superseded_by = $1
                WHERE id = $2 AND archived_at IS NULL
                """,
                newer_id,
                older_id,
            )
            resolved_count += 1

            await _log_action(
                conn,
                user_uuid,
                bank_uuid,
                action="resolve_conflict",
                memory_ids=[newer_id, older_id],
                details={
                    "classification": "UPDATE",
                    "kept": str(newer_id),
                    "archived": str(older_id),
                    "similarity": float(row["similarity"]),
                },
            )
        else:
            await _log_action(
                conn,
                user_uuid,
                bank_uuid,
                action="resolve_conflict",
                memory_ids=[row["id_a"], row["id_b"]],
                details={
                    "classification": "KEEP_BOTH",
                    "similarity": float(row["similarity"]),
                },
            )

    return resolved_count


async def _classify_conflict(
    client: AsyncOpenAI,
    content_a: str,
    content_b: str,
    created_a: datetime,
    created_b: datetime,
) -> str:
    """Ask the LLM whether two similar memories represent an update or are distinct.

    Returns 'UPDATE' or 'KEEP_BOTH'.
    """
    prompt = (
        "You are a memory deduplication classifier. Two memories from the same user "
        "are semantically similar. Decide if the newer one UPDATES/replaces the older "
        "one, or if they should BOTH be kept as distinct memories.\n\n"
        f"Memory A (created {created_a.isoformat()}):\n{content_a}\n\n"
        f"Memory B (created {created_b.isoformat()}):\n{content_b}\n\n"
        "Respond with exactly one word: UPDATE or KEEP_BOTH\n"
        "- UPDATE means the newer memory supersedes the older (e.g., a fact changed)\n"
        "- KEEP_BOTH means they are related but distinct memories worth preserving"
    )

    try:
        response = await client.chat.completions.create(
            model=_CLASSIFICATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0,
        )
        answer = response.choices[0].message.content.strip().upper()
        if answer in ("UPDATE", "KEEP_BOTH"):
            return answer
        # Default to KEEP_BOTH on unexpected output — conservative approach
        logger.warning("Unexpected LLM classification: %s — defaulting to KEEP_BOTH", answer)
        return "KEEP_BOTH"
    except Exception:
        logger.warning(
            "LLM conflict classification failed — defaulting to KEEP_BOTH",
            exc_info=True,
        )
        return "KEEP_BOTH"


# ---------------------------------------------------------------------------
# Phase 4: Entity Extraction (LLM)
# ---------------------------------------------------------------------------


async def _phase_entity_extraction(
    conn,
    user_uuid: uuid.UUID,
    bank_uuid: uuid.UUID,
) -> int:
    """Extract entities from memories that lack entity metadata.

    Batches memories in groups of 10 per LLM call. Upserts into
    memory_entities and updates memory metadata with entity references.

    Returns the number of entities extracted.
    """
    # Find memories without entity metadata
    rows = await conn.fetch(
        """
        SELECT id, content, memory_type
        FROM memories
        WHERE user_id = $1::uuid
          AND bank_id = $2::uuid
          AND archived_at IS NULL
          AND (
              metadata->>'entities' IS NULL
              OR metadata->>'entities' = '[]'
              OR metadata->>'entities' = ''
          )
        ORDER BY created_at DESC
        LIMIT 200
        """,
        user_uuid,
        bank_uuid,
    )

    if not rows:
        return 0

    client = get_openai_client()
    total_entities = 0

    # Process in batches
    for i in range(0, len(rows), _ENTITY_BATCH_SIZE):
        batch = rows[i : i + _ENTITY_BATCH_SIZE]
        entities_by_memory = await _extract_entities_batch(client, batch)

        for memory_row, entities in zip(batch, entities_by_memory, strict=True):
            if not entities:
                # Mark as processed even if no entities found (empty list)
                await conn.execute(
                    """
                    UPDATE memories
                    SET metadata = jsonb_set(
                        COALESCE(metadata, '{}'::jsonb),
                        '{entities}',
                        '[]'::jsonb
                    )
                    WHERE id = $1
                    """,
                    memory_row["id"],
                )
                continue

            memory_id = memory_row["id"]
            entity_names = []

            for entity in entities:
                entity_name = entity.get("name", "").strip()
                entity_type = entity.get("type", "topic").strip().lower()
                relationship = entity.get("relationship", "").strip()

                if not entity_name:
                    continue

                # Validate entity_type against schema constraint
                if entity_type not in ("person", "organization", "place", "project", "topic"):
                    entity_type = "topic"

                # Upsert entity — add memory reference and any new facts
                await conn.execute(
                    """
                    INSERT INTO memory_entities
                        (user_id, bank_id, entity_name, entity_type, memory_ids, facts)
                    VALUES ($1::uuid, $2::uuid, $3, $4, ARRAY[$5::uuid], $6::jsonb)
                    ON CONFLICT (user_id, bank_id, entity_name, entity_type)
                    DO UPDATE SET
                        memory_ids = array_append(
                            array_remove(memory_entities.memory_ids, $5::uuid),
                            $5::uuid
                        ),
                        facts = memory_entities.facts || $6::jsonb,
                        updated_at = now()
                    """,
                    user_uuid,
                    bank_uuid,
                    entity_name,
                    entity_type,
                    memory_id,
                    json.dumps([{"content": relationship, "memory_id": str(memory_id)}])
                    if relationship
                    else "[]",
                )

                entity_names.append({"name": entity_name, "type": entity_type})
                total_entities += 1

            # Update memory metadata with entity references
            await conn.execute(
                """
                UPDATE memories
                SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{entities}',
                    $1::jsonb
                )
                WHERE id = $2
                """,
                json.dumps(entity_names),
                memory_id,
            )

        # Log the batch
        batch_ids = [row["id"] for row in batch]
        await _log_action(
            conn,
            user_uuid,
            bank_uuid,
            action="extract_entity",
            memory_ids=batch_ids,
            details={"batch_size": len(batch), "entities_extracted": total_entities},
        )

    return total_entities


async def _extract_entities_batch(
    client: AsyncOpenAI,
    memories: list,
) -> list[list[dict]]:
    """Extract entities from a batch of memories using a single LLM call.

    Returns a list (one per memory) of entity lists.
    Each entity is {name, type, relationship}.
    """
    memories_text = ""
    for idx, row in enumerate(memories):
        memories_text += f"\n[Memory {idx + 1}] ({row['memory_type']}): {row['content']}\n"

    prompt = (
        "Extract named entities from each memory below. "
        "For each memory, return a JSON array of entities.\n"
        "Each entity should have:\n"
        '  - "name": the entity name\n'
        '  - "type": one of person, organization, place, project, topic\n'
        '  - "relationship": brief description of how this entity relates to the memory\n\n'
        "Return a JSON array of arrays (one inner array per memory, in order).\n"
        "If a memory has no entities, return an empty array for it.\n"
        "Return ONLY valid JSON, no markdown fences or explanation.\n"
        f"\nMemories:{memories_text}"
    )

    try:
        response = await client.chat.completions.create(
            model=_CLASSIFICATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)

        # The response might be {"entities": [[...]]} or just [[...]]
        if isinstance(parsed, dict):
            # Try common wrapper keys
            for key in ("entities", "results", "memories", "data"):
                if key in parsed:
                    parsed = parsed[key]
                    break
            else:
                # If it's a dict with integer-like keys, convert
                if all(k.isdigit() for k in parsed):
                    parsed = [parsed[k] for k in sorted(parsed, key=int)]
                else:
                    logger.warning("Unexpected entity extraction format: %s", list(parsed.keys()))
                    return [[] for _ in memories]

        if not isinstance(parsed, list):
            return [[] for _ in memories]

        # Ensure we have one result per memory
        while len(parsed) < len(memories):
            parsed.append([])

        return parsed[: len(memories)]

    except Exception:
        logger.warning("Entity extraction LLM call failed", exc_info=True)
        return [[] for _ in memories]


# ---------------------------------------------------------------------------
# Phase 5: Archive Stale Memories
# ---------------------------------------------------------------------------


async def _phase_archive_stale(
    conn,
    user_uuid: uuid.UUID,
    bank_uuid: uuid.UUID,
) -> int:
    """Archive memories with low importance, old age, and zero access.

    Criteria: importance_score < 0.1 AND age > 90 days AND access_count = 0.

    Returns the number of memories archived.
    """
    rows = await conn.fetch(
        """
        UPDATE memories
        SET archived_at = now(),
            archived_reason = 'low_importance_decay'
        WHERE user_id = $1::uuid
          AND bank_id = $2::uuid
          AND archived_at IS NULL
          AND importance_score < $3
          AND created_at < now() - make_interval(days => $4)
          AND COALESCE(access_count, 0) = 0
        RETURNING id
        """,
        user_uuid,
        bank_uuid,
        _ARCHIVE_SCORE_THRESHOLD,
        _ARCHIVE_AGE_DAYS,
    )

    archived_count = len(rows)

    if archived_count > 0:
        archived_ids = [row["id"] for row in rows]
        await _log_action(
            conn,
            user_uuid,
            bank_uuid,
            action="archive",
            memory_ids=archived_ids,
            details={"count": archived_count, "reason": "low_importance_decay"},
        )

    return archived_count


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


async def _log_action(
    conn,
    user_uuid: uuid.UUID,
    bank_uuid: uuid.UUID,
    action: str,
    memory_ids: list[uuid.UUID],
    details: dict[str, Any] | None = None,
) -> None:
    """Write an entry to the consolidation_log table."""
    await conn.execute(
        """
        INSERT INTO consolidation_log (user_id, bank_id, action, memory_ids, details)
        VALUES ($1::uuid, $2::uuid, $3, $4::uuid[], $5::jsonb)
        """,
        user_uuid,
        bank_uuid,
        action,
        memory_ids,
        json.dumps(details or {}),
    )


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def consolidate_user(user_id: str, bank_id: str) -> dict:
    """Run the full 5-phase consolidation pipeline for one user+bank.

    Returns a summary dict with counts of each action taken.
    """
    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError as err:
        return {"error": str(err)}

    pool = await get_pool()
    summary: dict[str, Any] = {
        "user_id": user_id,
        "bank_id": bank_id,
        "started_at": datetime.now(UTC).isoformat(),
        "scores_updated": 0,
        "duplicates_merged": 0,
        "conflicts_resolved": 0,
        "entities_extracted": 0,
        "stale_archived": 0,
        "error": None,
    }

    try:
        async with pool.acquire() as conn:
            # Phase 1: Importance Scoring (pure SQL)
            logger.info("Phase 1: Scoring memories for user=%s bank=%s", user_id, bank_id)
            summary["scores_updated"] = await _phase_importance_scoring(conn, user_uuid, bank_uuid)

            # Phase 2: Near-Duplicate Merge (SQL + embeddings)
            logger.info("Phase 2: Deduplicating for user=%s bank=%s", user_id, bank_id)
            summary["duplicates_merged"] = await _phase_duplicate_merge(conn, user_uuid, bank_uuid)

            # Phase 3: Conflict Resolution (LLM)
            logger.info("Phase 3: Resolving conflicts for user=%s bank=%s", user_id, bank_id)
            summary["conflicts_resolved"] = await _phase_conflict_resolution(
                conn,
                user_uuid,
                bank_uuid,
            )

            # Phase 4: Entity Extraction (LLM)
            logger.info("Phase 4: Extracting entities for user=%s bank=%s", user_id, bank_id)
            summary["entities_extracted"] = await _phase_entity_extraction(
                conn,
                user_uuid,
                bank_uuid,
            )

            # Phase 5: Archive Stale (pure SQL)
            logger.info("Phase 5: Archiving stale memories for user=%s bank=%s", user_id, bank_id)
            summary["stale_archived"] = await _phase_archive_stale(conn, user_uuid, bank_uuid)

    except Exception as exc:
        logger.error(
            "Consolidation failed for user=%s bank=%s: %s",
            user_id,
            bank_id,
            exc,
            exc_info=True,
        )
        summary["error"] = str(exc)

    summary["completed_at"] = datetime.now(UTC).isoformat()
    logger.info("Consolidation complete: %s", summary)
    return summary


async def consolidate_all_active_users() -> dict:
    """Run consolidation for all users with activity since their last consolidation.

    Queries for distinct user+bank pairs that have memories created or accessed
    after the user's last_consolidation_at timestamp (or ever, if never consolidated).

    Returns a summary dict with per-user results and aggregate counts.
    """
    pool = await get_pool()

    # Find all user+bank pairs with activity since last consolidation
    rows = await pool.fetch(
        """
        SELECT DISTINCT m.user_id, m.bank_id
        FROM memories m
        JOIN profiles p ON m.user_id = p.id
        WHERE m.archived_at IS NULL
          AND (
              p.last_consolidation_at IS NULL
              OR m.created_at > p.last_consolidation_at
              OR m.last_accessed_at > p.last_consolidation_at
          )
        """,
    )

    results: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "users_processed": 0,
        "total_scores_updated": 0,
        "total_duplicates_merged": 0,
        "total_conflicts_resolved": 0,
        "total_entities_extracted": 0,
        "total_stale_archived": 0,
        "errors": [],
        "user_results": [],
    }

    # Track which user_ids we've consolidated (for updating last_consolidation_at)
    consolidated_user_ids: set[uuid.UUID] = set()

    # Parallelize user consolidation with bounded concurrency
    sem = asyncio.Semaphore(_USER_CONCURRENCY)

    async def process_one(row):
        async with sem:
            user_id = str(row["user_id"])
            bank_id = str(row["bank_id"])
            return row, await consolidate_user(user_id, bank_id)

    user_results = await asyncio.gather(*[process_one(r) for r in rows], return_exceptions=True)

    for item in user_results:
        if isinstance(item, Exception):
            results["errors"].append({"error": str(item)})
            continue
        row, summary = item
        results["user_results"].append(summary)

        if summary.get("error"):
            results["errors"].append(
                {
                    "user_id": str(row["user_id"]),
                    "bank_id": str(row["bank_id"]),
                    "error": summary["error"],
                }
            )
        else:
            results["users_processed"] += 1
            results["total_scores_updated"] += summary["scores_updated"]
            results["total_duplicates_merged"] += summary["duplicates_merged"]
            results["total_conflicts_resolved"] += summary["conflicts_resolved"]
            results["total_entities_extracted"] += summary["entities_extracted"]
            results["total_stale_archived"] += summary["stale_archived"]
            consolidated_user_ids.add(row["user_id"])

    # Update last_consolidation_at for all successfully consolidated users
    if consolidated_user_ids:
        await pool.execute(
            """
            UPDATE profiles
            SET last_consolidation_at = now()
            WHERE id = ANY($1::uuid[])
            """,
            list(consolidated_user_ids),
        )

    results["completed_at"] = datetime.now(UTC).isoformat()
    logger.info(
        "Consolidation run complete: %d users, %d errors",
        results["users_processed"],
        len(results["errors"]),
    )
    return results
