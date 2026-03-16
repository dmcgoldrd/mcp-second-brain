#!/usr/bin/env python3
"""Claude Code Stop hook -- extracts memories from conversation transcripts.

Reads the transcript, uses an LLM to identify memorable facts, and stores
them in MCP Brain via the create_memory MCP tool.

Install in Claude Code:
  Add to ~/.claude/hooks.json or project .claude/hooks.json:
  {
    "hooks": {
      "Stop": [{
        "type": "command",
        "command": "python3 /path/to/mcp-brain/hooks/extract_memories.py",
        "timeout": 15000
      }]
    }
  }

Environment:
  MCPBRAIN_URL   -- MCP Brain server URL (default: http://localhost:8080)
  MCPBRAIN_TOKEN -- Supabase JWT for authentication
  OPENAI_API_KEY -- For the extraction LLM (gpt-4o-mini)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCPBRAIN_URL = os.environ.get("MCPBRAIN_URL", "http://localhost:8080").rstrip("/")
MCPBRAIN_TOKEN = os.environ.get("MCPBRAIN_TOKEN", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
EXTRACTION_MODEL = os.environ.get("MCPBRAIN_EXTRACTION_MODEL", "gpt-4o-mini")
MAX_MESSAGE_PAIRS = int(os.environ.get("MCPBRAIN_MAX_PAIRS", "5"))

# MCP JSON-RPC constants (same as benchmarks/providers/mcpbrain.py)
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-03-26"

EXTRACTION_PROMPT = """\
Extract memorable facts from this conversation that should be stored in long-term memory.
Only extract facts that are:
- Personal information about the user (name, preferences, relationships, location)
- Decisions the user made
- Important project context or technical decisions
- Preferences or opinions the user expressed

Return a JSON array of objects, each with:
- "content": the fact to remember (concise, 1-2 sentences)
- "memory_type": one of observation, task, idea, reference, person_note, decision, preference
- "tags": relevant tags (1-3 tags)

If there are no memorable facts, return an empty array [].
Do NOT extract:
- Routine coding instructions
- Temporary debugging context
- Questions the user already got answers to
"""

# ---------------------------------------------------------------------------
# Logging -- all output to stderr (visible in Claude Code hook output)
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[mcp-brain-hook] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp-brain-hook")


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------


def read_transcript(transcript_path: str) -> list[dict]:
    """Read a Claude Code JSONL transcript and return message objects.

    Claude Code transcripts are JSONL files where each line is a JSON object
    with at minimum a "type" field. We care about "human" and "assistant" turns.
    """
    messages: list[dict] = []
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    messages.append(obj)
                except json.JSONDecodeError:
                    continue
    except (FileNotFoundError, PermissionError, OSError) as exc:
        logger.warning("Could not read transcript at %s: %s", transcript_path, exc)
    return messages


def extract_recent_pairs(messages: list[dict], max_pairs: int) -> str:
    """Extract the last N user+assistant message pairs as readable text.

    Walks the transcript in reverse, collecting pairs of user (human) and
    assistant messages. Returns them formatted as a conversation string.
    """
    # Normalize: extract role and text content from various transcript formats
    normalized: list[dict[str, str]] = []
    for msg in messages:
        role = msg.get("role", msg.get("type", ""))
        # Map common role names
        if role in ("human", "user"):
            role = "user"
        elif role in ("assistant",):
            role = "assistant"
        else:
            continue

        # Extract text content -- handle both string and list-of-blocks formats
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = "\n".join(text_parts)
        elif not isinstance(content, str):
            content = str(content)

        if content.strip():
            normalized.append({"role": role, "text": content.strip()})

    if not normalized:
        return ""

    # Walk backward to collect last N pairs
    pairs: list[tuple[str, str]] = []
    i = len(normalized) - 1
    while i >= 0 and len(pairs) < max_pairs:
        # Find assistant message
        if normalized[i]["role"] == "assistant":
            assistant_text = normalized[i]["text"]
            # Find preceding user message
            j = i - 1
            while j >= 0 and normalized[j]["role"] != "user":
                j -= 1
            if j >= 0:
                user_text = normalized[j]["text"]
                pairs.append((user_text, assistant_text))
                i = j - 1
            else:
                # No preceding user message found
                i -= 1
        else:
            i -= 1

    # Reverse to chronological order
    pairs.reverse()

    # Format as conversation text
    lines: list[str] = []
    for user_text, assistant_text in pairs:
        # Truncate very long messages to keep extraction costs low
        lines.append(f"User: {user_text[:2000]}")
        lines.append(f"Assistant: {assistant_text[:2000]}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------


def extract_facts(conversation_text: str) -> list[dict]:
    """Use gpt-4o-mini to extract memorable facts from conversation text.

    Returns a list of dicts with keys: content, memory_type, tags.
    Returns an empty list on any error.
    """
    if not conversation_text.strip():
        return []

    try:
        import openai
    except ImportError:
        logger.error("openai package not installed. Run: pip install openai")
        return []

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=EXTRACTION_MODEL,
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            temperature=0.0,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "[]"

        # Parse the response -- may be a raw array or wrapped in an object
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            facts = parsed
        elif isinstance(parsed, dict):
            # Handle {"facts": [...]} or {"memories": [...]} wrappers
            facts = parsed.get("facts") or parsed.get("memories") or parsed.get("results") or []
        else:
            facts = []

        # Validate each fact has required fields
        valid_types = {
            "observation",
            "task",
            "idea",
            "reference",
            "person_note",
            "decision",
            "preference",
        }
        validated: list[dict] = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            content = fact.get("content", "").strip()
            if not content:
                continue
            memory_type = fact.get("memory_type", "observation")
            if memory_type not in valid_types:
                memory_type = "observation"
            tags = fact.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            tags = [str(t) for t in tags[:3]]

            validated.append(
                {
                    "content": content,
                    "memory_type": memory_type,
                    "tags": tags,
                }
            )

        return validated

    except (openai.APIError, openai.APIConnectionError, openai.RateLimitError) as exc:
        logger.error("OpenAI API error during extraction: %s", exc)
        return []
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.error("Failed to parse extraction response: %s", exc)
        return []
    except Exception as exc:
        logger.error("Unexpected error during extraction: %s", exc)
        return []


# ---------------------------------------------------------------------------
# MCP Brain storage (via MCP JSON-RPC over HTTP)
# ---------------------------------------------------------------------------


class MCPBrainClient:
    """Lightweight synchronous client for calling MCP Brain tools.

    Uses the same MCP JSON-RPC protocol as benchmarks/providers/mcpbrain.py
    but synchronous (httpx sync client) since this runs as a standalone script.
    """

    def __init__(self, base_url: str, token: str) -> None:
        self.mcp_url = f"{base_url}/mcp"
        self.token = token
        self._session_id: str | None = None
        self._initialized = False
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                timeout=httpx.Timeout(15.0),
            )
        return self._client

    def _ensure_initialized(self) -> None:
        """Perform MCP initialize handshake if not already done."""
        if self._initialized:
            return

        client = self._get_client()

        # 1. Send initialize request
        init_payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "mcp-brain-hook",
                    "version": "0.1.0",
                },
            },
        }

        resp = client.post(self.mcp_url, json=init_payload)
        resp.raise_for_status()

        # Extract session ID
        self._session_id = resp.headers.get("mcp-session-id")
        if self._session_id:
            client.headers["mcp-session-id"] = self._session_id

        # 2. Send initialized notification
        notif_payload = {
            "jsonrpc": JSONRPC_VERSION,
            "method": "notifications/initialized",
        }
        client.post(self.mcp_url, json=notif_payload)

        self._initialized = True

    def _parse_response(self, text: str, content_type: str) -> dict:
        """Parse MCP response (SSE or plain JSON)."""
        if "event-stream" in content_type:
            for line in text.splitlines():
                if line.startswith("data: "):
                    try:
                        return json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
        return json.loads(text)

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool and return the parsed result."""
        self._ensure_initialized()
        client = self._get_client()

        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        resp = client.post(self.mcp_url, json=payload)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        body = self._parse_response(resp.text, content_type)

        if "error" in body:
            raise RuntimeError(f"MCP tool error: {body['error']}")

        # Extract text content from MCP result
        result = body.get("result", {})
        content_list = result.get("content", [])
        for item in content_list:
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (json.JSONDecodeError, KeyError):
                    return {"raw": item.get("text", "")}

        return result

    def close(self) -> None:
        """Clean up the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None


def store_memories(facts: list[dict]) -> int:
    """Store extracted facts in MCP Brain via the create_memory tool.

    Returns the number of successfully stored memories.
    """
    if not facts:
        return 0

    if not MCPBRAIN_TOKEN:
        logger.error("MCPBRAIN_TOKEN not set -- cannot store memories")
        return 0

    stored = 0
    client = MCPBrainClient(MCPBRAIN_URL, MCPBRAIN_TOKEN)

    try:
        for fact in facts:
            try:
                result = client.call_tool(
                    "create_memory",
                    {
                        "content": fact["content"],
                        "memory_type": fact["memory_type"],
                        "tags": fact.get("tags", []),
                        "source": "mcp",
                        "metadata": json.dumps(
                            {
                                "source_hook": "claude_code_stop",
                                "auto_extracted": True,
                            }
                        ),
                    },
                )

                status = result.get("status", "")
                if status == "created":
                    stored += 1
                    memory_id = result.get("memory_id", "?")
                    logger.info(
                        "Stored: %s (id=%s, type=%s)",
                        fact["content"][:80],
                        memory_id,
                        fact["memory_type"],
                    )

                    # Log conflicts if detected
                    conflicts = result.get("conflicts", [])
                    if conflicts:
                        logger.info(
                            "  -> %d potential conflict(s) detected",
                            len(conflicts),
                        )
                elif status == "error":
                    logger.warning(
                        "Server rejected memory: %s",
                        result.get("message", result.get("error", "unknown")),
                    )
                else:
                    # Unknown status but no error -- count as stored
                    stored += 1

            except Exception as exc:
                logger.error(
                    "Failed to store memory '%s': %s",
                    fact["content"][:60],
                    exc,
                )
    finally:
        client.close()

    return stored


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Hook entry point. Reads JSON from stdin, extracts and stores memories."""

    # Preflight: check required environment
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set -- skipping memory extraction")
        sys.exit(0)  # Exit 0 so we don't block Claude Code

    if not MCPBRAIN_TOKEN:
        logger.error("MCPBRAIN_TOKEN not set -- skipping memory extraction")
        sys.exit(0)

    # Read hook input from stdin (Claude Code passes JSON with transcript_path)
    try:
        raw_input = sys.stdin.read()
    except Exception:
        logger.error("Failed to read stdin")
        sys.exit(0)

    if not raw_input.strip():
        logger.info("No input received -- nothing to extract")
        sys.exit(0)

    try:
        hook_input = json.loads(raw_input)
    except json.JSONDecodeError:
        logger.error("Invalid JSON on stdin")
        sys.exit(0)

    transcript_path = hook_input.get("transcript_path", "")
    if not transcript_path:
        logger.info("No transcript_path in hook input -- nothing to extract")
        sys.exit(0)

    # 1. Read the transcript
    logger.info("Reading transcript: %s", transcript_path)
    messages = read_transcript(transcript_path)
    if not messages:
        logger.info("Empty transcript -- nothing to extract")
        sys.exit(0)

    # 2. Extract recent conversation pairs
    conversation_text = extract_recent_pairs(messages, MAX_MESSAGE_PAIRS)
    if not conversation_text.strip():
        logger.info("No user/assistant messages found in transcript")
        sys.exit(0)

    logger.info("Extracted %d chars from last %d pairs", len(conversation_text), MAX_MESSAGE_PAIRS)

    # 3. Use LLM to identify memorable facts
    logger.info("Extracting facts with %s...", EXTRACTION_MODEL)
    facts = extract_facts(conversation_text)

    if not facts:
        logger.info("No memorable facts found -- nothing to store")
        sys.exit(0)

    logger.info("Found %d memorable fact(s)", len(facts))

    # 4. Store in MCP Brain
    stored = store_memories(facts)
    logger.info("Stored %d/%d memories in MCP Brain", stored, len(facts))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never crash the hook -- log and exit cleanly
        logger.error("Unhandled error: %s", exc)
        sys.exit(0)
