"""Reranker cross-encoder (le « jury d'entretien ») : lit la question ET le passage ensemble."""

from __future__ import annotations


class CrossEncoderReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", max_length: int = 512) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self._model = CrossEncoder(model_name, max_length=max_length, device="cpu")

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        """Score de pertinence entre 0 et 1 (sigmoïde) pour chaque passage.

        Ce n'est PAS une probabilité calibrée : le seuil d'abstention se choisit sur le golden set.
        """
        if not docs:
            return []
        import torch

        scores = self._model.predict(
            [(query, d) for d in docs], activation_fn=torch.nn.Sigmoid(), show_progress_bar=False
        )
        return [float(s) for s in scores]
