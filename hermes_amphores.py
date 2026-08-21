"""
hermes_amphores.py
====================
Gestion des contextes système (Amphores) pour Hermes.
Chaque contexte définit un nom, une description et un prompt système.

Deux origines possibles, toutes deux stockées dans hermes.db (SQLite, via
hermes_accounts.get_connection) :
- Amphores globales : partagées par tout le monde, table amphores_global.
- Amphores perso : propres à un utilisateur authentifié, table amphores_perso.
  Nécessitent donc [auth] authentification = userpass.

Importé par hermes-web.py.

Utilisation :
    from hermes_amphores import (
        charger_amphores, sauvegarder_amphores, amphore_par_id,
        creer_amphore, mettre_a_jour_amphore, supprimer_amphore, ID_DEFAUT,
        charger_amphores_perso, creer_amphore_perso,
        mettre_a_jour_amphore_perso, supprimer_amphore_perso,
    )
"""

import re
import time
from typing import Optional

ID_DEFAUT = "defaut"


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


def _connexion_global():
    """
    Ouvre la connexion partagée (hermes.db) et s'assure que la table
    amphores_global existe. Import différé de hermes_accounts pour ne pas
    imposer cette dépendance (sqlite3, extra_streamlit_components...) inutilement.
    """
    from hermes_accounts import get_connection
    con = get_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS amphores_global (
            id            TEXT PRIMARY KEY,
            nom           TEXT NOT NULL,
            description   TEXT,
            system_prompt TEXT NOT NULL,
            created_at    INTEGER NOT NULL
        )
    """)
    con.commit()
    return con


# API publique pour Amphores globales (SQLite, table amphores_global)

def charger_amphores(sys_prompt_conf: str) -> list[dict]:
    """
    Charge les amphores globales depuis hermes.db.
    Si aucune amphore 'Par défaut' n'existe encore, la crée avec le prompt de hermes.conf.
    """
    con = _connexion_global()
    try:
        lignes = con.execute(
            "SELECT id, nom, description, system_prompt FROM amphores_global ORDER BY created_at ASC"
        ).fetchall()
        amphores = [dict(l) for l in lignes]
    finally:
        con.close()

    if not any(a["id"] == ID_DEFAUT for a in amphores):
        amphores = [_amphore_defaut(sys_prompt_conf)] + amphores
        sauvegarder_amphores(amphores)
    return amphores


def sauvegarder_amphores(amphores: list[dict]) -> None:
    """
    Persiste la liste complète des amphores globales dans hermes.db (synchronisation
    complète : insère/actualise chaque amphore de la liste, supprime celles absentesn
    même sémantique que l'ancien remplacement intégral du fichier JSON).
    """
    con = _connexion_global()
    try:
        ids_conserves = [a["id"] for a in amphores]
        if ids_conserves:
            placeholders = ",".join("?" * len(ids_conserves))
            con.execute(f"DELETE FROM amphores_global WHERE id NOT IN ({placeholders})", ids_conserves)
        else:
            con.execute("DELETE FROM amphores_global")
        for a in amphores:
            con.execute(
                "INSERT INTO amphores_global (id, nom, description, system_prompt, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET nom=excluded.nom, description=excluded.description, "
                "system_prompt=excluded.system_prompt",
                (a["id"], a["nom"], a.get("description", ""), a["system_prompt"], int(time.time())),
            )
        con.commit()
    finally:
        con.close()


def amphore_par_id(amphores: list[dict], amphore_id: str) -> Optional[dict]:
    """Retourne un amphore par son id, ou None si introuvable (globale ou perso)."""
    return next((a for a in amphores if a["id"] == amphore_id), None)


def creer_amphore(nom: str, system_prompt: str, description: str = "") -> dict:
    """Crée une nouvelle amphore globale avec un identifiant unique (pas encore persistée :
    à ajouter à la liste puis passer à sauvegarder_amphores)."""
    return {
        "id":            _amphore_id_depuis_nom(nom),
        "nom":           nom.strip(),
        "description":   description.strip(),
        "system_prompt": system_prompt.strip(),
    }


def mettre_a_jour_amphore(amphores: list[dict], amphore_id: str, **champs) -> list[dict]:
    """
    Met à jour les champs d'une amphore globale existante dans une liste en mémoire.
    Retourne une nouvelle liste (non-mutante), à persister ensuite via sauvegarder_amphores.
    """
    return [
        {**a, **champs} if a["id"] == amphore_id else a
        for a in amphores
    ]


def supprimer_amphore(amphores: list[dict], amphore_id: str) -> list[dict]:
    """
    Supprime une amphore globale par son id dans une liste en mémoire.
    L'amphore 'defaut' est protégée et ne peut pas être supprimée.
    Retourne une nouvelle liste, à persister ensuite via sauvegarder_amphores.
    """
    if amphore_id == ID_DEFAUT:
        return amphores
    return [a for a in amphores if a["id"] != amphore_id]


# API publique pour Amphores personnelles (SQLite, table amphores_perso, par utilisateur authentifié)

def _connexion_perso():
    """
    Ouvre la connexion partagée (hermes.db) et s'assure que la table
    amphores_perso existe. Import différé de hermes_accounts pour ne pas
    imposer cette dépendance (sqlite3, extra_streamlit_components...) quand
    l'authentification est désactivée ([auth] authentification = none).
    """
    from hermes_accounts import get_connection
    con = get_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS amphores_perso (
            id            TEXT PRIMARY KEY,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            nom           TEXT NOT NULL,
            description   TEXT,
            system_prompt TEXT NOT NULL,
            created_at    INTEGER NOT NULL
        )
    """)
    con.commit()
    return con


def _amphore_perso_id_depuis_nom(user_id: int, nom: str) -> str:
    """Identifiant unique préfixé par l'utilisateur, pour ne jamais entrer en
    collision avec un id d'amphore globale ni celui d'un autre utilisateur."""
    base = re.sub(r"[^a-z0-9]+", "_", nom.lower().strip()).strip("_") or "amphore"
    return f"perso_{user_id}_{base}_{int(time.time()) % 100000:05d}"


def charger_amphores_perso(user_id: int) -> list[dict]:
    """Charge les amphores perso d'un utilisateur, dans l'ordre de création."""
    con = _connexion_perso()
    try:
        lignes = con.execute(
            "SELECT id, nom, description, system_prompt FROM amphores_perso "
            "WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        ).fetchall()
        return [dict(l) for l in lignes]
    finally:
        con.close()


def creer_amphore_perso(user_id: int, nom: str, system_prompt: str, description: str = "") -> dict:
    """Crée une nouvelle amphore perso pour un utilisateur et la retourne."""
    nouvel_amphore = {
        "id":            _amphore_perso_id_depuis_nom(user_id, nom),
        "nom":           nom.strip(),
        "description":   description.strip(),
        "system_prompt": system_prompt.strip(),
    }
    con = _connexion_perso()
    try:
        con.execute(
            "INSERT INTO amphores_perso (id, user_id, nom, description, system_prompt, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nouvel_amphore["id"], user_id, nouvel_amphore["nom"],
             nouvel_amphore["description"], nouvel_amphore["system_prompt"], int(time.time())),
        )
        con.commit()
    finally:
        con.close()
    return nouvel_amphore


def mettre_a_jour_amphore_perso(user_id: int, amphore_id: str, **champs) -> None:
    """Met à jour une amphore perso (uniquement si elle appartient à user_id)."""
    permis = {k: v for k, v in champs.items() if k in ("nom", "description", "system_prompt")}
    if not permis:
        return
    con = _connexion_perso()
    try:
        colonnes = ", ".join(f"{k} = ?" for k in permis)
        con.execute(
            f"UPDATE amphores_perso SET {colonnes} WHERE id = ? AND user_id = ?",
            (*permis.values(), amphore_id, user_id),
        )
        con.commit()
    finally:
        con.close()


def supprimer_amphore_perso(user_id: int, amphore_id: str) -> None:
    """Supprime une amphore perso (uniquement si elle appartient à user_id)."""
    con = _connexion_perso()
    try:
        con.execute("DELETE FROM amphores_perso WHERE id = ? AND user_id = ?", (amphore_id, user_id))
        con.commit()
    finally:
        con.close()
