from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files

from money_movement.risk_review.models import PolicyEvidence

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class PolicyChunk:
    evidence_id: str
    source: str
    section: str
    text: str
    term_counts: Counter[str]


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class PolicyRetriever:
    def __init__(self, chunks: tuple[PolicyChunk, ...]) -> None:
        if not chunks:
            raise ValueError("at least one policy chunk is required")
        self._chunks = chunks
        self._document_frequency: Counter[str] = Counter()
        for chunk in chunks:
            self._document_frequency.update(chunk.term_counts.keys())
        self._average_length = sum(sum(chunk.term_counts.values()) for chunk in chunks) / len(chunks)

    @classmethod
    def from_package(cls) -> PolicyRetriever:
        policy_root = files("money_movement.risk_review").joinpath("policies")
        chunks: list[PolicyChunk] = []
        for resource in sorted(policy_root.iterdir(), key=lambda item: item.name):
            if resource.name.endswith(".md"):
                with resource.open("r", encoding="utf-8") as handle:
                    text = handle.read()
                chunks.extend(_parse_policy_text(resource.name, text))
        return cls(tuple(chunks))

    def search(self, query: str, *, limit: int = 3) -> tuple[PolicyEvidence, ...]:
        terms = _tokens(query)
        if not terms or limit < 1:
            return ()
        total_documents = len(self._chunks)
        scored: list[tuple[float, PolicyChunk]] = []
        for chunk in self._chunks:
            length = sum(chunk.term_counts.values())
            score = 0.0
            for term in terms:
                frequency = chunk.term_counts[term]
                if frequency == 0:
                    continue
                document_frequency = self._document_frequency[term]
                inverse_document_frequency = math.log(
                    1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + 1.5 * (0.25 + 0.75 * length / self._average_length)
                score += inverse_document_frequency * frequency * 2.5 / denominator
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].evidence_id))
        return tuple(
            PolicyEvidence(
                evidence_id=chunk.evidence_id,
                source=chunk.source,
                section=chunk.section,
                excerpt=chunk.text[:320],
                score=round(score, 6),
            )
            for score, chunk in scored[:limit]
        )


def _parse_policy_text(filename: str, text: str) -> list[PolicyChunk]:
    chunks: list[PolicyChunk] = []
    heading = "Overview"
    lines: list[str] = []

    def add_chunk() -> None:
        body = " ".join(line.strip() for line in lines if line.strip()).strip()
        if not body:
            return
        slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        chunks.append(
            PolicyChunk(
                evidence_id=f"{filename.removesuffix('.md')}:{slug}",
                source=filename,
                section=heading,
                text=body,
                term_counts=Counter(_tokens(f"{heading} {body}")),
            )
        )

    for raw_line in text.splitlines():
        if raw_line.startswith("## "):
            add_chunk()
            heading = raw_line.removeprefix("## ").strip()
            lines = []
        elif not raw_line.startswith("# "):
            lines.append(raw_line)
    add_chunk()
    return chunks
