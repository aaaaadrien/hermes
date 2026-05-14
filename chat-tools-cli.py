"""
chat-tools-cli.py
=================
Agent conversationnel en ligne de commande utilisant un LLM local.
La configuration est lue depuis chat-tools.conf.
Les outils sont définis dans chat_tools_tools.py.

Lancement :
  python chat-tools-cli.py
"""

import json
import sys
import configparser
from pathlib import Path

from openai import OpenAI

# Module partagé contenant outils + catalogue + dispatcher
from chat_tools_tools import outils_actifs, executer_outil, ICONES_OUTILS


# Couleurs pour la console
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    CYAN   = "\033[96m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    DIM    = "\033[2m"
    BLUE   = "\033[94m"
    RED    = "\033[91m"


# Chargemen config
def charger_config(chemin: str = "chat-tools.conf") -> configparser.ConfigParser:
    conf = configparser.ConfigParser()
    path = Path(chemin)
    if not path.exists():
        path = Path(__file__).parent / chemin
    if not path.exists():
        print(f"{C.RED}[ERREUR] Fichier de configuration introuvable : {chemin}{C.RESET}")
        sys.exit(1)
    conf.read(str(path), encoding="utf-8")
    return conf


# Init client LLM
def creer_client(conf: configparser.ConfigParser) -> OpenAI:
    return OpenAI(
        base_url=conf.get("llm", "base_url"),
        api_key=conf.get("llm", "api_key"),
    )


# Programme (boucle) 
def main():
    conf   = charger_config()
    client = creer_client(conf)

    model       = conf.get("llm",   "model")
    max_tokens  = conf.getint("llm",  "max_tokens",  fallback=2048)
    temperature = conf.getfloat("llm", "temperature", fallback=0.7)
    sys_prompt  = conf.get("agent", "system_prompt")
    banner      = conf.get("cli",   "banner")
    user_pfx    = conf.get("cli",   "user_prefix",  fallback="Vous")
    agent_pfx   = conf.get("cli",   "agent_prefix", fallback="Agent")

    outils = outils_actifs(conf)   # liste filtrée selon [tools] dans le .conf

    # entete
    print(f"\n{C.BOLD}{C.CYAN}{banner}{C.RESET}")
    print(f"{C.DIM}Modèle : {model}  |  Outils actifs : {len(outils)}{C.RESET}\n")

    messages = [{"role": "system", "content": sys_prompt}]

    while True:
        # saisir user
        try:
            prompt = input(f"{C.BOLD}{C.GREEN}{user_pfx} :{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C.DIM}Session terminée.{C.RESET}")
            break

        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit", "quitter", "q"):
            print(f"{C.DIM}Au revoir !{C.RESET}")
            break

        messages.append({"role": "user", "content": prompt})

        # Premier appel LLM
        try:
            reponse = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=outils,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            print(f"{C.RED}[ERREUR LLM] {e}{C.RESET}")
            messages.pop()
            continue

        message_ia = reponse.choices[0].message

        # Le LLM veut utiliser un outil
        if message_ia.tool_calls:
            messages.append(message_ia)

            for appel in message_ia.tool_calls:
                nom_outil = appel.function.name
                label     = ICONES_OUTILS.get(nom_outil, f"🔧 {nom_outil}")
                try:
                    args = json.loads(appel.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                print(f"  {C.YELLOW}⚙  {label} — args : {args}{C.RESET}")
                resultat = executer_outil(nom_outil, args)   # ← dispatcher partagé
                print(f"  {C.DIM}↳ {resultat}{C.RESET}")

                messages.append({
                    "role":         "tool",
                    "tool_call_id": appel.id,
                    "name":         nom_outil,
                    "content":      resultat,
                })

            # Synthese et réponse finale
            try:
                reponse_finale = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                texte_final = reponse_finale.choices[0].message.content
            except Exception as e:
                texte_final = f"[ERREUR lors de la synthèse : {e}]"

            print(f"\n{C.BOLD}{C.BLUE}{agent_pfx} :{C.RESET} {texte_final}\n")
            messages.append({"role": "assistant", "content": texte_final})

        # Sinon on utilise pas d'outil
        else:
            texte = message_ia.content or "(réponse vide)"
            print(f"\n{C.BOLD}{C.BLUE}{agent_pfx} :{C.RESET} {texte}\n")
            messages.append({"role": "assistant", "content": texte})


if __name__ == "__main__":
    main()
