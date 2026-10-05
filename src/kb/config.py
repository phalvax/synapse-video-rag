"""Chargement de la configuration : fichier .env + profil YAML (free | dataiku | market).

Les valeurs `${VAR}` ou `${VAR:-défaut}` des profils sont remplacées par les variables
d'environnement, pour que le même profil marche sur tous les PC sans modifier le code.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = ROOT / "profiles"
MODELS_DIR = ROOT / "data" / "models"  # modèles téléchargés à la main (optionnel)
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    """Remplace récursivement ${VAR} / ${VAR:-défaut} par les variables d'environnement."""
    if isinstance(value, str):
        return _VAR.sub(lambda m: os.getenv(m.group(1)) or (m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class ModelOption(BaseModel):
    """Un modèle sélectionnable pour ce profil (ex. Luna / Terra / Sol côté Dataiku)."""

    id: str
    label: str = ""
    input_per_m: float = 0.0
    output_per_m: float = 0.0


class EndpointSettings(BaseModel):
    """Une « prise » compatible OpenAI (Ollama, Dataiku LLM Mesh, autre fournisseur)."""

    base_url: str
    model: str
    api_key_env: str | None = None
    temperature: float | None = 0.0  # None = ne pas envoyer le paramètre
    input_per_m: float = 0.0  # tarif $ / million de tokens en entrée (0 = gratuit)
    output_per_m: float = 0.0  # tarif $ / million de tokens en sortie
    timeout_s: float = 120.0  # un LLM local sur CPU peut dépasser la minute
    # Modèles qu'un appelant (front, Web App Dataiku) peut choisir par requête ; vide = seul
    # `model` est autorisé. Chaque choix porte SON tarif (sinon le coût affiché serait faux).
    models: list[ModelOption] = []

    def options(self) -> list[ModelOption]:
        """Modèles autorisés ; le modèle par défaut du profil en premier, toujours présent."""
        listed = [m for m in self.models if m.id != self.model]
        default = next((m for m in self.models if m.id == self.model), None) or ModelOption(
            id=self.model, label=self.model, input_per_m=self.input_per_m,
            output_per_m=self.output_per_m)
        return [default, *listed]

    def with_model(self, model_id: str) -> EndpointSettings:
        """Copie des réglages pour ce modèle (tarifs compris) ; ValueError s'il est interdit."""
        for m in self.options():
            if m.id == model_id:
                return self.model_copy(update={"model": m.id, "input_per_m": m.input_per_m,
                                               "output_per_m": m.output_per_m})
        allowed = ", ".join(m.id for m in self.options())
        raise ValueError(f"modèle non autorisé pour ce profil : {model_id} (choix : {allowed})")

    def api_key(self) -> str:
        if not self.api_key_env:
            return "not-needed"
        return os.getenv(self.api_key_env) or "not-needed"


class TranscriptionSettings(BaseModel):
    engine: str = "faster-whisper"
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str | None = None
    vad_filter: bool = True


class VisionSettings(BaseModel):
    """Images et pages scannées : OCR (Tesseract) + description par le LLM de vision."""

    describe: bool = True  # False : OCR seul (le LLM de vision coûte ~1 min par image sur CPU)
    frames: bool = True  # vidéos : lire aussi ce qui est MONTRÉ (diapos, tableau) — ingest.frames
    max_video_descriptions: int = 8  # plafond de descriptions IA par vidéo (coût)


class RetrievalSettings(BaseModel):
    top_k: int = 20  # candidats de chaque détective (dense, BM25) avant fusion
    rerank_candidates: int = 8  # passages soumis au cross-encoder (coût CPU ∝ ce nombre)
    rerank_max_length: int = 512  # tokens (question + passage) vus par le cross-encoder
    rerank_top_n: int = 5
    abstain_threshold: float = 0.35  # sur le score du reranker (0..1)
    chunk_target_tokens: int = 400
    chunk_overlap_segments: int = 1
    rrf_k: int = 60
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    answer_sources: int = 3  # passages envoyés au LLM pour rédiger la réponse
    # Langue du corpus : la question est traduite vers elle avant la recherche (agent/query.py).
    # None = pas de traduction (aucun appel LLM en plus).
    query_language: str | None = None


class Settings(BaseModel):
    profile: str
    llm: EndpointSettings
    embedding: EndpointSettings
    transcription: TranscriptionSettings = TranscriptionSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    vision: VisionSettings = VisionSettings()
    data_dir: Path = ROOT / "data"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def videos_file(self) -> Path:
        return self.data_dir / "videos.jsonl"

    @property
    def kb_db_file(self) -> Path:
        return self.data_dir / "kb.sqlite"

    @property
    def index_dir(self) -> Path:
        """Un index par profil : les embeddings bge-m3 et Embedding v3 Small ne se mélangent pas."""
        return self.data_dir / "index" / self.profile


def load_settings(profile: str | None = None) -> Settings:
    """Charge `.env` puis `profiles/<profile>.yaml` (PROFILE=free par défaut)."""
    load_dotenv(ROOT / ".env")
    name = profile or os.getenv("PROFILE", "free")
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))
        raise FileNotFoundError(f"Profil '{name}' introuvable. Disponibles : {available}")
    raw = _expand(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return Settings(profile=name, **raw)
