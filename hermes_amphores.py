"""
hermes_amphores.py
====================
Gestion des contextes système (Amphores) pour Hermes.
Chaque contexte définit un nom, une description et un prompt système.
Stockage persistant dans hermes-amphores.json (créé automatiquement).

Importé par hermes-web.py.

Utilisation :
    from hermes_amphores import (
        charger_amphores, sauvegarder_amphores, amphore_par_id,
        creer_amphore, mettre_a_jour_amphore, supprimer_amphore, ID_DEFAUT
    )
"""

import json
import re
import time
from pathlib import Path
from typing import Optional

FICHIER_AMPHORES = Path("hermes-amphores.json")
ID_DEFAUT        = "defaut"


# Helpers internes

def _amphore_id_depuis_nom(nom: str) -> str:
    """Génère un identifiant unique et lisible depuis un nom."""
    base = re.sub(r"[^a-z0-9]+", "_", nom.lower().strip()).strip("_") or "amphore"
    return f"{base}_{int(time.time()) % 100000:05d}"


def _amphore_defaut(sys_prompt: str) -> dict:
    return {
        "id":            ID_DEFAUT,
        "nom":           "Par défaut",
        "description":   "",
        "system_prompt": sys_prompt,
    }


# API publique

def charger_amphores(sys_prompt_conf: str) -> list[dict]:
    """
    Charge les amphores depuis hermes-amphores.json.
    Si le fichier n'existe pas, le crée avec une amphore 'Par défaut'
    dont le prompt est celui de hermes.conf.
    """
    if not FICHIER_AMPHORES.exists():
        amphores = [_amphore_defaut(sys_prompt_conf)]
        sauvegarder_amphores(amphores)
        return amphores
    try:
        with open(FICHIER_AMPHORES, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return [_amphore_defaut(sys_prompt_conf)]


def sauvegarder_amphores(amphores: list[dict]) -> None:
    """Persiste la liste complète des amphores dans hermes-amphores.json."""
    with open(FICHIER_AMPHORES, "w", encoding="utf-8") as f:
        json.dump(amphores, f, ensure_ascii=False, indent=2)


def amphore_par_id(amphores: list[dict], amphore_id: str) -> Optional[dict]:
    """Retourne un amphore par son id, ou None si introuvable."""
    return next((a for a in amphores if a["id"] == amphore_id), None)


def creer_amphore(nom: str, system_prompt: str, description: str = "") -> dict:
    """Crée une nouvelle amphore avec un identifiant unique."""
    return {
        "id":            _amphore_id_depuis_nom(nom),
        "nom":           nom.strip(),
        "description":   description.strip(),
        "system_prompt": system_prompt.strip(),
    }


def mettre_a_jour_amphore(amphores: list[dict], amphore_id: str, **champs) -> list[dict]:
    """
    Met à jour les champs d'une amphore existante.
    Retourne une nouvelle liste (non-mutant).
    """
    return [
        {**a, **champs} if a["id"] == amphore_id else a
        for a in amphores
    ]


def supprimer_amphore(amphores: list[dict], amphore_id: str) -> list[dict]:
    """
    Supprime une amphore par son id.
    L'amphore 'defaut' est protégé et ne peut pas être supprimé.
    """
    if amphore_id == ID_DEFAUT:
        return amphores
    return [a for a in amphores if a["id"] != amphore_id]
