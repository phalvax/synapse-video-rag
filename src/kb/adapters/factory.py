"""Construit les bons adapters à partir du profil actif.

Les imports lourds (faster-whisper, chromadb, torch) sont faits à la demande : `kb.cli check`
et les tests unitaires restent rapides et n'exigent pas les extras `asr` / `index`.
"""

from __future__ import annotations

from kb.adapters.openai_compat import OpenAICompatEmbedder, OpenAICompatLLM
from kb.config import MODELS_DIR, Settings


def build_llm(settings: Settings) -> OpenAICompatLLM:
    s = settings.llm
    return OpenAICompatLLM(base_url=s.base_url, api_key=s.api_key(), model=s.model,
                           temperature=s.temperature, timeout=s.timeout_s)


def build_embedder(settings: Settings) -> OpenAICompatEmbedder:
    s = settings.embedding
    return OpenAICompatEmbedder(base_url=s.base_url, api_key=s.api_key(), model=s.model,
                                timeout=s.timeout_s)


def local_or_hub(folder_name: str, hub_name: str) -> str:
    """`data/models/<folder_name>` s'il a été téléchargé à la main (utile quand le réseau
    coupe les gros téléchargements Hugging Face), sinon le nom Hugging Face."""
    path = MODELS_DIR / folder_name
    return str(path) if (path / "config.json").exists() else hub_name


def cuda_available() -> bool:
    """GPU NVIDIA utilisable par faster-whisper (CTranslate2) ? Faux si la lib est absente."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 — pas de CUDA, pilote absent, lib non installée…
        return False


def resolve_device(device: str, compute_type: str) -> tuple[str, str]:
    """`auto` : GPU → (cuda, float16), sinon (cpu, int8) — le mode le plus rapide sans GPU.
    La même recette tourne ainsi sur un env Dataiku avec ou sans GPU, sans modification."""
    gpu = cuda_available() if device == "auto" else device == "cuda"
    dev = ("cuda" if gpu else "cpu") if device == "auto" else device
    ctype = ("float16" if gpu else "int8") if compute_type == "auto" else compute_type
    return dev, ctype


def build_transcriber(settings: Settings, model_size: str | None = None):
    from kb.adapters.transcribe_fw import FasterWhisperTranscriber

    t = settings.transcription
    size = model_size or t.model_size
    device, compute_type = resolve_device(t.device, t.compute_type)
    return FasterWhisperTranscriber(
        model_size=local_or_hub(f"faster-whisper-{size}", size),
        device=device, compute_type=compute_type, vad_filter=t.vad_filter,
    )


def build_store(settings: Settings):
    from kb.adapters.vs_chroma import ChromaStore

    return ChromaStore(settings.index_dir / "chroma")


def build_reranker(settings: Settings):
    from kb.adapters.rerank_bge import CrossEncoderReranker

    r = settings.retrieval
    return CrossEncoderReranker(
        local_or_hub(r.reranker_model.split("/")[-1], r.reranker_model), r.rerank_max_length
    )
