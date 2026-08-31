"""
reddit_client.py — Lee posts públicos de subreddits financieros (r/wallstreetbets,
r/stocks, r/investing, r/StockMarket) para sentimiento retail.

Por qué Reddit y no X/Twitter: X cobra por post leído desde 2026 (sin tier
gratis para developers nuevos) y no tiene ningún filtro de calidad. Reddit
tiene un tier gratis real para uso no comercial (100 QPM por OAuth client,
confirmado en support.reddithelp.com, actualizado mayo 2026) y el score
(upvotes) actúa como filtro de calidad incorporado.

IMPORTANTE — proceso de acceso (cambió en 2026, ya no es autoservicio puro):
1. Pedir acceso a la Data API para uso no comercial acá:
   https://support.reddithelp.com/hc/en-us/requests/new?ticket_form_id=14868593862164
2. Registrar una app tipo "script" en https://www.reddit.com/prefs/apps para
   obtener client_id/client_secret.
3. Cargar en tu config.env (NUNCA se sube al repo, está en .gitignore):
   REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME

Reddit exige un User-Agent con formato específico y con tu usuario real
(si no, te limita agresivamente) — por eso se arma automático acá abajo
a partir de REDDIT_USERNAME, nunca hardcodeado en el código.

Usa OAuth de solo lectura (client_credentials) — NO necesita la contraseña
de tu cuenta de Reddit, solo las credenciales de la app.
"""
import requests
import os
import time

REDDIT_SUBREDDITS_DEFAULT = ["wallstreetbets", "stocks", "investing", "StockMarket"]

_token_cache = {"access_token": None, "expira": 0}


def _build_user_agent() -> str:
    """
    Arma el User-Agent en el formato que exige Reddit:
    <plataforma>:<id de la app>:<version> (by /u/<usuario>)
    El usuario sale de REDDIT_USERNAME (config.env local, nunca del código).
    """
    username = os.getenv("REDDIT_USERNAME", "").strip()
    contacto = f"(by /u/{username})" if username else "(contacto no configurado)"
    return f"script:agente-wallbit:v1.0 {contacto}"


def _get_access_token():
    """Pide (o reusa desde caché) un token OAuth de solo lectura."""
    if _token_cache["access_token"] and time.time() < _token_cache["expira"]:
        return _token_cache["access_token"]

    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    try:
        auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
        headers = {"User-Agent": _build_user_agent()}
        data = {"grant_type": "client_credentials"}
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=auth, data=data, headers=headers, timeout=10
        )
        r.raise_for_status()
        token_data = r.json()
        _token_cache["access_token"] = token_data["access_token"]
        _token_cache["expira"] = time.time() + token_data.get("expires_in", 3600) - 60
        return _token_cache["access_token"]
    except Exception:
        return None


def _parse_reddit_listing(data: dict) -> list:
    """
    Lógica PURA de parseo de la respuesta JSON de Reddit. Separada de la
    llamada de red para poder testearla sin internet.
    """
    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        posts.append({
            "titulo": p.get("title", ""),
            "subreddit": p.get("subreddit", ""),
            "score": p.get("score", 0),
            "comentarios": p.get("num_comments", 0),
            "url": f"https://reddit.com{p.get('permalink', '')}",
            "fecha": p.get("created_utc")
        })
    posts.sort(key=lambda x: x["score"], reverse=True)
    return posts


def search_reddit(query: str, subreddits: list = None, limit: int = 10) -> dict:
    """
    Busca menciones de un ticker/empresa en subreddits financieros de la
    última semana. Devuelve título, subreddit, score (upvotes), cantidad
    de comentarios y URL — rankeado por score descendente.
    """
    token = _get_access_token()
    if not token:
        return {
            "ok": False,
            "error": "Reddit no configurado — falta REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET en config.env"
        }

    subreddits = subreddits or REDDIT_SUBREDDITS_DEFAULT
    subreddit_str = "+".join(subreddits)

    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": _build_user_agent()
        }
        params = {"q": query, "restrict_sr": "true", "sort": "relevance", "t": "week", "limit": limit}
        url = f"https://oauth.reddit.com/r/{subreddit_str}/search"

        r = requests.get(url, headers=headers, params=params, timeout=12)
        r.raise_for_status()
        return {"ok": True, "data": _parse_reddit_listing(r.json())}

    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout consultando Reddit"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
