"""
hermes_conversations.py
========================
Historique des conversations par utilisateur pour Hermes.

Importé par hermes-web.py :
    from hermes_conversations import ajouter_message, vider_conversation, widget_conversations
"""

import time
from typing import Optional

import streamlit as st

from hermes_accounts import get_connection

TITRE_DEFAUT = "Nouvelle conversation"
LONGUEUR_TITRE_AUTO = 40


# CRUD conversations / messages
def lister_conversations(user_id: int) -> list[dict]:
    """Liste les conversations d'un utilisateur, la plus récemment modifiée en premier."""
    con = get_connection()
    try:
        lignes = con.execute(
            "SELECT id, titre, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(l) for l in lignes]
    finally:
        con.close()

def creer_conversation(user_id: int, amphore_id: Optional[str], titre: str = TITRE_DEFAUT) -> int:
    """Crée une conversation vide et retourne son id."""
    maintenant = int(time.time())
    con = get_connection()
    try:
        cur = con.execute(
            "INSERT INTO conversations (user_id, titre, amphore_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, titre, amphore_id, maintenant, maintenant),
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()

def charger_messages(conversation_id: int) -> list[dict]:
    """Charge les messages (role/content) d'une conversation, dans l'ordre chronologique."""
    con = get_connection()
    try:
        lignes = con.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        return [{"role": l["role"], "content": l["content"]} for l in lignes]
    finally:
        con.close()

def ajouter_message(conversation_id: int, role: str, content: str) -> None:
    """
    Ajoute un message à la conversation et met à jour sa date de modification.
    Si c'est le tout premier message utilisateur et que le titre est encore
    celui par défaut, le titre est automatiquement dérivé de son contenu.
    """
    maintenant = int(time.time())
    con = get_connection()
    try:
        con.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, maintenant),
        )
        con.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (maintenant, conversation_id),
        )

        if role == "user":
            ligne = con.execute(
                "SELECT titre FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if ligne and ligne["titre"] == TITRE_DEFAUT:
                nb_user = con.execute(
                    "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ? AND role = 'user'",
                    (conversation_id,),
                ).fetchone()["n"]
                if nb_user == 1:
                    titre_auto = content.strip().replace("\n", " ")[:LONGUEUR_TITRE_AUTO]
                    if len(content.strip()) > LONGUEUR_TITRE_AUTO:
                        titre_auto += "…"
                    con.execute(
                        "UPDATE conversations SET titre = ? WHERE id = ?",
                        (titre_auto or TITRE_DEFAUT, conversation_id),
                    )
        con.commit()
    finally:
        con.close()

def renommer_conversation(conversation_id: int, nouveau_titre: str) -> None:
    con = get_connection()
    try:
        con.execute(
            "UPDATE conversations SET titre = ? WHERE id = ?",
            (nouveau_titre.strip() or TITRE_DEFAUT, conversation_id),
        )
        con.commit()
    finally:
        con.close()

def supprimer_conversation(conversation_id: int) -> None:
    con = get_connection()
    try:
        con.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        con.commit()
    finally:
        con.close()

def vider_conversation(conversation_id: int) -> None:
    """Efface uniquement les messages d'une conversation (conserve titre/id)."""
    con = get_connection()
    try:
        con.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        con.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (int(time.time()), conversation_id),
        )
        con.commit()
    finally:
        con.close()


# Widget sidebar (intégration minimale dans hermes-web.py)
def widget_conversations(user: dict, amphore_id_actif: str, sys_prompt_defaut: str) -> None:
    """
    Affiche la section Conversations dans la sidebar : sélection, création,
    renommage et suppression. Met à jour st.session_state['conversation_id'] et
    st.session_state['messages'] en fonction de la conversation active.

    Au premier affichage après connexion conversation vierge (conversation_id = None)

    À appeler une fois par run, dans `with st.sidebar:`, après avoir déterminé
    l'amphore active (amphore_id_actif sert de contexte par défaut aux nouvelles
    conversations).
    """
    st.subheader("💬 Conversations")

    conversations = lister_conversations(user["id"])
    titres = {c["id"]: c["titre"] for c in conversations}

    def _charger_dans_session(conv_id: int) -> None:
        messages = charger_messages(conv_id)
        if not messages or messages[0]["role"] != "system":
            messages = [{"role": "system", "content": sys_prompt_defaut}] + messages
        st.session_state["messages"] = messages

    def _demarrer_conversation_vierge() -> None:
        st.session_state["conversation_id"] = None
        st.session_state["messages"] = [{"role": "system", "content": sys_prompt_defaut}]

    # Premier affichage de la session : conversation vierge par défaut
    if "conversation_id" not in st.session_state:
        _demarrer_conversation_vierge()

    # Si la conversation active a été supprimée entre-temps (autre onglet, etc.)
    if st.session_state["conversation_id"] is not None and st.session_state["conversation_id"] not in titres:
        _demarrer_conversation_vierge()

    ids_options = [None] + [c["id"] for c in conversations]  # None = "conversation vierge"

    def _format_conversation(i):
        return "🆕 Nouvelle conversation" if i is None else titres[i]

    def _changer_conversation():
        nouvel_id = st.session_state["sel_conversation"]
        if nouvel_id is None:
            _demarrer_conversation_vierge()
        else:
            st.session_state["conversation_id"] = nouvel_id
            _charger_dans_session(nouvel_id)

    # selectbox resynchronisé à chaque run avec conversation_id sinon ça bug
    st.session_state["sel_conversation"] = st.session_state["conversation_id"]

    st.selectbox(
        "Reprendre une conversation",
        options=ids_options,
        format_func=_format_conversation,
        key="sel_conversation",
        on_change=_changer_conversation,
    )

    conv_id_actif = st.session_state["conversation_id"]

    @st.dialog("✏️ Renommer la conversation")
    def _dialog_renommer(conv_id: int, titre_actuel: str):
        nouveau_titre = st.text_input("Nouveau titre", value=titre_actuel)
        if st.button("Enregistrer", use_container_width=True):
            renommer_conversation(conv_id, nouveau_titre)
            st.rerun()

    @st.dialog("🗑️ Supprimer la conversation")
    def _dialog_supprimer(conv_id: int, titre: str):
        st.warning(f"Supprimer « {titre} » ? Cette action est irréversible.")
        cc1, cc2 = st.columns(2)
        if cc1.button("Confirmer", use_container_width=True):
            supprimer_conversation(conv_id)
            _demarrer_conversation_vierge()
            st.rerun()
        if cc2.button("Annuler", use_container_width=True):
            st.rerun()

    c1, c2, c3 = st.columns(3)

    if c1.button("➕", use_container_width=True, help="Nouvelle conversation"):
        _demarrer_conversation_vierge()
        st.rerun()

    if c2.button("🗑️", use_container_width=True, help="Supprimer cette conversation", disabled=conv_id_actif is None):
        _dialog_supprimer(conv_id_actif, titres[conv_id_actif])

    if c3.button("✏️", use_container_width=True, help="Renommer cette conversation", disabled=conv_id_actif is None):
        _dialog_renommer(conv_id_actif, titres[conv_id_actif])
