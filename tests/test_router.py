"""Routage « point de situation » → point mission, sans LLM."""

import pytest

from kb.agent.router import recap_target

MISSIONS = ["ES2002", "ES2004"]


@pytest.mark.parametrize("question, expected", [
    ("Fais-moi un point sur la mission ES2002", "ES2002"),
    ("Où en est le projet es2004 ?", "ES2004"),
    ("Résumé des réunions ES2002 stp", "ES2002"),
    ("What is the progress of ES2004?", "ES2004"),
    ("Quel est le prix de vente de la télécommande ?", None),          # question ordinaire
    ("Quel bouton a été choisi dans ES2002 ?", None),                   # mission, pas d'intention
    ("Fais-moi un point sur le projet", None),                          # 2 missions : ambigu
    ("Compare l'avancement de ES2002 et ES2004", None),                 # 2 missions nommées
])
def test_recap_target(question, expected):
    assert recap_target(question, MISSIONS) == expected


def test_single_mission_can_be_implicit():
    assert recap_target("Où en est le projet ?", ["ES2002"]) == "ES2002"
    assert recap_target("Où en est le projet ?", []) is None
