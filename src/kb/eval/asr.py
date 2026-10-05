"""Banc d'essai transcription : WER (vs référence humaine TED) et vitesse, par modèle Whisper."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from kb.config import ROOT, Settings
from kb.eval.metrics import mean, word_error_rate
from kb.eval.references import align_to_reference, fetch_ted_reference, reference_text
from kb.jsonl import read_jsonl
from kb.schemas import Segment, Video

REPORTS_DIR = ROOT / "docs" / "reports"
EDGE_S = 10.0  # on ignore les 10 dernières secondes : phrase coupée par la fin du fichier


@dataclass
class AsrScore:
    model: str
    video_id: str
    audio_s: float
    ref_words: int
    wer: float
    rtf: float | None
    mean_logprob: float
    offset_s: float  # décalage de chronologie fichier ↔ TED, mesuré près de la coupe
    ts_error_s: float  # écart médian des débuts de phrase après correction du décalage
    ts_matches: int


def hypothesis_text(segments: list[Segment], until_s: float) -> str:
    return " ".join(s.text for s in segments if s.start_s < until_s)


def score_model(model: str, data_dir: Path, refs_dir: Path) -> list[AsrScore]:
    runs = {}
    log = data_dir / "ingest_runs.jsonl"
    if log.exists():
        for line in log.read_text("utf-8").splitlines():
            r = json.loads(line)
            runs[r["video_id"]] = r["rtf"]
    scores = []
    for video in read_jsonl(data_dir / "videos.jsonl", Video):
        segments = read_jsonl(data_dir / "transcripts" / f"{video.video_id}.jsonl", Segment)
        cues = fetch_ted_reference(video.video_id, refs_dir)
        until = video.duration_s - EDGE_S
        # La chronologie de notre fichier peut différer de celle de TED : on coupe la
        # référence au même endroit du DISCOURS, grâce au décalage mesuré près de la coupe.
        local = align_to_reference(segments, cues, around_s=until)
        ref = reference_text(cues, until - local.offset_s)
        overall = align_to_reference(segments, cues)
        scores.append(
            AsrScore(
                model=model,
                video_id=video.video_id,
                audio_s=video.duration_s,
                ref_words=len(ref.split()),
                wer=word_error_rate(ref, hypothesis_text(segments, until)),
                rtf=runs.get(video.video_id),
                mean_logprob=mean([s.avg_logprob or 0.0 for s in segments]),
                offset_s=local.offset_s,
                ts_error_s=overall.median_abs_error_s,
                ts_matches=overall.matches,
            )
        )
    return scores


def run_asr_benchmark(settings: Settings, folder: Path, models: list[str]) -> list[AsrScore]:
    from kb.adapters.factory import build_transcriber
    from kb.ingest.pipeline import ingest_folder

    refs_dir = settings.data_dir / "references"
    all_scores: list[AsrScore] = []
    for model in models:
        s = settings.model_copy(deep=True)
        s.data_dir = settings.data_dir / "asr" / model
        if not (s.videos_file.exists() and len(read_jsonl(s.videos_file, Video)) > 0):
            ingest_folder(folder, build_transcriber(s, model), s, model_name=model)
        all_scores += score_model(model, s.data_dir, refs_dir)
    _write_report(all_scores)
    return all_scores


def _write_report(scores: list[AsrScore]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"asr_{dt.date.today().isoformat()}.md"
    lines = [
        "# Transcription : WER et vitesse (mesuré)",
        "",
        "Référence : transcription humaine TED. WER = (S + D + I) / N après normalisation "
        "(minuscules, ponctuation et didascalies retirées). Matériel : CPU, int8.",
        "",
        "| Modèle | Vidéo | Audio (min) | Mots réf. | WER | RTF | Décalage TED | "
        "Écart timestamps (médian) | logprob moyen |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        rtf = f"{s.rtf:.2f}" if s.rtf is not None else "—"
        lines.append(f"| {s.model} | {s.video_id[:40]} | {s.audio_s / 60:.1f} | {s.ref_words} | "
                     f"{s.wer:.1%} | {rtf} | {s.offset_s:+.1f} s | {s.ts_error_s:.1f} s "
                     f"({s.ts_matches} phrases) | {s.mean_logprob:.3f} |")
    lines += ["", "**Global (pondéré par le nombre de mots de référence) :**", ""]
    for model in dict.fromkeys(s.model for s in scores):
        ms = [s for s in scores if s.model == model]
        words = sum(s.ref_words for s in ms)
        wer = sum(s.wer * s.ref_words for s in ms) / words
        audio = sum(s.audio_s for s in ms)
        rtfs = [s.rtf * s.audio_s for s in ms if s.rtf is not None]
        rtf = sum(rtfs) / audio if len(rtfs) == len(ms) else None
        speed = f"RTF {rtf:.2f} → {rtf * 1000:.0f} h de calcul CPU pour 1 000 h" if rtf else ""
        lines.append(f"- `{model}` : WER **{wer:.1%}** sur {words} mots "
                     f"({audio / 60:.1f} min). {speed}")
    path.write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))
    print(f"\nRapport : {path}")
    return path
