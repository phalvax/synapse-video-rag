"""L1 Structuration : transcript → fiches REX (une par problème technique réellement traité).

Même politique anti-hallucination que l'agent (CLAUDE.md, section 7) : JSON contraint,
`evidence_quote` vérifiée mot pour mot dans la transcription, sinon la fiche est rejetée.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from kb.adapters.base import LLM
from kb.agent.guardrails import parse_output, snap_quote, verify_quote
from kb.index.chunking import fmt_ts
from kb.schemas import FicheREX, Segment, Video
from kb.structure.prompts import FICHES_SCHEMA, SYSTEM, USER_TEMPLATE


class _LlmFiche(BaseModel):
    problem: str
    solution: str | None = None
    technologies: list[str] = Field(default_factory=list)
    client: str | None = None
    author: str | None = None
    start_s: float = 0.0
    end_s: float = 0.0
    evidence_quote: str


class _LlmFiches(BaseModel):
    fiches: list[_LlmFiche] = Field(default_factory=list)


def format_transcript(segments: list[Segment]) -> str:
    return "\n".join(f"[{fmt_ts(s.start_s)}] {s.text}" for s in segments)


def extract_fiches(video: Video, segments: list[Segment], llm: LLM) -> list[FicheREX]:
    """Appelle le LLM, valide le JSON (une nouvelle tentative), vérifie chaque preuve."""
    if not segments:
        return []
    transcript_text = " ".join(s.text for s in segments)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER_TEMPLATE.format(
            title=video.title, transcript=format_transcript(segments))},
    ]
    draft = _LlmFiches()
    for attempt in (1, 2):
        raw = llm.complete(messages, json_schema=FICHES_SCHEMA, temperature=0)
        try:
            draft = parse_output(raw, _LlmFiches)
            break
        except ValueError:
            if attempt == 2:
                return []
            messages = messages + [
                {"role": "assistant", "content": raw[:2000]},
                {"role": "user", "content": "Ta réponse n'était pas du JSON valide au format "
                                            "demandé. Renvoie UNIQUEMENT le JSON."},
            ]

    fiches: list[FicheREX] = []
    for i, f in enumerate(draft.fiches, start=1):
        quote = snap_quote(f.evidence_quote, transcript_text) or (
            f.evidence_quote if verify_quote(f.evidence_quote, transcript_text) else None
        )
        if quote is None:
            continue  # sans preuve vérifiable, la fiche n'est pas retenue
        start_s = min(max(f.start_s, 0.0), video.duration_s)
        end_s = min(max(f.end_s, start_s), video.duration_s or f.end_s)
        fiches.append(FicheREX(
            fiche_id=f"{video.video_id}__{i:02d}",
            video_id=video.video_id,
            problem=f.problem,
            solution=f.solution,
            technologies=f.technologies,
            client=f.client,
            author=f.author,
            start_s=start_s,
            end_s=end_s,
            evidence_quote=quote,
        ))
    return fiches
