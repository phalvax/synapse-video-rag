"""Contrat de données commun (CLAUDE.md, section 6).

Toute l'équipe produit et consomme ces objets : on ne change un champ qu'après
accord en PR, sinon l'ingestion, l'index, l'agent et le front ne se parlent plus.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, model_validator


class Video(BaseModel):
    video_id: str
    title: str
    source_uri: str
    duration_s: float = Field(ge=0)
    date: dt.date | None = None
    author: str | None = None
    client: str | None = None
    mission: str | None = None
    language: str | None = None
    # Formulaire d'import (optionnels, rétrocompatibles) : contexte saisi par l'humain.
    description: str | None = None
    contact: str | None = None  # qui contacter à propos de cet enregistrement
    sha256: str | None = None  # empreinte du fichier : un doublon exact n'est pas retraité
    # « video », « audio », « document » (PDF…), « image » ; None = ancien média audio/vidéo.
    kind: str | None = None


class Segment(BaseModel):
    """Une phrase (ou un tour de parole) horodatée issue de la transcription."""

    video_id: str
    seg_id: int = Field(ge=0)
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    text: str
    speaker: str | None = None
    avg_logprob: float | None = None
    # Documents : numéro de page (1…). La position `start_s` vaut alors page + rang/1000, ce qui
    # garde un axe ordonné commun aux médias et aux documents (chunks, moments, filtres).
    page: int | None = None
    # None = parole transcrite ou texte du document ; « ocr » = texte lu dans une image ;
    # « visual » = description GÉNÉRÉE d'une image (à vérifier sur l'image, pas une preuve).
    modality: str | None = None

    @model_validator(mode="after")
    def _check_times(self) -> Segment:
        if self.end_s < self.start_s:
            raise ValueError("end_s doit être >= start_s")
        return self


class Chunk(BaseModel):
    """Une « page photocopiée » (~2-3 min) indexée pour la recherche."""

    chunk_id: str
    video_id: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    text: str
    context_header: str = ""
    client: str | None = None
    date: dt.date | None = None
    page: int | None = None  # documents : la page du chunk (un chunk ne déborde jamais d'une page)
    modality: str | None = None  # voir Segment.modality (un chunk ne mélange jamais deux natures)

    def text_for_embedding(self) -> str:
        return f"{self.context_header}\n{self.text}".strip()


class FicheREX(BaseModel):
    """Fiche retour d'expérience extraite par le LLM (champs vides si l'info est absente)."""

    fiche_id: str
    video_id: str
    problem: str
    solution: str | None = None
    technologies: list[str] = Field(default_factory=list)
    client: str | None = None
    author: str | None = None
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    evidence_quote: str


class Person(BaseModel):
    name: str
    role: str | None = None
    contact: str | None = None
    still_employed: bool | None = None


class Citation(BaseModel):
    chunk_id: str
    video_id: str
    start_s: float = Field(ge=0)
    quote: str
    verified: bool = False  # rempli par le code (guardrails), jamais par le LLM
    page: int | None = None  # documents : la page à ouvrir (au lieu d'une seconde)
    modality: str | None = None  # « ocr » : texte lu dans l'image ; « visual » : description IA


class Answer(BaseModel):
    """Sortie de l'agent : une réponse prouvée, ou une abstention explicite."""

    answer: str | None = None
    not_found: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    citations: list[Citation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> Answer:
        if self.not_found and self.citations:
            raise ValueError("Une abstention (not_found) ne doit pas contenir de citations.")
        if not self.not_found and not self.answer:
            raise ValueError("Une réponse doit avoir un texte, sinon not_found=True.")
        return self
