"""
hermes-web.py
=================
Agent conversationnel en web utilisant un LLM local.
Interface web pour l'agent conversationnel, construite avec Streamlit.
La configuration est lue depuis hermes-web.conf.
Les outils sont définis dans hermes_tools.py.

Lancement :
  streamlit run hermes-web.py
"""

import json
import configparser
import time
from pathlib import Path

import requests
import streamlit as st
from openai import OpenAI

import base64

# Module partagé contenant outils + catalogue + dispatcher
from hermes_tools import outils_actifs, executer_outil, ICONES_OUTILS

# Module outil_transcrire_audio importé à part et appelé directement (pas via executer_outil)
# il a besoin des bytes bruts du fichier joint sinon ça marche pas (a améilorer plus tard)
from hermes_tools import outil_transcrire_audio

# Module de gestion des contextes système (Amphores)
from hermes_amphores import (
    charger_amphores, sauvegarder_amphores, amphore_par_id,
    creer_amphore, mettre_a_jour_amphore, supprimer_amphore, ID_DEFAUT,
)

# Gestion de l'upload de fichiers
TYPES_IMAGE   = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
TYPES_TEXTE   = {".txt", ".md", ".py", ".sh", ".conf", ".ini", ".log", ".yaml", ".yml",
                 ".json", ".xml", ".html", ".css", ".js", ".ts", ".csv"}
TYPES_AUDIO   = {".wav", ".aiff", ".flac", ".ogg", ".mp3", ".m4a"}
TYPES_VIDEO   = {".mp4", ".mkv", ".mov", ".avi"}
TYPES_AUDIO_VIDEO = TYPES_AUDIO | TYPES_VIDEO

EXTENSIONS_UPLOAD = [
    "txt", "md", "py", "sh", "conf", "ini", "log", "yaml", "yml",
    "json", "xml", "html", "css", "js", "ts",
    "csv", "xlsx", "xls", "ods",
    "pdf",
    "odt", "odp",
    "png", "jpg", "jpeg", "gif", "webp",
    ".wav", ".aiff", ".flac", ".ogg", ".mp3", ".m4a",
    ".mp4", ".mkv", ".mov", ".avi",
]

# Limite de caractères injectés dans le contexte pour les fichiers texte
LIMITE_CONTEXTE = 65536

def extraire_contenu_fichier(fichier, conf: configparser.ConfigParser) -> dict:
    """
    Analyse le fichier uploadé et retourne un dict :
      {
        "type":    "image" | "texte" | "audio",
        "nom":     str,
        "contenu": str | None   # texte extrait (None pour audio/image)
        "b64":     str | None   # base64 pour les images
        "mime":    str | None   # MIME type pour les images/audio
        "donnees": bytes | None # contenu binaire brut (audio/vidéo uniquement)
      }
    """
    nom  = fichier.name
    ext  = Path(nom).suffix.lower()
    mime = fichier.type  # fourni par Streamlit

    # Images : encodage base64 pour les modèles multimodaux
    if mime in TYPES_IMAGE or ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        donnees = fichier.read()
        b64     = base64.b64encode(donnees).decode("utf-8")
        return {"type": "image", "nom": nom, "contenu": None, "b64": b64, "mime": mime}

    # Audio / vidéo : bytes bruts conservés et transcription déclenchée que si llm décide d'appeler outil_transcrire_audio
    if ext in TYPES_AUDIO_VIDEO or (mime and (mime.startswith("audio/") or mime.startswith("video/"))):
        donnees = fichier.getvalue() if hasattr(fichier, "getvalue") else fichier.read()
        return {"type": "audio", "nom": nom, "contenu": None, "b64": None, "mime": mime, "donnees": donnees}
        
    # PDF : extraction via PyMuPDF
    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF
            donnees = fichier.read()
            doc     = fitz.open(stream=donnees, filetype="pdf")
            texte   = "\n".join(page.get_text() for page in doc)
        except ImportError:
            texte = "⚠️ PyMuPDF non installé (pip install pymupdf). Impossible d'extraire le PDF."
        except Exception as e:
            texte = f"⚠️ Erreur lors de l'extraction PDF : {e}"
        return {"type": "texte", "nom": nom, "contenu": texte[:LIMITE_CONTEXTE], "b64": None, "mime": None}

    # CSV
    if ext == ".csv":
        try:
            import pandas as pd
            import io
            df    = pd.read_csv(io.BytesIO(fichier.read()))
            texte = df.to_markdown(index=False)
        except ImportError:
            texte = "⚠️ pandas non installé (pip install pandas). Impossible de lire le CSV."
        except Exception as e:
            texte = f"⚠️ Erreur lors de la lecture CSV : {e}"
        return {"type": "texte", "nom": nom, "contenu": texte[:LIMITE_CONTEXTE], "b64": None, "mime": None}

    # Excel
    if ext in {".xlsx", ".xls"}:
        try:
            import pandas as pd
            import io
            df    = pd.read_excel(io.BytesIO(fichier.read()))
            texte = df.to_markdown(index=False)
        except ImportError:
            texte = "⚠️ pandas/openpyxl non installés (pip install pandas openpyxl). Impossible de lire le fichier Excel."
        except Exception as e:
            texte = f"⚠️ Erreur lors de la lecture Excel : {e}"
        return {"type": "texte", "nom": nom, "contenu": texte[:LIMITE_CONTEXTE], "b64": None, "mime": None}

    # ODS
    if ext == ".ods":
        try:
            import io
            import odf  # verifie que odfpy est disponible avant d'appeler pandas
            import pandas as pd
            df    = pd.read_excel(io.BytesIO(fichier.read()), engine="odf")
            texte = df.to_markdown(index=False)
        except ImportError as e:
            texte = f"⚠️ Bibliothèque manquante pour lire le fichier ODS : {e} (pip install pandas odfpy)"
        except Exception as e:
            texte = f"⚠️ Erreur lors de la lecture ODS : {e}"
        return {"type": "texte", "nom": nom, "contenu": texte[:LIMITE_CONTEXTE], "b64": None, "mime": None}

    # ODT
    if ext == ".odt":
        try:
            import io
            from odf.opendocument import load as odf_load
            from odf import teletype
            from odf.text import P
            doc        = odf_load(io.BytesIO(fichier.read()))
            paragraphs = doc.body.getElementsByType(P)
            texte      = "\n".join(teletype.extractText(p) for p in paragraphs)
            if not texte.strip():
                texte = "⚠️ Le document ODT semble vide ou son contenu n'a pas pu être extrait."
        except ImportError as e:
            texte = f"⚠️ Bibliothèque manquante pour lire le fichier ODT : {e} (pip install odfpy)"
        except Exception as e:
            texte = f"⚠️ Erreur lors de la lecture ODT : {e}"
        return {"type": "texte", "nom": nom, "contenu": texte[:LIMITE_CONTEXTE], "b64": None, "mime": None}

    # ODP
    if ext == ".odp":
        try:
            import io
            from odf.opendocument import load as odf_load
            from odf import teletype
            from odf.text import P
            doc   = odf_load(io.BytesIO(fichier.read()))
            # Extraction de tous les paragraphes (contenus dans les slides)
            elements = doc.getElementsByType(P)
            texte    = "\n".join(teletype.extractText(e) for e in elements)
            if not texte.strip():
                texte = "⚠️ Le document ODP semble vide ou son contenu n'a pas pu être extrait."
        except ImportError as e:
            texte = f"⚠️ Bibliothèque manquante pour lire le fichier ODP : {e} (pip install odfpy)"
        except Exception as e:
            texte = f"⚠️ Erreur lors de la lecture ODP : {e}"
        return {"type": "texte", "nom": nom, "contenu": texte[:LIMITE_CONTEXTE], "b64": None, "mime": None}

    # Fichiers texte brut (ou fallback)
    try:
        texte = fichier.read().decode("utf-8", errors="replace")
    except Exception as e:
        texte = f"⚠️ Impossible de lire le fichier : {e}"
    return {"type": "texte", "nom": nom, "contenu": texte[:LIMITE_CONTEXTE], "b64": None, "mime": None}


def construire_message_avec_fichier(info: dict, prompt: str) -> dict:
    """
    Construit le message user à envoyer au LLM en fonction du type de fichier.
    - Image  : format multimodal OpenAI (base64)
    - Audio  : note indiquant un fichier joint (LLM doit appeler "outil_transcrire_audio" si besoin texte dicté)
    - Texte  : injection dans le contenu texte
    """
    if info["type"] == "image":
        return {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{info['mime']};base64,{info['b64']}"
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }
    # TODO : y a peut être mieux pour ça
    elif info["type"] == "audio":
        contenu_injecte = (
            f"[Un fichier audio/vidéo est joint à ce message : `{info['nom']}`. "
            f"Utilise l'outil de transcription (outil_transcrire_audio) pour en obtenir "
            f"le texte dicté si c'est nécessaire pour répondre à la question.]\n\n"
            f"Question : {prompt}"
        )
        return {"role": "user", "content": contenu_injecte}
    else:
        contenu_injecte = (
            f"Voici le contenu du fichier `{info['nom']}` :\n\n"
            f"```\n{info['contenu']}\n```\n\n"
            f"Question : {prompt}"
        )
        return {"role": "user", "content": contenu_injecte}


# Chargement config
@st.cache_resource
def charger_config(chemin: str = "hermes.conf") -> configparser.ConfigParser:
    """
    Lit le fichier hermes.conf une seule fois (mis en cache par Streamlit).
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

page_title  = conf.get("web",   "page_title",  fallback="Hermes chatbot by Linuxtricks.fr")
page_icon   = conf.get("web",   "page_icon",   fallback="📜")
header      = conf.get("web",   "header",      fallback="Hermes chatbot by Linuxtricks.fr")
sys_prompt  = conf.get("agent", "system_prompt")
model       = conf.get("llm",   "model")
max_tokens  = conf.getint("llm",   "max_tokens",   fallback=2048)
temperature = conf.getfloat("llm", "temperature",  fallback=0.7)
editamphores = conf.getboolean("amphores", "editamphores", fallback=True)

#st.set_page_config(page_title=page_title, page_icon=page_icon, layout="centered")
st.set_page_config(page_title=page_title, page_icon=page_icon, layout="wide")


# Interface Streamlit Latérale
outils = outils_actifs(conf)   # liste filtrée selon [tools] dans le .conf

with st.sidebar:

    # Contextes système (Amphores)
    st.subheader("🏺 Amphores")

    # Initialisation au premier chargement de la session
    if "amphores" not in st.session_state:
        st.session_state["amphores"] = charger_amphores(sys_prompt)
    if "amphore_actif_id" not in st.session_state:
        st.session_state["amphore_actif_id"] = st.session_state["amphores"][0]["id"]

    amphores_list = st.session_state["amphores"]
    amphore_actif = amphore_par_id(amphores_list, st.session_state["amphore_actif_id"]) or amphores_list[0]
    idx_actif = next((i for i, g in enumerate(amphores_list) if g["id"] == amphore_actif["id"]), 0)

    def _appliquer_amphore_selectionnee():
        """Callback : applique immédiatement l'amphore choisie dans le menu déroulant
        (sans réinitialiser la conversation — seul le bouton 'Effacer la conversation' le fait)."""
        liste = st.session_state["amphores"]
        idx = st.session_state["sel_amphore"]
        sel = liste[idx]
        st.session_state["amphore_actif_id"] = sel["id"]
        if st.session_state.get("messages") and st.session_state.messages[0]["role"] == "system":
            st.session_state.messages[0]["content"] = sel["system_prompt"]

    # Sélecteur de contexte, appliqué immédiatement via callback
    st.selectbox(
        "Contexte actif",
        options=range(len(amphores_list)),
        index=idx_actif,
        format_func=lambda i: amphores_list[i]["nom"],
        label_visibility="visible",
        key="sel_amphore",
        help="🏺 Les amphores sont des contextes personnalisés (prompt système) qui changent le comportement de l'IA.",
        on_change=_appliquer_amphore_selectionnee,
    )
    if amphore_actif.get("description"):
        st.caption(f"*{amphore_actif['description']}*")

    # Boutons de gestion (masqués si editamphores = no dans hermes.conf)
    if editamphores:

        @st.dialog("➕ Nouvelle amphore")
        def _dialog_nouvelle_amphore():
            f_nom = st.text_input("Nom *", placeholder="Ex : Expert Python")
            f_desc = st.text_input("Description", placeholder="Optionnel")
            f_prompt = st.text_area(
                "Prompt système *", height=160,
                placeholder="Tu es un expert Python spécialisé en optimisation de code",
            )
            c1, c2 = st.columns(2)
            if c1.button("💾 Créer", use_container_width=True):
                if f_nom.strip() and f_prompt.strip():
                    nouveau = creer_amphore(f_nom, f_prompt, f_desc)
                    liste = st.session_state["amphores"] + [nouveau]
                    sauvegarder_amphores(liste)
                    st.session_state["amphores"] = liste
                    st.session_state["amphore_actif_id"] = nouveau["id"]
                    if st.session_state.get("messages") and st.session_state.messages[0]["role"] == "system":
                        st.session_state.messages[0]["content"] = nouveau["system_prompt"]
                    st.success(f"✅ Amphore « {f_nom} » créée !")
                    st.rerun()
                else:
                    st.warning("Le nom et le prompt système sont obligatoires.")
            if c2.button("Annuler", use_container_width=True):
                st.rerun()

        @st.dialog("✏️ Modifier l'amphore")
        def _dialog_editer_amphore(amphore):
            est_defaut = amphore["id"] == ID_DEFAUT
            if est_defaut:
                st.caption("🔒 Le contexte « Par défaut » ne peut pas être modifié (issu de hermes.conf).")
            e_nom = st.text_input("Nom", value=amphore["nom"], disabled=est_defaut)
            e_desc = st.text_input("Description", value=amphore.get("description", ""), disabled=est_defaut)
            e_prompt = st.text_area("Prompt système", value=amphore["system_prompt"], height=160, disabled=est_defaut)

            c1, c2 = st.columns(2)
            if c1.button("💾 Sauvegarder", use_container_width=True, disabled=est_defaut):
                updated = mettre_a_jour_amphore(
                    st.session_state["amphores"], amphore["id"],
                    nom=e_nom, description=e_desc, system_prompt=e_prompt,
                )
                sauvegarder_amphores(updated)
                st.session_state["amphores"] = updated
                if (st.session_state.get("messages") and st.session_state.messages[0]["role"] == "system"
                        and st.session_state["amphore_actif_id"] == amphore["id"]):
                    st.session_state.messages[0]["content"] = e_prompt
                st.success("✅ Amphore mise à jour !")
                st.rerun()
            if c2.button("Fermer", use_container_width=True):
                st.rerun()

            if not est_defaut:
                #st.divider()
                st.markdown("<hr style='margin: 6px 0; opacity: 0.3;'>", unsafe_allow_html=True)
                del_confirm = st.checkbox("Je confirme la suppression", key="chk_del_amphore")
                if st.button("🗑️ Supprimer cette amphore", use_container_width=True, disabled=not del_confirm):
                    liste = supprimer_amphore(st.session_state["amphores"], amphore["id"])
                    sauvegarder_amphores(liste)
                    st.session_state["amphores"] = liste
                    # On revient toujours sur le contexte "Par défaut" après suppression
                    defaut = amphore_par_id(liste, ID_DEFAUT) or liste[0]
                    st.session_state["amphore_actif_id"] = defaut["id"]
                    if st.session_state.get("messages") and st.session_state.messages[0]["role"] == "system":
                        st.session_state.messages[0]["content"] = defaut["system_prompt"]
                    st.rerun()

        col_amph_1, col_amph_2 = st.columns(2)
        if col_amph_1.button("➕ Nouvelle", use_container_width=True, key="btn_nouvelle_amphore"):
            _dialog_nouvelle_amphore()
        if col_amph_2.button(
            "✏️ Éditer", use_container_width=True, key="btn_editer_amphore",
            disabled=(amphore_actif["id"] == ID_DEFAUT),
        ):
            _dialog_editer_amphore(amphore_actif)

    # fin Contextes (Amphores)
    
    #st.divider()
    st.markdown("<hr style='margin: 6px 0; opacity: 0.3;'>", unsafe_allow_html=True)

    # Fichiers à joindre
    st.subheader("📎 Fichier joint")
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = 0
    fichier_upload = st.file_uploader(
        "Joindre un fichier à la prochaine question",
        type=EXTENSIONS_UPLOAD,
        help=(
            "Texte / code / config : injection dans le contexte\n"
            "PDF : extraction du texte (PyMuPDF)\n"
            "CSV / Excel / ODS : tableau markdown (pandas + odfpy)\n"
            "ODT / ODP : extraction du texte (odfpy)\n"
            "Image : envoi base64 (modèle multimodal requis)\n"
            "Audio / vidéo : transcrit uniquement si le LLM appelle l'outil outil_transcrire_audio"
        ),
        key=f"uploader_{st.session_state['uploader_key']}",
    )

    # Aperçu et mise en cache du fichier dans la session
    if fichier_upload is not None:
        # Mémorisation uniquement si c'est un nouveau fichier
        if st.session_state.get("fichier_nom") != fichier_upload.name:
            with st.spinner("Lecture du fichier..."):
                info = extraire_contenu_fichier(fichier_upload, conf)
            st.session_state["fichier_info"] = info
            st.session_state["fichier_nom"]  = fichier_upload.name

        info_cache = st.session_state.get("fichier_info", {})
        if info_cache.get("type") == "image":
            st.success(f"🖼️ Image prête : `{info_cache['nom']}`")
        elif info_cache.get("type") == "audio":
            st.success(f"🎙️ Audio/vidéo joint : `{info_cache['nom']}`")
            st.caption("Sera transcrit uniquement si nécessaire pour répondre à la question.")
        else:
            nb_chars = len(info_cache.get("contenu") or "")
            st.success(f"📄 `{info_cache['nom']}` — {nb_chars} caractères extraits")

        if st.button("🗑️ Retirer le fichier", use_container_width=True):
            st.session_state.pop("fichier_info", None)
            st.session_state.pop("fichier_nom",  None)
            st.rerun()
    else:
        # Nettoyage si l'utilisateur retire le fichier via le widget
        st.session_state.pop("fichier_info", None)
        st.session_state.pop("fichier_nom",  None)
    # fin fichier


    # Effacer la conversation 
    #st.divider()
    st.markdown("<hr style='margin: 6px 0; opacity: 0.3;'>", unsafe_allow_html=True)
    if st.button("🗑️ Effacer la conversation", use_container_width=True):
        # st.session_state.messages = [{"role": "system", "content": sys_prompt}]
        # Repart avec le prompt du contexte actif (pas celui du .conf)
        prompt_actif = amphore_actif.get("system_prompt", sys_prompt)
        st.session_state.messages = [{"role": "system", "content": prompt_actif}]
        st.session_state.pop("fichier_info",    None)
        st.session_state.pop("fichier_nom",     None)
        st.session_state.pop("fichier_genere",  None)
        st.session_state.pop("derniere_reponse",None)
        st.session_state["temps_reponse"] = None
        st.rerun()

    # Temps de réponse (infos)
    #st.divider()
    st.markdown("<hr style='margin: 6px 0; opacity: 0.3;'>", unsafe_allow_html=True)
    tr = st.session_state.get("temps_reponse")
    st.markdown(f"**Temps de réponse :** {f'{int(tr)}s' if tr is not None else 'None'}")
        
    # Infos
    #st.divider()
    st.markdown("<hr style='margin: 6px 0; opacity: 0.3;'>", unsafe_allow_html=True)
    st.header("Informations")
    st.markdown(f"**Modèle :** `{model}`")
    st.markdown(f"**Température :** `{temperature}`")
    st.markdown(f"**Max tokens :** `{max_tokens}`")
    st.markdown(f"**Outils actifs :** {len(outils)}")
    for o in outils:
        nom   = o["function"]["name"]
        icone = ICONES_OUTILS.get(nom, "⚙️")
        st.markdown(f"{icone} `{nom}`")


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
        #st.markdown(content)
        if isinstance(content, list):
            for bloc in content:
                if isinstance(bloc, dict) and bloc.get("type") == "text":
                    st.markdown(bloc["text"])
                elif isinstance(bloc, dict) and bloc.get("type") == "image_url":
                    st.markdown("*(image jointe)*")
        else:
            st.markdown(content)

# Fichier généré : bouton de téléchargement persistant dans la vue principale
fichier_genere = st.session_state.get("fichier_genere")
if fichier_genere:
    import base64 as _b64
    col_dl, col_del = st.columns([5, 1])
    with col_dl:
        st.download_button(
            label=f"⬇️ Télécharger {fichier_genere['nom']}",
            data=_b64.b64decode(fichier_genere["b64"]),
            file_name=fichier_genere["nom"],
            mime=fichier_genere["mime"],
            use_container_width=True,
            key="dl_genere",
        )
    with col_del:
        if st.button("🗑️", use_container_width=True, key="del_genere", help="Effacer le fichier généré"):
            st.session_state.pop("fichier_genere", None)
            st.rerun()

# Zone de saisie
if prompt := st.chat_input("Posez votre question..."):
    _t0_question = time.time()
    #st.session_state.messages.append({"role": "user", "content": prompt}
    # Construction du message user (avec ou sans fichier)
    info_fichier = st.session_state.get("fichier_info")
    # Bytes conservés pour appel à outil_transcrire_audio
    audio_actif = info_fichier if (info_fichier and info_fichier.get("type") == "audio") else None

    if info_fichier:
        msg_user_llm = construire_message_avec_fichier(info_fichier, prompt)
        # Libération du fichier après envoi (une seule utilisation par défaut)
        st.session_state.pop("fichier_info", None)
        st.session_state.pop("fichier_nom",  None)
        st.session_state["uploader_key"] = st.session_state.get("uploader_key", 0) + 1
    else:
        msg_user_llm = {"role": "user", "content": prompt}

    # Ajout à l'historique et affichage
    st.session_state.messages.append(msg_user_llm)
    with st.chat_message("user"):
        st.markdown(prompt)
        if info_fichier:
            #label_type = "🖼️ image" if info_fichier["type"] == "image" else "📄 fichier texte"
            if info_fichier["type"] == "image":
                label_type = "🖼️ image"
            elif info_fichier["type"] == "audio":
                label_type = "🎙️ audio/vidéo"
            else:
                label_type = "📄 fichier texte"
            st.caption(f"{label_type} joint : `{info_fichier['nom']}`")

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
                    with st.spinner("Appel en cours..."):
                        #res_outil = executer_outil(nom_outil, args)   # dispatcher partagé
                        if nom_outil == "outil_transcrire_audio":
                            # Cas spécial : nécessite bytes réels du fichier joint que le dispatcher générique ne peut pas transporter.
                            if audio_actif:
                                res_outil = outil_transcrire_audio(
                                    audio_actif["donnees"], audio_actif["nom"], conf,
                                    ignorer_debut_secondes=args.get("ignorer_debut_secondes", 0) or 0,
                                    ignorer_fin_secondes=args.get("ignorer_fin_secondes", 0) or 0,
                                )
                            else:
                                res_outil = "⚠️ Aucun fichier audio/vidéo n'est joint à ce message."
                        else:
                            res_outil = executer_outil(nom_outil, args)   # dispatcher partagé

                    # Interception de la génération de fichier
                    res_outil_llm = res_outil
                    if nom_outil == "outil_generer_fichier":
                        try:
                            parsed = json.loads(res_outil)
                            if isinstance(parsed, dict) and parsed.get("__fichier_genere__"):
                                st.session_state["fichier_genere"] = parsed
                                res_outil_llm = (
                                    f"✅ Fichier `{parsed['nom']}` généré avec succès "
                                    f"au format {parsed['format'].upper()}. "
                                    f"Il est disponible en téléchargement dans la vue principale."
                                )
                                # Bouton dans le chat immédiatement
                                st.success(f"💾 Fichier prêt : `{parsed['nom']}`")
                                st.download_button(
                                    label=f"⬇️ Télécharger {parsed['nom']}",
                                    data=base64.b64decode(parsed["b64"]),
                                    file_name=parsed["nom"],
                                    mime=parsed["mime"],
                                    use_container_width=True,
                                    key=f"dl_chat_{parsed['nom']}",
                                )

                            else:
                                st.markdown(res_outil)
                        except (ValueError, TypeError):
                            st.markdown(res_outil)
                    else:
                        st.markdown(res_outil)

                st.session_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": call.id,
                    "name":         nom_outil,
                    "content":      res_outil_llm,
                })

            # Synthese et réponse finale
            with st.spinner("Rédaction de la réponse..."):
                try:
                    final     = client.chat.completions.create(
                        model=model,
                        messages=st.session_state.messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        # stream=True, # TODO BUG STREAM
                    )
                    txt_final = final.choices[0].message.content
                except Exception as e:
                    txt_final = f"Erreur lors de la synthèse : {e}"
                    st.error(txt_final)
                    st.stop()

            st.markdown(txt_final)
            #txt_final = st.write_stream(final)  # TODO BUG STREAM
            st.session_state.messages.append({"role": "assistant", "content": txt_final})
            st.session_state["derniere_reponse"] = txt_final

        # Sinon on utilise pas d'outil
        else:
            #texte = msg_ia.content or "*(réponse vide)*"
            #st.markdown(texte)
            # Activer le mode streaming
            try:
                flux = client.chat.completions.create(
                    model=model,
                    messages=st.session_state.messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                )
                texte = st.write_stream(flux)
                
            except Exception as e:
                st.error(f"Erreur pendant le streaming : {e}")
                texte = "*(erreur de génération)*"

            st.session_state.messages.append({"role": "assistant", "content": texte})
            st.session_state["derniere_reponse"] = texte

        # Temps de réponse (du clic "Envoyer" à la réponse finale affichée)
        st.session_state["temps_reponse"] = time.time() - _t0_question

        # Rerendu pour que les widgets hors du bloc chat (ex: bouton de téléchargement) soient visibles
        st.rerun()
