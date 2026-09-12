"""
hermes_accounts.py
====================
Gestion des comptes utilisateurs pour Hermes (mode `authentification = userpass`)
Stockage persistant dans hermes.db (SQLite, créé automatiquement, voir en dessous)
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

FICHIER_DB = Path("data/hermes.db")

ITERATIONS_PBKDF2 = 200_000
NOM_COOKIE = "hermes_session"
DUREE_SESSION_JOURS = 30


# Connexion partagée (aussi utilisée par hermes_conversations.py)

def get_connection() -> sqlite3.Connection:
    """
    Ouvre (et crée la première fois) hermes.db avec le schéma complet
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

    # Migration : colonne is_admin (préparation d'une future gestion des droits/utilisateurs).
    # ALTER TABLE échoue silencieusement si la colonne existe déjà (bases créées avant cet ajout).
    # TODO A SUPPR DANS QUELQUES TEMPS
    try:
        con.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        con.commit()
    except sqlite3.OperationalError:
        pass

    # Migration : colonne is_active (désactivation de compte sans suppression, gérée par un admin).
    # ALTER TABLE échoue silencieusement si la colonne existe déjà (bases créées avant cet ajout).
    # TODO A SUPPR DANS QUELQUES TEMPS
    try:
        con.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        con.commit()
    except sqlite3.OperationalError:
        pass

    # Migration : colonnes auth_provider ('local' ou 'oidc') et oidc_sub (identifiant stable
    # côté fournisseur OIDC, claim 'sub' du id_token) pour les comptes provisionnés via SSO.
    # ALTER TABLE échoue silencieusement si les colonnes existent déjà (bases créées avant cet ajout).
    # TODO A SUPPR DANS QUELQUES TEMPS
    try:
        con.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT NOT NULL DEFAULT 'local'")
        con.commit()
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE users ADD COLUMN oidc_sub TEXT")
        con.commit()
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oidc_sub ON users(oidc_sub) WHERE oidc_sub IS NOT NULL")
        con.commit()
    except sqlite3.OperationalError:
        pass

    # Premier lancement : si le compte id=1 n'existe pas encore, crée un compte admin par défaut
    # (identifiant "admin" / mot de passe "admin"), marqué is_admin=1. À changer immédiatement
    # via le formulaire de changement de mot de passe une fois connecté.
    existe_id_1 = con.execute("SELECT 1 FROM users WHERE id = 1").fetchone()
    if not existe_id_1:
        h, sel = _hash_mdp("admin")
        con.execute(
            "INSERT INTO users (id, username, password_hash, salt, created_at, is_admin) "
            "VALUES (1, 'admin', ?, ?, ?, 1)",
            (h, sel, int(time.time())),
        )
        con.commit()

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


# fonction résoudre (ou créer au premier login) le compte local associé à un utilisateur OIDC
def resoudre_ou_creer_utilisateur_oidc(sub: str, username_prefere: str) -> dict:
    """
    Retourne le compte local lié au claim 'sub' du id_token OIDC (identifiant stable
    côté fournisseur d'identité). Le crée automatiquement à la première connexion
    (auth_provider='oidc', mot de passe local inutilisable généré aléatoirement,
    ces comptes ne peuvent de toute façon jamais se connecter via le formulaire mdp).

    username_prefere : claim 'preferred_username' (ou équivalent) du id_token, utilisé
    comme nom affiché. En cas de collision avec un compte local existant (username
    différent auth_provider), un suffixe dérivé de sub est ajouté pour rester unique!

    Retourne {'id', 'username', 'is_admin', 'auth_provider'}.
    """
    con = get_connection()
    try:
        ligne = con.execute(
            "SELECT id, username, is_admin, auth_provider, is_active FROM users WHERE oidc_sub = ?",
            (sub,),
        ).fetchone()
        if ligne:
            return {
                "id": ligne["id"], "username": ligne["username"],
                "is_admin": bool(ligne["is_admin"]), "auth_provider": ligne["auth_provider"],
            }

        # Premier login : provisioning du compte local
        username = (username_prefere or f"oidc_{sub[:8]}").strip()
        collision = con.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if collision:
            username = f"{username}_{sub[:6]}"

        # Mot de passe local inutilisable (aléatoire, jamais communiqué) : les comptes OIDC
        # ne se connectent que via le bouton SSO, jamais via le formulaire mot de passe.
        # Y a peut etre mieux mais on laisse comme ça
        h, sel = _hash_mdp(secrets.token_urlsafe(32))
        cur = con.execute(
            "INSERT INTO users (username, password_hash, salt, created_at, auth_provider, oidc_sub) "
            "VALUES (?, ?, ?, ?, 'oidc', ?)",
            (username, h, sel, int(time.time()), sub),
        )
        con.commit()
        return {"id": cur.lastrowid, "username": username, "is_admin": False, "auth_provider": "oidc"}
    finally:
        con.close()


# fonction changer le mot de passe d'un compte existant
def changer_mot_de_passe(user_id: int, mdp_actuel: str, nouveau_mdp: str) -> tuple[bool, str]:
    """
    Change le mot de passe d'un compte, après vérification du mot de passe actuel.
    Refuse pour un compte OIDC (géré par le fournisseur d'identité, pas par Hermes).
    Retourne (succès, message).
    """
    if len(nouveau_mdp) < 6:
        return False, "Le nouveau mot de passe doit faire au moins 6 caractères."

    con = get_connection()
    try:
        ligne = con.execute(
            "SELECT password_hash, salt, auth_provider FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not ligne:
            return False, "Compte introuvable."
        if ligne["auth_provider"] == "oidc":
            return False, "Ce compte est géré via SSO (OIDC) : le mot de passe ne peut pas être changé ici."

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


# fonction (admin) réinitialiser le mot de passe d'un utilisateur SANS connaître l'ancien
def reinitialiser_mot_de_passe(user_id: int, nouveau_mdp: str) -> tuple[bool, str]:
    """
    Change le mot de passe d'un compte sans vérifier l'ancien (usage réservé à un admin,
    contrairement à changer_mot_de_passe qui exige le mot de passe actuel).
    Refuse pour un compte OIDC (géré par le fournisseur d'identité, pas par Hermes).
    Retourne (succès, message).
    """
    if len(nouveau_mdp) < 6:
        return False, "Le nouveau mot de passe doit faire au moins 6 caractères."

    con = get_connection()
    try:
        ligne = con.execute("SELECT auth_provider FROM users WHERE id = ?", (user_id,)).fetchone()
        if not ligne:
            return False, "Compte introuvable."
        if ligne["auth_provider"] == "oidc":
            return False, "Ce compte est géré via SSO (OIDC) : son mot de passe ne peut pas être réinitialisé ici."

        h_nouveau, sel_nouveau = _hash_mdp(nouveau_mdp)
        con.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (h_nouveau, sel_nouveau, user_id),
        )
        con.commit()
        return True, "Mot de passe réinitialisé avec succès."
    finally:
        con.close()


# fonction (admin) lister tous les comptes
def lister_utilisateurs() -> list[dict]:
    """Liste tous les comptes utilisateurs, triés par nom. Retourne id/username/is_admin/is_active/auth_provider/created_at."""
    con = get_connection()
    try:
        lignes = con.execute(
            "SELECT id, username, is_admin, is_active, auth_provider, created_at FROM users ORDER BY username ASC"
        ).fetchall()
        return [
            {
                "id": l["id"], "username": l["username"],
                "is_admin": bool(l["is_admin"]), "is_active": bool(l["is_active"]),
                "auth_provider": l["auth_provider"], "created_at": l["created_at"],
            }
            for l in lignes
        ]
    finally:
        con.close()


# fonction (admin) définir/retirer le statut administrateur d'un compte
def definir_admin(user_id: int, is_admin: bool) -> tuple[bool, str]:
    """
    Définit (ou retire) le statut administrateur d'un compte.
    Retourne (succès, message).
    """
    con = get_connection()
    try:
        existe = con.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if not existe:
            return False, "Compte introuvable."
        con.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, user_id))
        con.commit()
        return True, "Statut administrateur mis à jour."
    finally:
        con.close()


# fonction (admin) activer/désactiver un compte (sans le supprimer)
def definir_actif(user_id: int, is_active: bool, acteur_id: Optional[int] = None) -> tuple[bool, str]:
    """
    Active ou désactive un compte. Un compte désactivé ne peut plus se connecter
    (identifiants refusés, sessions existantes révoquées immédiatement) mais ses
    données (conversations, amphores perso...) sont conservées.

    acteur_id : id de l'admin qui effectue l'action (pour empêcher l'auto-désactivation).

    Règles de désactivation :
      - Un admin ne peut pas désactiver son propre compte (acteur_id == user_id).
      - Un compte administrateur (y compris id=1) ne peut être désactivé que s'il reste
        au moins un autre compte administrateur actif après coup.

    Retourne (succès, message).
    """
    con = get_connection()
    try:
        cible = con.execute("SELECT id, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if not cible:
            return False, "Compte introuvable."

        if not is_active:
            if acteur_id is not None and acteur_id == user_id:
                return False, "Vous ne pouvez pas désactiver votre propre compte."
            if cible["is_admin"]:
                autre_admin_actif = con.execute(
                    "SELECT 1 FROM users WHERE is_admin = 1 AND is_active = 1 AND id != ? LIMIT 1",
                    (user_id,),
                ).fetchone()
                if not autre_admin_actif:
                    return False, (
                        "Impossible de désactiver ce compte : il doit rester au moins "
                        "un administrateur actif."
                    )

        con.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id))
        if not is_active:
            # Révoque immédiatement toutes les sessions en cours pour ce compte
            con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        con.commit()
        return True, "Compte activé." if is_active else "Compte désactivé."
    finally:
        con.close()


# fonction vérif un compte
def verifier_identifiants(username: str, mdp: str) -> Optional[dict]:
    """
    Vérifie le couple identifiant/mot de passe. Refuse la connexion si le compte est désactivé
    ou si c'est un compte OIDC (qui ne peut se connecter que via SSO).
    Retourne {'id', 'username', 'is_admin', 'auth_provider'} ou None.
    """
    username = username.strip()
    con = get_connection()
    try:
        ligne = con.execute(
            "SELECT id, username, password_hash, salt, is_admin, is_active, auth_provider FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not ligne:
            return None
        if ligne["auth_provider"] == "oidc":
            return None
        h, _ = _hash_mdp(mdp, ligne["salt"])
        if h != ligne["password_hash"]:
            return None
        if not ligne["is_active"]:
            return None
        return {
            "id": ligne["id"], "username": ligne["username"],
            "is_admin": bool(ligne["is_admin"]), "auth_provider": ligne["auth_provider"],
        }
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
    """Vérifie un jeton de session. Retourne {'id', 'username', 'is_admin', 'auth_provider'} ou None si absent/expiré/désactivé."""
    con = get_connection()
    try:
        ligne = con.execute(
            "SELECT s.user_id AS id, u.username, u.is_admin, u.is_active, u.auth_provider, s.expire_at FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        if not ligne:
            return None
        if ligne["expire_at"] < int(time.time()) or not ligne["is_active"]:
            con.execute("DELETE FROM sessions WHERE token = ?", (token,))
            con.commit()
            return None
        return {
            "id": ligne["id"], "username": ligne["username"],
            "is_admin": bool(ligne["is_admin"]), "auth_provider": ligne["auth_provider"],
        }
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


def ecran_connexion(cookie_manager: stx.CookieManager, conf, register: bool = False) -> Optional[dict]:
    """
    Point d'entrée unique appelé depuis hermes-web.py
    
    - cookie_manager : instance unique créée une fois par run via obtenir_cookie_manager()
    - conf : configuration hermes.conf (nécessaire pour l'OIDC, section [oidc])
    - register : reflète l'option register de la section [auth] 

    - Si l'utilisateur est déjà connecté dans cette session (ou via le cookie) : 
      - retourne son dict ({'id', 'username', 'is_admin', 'auth_provider'}) continue

    Connexion : à la connexion (locale ou OIDC), un jeton est créé en base et déposé
    dans un cookie navigateur (un utilisateur OIDC obtient exactement la même session
    persistante qu'un utilisateur local, donc le reste de l'application (conversations,
    amphores perso, panneau admin...) fonctionne sans distinction de provenance.

    Déconnexion : le bouton déconnexion met st.session_state["auth_afficher_deconnexion"] = True
    et affiche un écran de confirmation avant d'effectuer réellement la déconnexion.
    (pas top mais plus facile que de refresh la page)
    """
    # Retour de callback OIDC (?code=&state= dans l'URL) : traité en priorité, avant
    # toute autre logique, indépendamment de auth_afficher_connexion (la redirection
    # complète vers l'IdP peut faire perdre cet état côté session selon le navigateur).
    if "auth_user" not in st.session_state and conf.getboolean("oidc", "enabled", fallback=False):
        from hermes_oidc import traiter_callback
        claims = traiter_callback(conf)
        if claims is not None:
            utilisateur = resoudre_ou_creer_utilisateur_oidc(
                sub=claims["sub"],
                username_prefere=claims.get("preferred_username") or claims.get("email") or "",
            )
            con = get_connection()
            try:
                actif = con.execute("SELECT is_active FROM users WHERE id = ?", (utilisateur["id"],)).fetchone()
            finally:
                con.close()
            if actif and not actif["is_active"]:
                st.error("❌ Ce compte a été désactivé.")
                st.query_params.clear()
                st.stop()

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
            st.query_params.clear()
            time.sleep(0.5)  # laisse le temps au composant JS d'écrire le cookie
            st.rerun()

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

    if conf.getboolean("oidc", "enabled", fallback=False):
        from hermes_oidc import construire_url_autorisation
        url_sso = construire_url_autorisation(conf)
        if url_sso:
            st.link_button("🔐 Connexion SSO", url_sso, use_container_width=True, type="primary")
            st.divider()
        else:
            st.warning("⚠️ SSO indisponible (fournisseur d'identité injoignable).")

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
