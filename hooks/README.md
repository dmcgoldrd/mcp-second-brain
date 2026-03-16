# MCP Brain Auto-Extraction Hooks

## Claude Code (Stop Hook)

Automatically extracts memorable facts from your conversations and stores
them in MCP Brain.

### How It Works

When a Claude Code conversation ends (Stop hook), the script:

1. Reads the conversation transcript from the path Claude Code provides via stdin
2. Extracts the last 5 user+assistant message pairs (configurable)
3. Sends them to gpt-4o-mini to identify memorable facts
4. Stores each fact in MCP Brain via the `create_memory` MCP tool

### Install

Add to your Claude Code hooks config (`~/.claude/hooks.json` or project `.claude/hooks.json`):

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "python3 /path/to/mcp-brain/hooks/extract_memories.py",
        "timeout": 15000
      }
    ]
  }
}
```

Replace `/path/to/mcp-brain` with the actual path to your MCP Brain checkout.

### Dependencies

The hook script is standalone (no imports from `src/`). It requires:

```
pip install openai httpx
```

Or if you already have the MCP Brain virtualenv activated, these are already installed.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCPBRAIN_URL` | No | `http://localhost:8080` | MCP Brain server URL |
| `MCPBRAIN_TOKEN` | **Yes** | -- | Supabase JWT for authentication |
| `OPENAI_API_KEY` | **Yes** | -- | For the extraction LLM |
| `MCPBRAIN_EXTRACTION_MODEL` | No | `gpt-4o-mini` | LLM model for extraction |
| `MCPBRAIN_MAX_PAIRS` | No | `5` | Number of message pairs to extract from |

### Cost

Each extraction uses a single gpt-4o-mini call on ~2-4K tokens of conversation.
At current pricing, this costs approximately **$0.001 per conversation** (~$0.03/month
at 30 conversations/day).

### What It Extracts

- Personal facts (name, location, relationships)
- Preferences and opinions
- Decisions made during the conversation
- Project context and technical decisions
- Important reference information

### What It Skips

- Routine coding instructions ("fix this bug", "add a test")
- Temporary debugging context
- Questions the user already got answers to
- Tool outputs and code snippets

### Debugging

The hook logs to stderr, which is visible in Claude Code's hook output.
To test manually:

```bash
echo '{"transcript_path": "/path/to/transcript.jsonl"}' | \
  MCPBRAIN_TOKEN=your-jwt OPENAI_API_KEY=your-key \
  python3 hooks/extract_memories.py
```

### Architecture

```
Claude Code Stop Hook
        |
        | stdin: {"transcript_path": "..."}
        v
extract_memories.py
        |
        |-- 1. Read JSONL transcript
        |-- 2. Extract last 5 message pairs
        |-- 3. gpt-4o-mini: identify facts
        |-- 4. MCP JSON-RPC: create_memory (per fact)
        v
   MCP Brain Server
```

The script communicates with MCP Brain using the same MCP JSON-RPC protocol
that any MCP client uses (initialize handshake, then `tools/call`). This means
it works with the production server without any special API routes.

---

## Other Platforms (System Prompt)

For platforms without hook support (Cursor, VS Code Copilot, ChatGPT, etc.),
see `system_prompt.md` for a system prompt snippet that instructs the AI to
call memory tools inline during conversation.
