# Chatbot perso avec gestion d'outils (testé avec llama.cpp) 

- Agent conversationnel en Python connecté à un modèle LLM tournant en local via **llama.cpp**.
- Disponible en deux interfaces : **terminal (CLI)** et **web (Streamlit)**.
- Expérimentation de l'usage de tools, nécessite un modèle compatible/

## Fichiers

- hermes.conf : Configuration partagée
- hermes-cli.py : Interface en ligne de commande
- hermes-web.py : Interface web Streamlit


## Prérequis

- Python **3.9+**
- Un serveur d'inférence (exemple llama.cpp) mais pas forcément sur la même machine
- Un serveur whisper.cpp (optionnel) pour retranscrire de l'audio ou une vidéo pour analyse mais pas forcément sur la même machine

## Création d'un venv Python 

Pour isoler les dépendances python, créer un virtual env :
```bash
python3 -m venv venv
source venv/bin/activate
```

## Installation des dépendances

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
- Divers : cachetools

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

Active la gestion de comptes (utilisateur/mot de passe) et la sauvegarde des conversations, stockées dans **`hermes-users.db`** (base SQLite créée automatiquement au premier lancement, aucun serveur de base de données externe requis).

Une fois connecté, chaque échange est automatiquement enregistré. La sidebar propose de lister, reprendre, renommer et supprimer ses conversations. 

Si on veut autoriser la création de compte (juste username + pass, pas de mail) mettre **`register`** à on.

##  Lancement

### Copie de la config

Avant toute chose, créez le fichier de config à partir de l'exemple donné : 
```bash
cp hermes.conf.example hermes.conf
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
