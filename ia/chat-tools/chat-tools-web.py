"""
chat-tools-web.py
=================
Agent conversationnel en web utilisant un LLM local.
Interface web pour l'agent conversationnel, construite avec Streamlit.
La configuration est lue depuis chat-tools.conf.
Les outils sont définis dans chat_tools_tools.py.

Lancement :
  streamlit run chat-tools-web.py
"""

import json
import configparser
from pathlib import Path

import requests
import streamlit as st
from openai import OpenAI

# Module partagé contenant outils + catalogue + dispatcher
from chat_tools_tools import outils_actifs, executer_outil, ICONES_OUTILS


# Chargemen config
@st.cache_resource
def charger_config(chemin: str = "chat-tools.conf") -> configparser.ConfigParser:
    """
    Lit le fichier chat-tools.conf une seule fois (mis en cache par Streamlit).
    Affiche une erreur fatale si le fichier est introuvable.
    """
    conf = configparser.ConfigParser()
    path = Path(chemin)
    if not path.exists():
        path = Path(__file__).parent / chemin
    if not path.exists():
        st.error(f"Fichier de configuration introuvable : `{chemin}`")
        st.stop()
    conf.read(str(path), encoding="utf-8")
    return conf


@st.cache_resource
def creer_client(base_url: str, api_key: str) -> OpenAI:
    """
    Instancie le client OpenAI pointant vers llama.cpp.
    Mis en cache pour éviter de recréer la connexion à chaque rechargement.
    """
    return OpenAI(base_url=base_url, api_key=api_key)


# Interface Streamlit HEAD
conf = charger_config()

page_title  = conf.get("web",   "page_title",  fallback="Chat LLM Linuxtricks")
page_icon   = conf.get("web",   "page_icon",   fallback="🤖")
header      = conf.get("web",   "header",      fallback="Chat LLM Linuxtricks")
sys_prompt  = conf.get("agent", "system_prompt")
model       = conf.get("llm",   "model")
max_tokens  = conf.getint("llm",   "max_tokens",   fallback=2048)
temperature = conf.getfloat("llm", "temperature",  fallback=0.7)

st.set_page_config(page_title=page_title, page_icon=page_icon, layout="centered")

# Interface Streamlit Latérale
outils = outils_actifs(conf)   # liste filtrée selon [tools] dans le .conf

with st.sidebar:
    st.header("Session")
    st.markdown(f"**Modèle :** `{model}`")
    st.markdown(f"**Température :** `{temperature}`")
    st.markdown(f"**Max tokens :** `{max_tokens}`")
    st.markdown(f"**Outils actifs :** {len(outils)}")
    for o in outils:
        st.markdown(f"- `{o['function']['name']}`")
    st.divider()
    if st.button("🗑️ Effacer la conversation", use_container_width=True):
        st.session_state.messages = [{"role": "system", "content": sys_prompt}]
        st.rerun()

# Interface Streamlit Entete
st.title(header)
st.caption(f"Modèle : `{model}` — {conf.get('llm', 'base_url')}")

# Initialisation de l'historique
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": sys_prompt}]

# Client LLM (mis en cache)
client = creer_client(conf.get("llm", "base_url"), conf.get("llm", "api_key"))

# Affichage de l'historique
for message in st.session_state.messages:
    role    = message["role"]    if isinstance(message, dict) else message.role
    content = message["content"] if isinstance(message, dict) else message.content
    if role in ("system", "tool") or not content:
        continue
    with st.chat_message(role):
        st.markdown(content)

# Zone de saisie
if prompt := st.chat_input("Posez votre question…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            reponse = client.chat.completions.create(
                model=model,
                messages=st.session_state.messages,
                tools=outils,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            st.error(f"Erreur de connexion au LLM : {e}")
            st.stop()

        msg_ia = reponse.choices[0].message

        # Le LLM veut utiliser un outil
        if msg_ia.tool_calls:
            st.session_state.messages.append(msg_ia.model_dump())

            for call in msg_ia.tool_calls:
                nom_outil = call.function.name
                label     = ICONES_OUTILS.get(nom_outil, f"🔧 {nom_outil}")
                try:
                    args = json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                with st.expander(f"{label} — `{nom_outil}`", expanded=False):
                    st.markdown(f"**Paramètres :** `{args}`")
                    with st.spinner("Appel en cours…"):
                        res_outil = executer_outil(nom_outil, args)   # ← dispatcher partagé
                    st.markdown(res_outil)

                st.session_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": call.id,
                    "name":         nom_outil,
                    "content":      res_outil,
                })

            # Synthese et réponse finale
            with st.spinner("Rédaction de la réponse…"):
                try:
                    final     = client.chat.completions.create(
                        model=model,
                        messages=st.session_state.messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                    txt_final = final.choices[0].message.content
                except Exception as e:
                    txt_final = f"Erreur lors de la synthèse : {e}"

            st.markdown(txt_final)
            st.session_state.messages.append({"role": "assistant", "content": txt_final})

        # Sinon on utilise pas d'outil
        else:
            texte = msg_ia.content or "*(réponse vide)*"
            st.markdown(texte)
            st.session_state.messages.append({"role": "assistant", "content": texte})
