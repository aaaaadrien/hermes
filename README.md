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

##  Lancement

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
