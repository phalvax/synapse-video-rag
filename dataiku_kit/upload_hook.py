"""Traitement IMMÉDIAT après un upload dans la Web App Dataiku (au lieu d'attendre le scénario).

Statut : **kit, non testé sur une vraie instance Dataiku**.

À appeler dans le backend Python de la Web App, juste après l'écriture du fichier dans le
managed folder partagé. Le scénario `INGEST` (transcription des nouveaux fichiers → chunks →
embeddings / Knowledge Bank) démarre tout de suite, sans bloquer la requête HTTP.

    from upload_hook import save_and_process
    save_and_process(request.files["file"].filename, request.files["file"].stream,
                     meta={"title": "...", "mission": "ES2002", "date": "2026-09-12"})

Le formulaire (titre, mission, date, auteur, contact, description, langue) est enregistré à
côté du fichier (`<nom>.meta.json`) : `recipe_ingest.py` peut le relire pour l'appliquer, comme
le fait l'API locale (`kb.ingest.metadata`).
"""

from __future__ import annotations

import io
import json
from typing import BinaryIO

import dataiku

FOLDER_NAME = "video"
SCENARIO_ID = "INGEST"


def save_and_process(filename: str, stream: BinaryIO, meta: dict | None = None) -> str:
    """Écrit le fichier (et son formulaire) dans le dossier partagé, puis lance le scénario.

    Renvoie l'identifiant du run de scénario (pour afficher l'avancement dans la Web App)."""
    folder = dataiku.Folder(FOLDER_NAME)
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]  # jamais de chemin fourni par le client
    folder.upload_stream(name, stream)
    if meta:
        payload = {k: v for k, v in meta.items() if v not in (None, "")}
        folder.upload_stream(f"{name}.meta.json", io.BytesIO(json.dumps(payload).encode("utf-8")))
    scenario = dataiku.api_client().get_default_project().get_scenario(SCENARIO_ID)
    run = scenario.run()  # non bloquant : la Web App répond tout de suite
    return getattr(run, "id", str(run))
