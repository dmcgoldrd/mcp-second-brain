"""MCP Brain Benchmark Runner.

Downloads the LoCoMo dataset, ingests conversations into MCP Brain,
evaluates retrieval + answering quality, and generates a report.

Usage:
    cd benchmarks
    uv sync
    MCPBRAIN_TOKEN=... OPENAI_API_KEY=... uv run python run.py

Options:
    --dataset locomo          Dataset to use (default: locomo)
    --provider mcpbrain       Provider backend (default: mcpbrain)
    --judge gpt-4o-mini       LLM judge model (default: gpt-4o-mini)
    --answerer gpt-4o-mini    LLM answerer model (default: gpt-4o-mini)
    --limit N                 Limit total questions evaluated (0 = all)
    --conversations N         Limit conversations to process (0 = all)
    --search-limit N          Top-k memories to retrieve per query (default: 10)
    --seed N                  Random seed for reproducibility (default: 42)
    --output-dir DIR          Output directory for report (default: ./results/)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from evaluate import f1_token_overlap, llm_judge
from metrics import QuestionResult, compute_metrics
from providers.mcpbrain import MCPBrainProvider
from report import generate_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmarks.run")

# LoCoMo dataset source
LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
LOCOMO_PATH = Path(__file__).parent / "data" / "locomo10.json"

# Answer generation prompt
ANSWER_SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions "
    "based ONLY on the provided memory context.\n"
    "\n"
    "Rules:\n"
    "- Answer the question using ONLY the information "
    "in the provided memories.\n"
    "- If the memories don't contain enough information "
    "to answer, say \"I don't have enough information "
    'to answer this question."\n'
    "- Be concise and direct. Give the specific answer, "
    "not a paragraph.\n"
    "- If asked for a date, give the specific date.\n"
    "- If asked for a name, give the specific name.\n"
    "- Do not make up information not present in the memories."
)

ANSWER_USER_TEMPLATE = """Here are the relevant memories:

{context}

Question: {question}

Answer:"""


async def download_locomo() -> list[dict]:
    """Download the LoCoMo dataset if not already cached locally.

    Returns:
        List of conversation samples from the dataset.
    """
    if LOCOMO_PATH.exists():
        logger.info("Loading cached LoCoMo dataset from %s", LOCOMO_PATH)
        return json.loads(LOCOMO_PATH.read_text())

    logger.info("Downloading LoCoMo dataset from %s", LOCOMO_URL)
    LOCOMO_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(LOCOMO_URL)
        resp.raise_for_status()
        data = resp.json()

    LOCOMO_PATH.write_text(json.dumps(data, indent=2))
    logger.info("Saved LoCoMo dataset (%d conversations) to %s", len(data), LOCOMO_PATH)
    return data


def extract_conversation_turns(conversation: dict) -> list[dict]:
    """Extract all dialogue turns from a LoCoMo conversation object.

    Each turn becomes a memory with speaker, text, session info, and timestamp.

    Args:
        conversation: The 'conversation' field from a LoCoMo sample.

    Returns:
        List of dicts with keys: speaker, text, session, timestamp, dia_id.
    """
    turns = []
    session_idx = 1

    while True:
        session_key = f"session_{session_idx}"
        timestamp_key = f"session_{session_idx}_date_time"

        if session_key not in conversation:
            break

        session_turns = conversation[session_key]
        timestamp = conversation.get(timestamp_key, "")

        for turn in session_turns:
            speaker = turn.get("speaker", "")
            text = turn.get("text", "")
            dia_id = turn.get("dia_id", "")

            if text.strip():
                turns.append(
                    {
                        "speaker": speaker,
                        "text": text,
                        "session": session_idx,
                        "timestamp": timestamp,
                        "dia_id": dia_id,
                    }
                )

        session_idx += 1

    return turns


def format_memory_content(turn: dict) -> str:
    """Format a conversation turn into a memory-friendly string.

    Args:
        turn: A dialogue turn dict from extract_conversation_turns.

    Returns:
        Formatted string suitable for memory ingestion.
    """
    parts = []
    if turn.get("timestamp"):
        parts.append(f"[{turn['timestamp']}]")
    parts.append(f"{turn['speaker']}: {turn['text']}")
    return " ".join(parts)


async def generate_answer(
    question: str,
    memories: list[dict],
    client: AsyncOpenAI,
    model: str = "gpt-4o-mini",
) -> tuple[str, int]:
    """Generate an answer from retrieved memories using an LLM.

    Args:
        question: The evaluation question.
        memories: List of memory dicts from the provider search.
        client: OpenAI async client.
        model: Model to use for answer generation.

    Returns:
        Tuple of (answer_text, tokens_used).
    """
    if not memories:
        return "I don't have enough information to answer this question.", 0

    # Build context from retrieved memories
    context_parts = []
    for i, mem in enumerate(memories, 1):
        content = mem.get("content", mem.get("text", str(mem)))
        context_parts.append(f"{i}. {content}")
    context = "\n".join(context_parts)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": ANSWER_USER_TEMPLATE.format(context=context, question=question),
            },
        ],
        temperature=0.0,
        max_tokens=256,
    )

    answer = response.choices[0].message.content.strip()
    tokens = response.usage.total_tokens if response.usage else 0
    return answer, tokens


async def run_benchmark(args: argparse.Namespace) -> None:
    """Execute the full benchmark pipeline.

    1. Download LoCoMo dataset
    2. For each conversation: reset, ingest turns, evaluate questions
    3. Compute metrics and generate report
    """
    random.seed(args.seed)
    logger.info("Starting benchmark run (seed=%d)", args.seed)

    # Load dataset
    dataset = await download_locomo()
    logger.info("Dataset loaded: %d conversations", len(dataset))

    # Limit conversations if requested
    conversations = dataset
    if args.conversations > 0:
        conversations = conversations[: args.conversations]
        logger.info("Limited to %d conversations", len(conversations))

    # Initialize provider
    provider = MCPBrainProvider()
    openai_client = AsyncOpenAI()

    all_results: list[QuestionResult] = []
    questions_remaining = args.limit if args.limit > 0 else float("inf")
    total_questions_seen = 0

    try:
        for conv_idx, sample in enumerate(conversations):
            if questions_remaining <= 0:
                break

            sample_id = sample.get("sample_id", f"conv-{conv_idx}")
            conversation = sample.get("conversation", {})
            qa_list = sample.get("qa", [])

            if not qa_list:
                logger.info("Skipping conversation %s (no QA pairs)", sample_id)
                continue

            logger.info(
                "Processing conversation %d/%d: %s (%d questions)",
                conv_idx + 1,
                len(conversations),
                sample_id,
                len(qa_list),
            )

            # 1. Reset memories
            logger.info("  Resetting memories...")
            await provider.reset(user_id=sample_id)

            # 2. Ingest conversation turns
            turns = extract_conversation_turns(conversation)
            logger.info("  Ingesting %d turns...", len(turns))

            for turn_idx, turn in enumerate(turns):
                content = format_memory_content(turn)
                await provider.add_memory(
                    content=content,
                    user_id=sample_id,
                    session_id=f"session-{turn['session']}",
                )
                if (turn_idx + 1) % 50 == 0:
                    logger.info("    Ingested %d/%d turns", turn_idx + 1, len(turns))

            logger.info("  Ingestion complete. Evaluating %d questions...", len(qa_list))

            # 3. Evaluate each question
            for q_idx, qa in enumerate(qa_list):
                if questions_remaining <= 0:
                    break

                question = qa.get("question", "")
                gold_answer = qa.get("answer", "")
                category = qa.get("category", 0)
                question_id = f"{sample_id}-q{q_idx}"

                # Search
                search_start = time.perf_counter()
                memories = await provider.search(
                    query=question,
                    user_id=sample_id,
                    limit=args.search_limit,
                )
                search_ms = (time.perf_counter() - search_start) * 1000

                # Generate answer
                answer_start = time.perf_counter()
                predicted_answer, tokens_used = await generate_answer(
                    question=question,
                    memories=memories,
                    client=openai_client,
                    model=args.answerer,
                )
                answer_ms = (time.perf_counter() - answer_start) * 1000

                # Evaluate with LLM judge
                judge_score = await llm_judge(
                    question=question,
                    gold_answer=gold_answer,
                    predicted_answer=predicted_answer,
                    model=args.judge,
                    client=openai_client,
                )

                # Compute F1
                f1 = f1_token_overlap(gold_answer, predicted_answer)

                result = QuestionResult(
                    question_id=question_id,
                    question=question,
                    gold_answer=gold_answer,
                    predicted_answer=predicted_answer,
                    category=category,
                    llm_judge_score=judge_score,
                    f1_score=f1,
                    search_latency_ms=search_ms,
                    answer_latency_ms=search_ms + answer_ms,
                    memories_retrieved=len(memories),
                    tokens_used=tokens_used,
                    conversation_id=sample_id,
                )
                all_results.append(result)

                total_questions_seen += 1
                questions_remaining -= 1

                if total_questions_seen % 25 == 0:
                    running_accuracy = sum(r.llm_judge_score for r in all_results) / len(
                        all_results
                    )
                    logger.info(
                        "  Progress: %d questions, running accuracy: %.1f%%",
                        total_questions_seen,
                        running_accuracy * 100,
                    )

            logger.info(
                "  Conversation %s complete (%d questions evaluated)",
                sample_id,
                len([r for r in all_results if r.conversation_id == sample_id]),
            )

    finally:
        await provider.close()

    if not all_results:
        logger.error("No results to report. Check dataset and provider connection.")
        sys.exit(1)

    # 4. Compute metrics
    logger.info("Computing metrics over %d questions...", len(all_results))
    bench_metrics = compute_metrics(all_results)

    # 5. Generate report
    output_dir = Path(args.output_dir)
    run_params = {
        "dataset": args.dataset,
        "provider": args.provider,
        "judge_model": args.judge,
        "answerer_model": args.answerer,
        "search_limit": args.search_limit,
        "seed": args.seed,
        "limit": args.limit,
        "conversations": args.conversations,
        "total_questions": len(all_results),
        "total_conversations": bench_metrics.total_conversations,
    }

    generate_report(bench_metrics, run_params, output_dir)

    # Also save raw results for debugging
    raw_path = output_dir / "raw_results.json"
    raw_path.write_text(
        json.dumps(
            [
                {
                    "question_id": r.question_id,
                    "question": r.question,
                    "gold_answer": r.gold_answer,
                    "predicted_answer": r.predicted_answer,
                    "category": r.category,
                    "llm_judge_score": r.llm_judge_score,
                    "f1_score": r.f1_score,
                    "search_latency_ms": r.search_latency_ms,
                    "answer_latency_ms": r.answer_latency_ms,
                    "memories_retrieved": r.memories_retrieved,
                    "tokens_used": r.tokens_used,
                    "conversation_id": r.conversation_id,
                }
                for r in all_results
            ],
            indent=2,
        )
    )

    # Print summary
    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    print("=" * 60)
    print(f"Questions evaluated: {bench_metrics.total_questions}")
    print(f"LLM-as-Judge accuracy: {bench_metrics.llm_judge_accuracy * 100:.1f}%")
    print(f"Mean F1: {bench_metrics.mean_f1:.3f}")
    print(f"Search latency p95: {bench_metrics.search_latency_p95_ms:.0f}ms")
    print(f"\nReport saved to: {output_dir / 'report.md'}")
    print(f"Raw results saved to: {raw_path}")
    print(f"JSON metrics saved to: {output_dir / 'results.json'}")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MCP Brain Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dataset",
        default="locomo",
        choices=["locomo"],
        help="Benchmark dataset (default: locomo)",
    )
    parser.add_argument(
        "--provider",
        default="mcpbrain",
        choices=["mcpbrain"],
        help="Memory provider (default: mcpbrain)",
    )
    parser.add_argument(
        "--judge",
        default="gpt-4o-mini",
        help="LLM judge model (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--answerer",
        default="gpt-4o-mini",
        help="LLM answerer model (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit total questions (0 = all, default: 0)",
    )
    parser.add_argument(
        "--conversations",
        type=int,
        default=0,
        help="Limit conversations to process (0 = all, default: 0)",
    )
    parser.add_argument(
        "--search-limit",
        type=int,
        default=10,
        help="Top-k memories per search query (default: 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--output-dir",
        default="./results",
        help="Output directory for report files (default: ./results)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_benchmark(args))
