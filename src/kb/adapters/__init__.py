"""Les « prises » : chaque brique d'IA derrière une interface commune (voir base.py)."""

from kb.adapters.factory import build_embedder, build_llm

__all__ = ["build_llm", "build_embedder"]
