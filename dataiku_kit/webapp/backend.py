"""Web App Dataiku « Synapse » — onglet Python (backend Flask).

Version corrigée du 28/09 (sélecteur de modèle). Changements par rapport à la version d'origine,
tous marqués « CORRECTIF » :
1. Les modèles GPT-5.6 raisonnent avant de répondre : `temperature` peut être refusée et un budget
   de 800 tokens peut être entièrement consommé par le raisonnement (texte vide). On essaie avec
   température, puis sans, avec un budget plus large, et on remonte la VRAIE erreur.
2. `/ask` vérifie que le modèle demandé existe et renvoie `llm_id` = modèle réellement utilisé
   (le front l'affiche : preuve visible que la sélection a joué).
3. `/models` ne masque plus l'erreur de `list_llms()` (avant : liste vide silencieuse).

`app` est fourni par Dataiku (pas d'import).
"""

import io
import json
import mimetypes
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath

import dataiku
from flask import Response, jsonify, request, stream_with_context

KB_ID = "MaYVoAvG"
VIDEOS_DATASET = "video_team16"
SEGMENTS_DATASET = "segments_team16"
CHUNKS_DATASET = "chunks_team16"
SOURCE_FOLDER_ID = "dEil081g"
STATE_FOLDER_NAME = "transcription_state_team16"
METADATA_FILE = "meeting_metadata.json"
SCENARIO_NAME = "mise_a_jour_videos"
LLM_VARIABLE = "team16_llm_id"
# Visible dans /health : prouve que le backend redémarré est bien cette version.
BACKEND_VERSION = "correctif-modele-2026-09-28"
# CORRECTIF : les modèles à raisonnement dépensent une partie du budget en réflexion (invisible) ;
# à 800 tokens, Terra/Sol peuvent renvoyer un texte vide.
LLM_TOKEN_BUDGET = 4000
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_EXTENSIONS = {".aac", ".flac", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".ogg", ".opus", ".wav", ".webm", ".wma"}
STOP_WORDS = {"alors", "avec", "avoir", "cette", "dans", "des", "elle", "est", "faire", "les", "leur", "mais", "nous", "pour", "que", "qui", "quoi", "sur", "une", "vous", "quel", "quelle", "quels", "quelles"}


def _project():
    return dataiku.api_client().get_default_project()


def _records(dataset_name):
    try:
        frame = dataiku.Dataset(dataset_name).get_dataframe()
        return frame.where(frame.notna(), None).to_dict(orient="records")
    except Exception:
        return []


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _folder_by_name(name):
    folder_id = next(item["id"] for item in _project().list_managed_folders() if item.get("name") == name)
    return dataiku.Folder(folder_id)


def _read_metadata():
    try:
        with _folder_by_name(STATE_FOLDER_NAME).get_download_stream(METADATA_FILE) as stream:
            payload = json.loads(stream.read().decode("utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def _write_metadata(items):
    content = json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8")
    _folder_by_name(STATE_FOLDER_NAME).upload_stream(METADATA_FILE, io.BytesIO(content))


def _path_key(value):
    return str(value or "").strip().lstrip("/")


def _metadata_map():
    return {_path_key(item.get("source_path")): item for item in _read_metadata() if item.get("source_path")}


def _fallback_title(source_path):
    stem = PurePosixPath(str(source_path or "Enregistrement")).stem
    text = " ".join(re.sub("[_-]+", " ", stem).split()) or "Enregistrement"
    return text[0].upper() + text[1:]


def _video_rows():
    metadata, videos = _metadata_map(), []
    for row in _records(VIDEOS_DATASET):
        video_id, source_path = str(row.get("video_id") or ""), str(row.get("source_path") or "")
        if not video_id:
            continue
        meeting = metadata.get(_path_key(source_path), {})
        videos.append({
            "video_id": video_id, "source_path": source_path,
            "title": meeting.get("title") or _fallback_title(source_path),
            "description": meeting.get("description") or "", "author": meeting.get("author") or "",
            "employee_email": meeting.get("employee_email") or "", "meeting_date": meeting.get("meeting_date") or "",
            "meeting_time": meeting.get("meeting_time") or "", "mission": meeting.get("mission") or "",
            "tags": meeting.get("tags") or [], "classification": meeting.get("classification") or "Interne",
            "language": row.get("language") or "—", "duration_s": _number(row.get("duration_s")),
            "model": row.get("model") or "—", "segment_count": _integer(row.get("segment_count")),
            "media_url": f"media/{video_id}", "status": "indexed",
        })
    return videos


def _meetings():
    videos = {_path_key(row["source_path"]): row for row in _video_rows()}
    items = []
    documented_paths = set()
    for metadata in sorted(_read_metadata(), key=lambda item: item.get("created_at", ""), reverse=True):
        path = _path_key(metadata.get("source_path"))
        documented_paths.add(path)
        video = videos.get(path)
        merged = dict(metadata)
        merged.update({
            "status": "indexed" if video else metadata.get("status", "processing"),
            "video_id": video.get("video_id", "") if video else "",
            "duration_s": video.get("duration_s", 0) if video else 0,
            "segment_count": video.get("segment_count", 0) if video else 0,
            "language": video.get("language", "—") if video else "—",
        })
        items.append(merged)
    for path, video in videos.items():
        if path not in documented_paths:
            items.append({
                "record_id": video["video_id"], "source_path": video["source_path"],
                "original_filename": PurePosixPath(video["source_path"]).name,
                "title": video["title"], "author": "", "employee_email": "",
                "meeting_date": "", "meeting_time": "", "description": "",
                "mission": "", "tags": [], "classification": "Interne",
                "created_at": "", "status": "indexed", "video_id": video["video_id"],
                "duration_s": video["duration_s"], "segment_count": video["segment_count"],
                "language": video["language"],
            })
    return items


def _configured_llm_id():
    try:
        variables = _project().get_variables()
        return variables.get("standard", {}).get(LLM_VARIABLE) or variables.get("local", {}).get(LLM_VARIABLE) or ""
    except Exception:
        return ""


def _available_llms():
    """Modèles de complétion visibles par le projet : [{id, name}]."""
    items = []
    for model in _project().list_llms():
        model_id = str(getattr(model, "id", "") or "")
        if model_id:
            name = getattr(model, "description", "") or getattr(model, "name", "") or model_id
            items.append({"id": model_id, "name": str(name)})
    return items


def _complete(llm_id, messages):
    """CORRECTIF : appelle le modèle en s'adaptant à ce qu'il accepte ; renvoie (texte, réglages).

    Essai 1 avec température 0,1 ; essai 2 sans température (les modèles à raisonnement la
    refusent souvent) ; essai 3 sans aucun réglage. Si tout échoue, l'erreur RÉELLE de Dataiku
    est remontée au front au lieu d'un message générique.
    """
    last_error = "aucune réponse"
    attempts = ({"temperature": 0.1, "maxOutputTokens": LLM_TOKEN_BUDGET},
                {"maxOutputTokens": LLM_TOKEN_BUDGET},
                {})
    for settings in attempts:
        completion = _project().get_llm(llm_id).new_completion()
        for role, content in messages:
            completion.with_message(content, role=role)
        completion.settings.update(settings)
        try:
            response = completion.execute()
        except Exception as error:
            last_error = str(error)
            continue
        text = (getattr(response, "text", "") or "").strip()
        if response.success and text:
            return text, settings
        raw = getattr(response, "_raw", None) or {}
        last_error = raw.get("errorMessage") or (
            "réponse vide (budget de tokens consommé par le raisonnement ?)" if response.success else "échec sans message")
    raise RuntimeError(f"Le modèle « {llm_id} » n'a pas répondu : {last_error}")


def _source(document, index, metadata):
    meta = dict(document.metadata or {})
    meeting = metadata.get(_path_key(meta.get("source_path")), {})
    meta.update({"video_id": str(meta.get("video_id") or ""), "source_path": str(meta.get("source_path") or ""),
                 "start_s": _number(meta.get("start_s")), "end_s": _number(meta.get("end_s")),
                 "chunk_index": _integer(meta.get("chunk_index")), "meeting": meeting})
    return {"id": f"S{index}", "text": document.text or "", "score": _number(document.score), "metadata": meta,
            "title": meeting.get("title") or _fallback_title(meta.get("source_path")),
            "author": meeting.get("author") or "", "meeting_date": meeting.get("meeting_date") or ""}


def _tokens(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return {token for token in re.findall("[a-z0-9]{3,}", normalized.lower()) if token not in STOP_WORDS}


def _local_chunk_sources(question, metadata):
    """Fallback retrieval when the Knowledge Bank embeddings are unavailable."""
    query = _tokens(question)
    if not query:
        return []
    videos = {item["video_id"]: item for item in _video_rows()}
    sources = []
    for row in _records(CHUNKS_DATASET):
        text = str(row.get("text") or "").strip()
        video_id = str(row.get("video_id") or "")
        source_path = str(row.get("source_path") or videos.get(video_id, {}).get("source_path") or "")
        meeting = metadata.get(_path_key(source_path), {})
        catalog = " ".join([
            text, meeting.get("title", ""), meeting.get("description", ""),
            meeting.get("author", ""), meeting.get("mission", ""),
            " ".join(meeting.get("tags") or []),
        ])
        matches = query.intersection(_tokens(catalog))
        if not text or not matches:
            continue
        score = len(matches) / len(query)
        meta = {
            "video_id": video_id,
            "source_path": source_path,
            "start_s": _number(row.get("start_s")),
            "end_s": _number(row.get("end_s")),
            "chunk_index": _integer(row.get("chunk_index", row.get("index", 0))),
            "meeting": meeting,
        }
        sources.append({
            "id": f"S{len(sources) + 1}", "text": text, "score": score,
            "metadata": meta,
            "title": meeting.get("title") or _fallback_title(source_path),
            "author": meeting.get("author") or "",
            "meeting_date": meeting.get("meeting_date") or "",
        })
    sources.sort(key=lambda source: (source["score"], source["metadata"]["start_s"]), reverse=True)
    return sources


def _metadata_match(question, source):
    meeting = source["metadata"].get("meeting") or {}
    catalog = " ".join([source.get("title", ""), meeting.get("description", ""), meeting.get("author", ""),
                        meeting.get("mission", ""), " ".join(meeting.get("tags") or []), meeting.get("employee_email", "")])
    query = _tokens(question)
    return len(query.intersection(_tokens(catalog))) / len(query) if query else 0.0


def _reliability(sources):
    if not sources:
        return {"score": 0, "label": "Insuffisante", "reasons": []}
    values = [max(0.0, min(1.0, source["score"])) for source in sources[:4]]
    similarity = sum(values) / len(values)
    paths = {source["metadata"].get("source_path") for source in sources}
    complete = sum(1 for source in sources if all((source["metadata"].get("meeting") or {}).get(key) for key in ("title", "author", "meeting_date", "description")))
    score = round(100 * (0.55 * similarity + 0.20 * min(1, len(sources) / 4) + 0.15 * min(1, len(paths) / 2) + 0.10 * complete / len(sources)))
    label = "Élevée" if score >= 75 else "Modérée" if score >= 50 else "Limitée"
    return {"score": score, "label": label, "reasons": [f"{len(sources)} passage(s) exploité(s)", f"{len(paths)} enregistrement(s) distinct(s)", f"{complete}/{len(sources)} source(s) avec fiche complète"]}


def _slug(value):
    normalized = unicodedata.normalize("NFKD", str(value or "meeting"))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub("[^a-z0-9]+", "-", ascii_value).strip("-")[:60] or "meeting"


def _form_value(name, required=False, maximum=2000):
    value = str(request.form.get(name) or "").strip()
    if required and not value:
        raise ValueError(f"Le champ « {name} » est obligatoire.")
    return value[:maximum]


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "backend_version": BACKEND_VERSION, "knowledge_bank": KB_ID, "llm_id": _configured_llm_id(), "video_count": len(_video_rows()), "meeting_count": len(_read_metadata())})


@app.route("/videos", methods=["GET"])
def list_videos():
    return jsonify({"videos": _video_rows()})


@app.route("/meetings", methods=["GET"])
def list_meetings():
    return jsonify({"meetings": _meetings()})


@app.route("/segments/<video_id>", methods=["GET"])
def list_segments(video_id):
    rows = [row for row in _records(SEGMENTS_DATASET) if str(row.get("video_id") or "") == video_id]
    rows.sort(key=lambda row: _number(row.get("start_s")))
    return jsonify({"segments": [{"segment_index": _integer(row.get("segment_index")), "start_s": _number(row.get("start_s")),
                                  "end_s": _number(row.get("end_s")), "text": str(row.get("text") or ""),
                                  "language": row.get("language") or "—"} for row in rows]})


@app.route("/media/<video_id>", methods=["GET"])
def media(video_id):
    video = next((item for item in _video_rows() if item["video_id"] == video_id), None)
    if not video:
        return jsonify({"error": "Enregistrement introuvable."}), 404
    try:
        stream = dataiku.Folder(SOURCE_FOLDER_ID).get_download_stream(video["source_path"])
    except Exception as error:
        return jsonify({"error": str(error)}), 404

    def generate():
        try:
            while True:
                chunk = stream.read(1024 * 512)
                if not chunk:
                    break
                yield chunk
        finally:
            stream.close()

    content_type = mimetypes.guess_type(video["source_path"])[0] or "application/octet-stream"
    return Response(stream_with_context(generate()), mimetype=content_type)


@app.route("/models", methods=["GET"])
def models():
    # CORRECTIF : l'erreur de list_llms() est renvoyée au lieu d'une liste vide silencieuse.
    configured, items, error = _configured_llm_id(), [], ""
    try:
        items = [dict(model, configured=model["id"] == configured) for model in _available_llms()]
    except Exception as exc:
        error = str(exc)
    return jsonify({"models": items, "configured_llm_id": configured, "error": error})


@app.route("/ask", methods=["POST"])
def ask():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    mode = str(payload.get("mode") or "synthese")
    scope_video_id = str(payload.get("video_id") or "").strip()
    requested_llm = str(payload.get("llm_id") or "").strip()
    llm_id = requested_llm or _configured_llm_id()
    if not question:
        return jsonify({"error": "Écrivez une question."}), 400
    if mode not in {"strict", "synthese"}:
        return jsonify({"error": "Mode de réponse invalide."}), 400
    # CORRECTIF : un modèle demandé mais inconnu est refusé explicitement (avant : erreur opaque).
    if requested_llm and mode == "synthese":
        try:
            known = {model["id"] for model in _available_llms()}
        except Exception:
            known = set()  # liste indisponible : on laisse get_llm trancher
        if known and requested_llm not in known:
            return jsonify({"error": f"Modèle inconnu pour ce projet : {requested_llm}"}), 400
    try:
        metadata = _metadata_map()
        retrieval = "knowledge_bank"
        try:
            search = _project().get_knowledge_bank(KB_ID).search(question, max_documents=24, search_type="SIMILARITY")
            candidates = [_source(document, index, metadata) for index, document in enumerate(list(search.documents), 1)]
        except Exception:
            candidates = _local_chunk_sources(question, metadata)
            retrieval = "chunks_fallback"
        if scope_video_id:
            candidates = [source for source in candidates if source["metadata"].get("video_id") == scope_video_id]
        for source in candidates:
            source["ranking_score"] = source["score"] + 0.18 * _metadata_match(question, source)
        candidates.sort(key=lambda source: source["ranking_score"], reverse=True)
        sources = candidates[:6]
        for index, source in enumerate(sources, 1):
            source["id"] = f"S{index}"
        reliability = _reliability(sources)
        if not sources:
            return jsonify({"answer": "", "not_found": True, "note": "Aucun passage pertinent n’a été trouvé dans les réunions indexées.", "sources": [], "mode": mode, "llm_used": False, "llm_id": "", "reliability": reliability})
        confidence = max(source["score"] for source in sources)
        if mode == "strict":
            note = "Mode strict : contenu indexé mot pour mot."
            if retrieval == "chunks_fallback":
                note += " Recherche de secours effectuée directement dans les transcriptions."
            return jsonify({"answer": "Voici les extraits exacts les plus pertinents. Aucun texte n’a été généré.", "not_found": False, "note": note, "sources": sources, "mode": mode, "confidence": confidence, "reliability": reliability, "llm_used": False, "llm_id": "", "retrieval": retrieval})
        if not llm_id:
            note = f"Configurez la variable projet {LLM_VARIABLE} ou choisissez un modèle."
            if retrieval == "chunks_fallback":
                note += " Les passages viennent directement de chunks_team16."
            return jsonify({"answer": "Les passages ont été retrouvés. Sélectionnez un modèle Dataiku pour obtenir une synthèse.", "not_found": False, "note": note, "sources": sources, "mode": mode, "confidence": confidence, "reliability": reliability, "llm_used": False, "llm_id": "", "retrieval": retrieval})

        blocks = []
        for source in sources:
            meeting = source["metadata"].get("meeting") or {}
            blocks.append(
                f"[{source['id']}] {source['title']} | auteur: {meeting.get('author', 'non renseigné')} "
                f"| date: {meeting.get('meeting_date', 'non renseignée')} | mission: {meeting.get('mission', 'non renseignée')} "
                f"| début: {source['metadata']['start_s']:.1f}s\nDescription: {meeting.get('description', '')}\nTranscript: {source['text']}"
            )
        messages = [("system",
                     "Vous êtes Synapse, assistant de recherche dans des réunions d’entreprise. Répondez en français uniquement avec les sources fournies. "
                     "Citez chaque affirmation factuelle avec [S1], [S2], etc. Distinguez explicitement fait documenté et déduction. "
                     "Si les preuves sont insuffisantes ou contradictoires, dites-le. N’inventez jamais.")]
        for message in (payload.get("history") or [])[-6:]:
            role, content = message.get("role"), str(message.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append((role, content))
        messages.append(("user", f"Question : {question}\n\nSources :\n" + "\n\n".join(blocks)))
        answer, settings = _complete(llm_id, messages)
        note = "Synthèse générée uniquement à partir des passages affichés."
        if retrieval == "chunks_fallback":
            note += " Recherche de secours effectuée directement dans les transcriptions."
        return jsonify({"answer": answer, "not_found": False, "note": note,
                        "sources": sources, "mode": mode, "confidence": confidence, "reliability": reliability,
                        "llm_used": True, "llm_id": llm_id, "llm_settings": settings, "retrieval": retrieval})
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@app.route("/stats", methods=["GET"])
def stats():
    videos, meetings = _video_rows(), _meetings()
    complete = sum(1 for item in meetings if all(item.get(key) for key in ("title", "author", "meeting_date", "description")))
    return jsonify({
        "video_count": len(videos), "meeting_count": len(meetings),
        "processing_count": sum(item.get("status") != "indexed" for item in meetings),
        "segment_count": len(_records(SEGMENTS_DATASET)), "chunk_count": len(_records(CHUNKS_DATASET)),
        "duration_s": sum(video["duration_s"] for video in videos),
        "metadata_completion": round(100 * complete / len(meetings)) if meetings else 0,
        "languages": sorted({video["language"] for video in videos if video["language"] != "—"}),
        "model": next((video["model"] for video in videos if video["model"] != "—"), "—"),
        "knowledge_bank": KB_ID, "last_videos": videos[-7:][::-1],
    })


@app.route("/upload", methods=["POST"])
def upload():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "Sélectionnez un fichier audio ou vidéo."}), 400
    if request.content_length and request.content_length > MAX_UPLOAD_BYTES:
        return jsonify({"error": "Le fichier dépasse la limite de 2 Go."}), 413
    original_name = os.path.basename(uploaded.filename)
    extension = os.path.splitext(original_name)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "Format audio ou vidéo non pris en charge."}), 400
    try:
        title = _form_value("title", True, 180)
        author = _form_value("author", True, 120)
        employee_email = _form_value("employee_email", True, 180)
        meeting_date = _form_value("meeting_date", True, 10)
        meeting_time = _form_value("meeting_time", True, 5)
        description = _form_value("description", True, 2000)
        mission = _form_value("mission", True, 160)
        classification = _form_value("classification", True, 40)
        tags = [item.strip()[:50] for item in _form_value("tags", False, 500).split(",") if item.strip()][:12]
        if not re.fullmatch("[^@ ]+@[^@ ]+[.][^@ ]+", employee_email):
            return jsonify({"error": "L’adresse email n’est pas valide."}), 400
        datetime.strptime(meeting_date, "%Y-%m-%d")
        datetime.strptime(meeting_time, "%H:%M")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    record_id = uuid.uuid4().hex
    storage_name = f"{meeting_date}-{_slug(title)}-{record_id[:8]}{extension}"
    source_path = f"/meetings/{meeting_date[:4]}/{meeting_date[5:7]}/{storage_name}"
    record = {
        "record_id": record_id, "source_path": source_path, "original_filename": original_name,
        "title": title, "author": author, "employee_email": employee_email,
        "meeting_date": meeting_date, "meeting_time": meeting_time, "description": description,
        "mission": mission, "tags": tags, "classification": classification,
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "processing",
    }
    try:
        items = _read_metadata()
        duplicate = next((item for item in items if
                          str(item.get("original_filename") or "").lower() == original_name.lower()
                          and item.get("meeting_date") == meeting_date
                          and str(item.get("title") or "").lower() == title.lower()), None)
        if duplicate:
            return jsonify({"error": "Cette réunion a déjà été importée avec le même fichier, le même titre et la même date."}), 409
        dataiku.Folder(SOURCE_FOLDER_ID).upload_stream(source_path, uploaded.stream)
        items.append(record)
        _write_metadata(items)
        # Lancement immédiat après l'écriture réussie du média et de sa fiche.
        scenario = next(
            item for item in _project().list_scenarios()
            if getattr(item, "name", "") == SCENARIO_NAME
        ).to_scenario()
        scenario.run()
        return jsonify({
            "ok": True,
            "record": record,
            "scenario_started": True,
            "message": "Fiche enregistrée et transcription lancée immédiatement.",
        })
    except Exception as error:
        return jsonify({"error": str(error)}), 500
