"""Meta (Facebook/Instagram) + Google Business Profile publishing helpers."""
import logging
from typing import Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger("social_publishing")

GRAPH = "https://graph.facebook.com/v21.0"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GBP_ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
GBP_INFO_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
GBP_V4_BASE = "https://mybusiness.googleapis.com/v4"


# ---------------------------------------------------------------------------
# Meta (Facebook / Instagram)
# ---------------------------------------------------------------------------
async def meta_exchange_code(app_id: str, app_secret: str, redirect_uri: str, code: str) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{GRAPH}/oauth/access_token", params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        })
    if r.status_code != 200:
        raise HTTPException(502, f"Échange du code Meta échoué: {r.text[:300]}")
    return r.json()


async def meta_long_lived_token(app_id: str, app_secret: str, short_token: str) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{GRAPH}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        })
    if r.status_code != 200:
        raise HTTPException(502, f"Échange token longue durée Meta échoué: {r.text[:300]}")
    return r.json()


async def meta_fetch_pages(user_token: str) -> list:
    """Return [{id, name, access_token, instagram: {id, username} | None}] for the user's Pages."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{GRAPH}/me/accounts", params={
            "access_token": user_token,
            "fields": "id,name,access_token,instagram_business_account{id,username}",
            "limit": 50,
        })
    if r.status_code != 200:
        raise HTTPException(502, f"Récupération des Pages Facebook échouée: {r.text[:300]}")
    pages = []
    for p in r.json().get("data", []):
        pages.append({
            "id": p["id"],
            "name": p.get("name", ""),
            "access_token": p["access_token"],
            "instagram": p.get("instagram_business_account"),
        })
    if not pages:
        raise HTTPException(400, "Aucune Page Facebook trouvée sur ce compte. Créez une Page Facebook et réessayez.")
    return pages


async def meta_publish_facebook(page_id: str, page_token: str, message: str,
                                link: Optional[str] = None, image_url: Optional[str] = None) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        if image_url:
            data = {"url": image_url, "caption": message + (f"\n\n{link}" if link else ""),
                    "published": "true", "access_token": page_token}
            r = await client.post(f"{GRAPH}/{page_id}/photos", data=data)
        else:
            data = {"message": message, "access_token": page_token}
            if link:
                data["link"] = link
            r = await client.post(f"{GRAPH}/{page_id}/feed", data=data)
    if r.status_code not in (200, 201):
        if r.status_code == 401 or "OAuthException" in r.text:
            raise HTTPException(400, f"Token Facebook expiré ou permissions manquantes. Reconnectez Meta. ({r.text[:200]})")
        raise HTTPException(502, f"Publication Facebook échouée: {r.text[:300]}")
    j = r.json()
    post_id = j.get("post_id") or j.get("id") or ""
    return {"post_id": post_id, "post_url": f"https://www.facebook.com/{post_id}" if post_id else None}


async def meta_publish_instagram(ig_user_id: str, page_token: str, caption: str, image_url: str) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{GRAPH}/{ig_user_id}/media", data={
            "image_url": image_url, "caption": caption, "access_token": page_token,
        })
        if r.status_code not in (200, 201):
            raise HTTPException(502, f"Création du média Instagram échouée (vérifiez que l'image est une URL JPEG publique): {r.text[:300]}")
        creation_id = r.json().get("id")
        if not creation_id:
            raise HTTPException(502, "Instagram n'a pas retourné d'identifiant de média.")
        r2 = await client.post(f"{GRAPH}/{ig_user_id}/media_publish", data={
            "creation_id": creation_id, "access_token": page_token,
        })
        if r2.status_code not in (200, 201):
            raise HTTPException(502, f"Publication Instagram échouée: {r2.text[:300]}")
        media_id = r2.json().get("id", "")
        post_url = None
        try:
            r3 = await client.get(f"{GRAPH}/{media_id}", params={"fields": "permalink", "access_token": page_token})
            if r3.status_code == 200:
                post_url = r3.json().get("permalink")
        except Exception:
            pass
    return {"media_id": media_id, "post_url": post_url}


# ---------------------------------------------------------------------------
# Google Business Profile
# ---------------------------------------------------------------------------
async def gbp_exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
    if r.status_code != 200:
        raise HTTPException(502, f"Échange du code Google échoué: {r.text[:300]}")
    return r.json()


async def gbp_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
    if r.status_code != 200:
        raise HTTPException(400, f"Token Google Business expiré ou révoqué. Reconnectez votre compte. ({r.text[:200]})")
    return r.json()["access_token"]


async def gbp_list_locations(access_token: str) -> list:
    """Return [{location: 'accounts/x/locations/y', title, account}] for all GBP accounts."""
    headers = {"Authorization": f"Bearer {access_token}"}
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(GBP_ACCOUNTS_URL, headers=headers)
        if r.status_code == 403 and "SCOPE_INSUFFICIENT" in r.text:
            raise HTTPException(403, (
                "Le token Google Business n'a pas le scope business.manage (ancienne connexion). "
                "Cliquez « Déconnecter Google Business » puis reconnectez-vous — le nouveau consentement "
                "inclura le bon scope."
            ))
        if r.status_code == 403:
            raise HTTPException(403, (
                "Google Business refuse l'accès (quota API à 0 ?). Vérifiez que votre demande d'accès "
                "GBP API a été approuvée par Google et que « My Business Account Management API » est activée. "
                f"Détail : {r.text[:200]}"
            ))
        if r.status_code != 200:
            raise HTTPException(502, f"Liste des comptes Google Business échouée (API activée + projet approuvé ?): {r.text[:300]}")
        accounts = r.json().get("accounts", [])
        for acc in accounts:
            acc_name = acc.get("name", "")  # "accounts/123"
            rl = await client.get(
                f"{GBP_INFO_BASE}/{acc_name}/locations",
                headers=headers,
                params={"readMask": "name,title", "pageSize": 100},
            )
            if rl.status_code != 200:
                logger.warning("GBP locations list failed for %s: %s", acc_name, rl.text[:200])
                continue
            for loc in rl.json().get("locations", []):
                results.append({
                    "location": f"{acc_name}/{loc['name']}",  # accounts/x/locations/y
                    "title": loc.get("title", loc["name"]),
                    "account": acc.get("accountName", acc_name),
                })
    if not results:
        raise HTTPException(400, "Aucun établissement Google Business Profile trouvé sur ce compte.")
    return results


async def gbp_create_post(access_token: str, parent: str, summary: str, cta_url: Optional[str] = None) -> dict:
    body = {"languageCode": "fr", "summary": summary[:1500], "topicType": "STANDARD"}
    if cta_url:
        body["callToAction"] = {"actionType": "LEARN_MORE", "url": cta_url}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{GBP_V4_BASE}/{parent}/localPosts",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=body,
        )
    if r.status_code not in (200, 201):
        raise HTTPException(502, f"Création du post Google Business échouée: {r.text[:300]}")
    return r.json()


# ---------------------------------------------------------------------------
# AI post text generation
# ---------------------------------------------------------------------------
_NETWORK_SPECS = {
    "facebook": "un post Facebook engageant de 400-800 caractères : ton accessible et chaleureux, 2-3 emojis pertinents, une question ou un appel à l'action à la fin, 2-3 hashtags maximum. NE PAS inclure d'URL (elle sera ajoutée en lien).",
    "instagram": "une légende Instagram de 300-600 caractères : ton dynamique et visuel, emojis, phrases courtes, appel à l'action, puis 5-8 hashtags pertinents à la fin.",
    "gbp": "un post Google Business Profile de 400-1200 caractères (limite stricte 1500) : ton professionnel et local, phrases claires, valeur concrète pour le client, appel à l'action final. AUCUN hashtag, AUCUNE URL.",
}


async def generate_social_post_text(llm_key: str, draft: dict, network: str) -> str:
    title = draft.get("title", "")
    body = (draft.get("body_markdown") or "")[:3000]
    spec = _NETWORK_SPECS.get(network, _NETWORK_SPECS["facebook"])
    prompt = f"""Génère {spec}

Le post est rédigé en français à partir de cet article :
TITRE: {title}
EXTRAIT: {body}

Retourne UNIQUEMENT le texte du post, rien d'autre."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=llm_key,
            session_id=f"{network}-{draft.get('id')}",
            system_message="Tu es un expert en copywriting réseaux sociaux pour PME.",
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        resp = await chat.send_message(UserMessage(text=prompt))
        text = (resp or "").strip().strip('"').strip("'")
        if text:
            return text[:1500] if network == "gbp" else text
    except Exception as exc:
        logger.warning("%s post text generation failed: %s", network, exc)
    fallback = f"📢 Nouveau contenu : {title}\n\nDécouvrez nos conseils et notre expertise."
    return fallback if network == "gbp" else fallback + "\n\n#SEO #Conseils"
