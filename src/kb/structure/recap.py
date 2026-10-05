"""L3 « Zoom » : point de situation d'une mission (fenêtre → réunion → mission).

Même politique que l'agent (CLAUDE.md, section 7) :
- chaque point porte une citation RECALÉE sur le transcript (`snap_quote`), sinon il est
  écarté ; sa seconde vient du segment où la citation commence ;
- aux étages réunion et mission, le LLM ne choisit que des IDENTIFIANTS de points prouvés ;
  le code y rattache la preuve (un identifiant inventé est ignoré) ;
- les textes de synthèse (`summary`, `status`) sont générés : le front les étiquette comme
  tels, seules les citations sont du transcript.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from kb.adapters.base import LLM
from kb.agent.guardrails import normalize, parse_output, snap_quote
from kb.index.chunking import estimate_tokens, fmt_ts
from kb.schemas import Segment, Video
from kb.structure.recap_prompts import (
    KINDS,
    MISSION_SCHEMA,
    MISSION_SYSTEM,
    MISSION_USER,
    VIDEO_SCHEMA,
    VIDEO_SYSTEM,
    VIDEO_USER,
    WINDOW_SCHEMA,
    WINDOW_SYSTEM,
    WINDOW_USER,
)

WINDOW_TOKENS = 1200  # ~6 min de réunion : tient largement dans le contexte d'un petit LLM
MAX_KEY_POINTS = 8


# --- Sorties (servies telles quelles par l'API) ---------------------------------------------


class Evidence(BaseModel):
    video_id: str
    start_s: float
    quote: str  # extrait EXACT du transcript
    page: int | None = None  # documents : la page de l'extrait


class RecapPoint(BaseModel):
    kind: str
    text: str  # formulé par le LLM
    evidence: Evidence


class WindowRecap(BaseModel):
    start_s: float
    end_s: float
    summary: str
    points: list[RecapPoint] = Field(default_factory=list)


class VideoRecap(BaseModel):
    video_id: str
    title: str
    subject: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    key_points: list[RecapPoint] = Field(default_factory=list)
    windows: list[WindowRecap] = Field(default_factory=list)
    dropped_points: int = 0  # points dont la citation n'a pas été retrouvée dans le transcript


class MissionRecap(BaseModel):
    mission: str
    videos: list[VideoRecap]  # de la plus ancienne à la plus récente
    subject: str
    status: str
    decisions: list[RecapPoint] = Field(default_factory=list)
    open_issues: list[RecapPoint] = Field(default_factory=list)
    next_steps: list[RecapPoint] = Field(default_factory=list)
    model: str = ""
    generated_at: str = ""


# --- Sorties brutes du LLM -------------------------------------------------------------------


class _LlmPoint(BaseModel):
    kind: str = "info"
    text: str
    quote: str


class _LlmWindow(BaseModel):
    summary: str = ""
    points: list[_LlmPoint] = Field(default_factory=list)


class _LlmVideo(BaseModel):
    subject: str = ""
    summary: str = ""
    participants: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)


class _LlmMission(BaseModel):
    subject: str = ""
    status: str = ""
    decisions: list[str] = Field(default_factory=list)
    open_issues: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


# --- Fenêtres et preuves ---------------------------------------------------------------------


@dataclass
class Window:
    segments: list[Segment]

    @property
    def start_s(self) -> float:
        return self.segments[0].start_s

    @property
    def end_s(self) -> float:
        return self.segments[-1].end_s

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)


def make_windows(segments: list[Segment], max_tokens: int = WINDOW_TOKENS) -> list[Window]:
    """Segments consécutifs regroupés en fenêtres d'environ `max_tokens` (sans chevauchement)."""
    windows, current, size = [], [], 0
    for seg in segments:
        n = estimate_tokens(seg.text)
        if current and size + n > max_tokens:
            windows.append(Window(current))
            current, size = [], 0
        current.append(seg)
        size += n
    if current:
        windows.append(Window(current))
    return windows


def locate(quote: str, window: Window) -> float:
    """Seconde du segment où commence `quote` (déjà recalée sur le texte de la fenêtre)."""
    target = normalize(quote)
    text = ""
    starts = []
    for seg in window.segments:
        starts.append((len(text), seg.start_s))
        text += normalize(seg.text) + " "
    pos = text.find(target[:40])
    if pos < 0:
        return window.start_s
    for char_start, start_s in reversed(starts):
        if char_start <= pos:
            return start_s
    return window.start_s


def prove(points: list[_LlmPoint], window: Window, video_id: str) -> tuple[list[RecapPoint], int]:
    """Garde les points dont la citation est retrouvée dans la fenêtre (recalée), sinon écarte."""
    kept, dropped = [], 0
    for p in points:
        quote = snap_quote(p.quote, window.text)
        if quote is not None and not numbers_backed(p.text, quote):
            quote = number_evidence(p.text, window)  # la preuve du chiffre, pas une autre phrase
        if quote is None or not p.text.strip():
            dropped += 1
            continue
        kind = p.kind if p.kind in KINDS else "info"
        start = locate(quote, window)
        page = next((s.page for s in window.segments if s.start_s == start), None)
        kept.append(RecapPoint(kind=kind, text=p.text.strip(), evidence=Evidence(
            video_id=video_id, start_s=start, quote=quote, page=page)))
    return kept, dropped


# Un nombre collé à des lettres (ES2002, es2004d, mp3) est un identifiant, pas un chiffre affirmé.
_NUM = re.compile(r"(?<![A-Za-z\d])\d+(?:[.,]\d+)?(?![A-Za-z\d])")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def numbers(text: str) -> set[str]:
    """Nombres d'un texte, décimales comprises (« 2,5 » et « 2.5 » sont le même nombre)."""
    return {n.replace(",", ".") for n in _NUM.findall(text or "")}


def numbers_backed(text: str, quote: str) -> bool:
    """Chaque nombre du point figure dans sa citation (vu le 25/09 : « 2,5 cm » appuyé par
    « So we have it within cost anyway », alors que « We'll say 2.5 » est dit à 13:37)."""
    return numbers(text) <= numbers(quote)


def number_evidence(text: str, window: Window, before: int = 5, after: int = 20) -> str | None:
    """Extrait EXACT de la fenêtre qui contient tous les nombres du point, ou None.

    Il commence quelques mots avant le 1er nombre : le clic tombe quand il est prononcé."""
    wanted = numbers(text)
    tokens = window.text.split(" ")
    for i, tok in enumerate(tokens):
        if numbers(tok) & wanted:
            snippet = " ".join(tokens[max(0, i - before): i + after + 1])
            if wanted <= numbers(snippet):
                return snippet
    return None


def spoken_only(text: str, spoken: set[str]) -> str:
    """Retire les phrases qui contiennent un nombre jamais prononcé dans les réunions."""
    kept = [s for s in _SENTENCE.split(text.strip()) if numbers(s) <= spoken]
    return " ".join(kept)


def strip_ids(text: str, ids: list[str]) -> str:
    """Retire les noms de fichiers / identifiants de réunions que le petit LLM recopie malgré
    la consigne (« le prototype "Ami es2004d" a reçu » → « le prototype a reçu »)."""
    for ident in sorted(set(ids), key=len, reverse=True):
        pattern = r"\s*[(\"«']?\s*" + re.escape(ident) + r"\s*[)\"»']?"
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+([,.;:!?])", r"", re.sub(r"\s{2,}", " ", text)).strip()


def clean_participants(names: list[str]) -> list[str]:
    """Écarte les sorties parasites du LLM (« [ », « … ») : au moins 2 lettres."""
    return [n.strip() for n in names if sum(ch.isalpha() for ch in n) >= 2]


def _ask_json(llm: LLM, system: str, user: str, schema: dict, model: type[BaseModel]):
    """Un appel JSON validé, une nouvelle tentative, sinon None (l'étage fait sans)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in (1, 2):
        raw = llm.complete(messages, json_schema=schema, temperature=0)
        try:
            return parse_output(raw, model)
        except ValueError:
            if attempt == 2:
                return None
            messages = messages + [
                {"role": "assistant", "content": raw[:2000]},
                {"role": "user", "content": "Ta réponse n'était pas du JSON valide au format "
                                            "demandé. Renvoie UNIQUEMENT le JSON."},
            ]
    return None


def _pick(ids: list[str], table: dict[str, RecapPoint], limit: int = MAX_KEY_POINTS
          ) -> list[RecapPoint]:
    """Traduit les identifiants choisis par le LLM ; les inconnus et doublons sont ignorés."""
    out, seen = [], set()
    for raw in ids:
        key = raw.strip().strip("[]").upper()
        if key in table and key not in seen:
            seen.add(key)
            out.append(table[key])
    return out[:limit]


# --- Étages ----------------------------------------------------------------------------------


def recap_video(video: Video, segments: list[Segment], llm: LLM, log=print) -> VideoRecap:
    windows, dropped = [], 0
    for w in make_windows(segments):
        draft = _ask_json(llm, WINDOW_SYSTEM, WINDOW_USER.format(
            title=video.title, start=fmt_ts(w.start_s), end=fmt_ts(w.end_s), transcript=w.text),
            WINDOW_SCHEMA, _LlmWindow) or _LlmWindow()
        points, n_dropped = prove(draft.points, w, video.video_id)
        dropped += n_dropped
        windows.append(WindowRecap(start_s=w.start_s, end_s=w.end_s,
                                   summary=draft.summary.strip(), points=points))
        log(f"   [{fmt_ts(w.start_s)}–{fmt_ts(w.end_s)}] {len(points)} point(s) prouvé(s), "
            f"{n_dropped} écarté(s)")

    table = {f"P{i}": p for i, p in enumerate((p for w in windows for p in w.points), start=1)}
    draft = _ask_json(llm, VIDEO_SYSTEM, VIDEO_USER.format(
        title=video.title,
        summaries="\n".join(f"- [{fmt_ts(w.start_s)}] {w.summary}" for w in windows if w.summary),
        points="\n".join(f"{k} · {p.kind} · {p.text}" for k, p in table.items()) or "(aucun)"),
        VIDEO_SCHEMA, _LlmVideo) or _LlmVideo()
    return VideoRecap(
        video_id=video.video_id, title=video.title,
        subject=draft.subject.strip(), summary=draft.summary.strip(),
        participants=clean_participants(draft.participants),
        key_points=_pick(draft.key_points, table) or list(table.values())[:MAX_KEY_POINTS],
        windows=windows, dropped_points=dropped)


def recap_mission(mission: str, videos: list[VideoRecap], llm: LLM, model_name: str = "",
                  spoken: set[str] | None = None) -> MissionRecap:
    """`spoken` : nombres prononcés dans les réunions (None = pas de contrôle des synthèses)."""
    table: dict[str, RecapPoint] = {}
    blocks = []
    for i, v in enumerate(videos, start=1):
        lines = []
        for p in v.key_points:
            if not numbers_backed(p.text, p.evidence.quote):
                continue  # fiches réunion faites avant ce contrôle
            key = f"K{len(table) + 1}"
            table[key] = p
            lines.append(f"  {key} · {p.kind} · {p.text}")
        blocks.append(f"Réunion {i}/{len(videos)} — « {v.title} »\nSujet : {v.subject}\n"
                      f"Résumé : {v.summary}\nPoints :\n" + ("\n".join(lines) or "  (aucun)"))
    draft = _ask_json(llm, MISSION_SYSTEM, MISSION_USER.format(
        mission=mission, n=len(videos), meetings="\n\n".join(blocks)),
        MISSION_SCHEMA, _LlmMission) or _LlmMission()
    decisions = _pick(draft.decisions, table)
    used = {id(p) for p in decisions}
    open_issues = [p for p in _pick(draft.open_issues, table) if id(p) not in used]
    used |= {id(p) for p in open_issues}
    next_steps = [p for p in _pick(draft.next_steps, table) if id(p) not in used]
    ids = [x for v in videos for x in (v.title, v.video_id)]

    def check(text: str) -> str:
        text = strip_ids(text, ids)
        return spoken_only(text, spoken) if spoken is not None else text

    videos = [v.model_copy(update={"participants": clean_participants(v.participants),
                                   "subject": check(v.subject), "summary": check(v.summary)})
              for v in videos]
    return MissionRecap(
        mission=mission, videos=videos, subject=check(draft.subject),
        status=check(draft.status), decisions=decisions,
        open_issues=open_issues, next_steps=next_steps,
        model=model_name, generated_at=dt.datetime.now().isoformat(timespec="seconds"))


# --- Stockage (JSON dans data/recaps/) -------------------------------------------------------


def recaps_dir(data_dir: Path) -> Path:
    return data_dir / "recaps"


def video_recap_path(data_dir: Path, video_id: str) -> Path:
    return recaps_dir(data_dir) / "videos" / f"{video_id}.json"


def mission_recap_path(data_dir: Path, mission: str) -> Path:
    return recaps_dir(data_dir) / "missions" / f"{mission}.json"


def save(model: BaseModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=1), encoding="utf-8")


def load_mission_recap(data_dir: Path, mission: str) -> MissionRecap | None:
    path = mission_recap_path(data_dir, mission)
    if not path.exists():
        return None
    return MissionRecap.model_validate(json.loads(path.read_text(encoding="utf-8")))


def order_videos(videos: list[Video]) -> list[Video]:
    """De la plus ancienne à la plus récente : date si connue, sinon identifiant (a < b < c)."""
    return sorted(videos, key=lambda v: (v.date or dt.date.min, v.video_id))
