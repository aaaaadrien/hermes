"""
hermes_accounts.py
====================
Gestion des comptes utilisateurs pour Hermes (mode `authentification = userpass`)
Stockage persistant dans hermes-users.db (SQLite, créé automatiquement, voir en dessous)
Cette base contient aussi les tables des conversations (voir hermes_conversations.py)
et des sessions de connexion persistantes, qui réutilisent la connexion définie ici

Mot de passe jamais stocké en clair : PBKDF2-HMAC-SHA256 + sel aléatoire par compte
(bibliothèque standard, aucune dépendance externe type bcrypt, y a peut être mieux)

Connexion persistante ("rester connecté") : un jeton aléatoire est stocké en base
(table `sessions`) et déposé dans un cookie du navigateur via extra-streamlit-components
TODO dépendance tierce communautaire streamlit, à changer quand streamlit saura
     gérer les cookies en écriture

Importé par hermes-web.py :
    from hermes_accounts import ecran_connexion, obtenir_cookie_manager
"""

import hashlib
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import extra_streamlit_components as stx
import streamlit as st

FICHIER_DB = Path("hermes-users.db")
ITERATIONS_PBKDF2 = 200_000
NOM_COOKIE = "hermes_session"
DUREE_SESSION_JOURS = 30


# Connexion partagée (aussi utilisée par hermes_conversations.py)

def get_connection() -> sqlite3.Connection:
    """
    Ouvre (et crée la première fois) hermes-users.db avec le schéma complet
    (users, conversations, messages).
    BDD sqlite3 parce que pas un usage intensif et plus facile a gérer qu'un mariadb
    TODO a voir dans le temps la pertinence
    """
    con = sqlite3.connect(FICHIER_DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL") # mode WAL limite les verrous selon doc
    con.execute("PRAGMA foreign_keys=ON")
    # TODO : y a peut être mieux que faire à chaque connexion
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt          TEXT NOT NULL,
            created_at    INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            titre       TEXT NOT NULL,
            amphore_id  TEXT,
            created_at  INTEGER NOT NULL,
            updated_at  INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL,
            created_at      INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at  INTEGER NOT NULL,
            expire_at   INTEGER NOT NULL
        );
    """)
    con.commit()

    # Migration : colonne pieces_jointes (fichiers/images générés, en JSON) ajoutée après coup.
    # ALTER TABLE échoue silencieusement si la colonne existe déjà (bases créées avant cet ajout).
    # TODO A SUPPR DANS QUELQUES TEMPS
    try:
        con.execute("ALTER TABLE messages ADD COLUMN pieces_jointes TEXT")
        con.commit()
    except sqlite3.OperationalError:
        pass

    return con


# Hash de mot de passe (y a peut être mieux)
def _hash_mdp(mdp: str, sel_hex: Optional[str] = None) -> tuple[str, str]:
    """Retourne (hash_hex, sel_hex). Génère un sel aléatoire si non fourni."""
    sel = bytes.fromhex(sel_hex) if sel_hex else os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), sel, ITERATIONS_PBKDF2)
    return h.hex(), sel.hex()


# fonction créer un compte
def creer_compte(username: str, mdp: str) -> tuple[bool, str]:
    """
    Crée un compte
    Retourne (succès, message)
    """
    username = username.strip()
    if not username or not mdp:
        return False, "Nom d'utilisateur et mot de passe obligatoires."
    if len(mdp) < 6:
        return False, "Le mot de passe doit faire au moins 6 caractères."

    con = get_connection()
    try:
        existe = con.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existe:
            return False, f"Le compte « {username} » existe déjà."

        h, sel = _hash_mdp(mdp)
        con.execute(
            "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
            (username, h, sel, int(time.time())),
        )
        con.commit()
        return True, f"Compte « {username} » créé avec succès."
    finally:
        con.close()

# fonction changer le mot de passe d'un compte existant
def changer_mot_de_passe(user_id: int, mdp_actuel: str, nouveau_mdp: str) -> tuple[bool, str]:
    """
    Change le mot de passe d'un compte, après vérification du mot de passe actuel.
    Retourne (succès, message).
    """
    if len(nouveau_mdp) < 6:
        return False, "Le nouveau mot de passe doit faire au moins 6 caractères."

    con = get_connection()
    try:
        ligne = con.execute(
            "SELECT password_hash, salt FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not ligne:
            return False, "Compte introuvable."

        h_actuel, _ = _hash_mdp(mdp_actuel, ligne["salt"])
        if h_actuel != ligne["password_hash"]:
            return False, "Mot de passe actuel incorrect."

        h_nouveau, sel_nouveau = _hash_mdp(nouveau_mdp)
        con.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (h_nouveau, sel_nouveau, user_id),
        )
        con.commit()
        return True, "Mot de passe modifié avec succès."
    finally:
        con.close()


# fonction vérif un compte
def verifier_identifiants(username: str, mdp: str) -> Optional[dict]:
    """
    Vérifie le couple identifiant/mot de passe.
    Retourne {'id', 'username'} ou None.
    """
    username = username.strip()
    con = get_connection()
    try:
        ligne = con.execute(
            "SELECT id, username, password_hash, salt FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not ligne:
            return None
        h, _ = _hash_mdp(mdp, ligne["salt"])
        if h != ligne["password_hash"]:
            return None
        return {"id": ligne["id"], "username": ligne["username"]}
    finally:
        con.close()


# Sessions persistantes (jeton en base + cookie navigateur)
def creer_session(user_id: int, duree_jours: int = DUREE_SESSION_JOURS) -> str:
    """Crée une nouvelle session en base et retourne son jeton (à déposer en cookie)."""
    token = secrets.token_urlsafe(32)
    maintenant = int(time.time())
    con = get_connection()
    try:
        con.execute(
            "INSERT INTO sessions (token, user_id, created_at, expire_at) VALUES (?, ?, ?, ?)",
            (token, user_id, maintenant, maintenant + duree_jours * 86400),
        )
        con.commit()
        return token
    finally:
        con.close()


def verifier_session(token: str) -> Optional[dict]:
    """Vérifie un jeton de session. Retourne {'id', 'username'} ou None si absent/expiré."""
    con = get_connection()
    try:
        ligne = con.execute(
            "SELECT s.user_id AS id, u.username, s.expire_at FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        if not ligne:
            return None
        if ligne["expire_at"] < int(time.time()):
            con.execute("DELETE FROM sessions WHERE token = ?", (token,))
            con.commit()
            return None
        return {"id": ligne["id"], "username": ligne["username"]}
    finally:
        con.close()


def revoquer_session(token: str) -> None:
    """Supprime une session en base (à appeler à la déconnexion)."""
    con = get_connection()
    try:
        con.execute("DELETE FROM sessions WHERE token = ?", (token,))
        con.commit()
    finally:
        con.close()


# Écran de connexion Streamlit (intégration minimale dans hermes-web.py pour pas charger le code principal)
def obtenir_cookie_manager() -> stx.CookieManager:
    """
    Instancie le gestionnaire de cookies. À appeler UNE SEULE FOIS par run de
    script (depuis hermes-web.py), puis à repasser en paramètre à ecran_connexion()
    et deconnexion().
    """
    return stx.CookieManager()


def ecran_connexion(cookie_manager: stx.CookieManager, register: bool = False) -> Optional[dict]:
    """
    Point d'entrée unique appelé depuis hermes-web.py
    
    - cookie_manager : instance unique créée une fois par run via obtenir_cookie_manager()
    - register : reflète l'option register de la section [auth] 

    - Si l'utilisateur est déjà connecté dans cette session (ou via le cookie) : 
      - retourne son dict ({'id', 'username'}) continue

    Connexion : à la connexion, un jeton est créé en base et déposé dans un cookie navigateur
     
    Déconnexion : le bouton déconnexion met st.session_state["auth_afficher_deconnexion"] = True
    et affiche un écran de confirmation avant d'effectuer réellement la déconnexion.
    (pas top mais plus facile que de refresh la page)
    """
    # Reconnexion automatique via le cookie (si pas déjà authentifié dans la session)
    if "auth_user" not in st.session_state:
        token = cookie_manager.get(cookie=NOM_COOKIE)
        if token:
            utilisateur = verifier_session(token)
            if utilisateur:
                st.session_state["auth_user"] = utilisateur
                st.session_state["auth_token"] = token

    if "auth_user" in st.session_state:
        if not st.session_state.get("auth_afficher_deconnexion"):
            return st.session_state["auth_user"]

        # Écran de confirmation de déconnexion
        st.title("🔐 Déconnexion")
        st.write(f"Vous êtes connecté en tant que **{st.session_state['auth_user']['username']}**.")

        c1, c2 = st.columns(2)
        if c1.button("Se déconnecter", use_container_width=True, type="primary"):
            deconnexion_effective(cookie_manager)
            st.rerun()
        if c2.button("Annuler", use_container_width=True):
            st.session_state.pop("auth_afficher_deconnexion", None)
            st.rerun()

        st.stop()

    if not st.session_state.get("auth_afficher_connexion"):
        return None

    st.title("🔐 Connexion")

    if register:
        onglet_connexion, onglet_creation = st.tabs(["Connexion", "Créer un compte"])
    else:
        onglet_connexion = st.container()
        onglet_creation = None

    with onglet_connexion:
        with st.form("form_connexion"):
            u = st.text_input("Utilisateur")
            p = st.text_input("Mot de passe", type="password")
            valide = st.form_submit_button("Se connecter", use_container_width=True)
        if valide:
            utilisateur = verifier_identifiants(u, p)
            if utilisateur:
                token = creer_session(utilisateur["id"])
                cookie_manager.set(
                    NOM_COOKIE,
                    token,
                    expires_at=datetime.now() + timedelta(days=DUREE_SESSION_JOURS),
                    key="set_hermes_session_cookie",
                )
                st.session_state["auth_user"] = utilisateur
                st.session_state["auth_token"] = token
                st.session_state.pop("auth_afficher_connexion", None)
                time.sleep(0.5)  # laisse le temps au composant JS d'écrire le cookie
                st.rerun()
            else:
                st.error("❌ Identifiant ou mot de passe incorrect.")

    if register:
        with onglet_creation:
            with st.form("form_creation"):
                u2 = st.text_input("Choisir un nom d'utilisateur")
                p2 = st.text_input("Choisir un mot de passe", type="password")
                p2b = st.text_input("Confirmer le mot de passe", type="password")
                creer = st.form_submit_button("Créer le compte", use_container_width=True)
            if creer:
                if p2 != p2b:
                    st.error("❌ Les mots de passe ne correspondent pas.")
                else:
                    ok, message = creer_compte(u2, p2)
                    if ok:
                        st.success(f"✅ {message} Vous pouvez vous connecter dans l'onglet « Connexion ».")
                    else:
                        st.error(f"❌ {message}")

    st.divider()
    if st.button("← Continuer sans compte", use_container_width=True):
        st.session_state.pop("auth_afficher_connexion", None)
        st.rerun()

    st.stop()


def deconnexion_effective(cookie_manager: stx.CookieManager) -> None:
    """
    Effectue réellement la déconnexion : révoque la session en base, supprime
    le cookie, et nettoie st.session_state. Appelée uniquement depuis l'écran
    de confirmation de ecran_connexion() avc le bouton Se déconnecter.
    """
    token = st.session_state.get("auth_token")
    if token:
        revoquer_session(token)
        try:
            # TODO Y a mieux je pense pour contourner le bug 
            cookie_manager.delete(NOM_COOKIE, key="delete_hermes_session_cookie")
        except KeyError:
            pass
    st.session_state.pop("auth_user", None)
    st.session_state.pop("auth_token", None)
    st.session_state.pop("auth_afficher_connexion", None)
    st.session_state.pop("auth_afficher_deconnexion", None)
    st.session_state.pop("conversation_id", None)
    st.session_state.pop("messages", None)
