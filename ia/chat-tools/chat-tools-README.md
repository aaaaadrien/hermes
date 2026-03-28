# Tests de Chat LLM avec outils (testé avec llama.cpp) 

- Agent conversationnel en Python connecté à un modèle LLM tournant en local via **llama.cpp**.
- Disponible en deux interfaces : **terminal (CLI)** et **web (Streamlit)**.
- Expérimentation de l'usage de tools, nécessite un modèle compatible/

## Fichiers

- chat-tools.conf : Configuration partagée
- chat-tools-cli.py : Interface en ligne de commande
- chat-tools-web.py : Interface web Streamlit


## Prérequis

- Python **3.9+**
- Un serveur d'inférence (exemple llama.cpp) mais pas forcément sur la même machine


## Installation des dépendances

```bash
pip install openai requests streamlit ddgs
```


##  Lancement

### Interface CLI (terminal)

```bash
python chat-tools-cli.py
```

### Interface Web (Streamlit)

```bash
streamlit run chat-tools-web.py
```

Si streamlit est introuvable (pas dans le $PATH) : 
```bash
~/.local/bin/streamlit run chat-tools-web.py
```

Si besoin on peut éditer le fichier suivant pour configurer streamlit :
```
vim .streamlit/config.toml
```

Avec dedans :
```
# COnfig : https://docs.streamlit.io/develop/api-reference/configuration/config.toml
[browser]
serverAddress = "0.0.0.0"
#serverAddress = "localhost"
gatherUsageStats = false
serverPort = 8501
```
