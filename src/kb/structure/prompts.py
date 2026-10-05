"""Prompts L1 Structuration : transcript → fiches REX (CLAUDE.md, section 4)."""

from __future__ import annotations

SYSTEM = """Tu remplis des fiches de retour d'expérience (REX) à partir d'une transcription.

Règles :
1. N'utilise QUE le contenu de la transcription fournie. Aucune connaissance extérieure.
2. Une fiche par problème technique distinct réellement traité dans l'extrait. Zéro fiche
   si rien de tel n'est traité : réponds alors {"fiches": []}.
3. `evidence_quote` doit être un passage RECOPIÉ MOT POUR MOT de la transcription (pas de
   reformulation), d'au moins 12 caractères.
4. Un champ dont l'information est absente est `null` (ou [] pour technologies) : n'invente
   jamais un client, un auteur ou une techno non mentionnés.
5. `start_s` / `end_s` sont les timestamps (en secondes) de l'extrait qui contient la preuve.
6. Réponds en JSON valide, sans texte autour, au format demandé."""

FICHES_SCHEMA = {
    "type": "object",
    "properties": {
        "fiches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "problem": {"type": "string"},
                    "solution": {"type": ["string", "null"]},
                    "technologies": {"type": "array", "items": {"type": "string"}},
                    "client": {"type": ["string", "null"]},
                    "author": {"type": ["string", "null"]},
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                    "evidence_quote": {"type": "string"},
                },
                "required": ["problem", "start_s", "end_s", "evidence_quote"],
            },
        },
    },
    "required": ["fiches"],
}

USER_TEMPLATE = """Transcription horodatée de « {title} » :

{transcript}

Réponds en JSON : {{"fiches": [{{"problem": "…", "solution": "…ou null", \
"technologies": ["…"], "client": "…ou null", "author": "…ou null", "start_s": 12, \
"end_s": 48, "evidence_quote": "extrait mot pour mot"}}]}}
Si rien à extraire : {{"fiches": []}}"""
