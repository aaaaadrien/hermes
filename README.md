# Chatbot perso avec gestion d'outils (testé avec llama.cpp) 

- Agent conversationnel en Python connecté à un modèle LLM tournant en local via **llama.cpp**.
- Disponible en deux interfaces : **terminal (CLI)** et **web (Streamlit)**.
- Expérimentation de l'usage de tools, nécessite un modèle compatible.

__Pourquoi Hermès ?__

Dans la religion grecque antique, Hermès est le messager des dieux. Quoi de mieux pour nommer un outil qui est le messager de l'IA :)

## Fichiers

- hermes.conf : Configuration partagée
- hermes-cli.py : Interface en ligne de commande
- hermes-web.py : Interface web Streamlit


## Prérequis pour Hermes

### Sur le système 

- Python **3.9+**
- python-pip (Fedora/RHEL/Debian/Ubuntu : **python3-pip**)
- Python venv (Inclus dans Python sur Fedora/RHEl. Pour Debian/Ubuntu : **python3-venv**)

### Création d'un venv Python 

Pour isoler les dépendances python, créer un virtual env :
```bash
python3 -m venv venv
source venv/bin/activate
```

### Installation des dépendances

Via pip (universel)
```bash
pip install -r requirements.txt
```
- Gestion LLM : openai
- Requêtes LLM et externe : requests
- Interface web : streamlit
- FOnctions supplémentaires (cookie de connexion persistante) : extra-streamlit-components																		   
- Recherche web : ddgs
- Scrap pages : bs4
- Gestion fichier PDF : pymupdf fpdf2
- Gestion fichier : pandas
- Gestion XLS : openpyxl
- Gestion ODS/ODT/ODP : odfpy + tabulate
- Gestion DOCX : python-docx
- Téléchargement en ligne de vidéos : yt-dlp
- Divers : cachetools


## Serveurs `.cpp` (backends d'inférence)

Hermes ne fait qu'orchestrer des appels vers des serveurs d'inférence autohébergés, tous de la famille `.cpp` (llama.cpp et ses dérivés), chacun exposant une API compatible OpenAI.

Aucun n'est obligatoire à part llama.cpp. Les autres n'activent que des fonctionnalités optionnelles (transcription, génération d'image, synthèse vocale).

| Serveur | Fonctionnalité dans Hermes | Obligatoire |
|---|---|---|
| **llama.cpp** | Inférence LLM (conversation, appel d'outils) | Oui |
| **whisper.cpp** | Transcription audio/vidéo (upload + URL) | Non |
| **stablediffusion.cpp** | Génération d'image | Non |
| **audio.cpp** | Synthèse vocale (TTS) des réponses | Non |

Pour chacun, une vidéo d'installation et une fiche écrite (Linuxtricks) sont disponibles :

- **llama.cpp**
  - 🎥 Vidéo : https://www.youtube.com/watch?v=NFB-c7CoGm4
  - 📄 Fiche : https://www.linuxtricks.fr/wiki/ia-installer-llama-cpp-pour-servir-des-llm-nvidia-amd-cpu
- **whisper.cpp**
  - 🎥 Vidéo : https://www.youtube.com/watch?v=4y5wyLK8xjI
  - 📄 Fiche : https://www.linuxtricks.fr/wiki/ia-installer-whisper-cpp-pour-la-reconnaissance-vocale-nvidia-amd-cpu
- **stablediffusion.cpp**
  - 🎥 Vidéo : https://www.youtube.com/watch?v=GeIegX8gdR4
  - 📄 Fiche : https://www.linuxtricks.fr/wiki/ia-installer-stablediffusion-cpp-pour-la-generation-d-image-nvidia-amd-cpu
- **audio.cpp**
  - 🎥 Vidéo : https://www.youtube.com/watch?v=5vle0ONwmvs
  - 📄 Fiche : https://www.linuxtricks.fr/wiki/ia-installer-audio-cpp-pour-la-synthese-vocale-nvidia-amd-cpu

_Note :_ ces serveurs peuvent tourner sur la même machine qu'Hermes ou sur des machines distinctes (y compris différentes les unes des autres). Seule l'URL configurée dans `hermes.conf` (`base_url` de chaque section) compte.


## Upload de fichier audio / vidéo (transcription à la demande)

L'interface web permet de joindre un fichier audio ou vidéo (mp3, wav, ogg, flac, mp4, mkv, mov, avi, ...)
Contrairement aux autres fichiers, il **n'est pas transcrit immédiatement à l'upload** : le fichier est simplement joint au message, et c'est le LLM qui décide de déclencher la transcription via l'outil outil_transcrire_audio.

Cet outil est activable/désactivable comme les autres, si vous n'avez pas de whisper.cpp, dans `hermes.conf` :
```ini
[tools]
enable_transcrire_audio = true
```

Pour les fichiers **vidéo**, la piste audio est d'abord extraite et convertie en WAV via **ffmpeg** avant l'envoi à whisper.cpp
De fait, `ffmpeg` doit donc être installé et accessible dans le `PATH` de la machine qui héberge ce projet (pas sur le serveur d'inférence)

Dans le cadre de RHEL et clones, ffmpeg est dispo dans RPM Fusion Free : 
```bash
sudo dnf install --nogpgcheck https://dl.fedoraproject.org/pub/epel/epel-release-latest-$(rpm -E %rhel).noarch.rpm
sudo dnf install --nogpgcheck https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm
```

_Note :_ Pour améliorer la rapidité de traitement, silences retirés, découpe début/fin sur demande

## Transcription de vidéos en ligne (YouTube, Twitch, etc. via yt-dlp)

En plus des fichiers uploadés, le LLM peut transcrire directement une vidéo à partir de son **URL**, grâce à l'outil `outil_transcrire_video_url`. Il suffit de coller un lien vidéo dans le message (avec ou sans consigne explicite, ex : *"résume-moi cette vidéo : https://..."*) pour que l'outil soit déclenché automatiquement.

Deux chemins possibles selon le site :
- **Rapide (YouTube uniquement)** : si des sous-titres/transcription officiels sont disponibles, ils sont récupérés directement (pas de téléchargement, pas de whisper.cpp).
- **Générique (tous les sites pris en charge)** : la piste **audio uniquement** est téléchargée via **yt-dlp**, normalisée via ffmpeg, puis transcrite via whisper.cpp.

Cet outil est activable/désactivable comme les autres dans `hermes.conf` :
```ini
[tools]
enable_transcrire_video_url = true
```

`yt-dlp` doit être installé et accessible dans le `PATH` (inclus dans `requirements.txt`). `ffmpeg` est également nécessaire (voir section précédente).

Par sécurité, seuls les domaines explicitement autorisés peuvent être utilisés avec cet outil, la vérification est faite côté serveur, pas seulement dans la description donnée au LLM, pour empêcher un prompt malveillant de faire télécharger une URL arbitraire :

```ini
[video_url]
# Domaines autorisés, séparés par des virgules.
# Mettre "all" ou "*" pour désactiver la restriction et autoriser tous les sites (déconseillé).
domaines_autorises = youtube.com, twitch.tv, arte.tv
```

_Note :_ Pour améliorer la rapidité de traitement, silences retirés, découpe début/fin sur demande

## Génération d'image

Le LLM peut générer une image à partir d'une simple description texte (prompt) via l'outil outil_generation_image, qui s'appuie sur un serveur **stablediffusion.cpp** (API compatible OpenAI `/v1/images/generations`).

Cet outil est activable/désactivable comme les autres, si vous n'avez pas de stablediffusion.cpp, dans `hermes.conf` :
```ini
[tools]
enable_generation_image = true
```

L'URL du serveur ainsi que la taille par défaut se règlent dans la section `[image]` :
```ini
[image]
base_url = http://localhost:8082
endpoint = /v1/images/generations
size = 512x512
steps =
```

L'image générée s'affiche directement dans la conversation (interface web), avec un bouton de téléchargement.

_Note :_ La taille de l'image peut être demandée explicitement, mais attention, plus la résolution demandée est grande, plus la génération sera longue (et le serveur Stable Diffusion s'il est autohébergé, devra avoir assez de ressources)

## Synthèse vocale des réponses (TTS via audio.cpp, interface web)

Chaque réponse de l'assistant peut être écoutée via un bouton **"🔊 Écouter"**, qui envoie le texte à un serveur **audio.cpp** local (API compatible OpenAI `/v1/audio/speech`) et joue l'audio généré directement dans le navigateur.

Activable/désactivable dans `hermes.conf` :
```ini
[audio]
base_url = http://localhost:8083
endpoint = /v1/audio/speech
model = qwen3-tts
voice = Sohee
language = fr
tts = true
```

- **`model`** doit correspondre **exactement** à l'`id` du modèle TTS configuré côté serveur audio.cpp (champ `id` de la section `models` de son `server.json`).
- **`voice`** permet pour les modèles proposant plusieurs voix de sélectionner celle souhaitée.
- **`tts = false`** masque simplement le bouton "🔊 Écouter" partout dans l'interface, sans appel réseau.


## Amphores : contextes système personnalisés (interface web)

Une **amphore** est un contexte préconfiguré : un nom, une description optionnelle, et surtout un **prompt système** qui remplace celui défini par défaut dans `hermes.conf`. C'est un moyen rapide de changer le comportement de l'IA (ex : "Expert Python", "Correcteur orthographique", "Traducteur Anglais vers Français"...) sans éditer la configuration ni redémarrer le serveur.

Dans l'interface web, un menu déroulant dans la sidebar permet de choisir l'amphore active : le changement s'applique immédiatement au message système de la conversation en cours, sans réinitialiser l'historique (seul le bouton "Effacer la conversation" le fait).

### Deux origines d'amphores

- **Globales** : partagées par tout le monde, stockées dans `hermes.db`. Une amphore "Par défaut" existe toujours (reprend le `system_prompt` de `hermes.conf`) et ne peut pas être supprimée ni modifiée.
- **Perso** : propres à chaque utilisateur authentifié, stockées dans `hermes.db`. Invisibles et non modifiables par les autres utilisateurs. Nécessitent donc `[auth] authentification = userpass`.

Dans le sélecteur, les amphores globales sont préfixées 🌐 et les perso 👤, globales affichées en premier.

### Configuration (`hermes.conf`, section `[amphores]`)

```ini
[amphores]
# Visibilité des amphores dans l'interface :
# disabled : amphores non disponibles (défaut)
# user     : disponibles uniquement pour les utilisateurs authentifiés
# all      : disponibles pour tout le monde, authentifié ou non
mode = disabled

# Mot de passe pour déverrouiller la création/modification/suppression des amphores
# GLOBALES depuis l'interface (commande /amphores <mdp> dans le chat).
# Laisser vide = édition toujours affichée par défaut (pas de protection).
editpasswd = MDP
```

_Notes :_ les amphores globales sont consultables mais pas modifiables depuis l'interface. Pour afficher le menu de modification des amphores : commande `/amphores <mdp>` dans le chat.


## Comptes utilisateurs & historique des conversations (interface web)

**EXPERIMENTAL NE PAS ENCORE UTILISER**

L'interface web peut fonctionner selon deux modes, paramétré dans `hermes.conf` :

```ini
[auth]
authentification = none      # ou userpass
register = off               # ou on
```

### `authentification = none` (par défaut)

Comportement éphémère : pas de compte, pas de sauvegarde des conversations.
Chaque session de navigateur repart de zéro.

### `authentification = userpass`

Active la gestion de comptes (utilisateur/mot de passe) et la sauvegarde des conversations, stockées dans **`hermes.db`** (base SQLite créée automatiquement au premier lancement, aucun serveur de base de données externe requis).

Une fois connecté, chaque échange est automatiquement enregistré. La sidebar propose de lister, reprendre, renommer et supprimer ses conversations. 

Si on veut autoriser la création de compte (juste username + pass, pas de mail) mettre **`register`** à on.

##  Lancement

### Copie de la config

Avant toute chose, créez le fichier de config à partir de l'exemple donné : 
```bash
cp ressources/hermes.conf.example data/hermes.conf
```

Personnalisez éventuellement ce fichier selon ce que vous souhaitez !


### Interface CLI (terminal)

```bash
python hermes-cli.py
```

### Interface Web (Streamlit)

```bash
streamlit run hermes-web.py
```

### Configuration de Streamlit

Si besoin on peut éditer le fichier suivant pour configurer streamlit :
```
vim ~/.streamlit/config.toml
```

La config est donnée ici : https://docs.streamlit.io/develop/api-reference/configuration/config.toml

Voici un exemple :
```
[browser]
serverAddress = "0.0.0.0"
gatherUsageStats = false

[server]
address = "0.0.0.0"
port = 8888
maxUploadSize = 1500
```

Dans la section **browser** :
- **serverAddress** permet de ne pas afficher dans la console l'IP de l'interface LAN et l'IP publique
- **gatherUsageStats** permet de désactiver l'envoi de statistiques à Streamlit

Dans la section **server** :
- **address** permet d'écouter sur toutes les interfaces (ou l'interface donnée). Par défaut 0.0.0.0
- **port** permet de changer le port d'écoute, 8501 par défaut
- **maxUploadSize** permet de changer la taille max des fichiers uploadés en MB, par défaut 200

### Lancement en service systemd (optionnel)

Un exemple de fichier de service systemd est fourni dans `ressources/hermes.service`, pour lancer l'interface web automatiquement au démarrage (et la relancer en cas de plantage).

Adaptez-le à votre installation (utilisateur, chemin du projet, chemin du venv) puis installez-le :
```bash
sudo cp ressources/hermes.service /etc/systemd/system/hermes.service
sudo systemctl daemon-reload
sudo systemctl enable --now hermes.service
```

Pour suivre les logs :
```bash
sudo journalctl -u hermes.service -f
```
