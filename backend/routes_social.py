from datetime import datetime
from datetime import timedelta
from datetime import timezone
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional
import httpx
import jwt
import logging
import os
from app_core import EMERGENT_LLM_KEY, JWT_ALGORITHM, JWT_SECRET, api, db, dec, enc, get_current_user, now_iso
from routes_google import GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET

logger = logging.getLogger("routes_social")

# ---------------------------------------------------------------------------
# Meta (Facebook + Instagram) OAuth + Publishing
# ---------------------------------------------------------------------------
META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_REDIRECT_URI = os.environ.get("META_REDIRECT_URI", "")
META_SCOPES = "pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish,business_management"


class SocialPublishRequest(BaseModel):
    page_id: Optional[str] = None
    image_url: Optional[str] = None
    location: Optional[str] = None


@api.get("/meta/status")
async def meta_status(user=Depends(get_current_user)):
    doc = await db.users.find_one({"id": user["id"]}, {"meta": 1, "_id": 0})
    m = (doc or {}).get("meta") or {}
    pages = [
        {"id": p["id"], "name": p.get("name"), "instagram_id": p.get("instagram_id"),
         "instagram_username": p.get("instagram_username")}
        for p in (m.get("pages") or [])
    ]
    return {
        "server_configured": bool(META_APP_ID and META_APP_SECRET and META_REDIRECT_URI),
        "connected": bool(m.get("user_token")),
        "connected_at": m.get("connected_at"),
        "expires_at": m.get("expires_at"),
        "pages": pages,
    }


@api.get("/meta/login")
async def meta_login(user=Depends(get_current_user)):
    if not (META_APP_ID and META_APP_SECRET and META_REDIRECT_URI):
        raise HTTPException(503, "Meta OAuth non configuré côté serveur. Renseignez META_APP_ID/META_APP_SECRET/META_REDIRECT_URI dans backend/.env.")
    state_token = jwt.encode(
        {"sub": user["id"], "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    from urllib.parse import urlencode
    params = {
        "client_id": META_APP_ID,
        "redirect_uri": META_REDIRECT_URI,
        "state": state_token,
        "scope": META_SCOPES,
        "response_type": "code",
    }
    return {"authorization_url": f"https://www.facebook.com/v21.0/dialog/oauth?{urlencode(params)}"}


@api.get("/meta/oauth/callback")
async def meta_callback(code: str = "", state: str = "", error: str = "", error_description: str = ""):
    from fastapi.responses import RedirectResponse
    if error:
        raise HTTPException(400, f"Autorisation Meta refusée: {error_description or error}")
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload["sub"]
    except Exception as exc:
        raise HTTPException(400, f"État OAuth invalide ou expiré: {exc}")

    from social_publishing import meta_exchange_code, meta_long_lived_token, meta_fetch_pages
    tok = await meta_exchange_code(META_APP_ID, META_APP_SECRET, META_REDIRECT_URI, code)
    ll = await meta_long_lived_token(META_APP_ID, META_APP_SECRET, tok["access_token"])
    user_token = ll["access_token"]
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(ll.get("expires_in", 5184000)))).isoformat()
    pages = await meta_fetch_pages(user_token)
    stored_pages = [{
        "id": p["id"],
        "name": p["name"],
        "token": enc(p["access_token"]),
        "instagram_id": (p.get("instagram") or {}).get("id"),
        "instagram_username": (p.get("instagram") or {}).get("username"),
    } for p in pages]

    await db.users.update_one(
        {"id": user_id},
        {"$set": {"meta": {
            "user_token": enc(user_token),
            "expires_at": expires_at,
            "pages": stored_pages,
            "connected_at": now_iso(),
        }}},
    )
    frontend_url = META_REDIRECT_URI.replace("/api/meta/oauth/callback", "/drafts?meta=connected")
    return RedirectResponse(url=frontend_url)


@api.post("/meta/disconnect")
async def meta_disconnect(user=Depends(get_current_user)):
    await db.users.update_one({"id": user["id"]}, {"$unset": {"meta": ""}})
    return {"ok": True}


async def _get_meta_page(user_id: str, page_id: Optional[str], require_instagram: bool = False) -> dict:
    doc = await db.users.find_one({"id": user_id}, {"meta": 1, "_id": 0})
    m = (doc or {}).get("meta") or {}
    pages = m.get("pages") or []
    if not pages:
        raise HTTPException(400, "Compte Meta non connecté. Connectez Facebook/Instagram d'abord.")
    if require_instagram:
        pages = [p for p in pages if p.get("instagram_id")]
        if not pages:
            raise HTTPException(400, "Aucun compte Instagram professionnel lié à vos Pages Facebook. Liez votre compte Instagram à une Page dans les paramètres Meta.")
    if page_id:
        page = next((p for p in pages if p["id"] == page_id), None)
        if not page:
            raise HTTPException(404, "Page Facebook introuvable dans vos Pages connectées.")
        return page
    return pages[0]


@api.post("/drafts/{draft_id}/publish-facebook")
async def publish_draft_to_facebook(draft_id: str, req: Optional[SocialPublishRequest] = None, user=Depends(get_current_user)):
    req = req or SocialPublishRequest()
    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    page = await _get_meta_page(user["id"], req.page_id)
    page_token = dec(page["token"])

    from social_publishing import generate_social_post_text, meta_publish_facebook
    post_text = await generate_social_post_text(EMERGENT_LLM_KEY, d, "facebook")
    result = await meta_publish_facebook(
        page["id"], page_token, post_text,
        link=d.get("github_public_url"), image_url=req.image_url or d.get("cover_image_url"),
    )
    await db.drafts.update_one({"id": draft_id}, {"$set": {
        "facebook_post_id": result.get("post_id"),
        "facebook_post_url": result.get("post_url"),
        "facebook_posted_at": now_iso(),
    }})
    return {"ok": True, "page": page["name"], "post_text": post_text, **result}


@api.post("/drafts/{draft_id}/publish-instagram")
async def publish_draft_to_instagram(draft_id: str, req: Optional[SocialPublishRequest] = None, user=Depends(get_current_user)):
    req = req or SocialPublishRequest()
    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    image_url = req.image_url or d.get("cover_image_url")
    if not image_url:
        raise HTTPException(400, "Instagram exige une image. Générez une image de couverture ou fournissez l'URL publique d'une image (JPEG recommandé).")
    page = await _get_meta_page(user["id"], req.page_id, require_instagram=True)
    page_token = dec(page["token"])

    from social_publishing import generate_social_post_text, meta_publish_instagram
    caption = await generate_social_post_text(EMERGENT_LLM_KEY, d, "instagram")
    if d.get("github_public_url"):
        caption += f"\n\n🔗 Lien dans notre bio ou : {d['github_public_url']}"
    result = await meta_publish_instagram(page["instagram_id"], page_token, caption, image_url)
    await db.drafts.update_one({"id": draft_id}, {"$set": {
        "instagram_post_id": result.get("media_id"),
        "instagram_post_url": result.get("post_url"),
        "instagram_posted_at": now_iso(),
    }})
    return {"ok": True, "account": page.get("instagram_username"), "post_text": caption, **result}


# ---------------------------------------------------------------------------
# Google Business Profile OAuth + Publishing
# ---------------------------------------------------------------------------
GBP_CLIENT_ID = os.environ.get("GBP_CLIENT_ID", "") or GOOGLE_OAUTH_CLIENT_ID
GBP_CLIENT_SECRET = os.environ.get("GBP_CLIENT_SECRET", "") or GOOGLE_OAUTH_CLIENT_SECRET
GBP_REDIRECT_URI = os.environ.get("GBP_REDIRECT_URI", "")
GBP_SCOPES = "https://www.googleapis.com/auth/business.manage openid email"


def _gbp_configured() -> bool:
    return bool(GBP_CLIENT_ID and GBP_CLIENT_SECRET and GBP_REDIRECT_URI)


@api.get("/gbp/status")
async def gbp_status(user=Depends(get_current_user)):
    doc = await db.users.find_one({"id": user["id"]}, {"gbp": 1, "_id": 0})
    g = (doc or {}).get("gbp") or {}
    return {
        "server_configured": _gbp_configured(),
        "connected": bool(g.get("refresh_token")),
        "email": g.get("email"),
        "granted_scopes": g.get("granted_scopes"),
        "scope_ok": "business.manage" in (g.get("granted_scopes") or "") if g.get("refresh_token") else None,
        "accounts_check_status": g.get("accounts_check_status"),
        "connected_at": g.get("connected_at"),
    }


@api.get("/gbp/login")
async def gbp_login(user=Depends(get_current_user)):
    if not _gbp_configured():
        raise HTTPException(503, "Google Business Profile OAuth non configuré. Renseignez GBP_CLIENT_ID/GBP_CLIENT_SECRET/GBP_REDIRECT_URI (ou GOOGLE_OAUTH_CLIENT_ID/SECRET) dans backend/.env.")
    state_token = jwt.encode(
        {"sub": user["id"], "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    from urllib.parse import urlencode
    params = {
        "client_id": GBP_CLIENT_ID,
        "redirect_uri": GBP_REDIRECT_URI,
        "response_type": "code",
        "scope": GBP_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state_token,
    }
    return {"authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}


@api.get("/gbp/oauth/callback")
async def gbp_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import RedirectResponse
    if error:
        raise HTTPException(400, f"Autorisation Google refusée: {error}")
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload["sub"]
    except Exception as exc:
        raise HTTPException(400, f"État OAuth invalide ou expiré: {exc}")

    from social_publishing import gbp_exchange_code
    tok = await gbp_exchange_code(GBP_CLIENT_ID, GBP_CLIENT_SECRET, GBP_REDIRECT_URI, code)
    refresh_token = tok.get("refresh_token")
    if not refresh_token:
        raise HTTPException(400, "Google n'a pas retourné de refresh token. Révoquez l'accès de l'app sur myaccount.google.com/permissions puis reconnectez-vous.")

    # Vérifier que le scope business.manage a RÉELLEMENT été accordé
    granted_scopes = tok.get("scope", "")
    if "business.manage" not in granted_scopes:
        raise HTTPException(400, (
            "Google n'a pas accordé le scope business.manage (accordé : "
            f"{granted_scopes or 'aucun'}). Ajoutez le scope "
            "https://www.googleapis.com/auth/business.manage dans Google Cloud → OAuth consent screen → "
            "Data access, révoquez l'accès sur myaccount.google.com/permissions, puis reconnectez-vous."
        ))

    # Test réel immédiat : accounts.list doit répondre 200
    accounts_check = {"status": None, "detail": None}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            ar = await client.get(
                "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
                headers={"Authorization": f"Bearer {tok['access_token']}"},
            )
        accounts_check["status"] = ar.status_code
        if ar.status_code != 200:
            accounts_check["detail"] = ar.text[:200]
            logger.warning("GBP accounts.list check failed at connect: %s %s", ar.status_code, ar.text[:200])
    except Exception as exc:
        accounts_check["detail"] = str(exc)[:200]

    email = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {tok['access_token']}"},
            )
            if r.status_code == 200:
                email = r.json().get("email")
    except Exception:
        pass

    await db.users.update_one(
        {"id": user_id},
        {"$set": {"gbp": {
            "refresh_token": enc(refresh_token),
            "email": email,
            "granted_scopes": granted_scopes,
            "accounts_check_status": accounts_check["status"],
            "connected_at": now_iso(),
        }}},
    )
    ok_flag = "connected" if accounts_check["status"] == 200 else "connected_quota_pending"
    frontend_url = GBP_REDIRECT_URI.replace("/api/gbp/oauth/callback", f"/drafts?gbp={ok_flag}")
    return RedirectResponse(url=frontend_url)


@api.post("/gbp/disconnect")
async def gbp_disconnect(user=Depends(get_current_user)):
    await db.users.update_one({"id": user["id"]}, {"$unset": {"gbp": ""}})
    return {"ok": True}


async def _get_gbp_access_token(user_id: str) -> str:
    doc = await db.users.find_one({"id": user_id}, {"gbp": 1, "_id": 0})
    g = (doc or {}).get("gbp") or {}
    if not g.get("refresh_token"):
        raise HTTPException(400, "Google Business Profile non connecté.")
    from social_publishing import gbp_access_token
    return await gbp_access_token(GBP_CLIENT_ID, GBP_CLIENT_SECRET, dec(g["refresh_token"]))


@api.get("/gbp/locations")
async def gbp_locations(user=Depends(get_current_user)):
    access_token = await _get_gbp_access_token(user["id"])
    from social_publishing import gbp_list_locations
    return {"locations": await gbp_list_locations(access_token)}


@api.post("/drafts/{draft_id}/publish-gbp")
async def publish_draft_to_gbp(draft_id: str, req: Optional[SocialPublishRequest] = None, user=Depends(get_current_user)):
    req = req or SocialPublishRequest()
    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    access_token = await _get_gbp_access_token(user["id"])

    from social_publishing import gbp_list_locations, gbp_create_post, generate_social_post_text
    location = req.location
    if not location:
        locs = await gbp_list_locations(access_token)
        location = locs[0]["location"]

    summary = await generate_social_post_text(EMERGENT_LLM_KEY, d, "gbp")
    result = await gbp_create_post(access_token, location, summary, cta_url=d.get("github_public_url"))
    await db.drafts.update_one({"id": draft_id}, {"$set": {
        "gbp_post_name": result.get("name"),
        "gbp_post_url": result.get("searchUrl"),
        "gbp_posted_at": now_iso(),
    }})
    return {"ok": True, "location": location, "post_text": summary,
            "post_name": result.get("name"), "post_url": result.get("searchUrl")}


