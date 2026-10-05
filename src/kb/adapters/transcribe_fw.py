"""Adapter de transcription : faster-whisper (CTranslate2), en local sur CPU ou GPU CUDA."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from kb.adapters.base import TranscriptionResult
from kb.schemas import Segment

SAMPLE_RATE = 16_000


class NoAudioTrack(RuntimeError):
    """Fichier illisible ou sans piste audio (ex. vidéo muette, fichier corrompu)."""


def load_audio(parts: list[Path] | tuple[Path, ...]) -> np.ndarray:
    """Décode et met bout à bout les morceaux → signal 16 kHz mono float32.

    PyAV (embarqué par faster-whisper) lit tout ce que ffmpeg lit (mp4, mkv, avi, wav,
    m4a, opus…) : aucun ffmpeg système requis, la piste audio est extraite en mémoire.
    """
    from faster_whisper import decode_audio

    arrays = []
    for p in parts:
        try:
            arrays.append(decode_audio(str(p), sampling_rate=SAMPLE_RATE))
        except Exception as exc:  # PyAV lève des erreurs variées selon le conteneur
            raise NoAudioTrack(f"{p.name} : pas de piste audio lisible ({exc})") from exc
    return np.concatenate(arrays) if len(arrays) > 1 else arrays[0]


class FasterWhisperTranscriber:
    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        vad_filter: bool = True,
        beam_size: int = 5,
    ) -> None:
        from faster_whisper import WhisperModel

        self.model_size = model_size
        self.vad_filter = vad_filter
        self.beam_size = beam_size
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(
        self, audio: np.ndarray, video_id: str, language: str | None = None
    ) -> TranscriptionResult:
        segments, info = self._model.transcribe(
            audio,
            language=language,
            vad_filter=self.vad_filter,  # sans VAD, Whisper « invente » du texte sur les silences
            word_timestamps=True,  # bornes de segments plus précises
            beam_size=self.beam_size,
            condition_on_previous_text=False,  # évite les boucles de répétition
        )
        out = [
            Segment(
                video_id=video_id,
                seg_id=i,
                start_s=round(s.start, 2),
                end_s=round(max(s.end, s.start), 2),
                text=s.text.strip(),
                avg_logprob=round(s.avg_logprob, 4),
            )
            for i, s in enumerate(seg for seg in segments if seg.text.strip())
        ]
        return TranscriptionResult(
            segments=out, language=info.language, duration_s=len(audio) / SAMPLE_RATE
        )
