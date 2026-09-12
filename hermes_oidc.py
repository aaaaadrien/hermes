"""
hermes_oidc.py
================
Authentification OIDC (exemple Keycloak ou autre IDP) pour Hermes, en complément
de l'authentification locale (userpass).

Ne gère QUE le protocole OIDC (discovery, échange de code, vérification du
id_token, construction des URLs de connexion/déconnexion).
La résolution du compte local associé (création à la première connexion, session, cookie)
reste dans hermes_accounts.py, pour qu'un utilisateur OIDC soit traité
exactement comme un utilisateur local une fois authentifié.
(fichier annexe pour OIDC pour que ça soit propre)

Configuration attendue dans hermes.conf :
    [oidc]
    enabled       = true
    issuer        = https://sso.example.org/realms/mon-realm
    client_id     = hermes
    client_secret = ...
    redirect_uri  = https://hermes.linuxtricks.fr/
    scope         = openid profile email

Importé par hermes_accounts.py :
    from hermes_oidc import (
        oidc_actif, construire_url_autorisation, traiter_callback, construire_url_deconnexion,
    )
"""

import configparser
import hashlib
import hmac
import secrets
import time
from typing import Optional

import requests
import streamlit as st
from authlib.integrations.requests_client import OAuth2Session
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import KeySet


def oidc_actif(conf: configparser.ConfigParser) -> bool:
    """True si [oidc] enabled = true (ou 1/yes/on) dans hermes.conf."""
    return conf.getboolean("oidc", "enabled", fallback=False)


@st.cache_resource
def _oidc_discovery(issuer: str) -> dict:
    """Récupère le document de découverte OIDC (.well-known), mis en cache."""
    resp = requests.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration", timeout=10)
    resp.raise_for_status()
    return resp.json()


@st.cache_resource
def _oidc_jwks(jwks_uri: str) -> KeySet:
    """Récupère et met en cache le trousseau de clés publiques de l'IdP."""
    resp = requests.get(jwks_uri, timeout=10)
    resp.raise_for_status()
    return KeySet.import_key_set(resp.json())


def _generer_state_signe(secret: str) -> str:
    """
    Génère un paramètre 'state' anti-CSRF auto-vérifiable (nonce + timestamp + HMAC),
    pour ne pas dépendre de st.session_state qui peut être réinitialisé entre l'aller
    (redirection vers l'IdP) et le retour (callback) sur certains déploiements Streamlit.
    """
    nonce = secrets.token_urlsafe(16)
    horodatage = str(int(time.time()))
    base = f"{nonce}.{horodatage}"
    signature = hmac.new(secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{base}.{signature}"


def _verifier_state_signe(state: str, secret: str, duree_max_s: int = 600) -> bool:
    """Vérifie la signature et la fraîcheur d'un state généré par _generer_state_signe."""
    try:
        nonce, horodatage, signature = state.split(".")
        base = f"{nonce}.{horodatage}"
        attendu = hmac.new(secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, attendu):
            return False
        if int(time.time()) - int(horodatage) > duree_max_s:
            return False
        return True
    except Exception:
        return False


def construire_url_autorisation(conf: configparser.ConfigParser) -> Optional[str]:
    """
    Construit l'URL de redirection vers l'IdP pour démarrer le flux OIDC
    (à afficher via un bouton "Connexion SSO"). Retourne None si le
    document de découverte est inaccessible.
    """
    issuer        = conf.get("oidc", "issuer")
    client_id     = conf.get("oidc", "client_id")
    client_secret = conf.get("oidc", "client_secret")
    redirect_uri  = conf.get("oidc", "redirect_uri")
    scope         = conf.get("oidc", "scope", fallback="openid profile email")

    try:
        discovery = _oidc_discovery(issuer)
    except Exception:
        return None

    client = OAuth2Session(client_id, client_secret, redirect_uri=redirect_uri, scope=scope)
    state_signe = _generer_state_signe(client_secret)
    uri, _ = client.create_authorization_url(discovery["authorization_endpoint"], state=state_signe)
    return uri


def traiter_callback(conf: configparser.ConfigParser) -> Optional[dict]:
    """
    À appeler à chaque run tant que l'utilisateur n'est pas authentifié : si l'URL
    contient ?code=&state= (retour de l'IdP), échange le code, vérifie le id_token
    (signature + audience + issuer via JWKS), et retourne les claims du token
    ({'sub', 'preferred_username', 'email', ...}).

    Retourne None si ce n'est pas un callback OIDC (paramètres absents), et affiche
    une erreur + st.stop() en cas d'échec de validation (code/state invalide, token
    invalide...).
    """
    params = st.query_params
    code  = params.get("code")
    state = params.get("state")
    if not code:
        return None

    issuer        = conf.get("oidc", "issuer")
    client_id     = conf.get("oidc", "client_id")
    client_secret = conf.get("oidc", "client_secret")
    redirect_uri  = conf.get("oidc", "redirect_uri")

    if not state or not _verifier_state_signe(state, client_secret):
        st.error("❌ État OIDC invalide ou expiré (CSRF / lien périmé). Merci de relancer la connexion.")
        st.query_params.clear()
        if st.button("🔁 Relancer la connexion"):
            st.rerun()
        st.stop()

    try:
        discovery = _oidc_discovery(issuer)
    except Exception as e:
        st.error(f"❌ Impossible de contacter le fournisseur d'identité ({issuer}) : {e}")
        st.query_params.clear()
        st.stop()

    client = OAuth2Session(client_id, client_secret, redirect_uri=redirect_uri)
    try:
        token = client.fetch_token(discovery["token_endpoint"], code=code, grant_type="authorization_code")
    except Exception as e:
        st.error(f"❌ Échec de l'échange du code OIDC : {e}")
        st.query_params.clear()
        st.stop()

    try:
        jwks      = _oidc_jwks(discovery["jwks_uri"])
        token_obj = joserfc_jwt.decode(token["id_token"], jwks)
        registre  = joserfc_jwt.JWTClaimsRegistry(
            aud={"essential": True, "value": client_id},
            iss={"essential": True, "value": issuer},
        )
        registre.validate(token_obj.claims)
        claims = dict(token_obj.claims)
    except Exception as e:
        st.error(f"❌ id_token invalide : {e}")
        st.query_params.clear()
        st.stop()

    if not claims.get("sub"):
        st.error("❌ Le id_token ne contient pas de claim 'sub'.")
        st.query_params.clear()
        st.stop()

    claims["_id_token"] = token.get("id_token")
    claims["_end_session_endpoint"] = discovery.get("end_session_endpoint")
    return claims


def construire_url_deconnexion(conf: configparser.ConfigParser, id_token: Optional[str],
                                end_session_endpoint: Optional[str]) -> Optional[str]:
    """
    Construit l'URL de déconnexion côté IdP (si disponible). Retourne None si l'IdP
    n'expose pas de end_session_endpoint (dans ce cas, seule la session locale Hermes
    est fermée, l'utilisateur pourrait rester connecté côté IdP).
    """
    if not end_session_endpoint:
        return None
    redirect_uri = conf.get("oidc", "redirect_uri")
    url = f"{end_session_endpoint}?post_logout_redirect_uri={redirect_uri}"
    if id_token:
        url += f"&id_token_hint={id_token}"
    return url
