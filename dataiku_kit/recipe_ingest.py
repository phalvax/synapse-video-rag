"""Recette Python Dataiku — L0 Ingestion : managed folder `video` -> datasets `segments`, `videos`.

Statut : **kit, non testé sur une vraie instance Dataiku** (pas d'accès depuis ce repo).
Réutilise `kb.ingest` telle quelle ; seule la lecture des fichiers change (streams Dataiku au
lieu de chemins locaux — CLAUDE.md section 2 : « accès aux fichiers par streams uniquement »).

Ce qui a changé (retours de l'équipe, 27/09) :
- **GPU détecté tout seul** : profil `dataiku` en `device: auto` → cuda/float16 si l'env a un
  GPU, sinon cpu/int8 (le plus rapide sans GPU, mais lent). Rien à modifier dans la recette.
- **Seuls les NOUVEAUX fichiers sont transcrits** : les vidéos déjà présentes dans le dataset
  `videos` sont sautées ; les lignes existantes sont conservées (plus de retraitement du
  dossier entier à chaque lancement).
- **Pas de conversion en WAV** : PyAV (embarqué par faster-whisper) décode mp4, mkv, mov…
  directement en mémoire.
- **Doublons** : un fichier au contenu identique (même SHA-256) à une vidéo déjà traitée est
  ignoré.
- **Langue** : `LANGUAGE = "fr"` ou `"en"` saute la détection automatique de Whisper (utile si
  tout le corpus est dans une seule langue ; à mesurer, le gain est probablement faible).

Entrées / sorties : managed folder `video` ; datasets `segments` et `videos`.
Env de code : `py311_fasterwhisper` + ce repo installé (`pip install -e .`) ou importé en
bibliothèque de projet Git (cf. envs.md).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import dataiku
import pandas as pd

from kb.adapters.factory import build_transcriber, resolve_device
from kb.config import load_settings
from kb.ingest.dedup import file_sha256
from kb.ingest.metadata import UploadMeta, save_meta
from kb.ingest.pipeline import ingest_group
from kb.ingest.sources import MEDIA_EXTENSIONS, _split_part, discover_media, slugify
from kb.jsonl import read_jsonl
from kb.schemas import Segment

FOLDER_NAME = "video"
SEGMENTS_DATASET = "segments"
VIDEOS_DATASET = "videos"
MODEL_SIZE = None  # None = profil (large-v3-turbo) ; "small" si l'env n'a pas de GPU
LANGUAGE = None  # None = détection automatique ; "fr" / "en" pour la sauter


def _existing(name: str) -> pd.DataFrame:
    """Lignes déjà écrites (vide au premier lancement)."""
    try:
        return dataiku.Dataset(name).get_dataframe()
    except Exception:  # noqa: BLE001 — dataset jamais construit
        return pd.DataFrame()


def main() -> None:
    settings = load_settings("dataiku")
    if LANGUAGE:
        settings.transcription.language = LANGUAGE
    print("Transcription sur", resolve_device(settings.transcription.device,
                                              settings.transcription.compute_type))
    old_videos, old_segments = _existing(VIDEOS_DATASET), _existing(SEGMENTS_DATASET)
    done_ids = set(old_videos["video_id"]) if "video_id" in old_videos else set()
    done_hashes = set(old_videos["sha256"].dropna()) if "sha256" in old_videos else set()

    folder = dataiku.Folder(FOLDER_NAME)
    transcriber = None  # chargé seulement s'il y a du travail (le modèle pèse ~1,6 Go)
    new_videos, new_segments = [], []
    with tempfile.TemporaryDirectory() as tmp:
        local_dir = Path(tmp)
        for path in folder.list_paths_in_partition():
            if path.endswith(".meta.json"):  # formulaire déposé par la Web App (upload_hook.py)
                media = Path(path[: -len(".meta.json")])
                with folder.get_download_stream(path) as src:
                    meta = UploadMeta.model_validate(json.loads(src.read()))
                save_meta(settings.data_dir, slugify(_split_part(media.stem)[0]), meta)
                continue
            if Path(path).suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            dest = local_dir / Path(path).name
            with folder.get_download_stream(path) as src, dest.open("wb") as out:
                out.write(src.read())

        for group in discover_media(local_dir):
            if group.video_id in done_ids:
                continue  # déjà transcrit lors d'un lancement précédent
            if len(group.parts) == 1 and file_sha256(group.parts[0]) in done_hashes:
                print(f"= {group.video_id} : contenu identique à une vidéo déjà traitée, ignoré")
                continue
            transcriber = transcriber or build_transcriber(settings, MODEL_SIZE)
            video, stat = ingest_group(group, transcriber, settings,
                                       model_name=MODEL_SIZE or settings.transcription.model_size)
            print(f"→ {video.video_id} : {stat.audio_s / 60:.1f} min, RTF {stat.rtf:.2f}")
            new_videos.append(video.model_dump(mode="json"))
            segs = read_jsonl(settings.transcripts_dir / f"{video.video_id}.jsonl", Segment)
            new_segments += [s.model_dump() for s in segs]

    if not new_videos:
        print("Aucun nouveau fichier : datasets inchangés.")
        return
    dataiku.Dataset(VIDEOS_DATASET).write_with_schema(
        pd.concat([old_videos, pd.DataFrame(new_videos)], ignore_index=True))
    dataiku.Dataset(SEGMENTS_DATASET).write_with_schema(
        pd.concat([old_segments, pd.DataFrame(new_segments)], ignore_index=True))


if __name__ == "__main__":
    main()
