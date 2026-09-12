"""
Lightweight, dependency-free evaluation metrics for RAG answers.

These are deliberately simple, deterministic, and fast (no extra LLM calls
required) so they can run on every request without adding noticeable
latency or cost, while still giving a measurable signal about answer
quality. An optional LLM-judge scorer is also provided for offline/batch
evaluation where an extra model call is acceptable.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower())


_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "be", "been", "this", "that", "it", "as", "by",
    "with", "at", "from", "your", "you", "if", "not", "no", "do", "does",
    "will", "can", "should", "must", "may", "has", "have", "had",
}


def _content_words(text: str) -> set:
    return {w for w in _tokenize(text) if w not in _STOPWORDS and len(w) > 2}


@dataclass
class RagEvalResult:
    context_relevance: float          # 0-1: retrieved-chunk similarity to query
    groundedness: float                # 0-1: fraction of answer content words backed by context
    answer_relevance: float            # 0-1: overlap between answer and query terms
    coverage: float                    # 0-1: fraction of query terms addressed by retrieved context
    top_score: float                   # raw top retrieval similarity score
    num_sources: int
    flags: List[str] = field(default_factory=list)

    def overall(self) -> float:
        # Weighted blend; groundedness (hallucination proxy) weighted highest.
        return round(
            0.45 * self.groundedness
            + 0.25 * self.context_relevance
            + 0.2 * self.answer_relevance
            + 0.1 * self.coverage,
            3,
        )

    def as_dict(self) -> Dict:
        return {
            "context_relevance": round(self.context_relevance, 3),
            "groundedness": round(self.groundedness, 3),
            "answer_relevance": round(self.answer_relevance, 3),
            "coverage": round(self.coverage, 3),
            "top_retrieval_score": round(self.top_score, 3),
            "num_sources": self.num_sources,
            "overall_score": self.overall(),
            "flags": self.flags,
        }


def evaluate_rag_answer(
    query: str,
    answer: str,
    retrieved: Sequence[tuple],  # list of (chunk_dict, score)
    *,
    low_confidence_threshold: float = 0.35,
) -> RagEvalResult:
    """
    Compute measurable RAG quality metrics without an extra model call.

    - context_relevance: mean similarity score of retrieved chunks (already
      computed by the retriever), a direct proxy for "did we find the right
      material".
    - groundedness: fraction of the answer's non-trivial content words that
      also appear somewhere in the retrieved context. Low groundedness is a
      strong hallucination signal (the model said things not present in the
      supplied policy text).
    - answer_relevance: fraction of the query's content words that reappear
      in the answer, a proxy for "did we actually address the question".
    - coverage: fraction of the query's content words that appear in the
      *retrieved context* (independent of what the LLM did with it) -
      flags cases where retrieval itself missed the topic.
    """
    flags: List[str] = []
    scores = [s for _, s in retrieved]
    top_score = max(scores) if scores else 0.0
    context_relevance = sum(scores) / len(scores) if scores else 0.0

    context_text = " ".join(c.get("text", "") for c, _ in retrieved)
    context_words = _content_words(context_text)
    answer_words = _content_words(answer)
    query_words = _content_words(query)

    if answer_words:
        grounded_hits = answer_words & context_words
        groundedness = len(grounded_hits) / len(answer_words)
    else:
        groundedness = 0.0

    if query_words:
        answer_relevance = len(query_words & answer_words) / len(query_words)
        coverage = len(query_words & context_words) / len(query_words)
    else:
        answer_relevance = 0.0
        coverage = 0.0

    if not retrieved:
        flags.append("no_context_retrieved")
    if top_score < low_confidence_threshold:
        flags.append("low_retrieval_confidence")
    if groundedness < 0.3 and answer_words:
        flags.append("possible_hallucination")
    if coverage < 0.25 and query_words:
        flags.append("retrieval_may_have_missed_topic")

    return RagEvalResult(
        context_relevance=context_relevance,
        groundedness=groundedness,
        answer_relevance=answer_relevance,
        coverage=coverage,
        top_score=top_score,
        num_sources=len(retrieved),
        flags=flags,
    )


# ---------------------------------------------------------------------------
# Router confidence
# ---------------------------------------------------------------------------
@dataclass
class RouteDecision:
    agent: str
    confidence: float
    method: str            # "keyword" | "llm" | "default"
    matched_terms: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "agent": self.agent,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "matched_terms": self.matched_terms,
        }


# ---------------------------------------------------------------------------
# Offline / batch evaluation harness
# ---------------------------------------------------------------------------
@dataclass
class EvalCase:
    query: str
    expected_agent: Optional[str] = None
    must_contain: Optional[List[str]] = None  # substrings the answer should mention


def score_routing_accuracy(cases: Sequence[EvalCase], decisions: Sequence[str]) -> Dict:
    """Simple accuracy metric for offline router regression testing."""
    total = len(cases)
    correct = sum(
        1 for c, d in zip(cases, decisions)
        if c.expected_agent is None or c.expected_agent == d
    )
    return {"n": total, "correct": correct, "accuracy": round(correct / total, 3) if total else 0.0}
