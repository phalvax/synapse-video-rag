"""Déclencheur Python personnalisé du scénario `INGEST` (Dataiku → Scénario → Triggers →
« Custom trigger (Python) »).

Statut : **kit, non testé sur une vraie instance Dataiku**.

Le scénario actuel de l'équipe vérifie le dossier toutes les 30 min. Deux améliorations :
1. **Ce déclencheur** ne lance le scénario QUE s'il y a un fichier média pas encore traité
   (comparaison du dossier `video` avec le dataset `videos`) → on peut le faire tourner
   souvent (ex. toutes les 1-2 min, réglage « Run every » du trigger) sans relancer la chaîne
   pour rien.
2. **Immédiat après un upload** : voir `upload_hook.py` (la Web App lance le scénario elle-même).
Les deux sont complémentaires : le hook pour la réactivité, ce trigger comme filet de sécurité
(fichier déposé à la main dans le dossier, Web App arrêtée…).
"""

from __future__ import annotations

from pathlib import Path

import dataiku
from dataiku.scenario import Trigger

from kb.ingest.sources import MEDIA_EXTENSIONS, _split_part, slugify

FOLDER_NAME = "video"
VIDEOS_DATASET = "videos"


def pending_video_ids() -> set[str]:
    """Identifiants des enregistrements présents dans le dossier mais pas encore transcrits."""
    in_folder = {
        slugify(_split_part(Path(p).stem)[0])
        for p in dataiku.Folder(FOLDER_NAME).list_paths_in_partition()
        if Path(p).suffix.lower() in MEDIA_EXTENSIONS
    }
    try:
        done = set(dataiku.Dataset(VIDEOS_DATASET).get_dataframe(columns=["video_id"])["video_id"])
    except Exception:  # noqa: BLE001 — dataset jamais construit : tout est à traiter
        done = set()
    return in_folder - done


pending = pending_video_ids()
if pending:
    print(f"{len(pending)} enregistrement(s) à traiter : {', '.join(sorted(pending))}")
    Trigger().fire()
