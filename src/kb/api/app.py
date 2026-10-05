"""API FastAPI (Phase 6, CLAUDE.md section 11). Le backend garde les clés (D9) : rien côté
navigateur.

Routes :
  POST /videos                upload -> job d'ingestion (transcription + réindexation)
  GET  /jobs/{id}              statut du job
  GET  /videos                 liste
  GET  /videos/{id}            détail
  GET  /videos/{id}/media      octets du fichier (lecteur front)
  GET  /videos/{id}/fiches     fiches REX (outil query_fiches)
  GET  /videos/{id}/segments   transcript horodaté (lecteur front, FE-2)
  GET  /fiches?text=&client=&tech=  fiches REX toutes vidéos (écran Fiches du front, FE-2)
  POST /ask                    {question, mode, filters, profile} -> Answer
  GET  /metrics                8 indicateurs mesurés + courbe risque-couverture
                               (null = jamais mesuré, jamais inventé)
  GET  /tiers                  comparaison des paliers déjà mesurés (kb.cli eval-agent)
  GET  /experts?topic=         auteurs dont une fiche vérifiée traite du sujet
  GET  /missions               missions (vidéos groupées) et disponibilité du point
  GET  /missions/{m}/recap     point de situation (L3) : sujet, état, décisions, preuves
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from kb.agent.agent import Agent
from kb.agent.router import recap_target
from kb.config import Settings, load_settings
from kb.eval.summary import CORPORA, compute_kpis, compute_risk_coverage
from kb.eval.tiers import aggregate_tiers
from kb.jsonl import read_jsonl
from kb.schemas import Answer, Citation, FicheREX, Segment, Video
from kb.structure.recap import MissionRecap, load_mission_recap, order_videos
from kb.structure.store import query_fiches

from .jobs import create_job, get_job, run_in_background

app = FastAPI(title="Team 16 — Connaissance vidéo (Synchrone)")
# ponytail: CORS ouvert (démo locale, une seule origine front). Restreindre avant tout déploiement.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_agents: dict[str, Agent] = {}
_agents_lock = threading.Lock()


def _settings(profile: str | None) -> Settings:
    return load_settings(profile)


def _agent(profile: str | None, model: str | None = None) -> Agent:
    """Un agent par (profil, modèle) : choisir Terra ne doit pas répondre avec Luna.

    Avant le 27/09, `model` n'existait pas : un sélecteur de modèle côté client (Web App
    Dataiku) était ignoré et la réponse venait toujours du modèle par défaut du profil."""
    settings = load_settings(profile or "free")
    if model:
        settings.llm = settings.llm.with_model(model)  # ValueError si non autorisé
    key = f"{settings.profile}::{settings.llm.model}"
    with _agents_lock:
        if key not in _agents:
            _agents[key] = Agent.load(settings)
        return _agents[key]


def _videos(settings: Settings) -> list[Video]:
    return read_jsonl(settings.videos_file, Video) if settings.videos_file.exists() else []


# --- Vidéos -----------------------------------------------------------------------------


@app.get("/videos")
def list_videos(profile: str | None = None) -> list[Video]:
    return _videos(_settings(profile))


@app.get("/videos/{video_id}")
def get_video(video_id: str, profile: str | None = None) -> Video:
    for v in _videos(_settings(profile)):
        if v.video_id == video_id:
            return v
    raise HTTPException(404, f"Vidéo introuvable : {video_id}")


@app.get("/videos/{video_id}/media")
def video_media(video_id: str, profile: str | None = None) -> FileResponse:
    """Sert le fichier source. Vidéo en plusieurs morceaux (`_seg01`, `_seg02`…) : les morceaux
    sont recollés en un seul WAV (même assemblage que la transcription, donc les secondes du
    transcript et du lecteur coïncident) — sinon une citation après le 1er morceau tombe à côté."""
    video = get_video(video_id, profile)
    settings = _settings(profile)
    parts = [settings.data_dir / "videos" / name for name in video.source_uri.split(";")]
    for p in parts:
        if not p.exists():
            raise HTTPException(404, f"Fichier introuvable : {p.name}")
    if len(parts) == 1:
        return FileResponse(parts[0])
    return FileResponse(_joined_audio(parts, settings.data_dir / "media" / f"{video_id}.wav"),
                        media_type="audio/wav")


def _joined_audio(parts: list[Path], dest: Path) -> Path:
    """WAV 16 kHz mono des morceaux mis bout à bout, en cache (refait si un morceau change)."""
    import wave

    import numpy as np

    from kb.adapters.transcribe_fw import SAMPLE_RATE, load_audio

    if dest.exists() and dest.stat().st_mtime >= max(p.stat().st_mtime for p in parts):
        return dest
    pcm = (np.clip(load_audio(parts), -1.0, 1.0) * 32767).astype("<i2")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    tmp.replace(dest)
    return dest


@app.get("/videos/{video_id}/fiches")
def video_fiches(video_id: str, profile: str | None = None) -> list[FicheREX]:
    return query_fiches(_settings(profile).kb_db_file, video_id=video_id, limit=200)


@app.get("/videos/{video_id}/segments")
def video_segments(video_id: str, profile: str | None = None) -> list[Segment]:
    """Transcript horodaté (lecteur front) — [] si la vidéo n'a pas encore été transcrite."""
    path = _settings(profile).transcripts_dir / f"{video_id}.jsonl"
    return read_jsonl(path, Segment) if path.exists() else []


@app.get("/fiches")
def list_fiches(text: str | None = None, client: str | None = None, tech: str | None = None,
                profile: str | None = None, limit: int = 200) -> list[FicheREX]:
    return query_fiches(_settings(profile).kb_db_file, text=text, client=client,
                        technology=tech, limit=limit)


@app.post("/videos")
def upload_video(
    file: UploadFile,
    profile: str | None = None,
    title: str | None = Form(None),
    author: str | None = Form(None),
    date: str | None = Form(None),
    mission: str | None = Form(None),
    client: str | None = Form(None),
    contact: str | None = Form(None),
    description: str | None = Form(None),
    language: str | None = Form(None),
) -> dict:
    """Upload + formulaire d'import. Refuse tout de suite un doublon EXACT (même empreinte) ou
    un nom déjà pris (409) ; le reste (transcription, quasi-doublon, index) tourne en fond."""
    from pydantic import ValidationError

    from kb.ingest.dedup import file_sha256
    from kb.ingest.documents import DOCUMENT_EXTENSIONS
    from kb.ingest.metadata import UploadMeta, save_meta
    from kb.ingest.sources import MEDIA_EXTENSIONS, _split_part, slugify
    from kb.ingest.vision import IMAGE_EXTENSIONS

    if not file.filename:
        raise HTTPException(400, "Fichier sans nom.")
    name = Path(file.filename).name  # .name : ignore tout chemin fourni par le client
    suffix = Path(name).suffix.lower()
    if suffix not in MEDIA_EXTENSIONS | DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS:
        raise HTTPException(415, f"Format non pris en charge : {Path(name).suffix or name}")
    try:
        meta = UploadMeta(title=title, author=author, date=date, mission=mission, client=client,
                          contact=contact, description=description, language=language)
    except ValidationError as exc:
        raise HTTPException(422, f"Formulaire invalide : {exc.errors()[0]['msg']}") from exc

    s = _settings(profile)
    dest_dir = s.data_dir / "videos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if dest.exists():
        raise HTTPException(409, f"Un fichier « {name} » existe déjà : renommez-le.")
    tmp = dest_dir / f".{name}.upload"
    with tmp.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    digest = file_sha256(tmp)
    same = _video_with_hash(s, digest)
    if same is not None:
        tmp.unlink()
        raise HTTPException(409, f"Fichier déjà importé à l'identique : {same.title} "
                                 f"({same.video_id}). Rien n'a été retraité.")
    tmp.replace(dest)

    stem = Path(name).stem  # un document n'a pas de morceaux « _seg02 » à regrouper
    single = suffix in DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS
    video_id = slugify(stem if single else _split_part(stem)[0])
    save_meta(s.data_dir, video_id, meta)
    job = create_job()
    run_in_background(job.id, _ingest_and_index, s, job.id, video_id)
    return {"job_id": job.id, "video_id": video_id}


def _video_with_hash(settings: Settings, digest: str) -> Video | None:
    """Vidéo déjà importée avec cette empreinte. Les vidéos d'avant le formulaire n'en ont pas :
    on la calcule une fois et on l'enregistre (mono-fichier seulement)."""
    from kb.ingest.dedup import file_sha256
    from kb.jsonl import write_jsonl

    videos = _videos(settings)
    changed = False
    for i, v in enumerate(videos):
        if v.sha256 is None and ";" not in v.source_uri:
            path = settings.data_dir / "videos" / v.source_uri
            if path.exists():
                videos[i] = v = v.model_copy(update={"sha256": file_sha256(path)})
                changed = True
        if v.sha256 == digest:
            if changed:
                write_jsonl(settings.videos_file, videos)
            return v
    if changed:
        write_jsonl(settings.videos_file, videos)
    return None


def _ingest_and_index(settings: Settings, job_id: str, video_id: str | None = None) -> None:
    from kb.adapters.factory import build_transcriber
    from kb.api.jobs import update_job
    from kb.index.build import update_index
    from kb.ingest.pipeline import ingest_folder

    update_job(job_id, status="transcribing", video_id=video_id)
    model = settings.transcription.model_size
    stats = ingest_folder(settings.data_dir / "videos", build_transcriber(settings, model),
                          settings, model_name=model)
    new_ids = [st.video_id for st in stats]
    dup = _near_duplicate(settings, video_id) if video_id in new_ids else None
    if dup is not None:  # même contenu déjà indexé : on le met de côté, sans l'indexer
        _set_aside(settings, video_id)
        update_job(job_id, status="duplicate", duplicate_of=dup[0], similarity=round(dup[1], 3))
        return
    update_job(job_id, status="indexing", video_id=video_id or (new_ids[-1] if new_ids else None))
    if new_ids:
        update_index(settings, new_ids)  # incrémental : seules les nouvelles vidéos
    with _agents_lock:
        _agents.pop(settings.profile, None)  # le prochain /ask recharge l'index à jour
    update_job(job_id, status="done")


def _near_duplicate(settings: Settings, video_id: str) -> tuple[str, float] | None:
    from kb.ingest.dedup import find_near_duplicate

    def text(vid: str) -> str:
        path = settings.transcripts_dir / f"{vid}.jsonl"
        return " ".join(seg.text for seg in read_jsonl(path, Segment)) if path.exists() else ""

    others = {v.video_id: text(v.video_id) for v in _videos(settings) if v.video_id != video_id}
    return find_near_duplicate(text(video_id), others)


def _set_aside(settings: Settings, video_id: str) -> None:
    """Quasi-doublon : fichier déplacé dans data/duplicates/ (rien n'est supprimé), vidéo et
    transcript retirés du corpus."""
    from kb.jsonl import write_jsonl

    videos = _videos(settings)
    video = next((v for v in videos if v.video_id == video_id), None)
    write_jsonl(settings.videos_file, [v for v in videos if v.video_id != video_id])
    (settings.transcripts_dir / f"{video_id}.jsonl").unlink(missing_ok=True)
    if video is not None:
        aside = settings.data_dir / "duplicates"
        aside.mkdir(parents=True, exist_ok=True)
        for name in video.source_uri.split(";"):
            src = settings.data_dir / "videos" / name
            if src.exists():
                src.replace(aside / name)


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job introuvable : {job_id}")
    return asdict(job)


# --- Question / réponse ------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str
    mode: str = "synthese"
    filters: dict | None = None
    profile: str | None = None
    model: str | None = None  # un id de GET /models ; absent = modèle par défaut du profil


@app.get("/models")
def list_models(profile: str | None = None) -> dict:
    """Modèles qu'on peut choisir pour ce profil (le 1er est le défaut), avec leurs tarifs."""
    llm = _settings(profile).llm
    return {"profile": _settings(profile).profile, "default": llm.model,
            "models": [m.model_dump() for m in llm.options()]}


class MissionInfo(BaseModel):
    mission: str
    video_ids: list[str]
    recap_available: bool
    generated_at: str | None = None


@app.get("/missions")
def list_missions(profile: str | None = None) -> list[MissionInfo]:
    """Missions = vidéos regroupées par `Video.mission` (rattachées par `kb.cli recap`)."""
    s = _settings(profile)
    by_mission: dict[str, list[str]] = {}
    for v in order_videos([v for v in _videos(s) if v.mission]):
        by_mission.setdefault(v.mission, []).append(v.video_id)
    out = []
    for mission, ids in sorted(by_mission.items()):
        recap = load_mission_recap(s.data_dir, mission)
        out.append(MissionInfo(mission=mission, video_ids=ids, recap_available=recap is not None,
                               generated_at=recap.generated_at if recap else None))
    return out


@app.get("/missions/{mission}/recap")
def mission_recap(mission: str, profile: str | None = None) -> MissionRecap:
    recap = load_mission_recap(_settings(profile).data_dir, Path(mission).name)
    if recap is None:
        raise HTTPException(404, f"Pas de point de situation pour « {mission} » : lancer "
                                 f"`python -m kb.cli recap {mission} <video_ids…>`")
    return recap


class Lead(BaseModel):
    """Piste : passage proche montré quand l'agent s'abstient. Texte = transcript exact (rien
    de généré), mais ce n'est PAS une preuve de réponse — le front l'affiche comme telle."""

    video_id: str
    start_s: float
    text: str
    score: float | None = None  # score du reranker : un score, pas une probabilité
    page: int | None = None  # documents : la page à ouvrir
    modality: str | None = None  # « ocr » / « visual » : texte lu / description générée


class AskResponse(Answer):
    leads: list[Lead] = []  # rempli seulement en cas d'abstention (CLAUDE.md section 7)
    note: str = ""  # pourquoi l'agent s'est abstenu (seuil, citation non retrouvée…)
    search_query: str | None = None  # question réellement cherchée (traduite ou non)
    mission: str | None = None  # rempli si la question a été routée vers le point mission
    model: str | None = None  # modèle qui a réellement répondu (preuve que la sélection a joué)


LEADS = 3


@app.post("/ask")
def ask(req: AskRequest) -> AskResponse:
    routed = _recap_answer(req)
    if routed is not None:
        return routed
    try:
        agent = _agent(req.profile, req.model)
    except ValueError as exc:  # modèle non autorisé pour ce profil : erreur claire, pas de repli
        raise HTTPException(400, str(exc)) from exc
    res = agent.ask(req.question, mode=req.mode, filters=req.filters)
    used = getattr(getattr(agent, "settings", None), "llm", None)
    hits = getattr(res, "hits", [])[:LEADS] if res.answer.not_found else []
    leads = [Lead(video_id=h.chunk.video_id, start_s=h.moment_s, text=h.moment_text.strip(),
                  score=None if h.rerank_score is None else round(h.rerank_score, 3),
                  page=h.chunk.page, modality=h.chunk.modality)
             for h in hits]
    return AskResponse(**res.answer.model_dump(), leads=leads, note=getattr(res, "note", ""),
                       search_query=getattr(res, "search_query", None) or None,
                       model=used.model if used is not None else req.model)


def _recap_answer(req: AskRequest) -> AskResponse | None:
    """« Où en est la mission X ? » → le point mission déjà calculé (L3), sans appel LLM.

    La réponse reprend l'état du projet (texte généré, étiqueté comme tel) et, comme
    citations, les extraits EXACTS qui prouvent les décisions, points ouverts et étapes."""
    s = _settings(req.profile)
    available = [m.mission for m in list_missions(req.profile) if m.recap_available]
    target = recap_target(req.question, available)
    if target is None:
        return None
    recap = load_mission_recap(s.data_dir, target)
    points = (recap.decisions + recap.open_issues + recap.next_steps)[:ROUTED_CITATIONS]
    citations = [Citation(chunk_id="", video_id=p.evidence.video_id, start_s=p.evidence.start_s,
                          quote=p.evidence.quote, verified=True) for p in points]
    text = recap.status or recap.subject or f"Point de situation de la mission {target}."
    return AskResponse(answer=text, citations=citations, mission=target,
                       note=f"question routée vers le point mission « {target} » "
                            f"(généré le {recap.generated_at.replace('T', ' à ')})")


ROUTED_CITATIONS = 4


# --- Évaluation ---------------------------------------------------------------------------


@app.get("/metrics")
def metrics(profile: str | None = None, corpus: str = "ted") -> dict:
    """Les 8 indicateurs mesurés (docs/reports/agent_*, search_*, asr_*) ; `null` = jamais
    mesuré (faithfulness, hallucination, temps main-vs-outil) — jamais un chiffre inventé.
    `risk_coverage` : `null` si aucun rapport search_*, sinon la courbe (seuil, couverture,
    risque) qui sert à calibrer `abstain_threshold`."""
    if corpus not in CORPORA:
        raise HTTPException(400, f"corpus inconnu : {corpus} (attendu : {', '.join(CORPORA)})")
    p, prefix = _settings(profile).profile, CORPORA[corpus]
    return {**compute_kpis(p, prefix), "risk_coverage": compute_risk_coverage(p, prefix),
            "corpus": corpus}


@app.get("/tiers")
def tiers(profiles: list[str] = Query(default=["free", "dataiku", "market"]),
         mode: str = "synthese") -> dict:
    rows, missing = aggregate_tiers(profiles, mode)
    return {"rows": rows, "missing": missing}


@app.get("/experts")
def experts(topic: str, profile: str | None = None, limit: int = 20) -> list[dict]:
    """Auteurs dont au moins une fiche (preuve vérifiée) traite du sujet — jamais un annuaire."""
    db = _settings(profile).kb_db_file
    by_id = {f.fiche_id: f for f in (query_fiches(db, text=topic, limit=limit)
                                     + query_fiches(db, technology=topic, limit=limit))}
    by_author: dict[str, list[FicheREX]] = {}
    for f in by_id.values():
        if f.author:
            by_author.setdefault(f.author, []).append(f)
    return [
        {"author": author, "fiches": len(fs),
         "clients": sorted({f.client for f in fs if f.client}),
         "example": {"video_id": fs[0].video_id, "start_s": fs[0].start_s,
                    "problem": fs[0].problem}}
        for author, fs in sorted(by_author.items())
    ]
