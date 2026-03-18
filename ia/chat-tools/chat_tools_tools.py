"""
chat_tools_tools.py
===================
Module partagé contenant les outils (météo, wiki, change).
Importé par chat-tools-cli.py et chat-tools-web.py.
Important : pas de - mais des _ dans le fichier pour importer le module !

Utilisation :
    from chat_tools_tools import CATALOGUE_OUTILS, outils_actifs, executer_outil
"""

import configparser
import requests

# Récupère le bulletin météo complet pour une ville donnée.
def outil_meteo(ville: str) -> str:
    """
      1. Géolocalisation via l'API open-meteo geocoding
      2. Récupération des données météo (température, humidité, vent, état du ciel)
      3. Traduction du code météo WMO en texte lisible
    """
    try:
        geo_url = (
            f"https://geocoding-api.open-meteo.com/v1/search"
            f"?name={ville}&count=1&language=fr&format=json"
        )
        geo = requests.get(geo_url, timeout=5).json()
        if not geo.get("results"):
            return f"Désolé, la ville « {ville} » est introuvable."

        lieu = geo["results"][0]
        lat, lon = lieu["latitude"], lieu["longitude"]

        meteo_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
            f"&timezone=auto"
        )
        res     = requests.get(meteo_url, timeout=5).json()
        donnees = res["current"]

        traduction_temps = {
            0:  "Ciel dégagé ☀️",    1:  "Principalement dégagé 🌤️",
            2:  "Partiellement nuageux ⛅", 3: "Couvert ☁️",
            45: "Brouillard 🌫️",     48: "Brouillard givrant 🌫️❄️",
            51: "Bruine légère 🌦️",  61: "Pluie légère 🌧️",
            63: "Pluie modérée 🌧️",  65: "Pluie forte 🌧️💧",
            71: "Chute de neige légère 🌨️", 95: "Orage ⛈️",
        }
        etat = traduction_temps.get(donnees["weather_code"], "Conditions variables")

        return (
            f"Météo à {lieu['name']} ({lieu.get('country', '')}) : {etat}\n"
            f"  🌡 Température : {donnees['temperature_2m']}°C\n"
            f"  💧 Humidité    : {donnees['relative_humidity_2m']}%\n"
            f"  💨 Vent        : {donnees['wind_speed_10m']} km/h"
        )

    except requests.exceptions.Timeout:
        return "⚠️ Délai d'attente dépassé pour l'API météo."
    except Exception as e:
        return f"⚠️ Impossible de récupérer la météo ({e})."

# Retourne le résumé Wikipédia (version française) du sujet demandé.
def outil_wiki_old(sujet: str) -> str:
    """
    Utilise l'API REST de Wikipédia pour obtenir l'extrait de la page.
    """

    # Fix sinon bloqué
    headers = {
        'User-Agent': 'Linuxtricks/1.0'
    }
    
    try:
        url  = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{sujet.replace(' ', '_')}"
        res  = requests.get(url, headers=headers, timeout=5).json()
        texte = res.get("extract")
        if not texte:
            return f"Aucune page Wikipédia trouvée pour « {sujet} »."
        return texte

    except requests.exceptions.Timeout:
        return "⚠️ Délai d'attente dépassé pour Wikipédia."
    except Exception as e:
        return f"⚠️ Erreur lors de la recherche Wikipédia ({e})."
        
# Retourne la page Wikipédia (version française) du sujet demandé.
def outil_wiki(sujet: str) -> str:
    """
    Utilise l'Action API de Wikipédia pour obtenir l'entièreté du contenu d'une page.
    """
    url = "https://fr.wikipedia.org/w/api.php"
    
    # Fix sinon bloqué
    headers = {
        'User-Agent': 'Linuxtricks/1.0'
    }
    
    params = {
        "action": "query",
        "prop": "extracts",
        "explaintext": True,  # Récupère le texte brut sans HTML
        "titles": sujet,
        "format": "json",
        "redirects": 1
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        # Vérifie si la requête a réussi avant de tenter le décodage JSON
        response.raise_for_status()
        
        data = response.json()
        pages = data.get("query", {}).get("pages", {})
        
        # Récupération de la première page trouvée
        page_id = next(iter(pages))
        page_data = pages[page_id]

        if "missing" in page_data or page_id == "-1":
            return f"Aucune page Wikipédia trouvée pour « {sujet} »."

        texte = page_data.get("extract")
        if not texte:
            return f"Le contenu de la page « {sujet} » est vide."
            
        return texte

    except requests.exceptions.Timeout:
        return "⚠️ Délai d'attente dépassé pour Wikipédia."
    except requests.exceptions.HTTPError as e:
        return f"⚠️ Erreur HTTP (Accès refusé ou page inexistante) : {e}"
    except Exception as e:
        return f"⚠️ Erreur lors de la recherche Wikipédia ({e})."
        

# Convertit une somme d'une devise vers une autre en temps réel.
def outil_argent(montant: float, de_monnaie: str, vers_monnaie: str) -> str:
    """
    Utilise l'API open.er-api.com (gratuite, sans clé).

    Paramètres :
      montant      : valeur numérique à convertir
      de_monnaie   : code ISO 4217 source (ex : EUR)
      vers_monnaie : code ISO 4217 cible  (ex : USD)
    """
    try:
        url = f"https://open.er-api.com/v6/latest/{de_monnaie.upper()}"
        res = requests.get(url, timeout=5).json()

        if res.get("result") != "success":
            return f"⚠️ Devise source « {de_monnaie} » non reconnue."

        taux = res["rates"].get(vers_monnaie.upper())
        if taux is None:
            return f"⚠️ Devise cible « {vers_monnaie} » non reconnue."

        resultat = montant * taux
        return (
            f"💱 {montant} {de_monnaie.upper()} = {resultat:.2f} {vers_monnaie.upper()}\n"
            f"  Taux : 1 {de_monnaie.upper()} = {taux:.4f} {vers_monnaie.upper()}"
        )

    except requests.exceptions.Timeout:
        return "⚠️ Délai d'attente dépassé pour l'API de change."
    except Exception as e:
        return f"⚠️ Erreur de conversion monétaire ({e})."


# Catalogue JSON (schéma pour le LLM
CATALOGUE_OUTILS = [
    {
        "type": "function",
        "function": {
            "name": "outil_meteo",
            "description": "Donne la météo complète et en temps réel d'une ville (température, humidité, vent, état du ciel).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ville": {
                        "type": "string",
                        "description": "Nom de la ville (ex : Paris, London, Tokyo).",
                    }
                },
                "required": ["ville"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "outil_wiki",
            "description": "Recherche et retourne un résumé Wikipédia sur n'importe quel sujet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sujet": {
                        "type": "string",
                        "description": "Sujet à rechercher sur Wikipédia (ex : Tour Eiffel, Albert Einstein).",
                    }
                },
                "required": ["sujet"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "outil_argent",
            "description": "Convertit un montant d'une devise vers une autre avec les taux en temps réel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "montant":      {"type": "number", "description": "Valeur à convertir (ex : 100)."},
                    "de_monnaie":   {"type": "string", "description": "Code ISO 4217 source (ex : EUR)."},
                    "vers_monnaie": {"type": "string", "description": "Code ISO 4217 cible  (ex : USD)."},
                },
                "required": ["montant", "de_monnaie", "vers_monnaie"],
            },
        },
    },
]

# Emojis d'affichage (utilisés dans l'interface web)
ICONES_OUTILS = {
    "outil_meteo":  "🌤️ Météo",
    "outil_wiki":   "📖 Wikipédia",
    "outil_argent": "💱 Change",
}



# Fonctions utilitaires
# Retourne la liste des outils activés selon la section [tools] du .conf. Permet d'activer/désactiver chaque outil sans toucher au code.
def outils_actifs(conf: configparser.ConfigParser) -> list:
    mapping = {
        "enable_meteo":  "outil_meteo",
        "enable_wiki":   "outil_wiki",
        "enable_argent": "outil_argent",
    }
    actifs = []
    for cle, nom in mapping.items():
        if conf.getboolean("tools", cle, fallback=True):
            actifs.extend([o for o in CATALOGUE_OUTILS if o["function"]["name"] == nom])
    return actifs

# Dispatcher central : appelle la bonne fonction selon le nom renvoyé par le LLM.
# Toujours utiliser cette fonction plutôt qu'appeler les outils directement.
def executer_outil(nom: str, args: dict) -> str:
    if nom == "outil_meteo":
        return outil_meteo(args["ville"])
    elif nom == "outil_wiki":
        return outil_wiki(args["sujet"])
    elif nom == "outil_argent":
        return outil_argent(args["montant"], args["de_monnaie"], args["vers_monnaie"])
    return f"⚠️ Outil inconnu : « {nom} »."
