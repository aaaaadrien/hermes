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

## Installation des dépendances

Via pip (universel)
```bash
pip install openai requests streamlit ddgs bs4 pymupdf pandas openpyxl tabulate odfpy fpdf2 python-docx cachetools
```
- Gestion LLM : openai
- Requêtes LLM et externe : requests
- Interface web : streamlit
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
De fait, `ffmpeg` doit donc être installé et accessible dans le `PATH`.

Dans le cadre de RHEL et clones, ffmpeg est dispo dans RPM Fusion Free : 
```bash
sudo dnf install --nogpgcheck https://dl.fedoraproject.org/pub/epel/epel-release-latest-$(rpm -E %rhel).noarch.rpm
sudo dnf install --nogpgcheck https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm
```


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

Si streamlit est introuvable (pas dans le $PATH) : 
```bash
~/.local/bin/streamlit run hermes-web.py
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
#serverAddress = "localhost"
gatherUsageStats = false
serverPort = 8501

[server]
maxUploadSize = 1500
```

Dans la section **browser** :
- **serverAddress** permet de changer l'adresse d'écoute, 0.0.0.0 pour toutes les adresses, localhost par défaut
- **serverPort** permet de changer le port d'écoute, 8501 par défaut
- **gatherUsageStats** permet de désactiver l'envoi de statistiques à Streamlit

Dans la section **server** :
- **maxUploadSize** permet de changer la taille max des fichiers uploadés en MB, par défaut 200
