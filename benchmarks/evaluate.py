"""LLM-as-judge evaluation for benchmark answers.

Uses an OpenAI-compatible model (default: gpt-4o-mini) to judge whether a
predicted answer is correct given the question and gold-standard answer.
Also computes cheap token-overlap F1 as a secondary metric.
"""

from __future__ import annotations

import logging
import os
import re

from openai import AsyncOpenAI

logger = logging.getLogger("benchmarks.evaluate")

JUDGE_SYSTEM_PROMPT = """You are an impartial judge evaluating factual correctness of answers.

Given a question, the ground-truth answer, and a predicted answer, determine if the predicted
answer is CORRECT or INCORRECT.

Rules:
- The predicted answer is CORRECT if it conveys the same essential information as the ground truth.
- Minor wording differences, rephrasing, or additional context are
  acceptable if the core fact matches.
- Partial answers that capture the key fact are CORRECT.
- If the ground truth is a date, the predicted answer must match
  the date (exact or equivalent format).
- If the ground truth is "unanswerable" or indicates the question cannot be answered, the predicted
  answer is CORRECT only if it also indicates it cannot be answered.
- Do not penalize for extra correct information beyond what was asked.

Respond with EXACTLY one word: CORRECT or INCORRECT"""

JUDGE_USER_TEMPLATE = """Question: {question}

Ground Truth Answer: {gold_answer}

Predicted Answer: {predicted_answer}

Verdict:"""


async def llm_judge(
    question: str,
    gold_answer: str,
    predicted_answer: str,
    model: str = "gpt-4o-mini",
    client: AsyncOpenAI | None = None,
) -> int:
    """Use an LLM to judge answer correctness.

    Args:
        question: The benchmark question.
        gold_answer: The ground-truth answer.
        predicted_answer: The model's predicted answer.
        model: OpenAI model to use as judge.
        client: Optional pre-configured OpenAI client.

    Returns:
        1 if correct, 0 if incorrect.
    """
    if client is None:
        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": JUDGE_USER_TEMPLATE.format(
                        question=question,
                        gold_answer=gold_answer,
                        predicted_answer=predicted_answer,
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=5,
        )

        verdict = response.choices[0].message.content.strip().upper()
        return 1 if "CORRECT" in verdict and "INCORRECT" not in verdict else 0

    except Exception:
        logger.exception("LLM judge call failed for question: %s", question[:80])
        return 0


def f1_token_overlap(gold: str, predicted: str) -> float:
    """Compute token-level F1 overlap between gold and predicted answers.

    A cheap, deterministic metric that doesn't require API calls.
    Tokenizes by splitting on whitespace and punctuation.

    Args:
        gold: Ground-truth answer string.
        predicted: Predicted answer string.

    Returns:
        F1 score between 0.0 and 1.0.
    """
    gold_tokens = _tokenize(gold)
    pred_tokens = _tokenize(predicted)

    if not gold_tokens or not pred_tokens:
        return 1.0 if gold_tokens == pred_tokens else 0.0

    gold_set = set(gold_tokens)
    pred_set = set(pred_tokens)

    common = gold_set & pred_set
    if not common:
        return 0.0

    precision = len(common) / len(pred_set)
    recall = len(common) / len(gold_set)

    return 2 * precision * recall / (precision + recall)


def _tokenize(text: str) -> list[str]:
    """Lowercase and split on non-alphanumeric characters."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]
