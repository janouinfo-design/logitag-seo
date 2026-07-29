from app_core import gen_id

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Any
from typing import Dict
from typing import Optional
import asyncio
import httpx
import jwt
import os
import re
from app_core import JWT_ALGORITHM, JWT_SECRET, SitePublic, api, db, dec, enc, get_current_user, logger, now_iso
from routes_sites import _get_user_site, site_to_public

# Google OAuth 2.0 + Search Console + Analytics (real, replaces mocks)
# ---------------------------------------------------------------------------
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]
# Google normalise/réordonne les scopes au retour → tolérer les variations
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def _google_oauth_client_config() -> dict:
    if not (GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI):
        raise HTTPException(503, "Google OAuth n'est pas configuré côté serveur. Demandez à l'admin de renseigner GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI dans backend/.env.")
    return {
        "web": {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_OAUTH_REDIRECT_URI],
        }
    }


async def _get_google_credentials(user_id: str):
    """Load + auto-refresh Google credentials for a user. Returns google.oauth2.credentials.Credentials."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest

    doc = await db.users.find_one({"id": user_id}, {"google_oauth": 1, "_id": 0})
    gc = (doc or {}).get("google_oauth")
    if not gc or not gc.get("refresh_token"):
        raise HTTPException(400, "Google non connecté. Connectez votre compte Google dans la page Performance.")
    creds = Credentials(
        token=dec(gc.get("access_token")),
        refresh_token=dec(gc["refresh_token"]),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_OAUTH_CLIENT_ID,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=gc.get("scopes", GOOGLE_SCOPES),
    )
    if not creds.valid:
        try:
            await asyncio.to_thread(creds.refresh, GoogleRequest())
            await db.users.update_one(
                {"id": user_id},
                {"$set": {
                    "google_oauth.access_token": enc(creds.token),
                    "google_oauth.expiry": creds.expiry.isoformat() if creds.expiry else None,
                }},
            )
        except Exception as exc:
            logger.warning("Google refresh failed for user %s: %s", user_id, exc)
            raise HTTPException(400, f"Token Google expiré ou révoqué. Reconnectez votre compte Google. ({exc})")
    return creds


@api.get("/google/status")
async def google_status(user=Depends(get_current_user)):
    """Return whether the user has connected Google + which features are configured per site."""
    doc = await db.users.find_one({"id": user["id"]}, {"google_oauth": 1, "google_email": 1, "_id": 0})
    gc = (doc or {}).get("google_oauth") or {}
    configured = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI)
    return {
        "server_configured": configured,
        "connected": bool(gc.get("refresh_token")),
        "google_email": (doc or {}).get("google_email"),
        "scopes": gc.get("scopes", []),
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI if configured else None,
    }


@api.get("/google/login")
async def google_login(user=Depends(get_current_user)):
    """Return the Google authorization URL. Frontend should open it in a popup or full-page redirect."""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(_google_oauth_client_config(), scopes=GOOGLE_SCOPES)
    flow.redirect_uri = GOOGLE_OAUTH_REDIRECT_URI
    # encode user_id in state (signed via jwt to prevent tampering)
    state_token = jwt.encode(
        {"sub": user["id"], "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state_token,
    )
    # PKCE: the lib generates a code_verifier sent as code_challenge in auth_url.
    # Persist it (keyed by state) so the callback can complete the token exchange.
    code_verifier = getattr(flow, "code_verifier", None)
    if code_verifier:
        import hashlib as _hashlib
        await db.google_oauth_states.delete_many(
            {"created_at": {"$lt": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()}}
        )
        await db.google_oauth_states.update_one(
            {"state_hash": _hashlib.sha256(state_token.encode()).hexdigest()},
            {"$set": {"code_verifier": enc(code_verifier), "created_at": now_iso()}},
            upsert=True,
        )
    return {"authorization_url": auth_url}


@api.get("/google/callback")
@api.get("/google/oauth/callback")
async def google_callback(code: str, state: str, scope: Optional[str] = None):
    """OAuth callback. Exchanges code for tokens, stores refresh_token, redirects to frontend /performance."""
    from google_auth_oauthlib.flow import Flow
    from fastapi.responses import RedirectResponse
    # Decode state to get user_id
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload["sub"]
    except Exception as exc:
        raise HTTPException(400, f"État OAuth invalide ou expiré: {exc}")

    flow = Flow.from_client_config(_google_oauth_client_config(), scopes=GOOGLE_SCOPES, state=state)
    flow.redirect_uri = GOOGLE_OAUTH_REDIRECT_URI
    # PKCE: restore the code_verifier generated at /google/login
    import hashlib as _hashlib
    state_doc = await db.google_oauth_states.find_one_and_delete(
        {"state_hash": _hashlib.sha256(state.encode()).hexdigest()}
    )
    if state_doc and state_doc.get("code_verifier"):
        flow.code_verifier = dec(state_doc["code_verifier"])
    callback_url = f"{GOOGLE_OAUTH_REDIRECT_URI}?code={code}&state={state}"
    if scope:
        callback_url += f"&scope={scope}"
    try:
        await asyncio.to_thread(flow.fetch_token, authorization_response=callback_url)
    except Exception as exc:
        raise HTTPException(400, f"Échec d'échange du code OAuth: {exc}")

    creds = flow.credentials
    if not creds.refresh_token:
        raise HTTPException(400, "Pas de refresh_token reçu de Google. Révoquez l'accès dans https://myaccount.google.com/permissions et reconnectez.")

    # Get user's Google email via userinfo endpoint for display
    google_email = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"},
            )
            if r.status_code == 200:
                google_email = r.json().get("email")
    except Exception:
        pass

    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "google_oauth": {
                "access_token": enc(creds.token),
                "refresh_token": enc(creds.refresh_token),
                "scopes": list(creds.scopes or GOOGLE_SCOPES),
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
                "connected_at": now_iso(),
            },
            "google_email": google_email,
        }},
    )

    # Redirect to frontend
    # Frontend URL is derived from redirect_uri (strip the API callback path)
    frontend_url = (
        GOOGLE_OAUTH_REDIRECT_URI
        .replace("/api/google/oauth/callback", "/performance?google=connected")
        .replace("/api/google/callback", "/performance?google=connected")
    )
    return RedirectResponse(url=frontend_url)


@api.post("/google/disconnect")
async def google_disconnect(user=Depends(get_current_user)):
    await db.users.update_one(
        {"id": user["id"]},
        {"$unset": {"google_oauth": "", "google_email": ""}},
    )
    return {"ok": True}


@api.get("/google/gsc-sites")
async def google_list_gsc_sites(user=Depends(get_current_user)):
    """List Search Console properties the user has access to."""
    from googleapiclient.discovery import build
    creds = await _get_google_credentials(user["id"])
    def _list():
        service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        return service.sites().list().execute()
    try:
        data = await asyncio.to_thread(_list)
    except Exception as exc:
        raise HTTPException(502, f"Erreur Search Console: {exc}")
    items = data.get("siteEntry", [])
    return {"sites": [{"site_url": s.get("siteUrl"), "permission": s.get("permissionLevel")} for s in items]}


class GoogleSiteSettings(BaseModel):
    gsc_site_url: Optional[str] = None  # e.g. "https://www.logirent.ch/" or "sc-domain:logirent.ch"
    ga4_property_id: Optional[str] = None  # e.g. "123456789"


async def _resolve_gsc_property(user_id: str, typed: str) -> str:
    """Match the typed value against the user's real GSC properties (slash/www/sc-domain variants)."""
    from googleapiclient.discovery import build
    try:
        creds = await _get_google_credentials(user_id)

        def _list():
            service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
            return service.sites().list().execute()

        data = await asyncio.to_thread(_list)
        props = [s.get("siteUrl") for s in data.get("siteEntry", []) if s.get("siteUrl")]
    except Exception:
        return typed
    if typed in props:
        return typed
    domain = re.sub(r"^(sc-domain:|https?://)(www\.)?", "", typed.lower()).strip("/").split("/")[0]

    def _norm(p: str) -> str:
        return re.sub(r"^(sc-domain:|https?://)(www\.)?", "", p.lower()).strip("/")

    for p in props:
        if p == f"sc-domain:{domain}":
            return p
    for p in props:
        if _norm(p) == domain:
            return p
    return typed


@api.patch("/sites/{site_id}/google-settings", response_model=SitePublic)
async def update_site_google_settings(site_id: str, payload: GoogleSiteSettings, user=Depends(get_current_user)):
    site = await db.sites.find_one({"id": site_id, "user_id": user["id"]})
    if not site:
        raise HTTPException(404, "Site introuvable")
    updates = {}
    if payload.gsc_site_url is not None:
        typed = payload.gsc_site_url.strip()
        updates["gsc_site_url"] = (await _resolve_gsc_property(user["id"], typed)) if typed else None
    if payload.ga4_property_id is not None:
        raw = (payload.ga4_property_id or "").strip()
        if raw:
            cleaned = raw[2:] if raw.upper().startswith("G-") else raw
            cleaned = cleaned.replace(" ", "")
            if not cleaned.isdigit():
                raise HTTPException(400, (
                    "GA4 Property ID invalide : il faut l'ID NUMÉRIQUE de la propriété (ex. 435235709), "
                    "pas l'ID de mesure G-XXXXXXXX. Analytics → Administration → Paramètres de la propriété "
                    "→ « ID DE LA PROPRIÉTÉ »."
                ))
            updates["ga4_property_id"] = cleaned
        else:
            updates["ga4_property_id"] = None
    if updates:
        await db.sites.update_one({"id": site_id}, {"$set": updates})
    site = await db.sites.find_one({"id": site_id}, {"_id": 0})
    return site_to_public(site)


@api.get("/sites/{site_id}/performance-real")
async def site_performance_real(site_id: str, days: int = 28, user=Depends(get_current_user)):
    """Fetch real GSC + GA4 performance for a site over the last N days."""
    from googleapiclient.discovery import build
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest

    site = await _get_user_site(site_id, user)
    gsc_url = site.get("gsc_site_url")
    ga4_id = site.get("ga4_property_id")
    if not (gsc_url or ga4_id):
        raise HTTPException(400, "Aucune propriété GSC ni GA4 n'est configurée pour ce site. Allez sur Performance → Configurer Google.")

    creds = await _get_google_credentials(user["id"])
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)

    result: Dict[str, Any] = {"site_id": site_id, "label": site.get("label"), "mocked": False,
                              "gsc_site_url": gsc_url, "ga4_property_id": ga4_id,
                              "period": {"start": start_date.isoformat(), "end": end_date.isoformat()}}

    # --- GSC ---
    if gsc_url:
        def _gsc():
            svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
            # Daily aggregates
            daily = svc.searchanalytics().query(siteUrl=gsc_url, body={
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": ["date"],
                "rowLimit": 1000,
            }).execute()
            # Top queries
            queries = svc.searchanalytics().query(siteUrl=gsc_url, body={
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": ["query"],
                "rowLimit": 25,
            }).execute()
            return daily, queries
        try:
            daily_data, queries_data = await asyncio.to_thread(_gsc)
            daily_rows = []
            for r in daily_data.get("rows", []):
                impressions = r.get("impressions", 0)
                clicks = r.get("clicks", 0)
                daily_rows.append({
                    "date": r["keys"][0],
                    "impressions": int(impressions),
                    "clicks": int(clicks),
                    "ctr": round((r.get("ctr") or 0) * 100, 2),
                    "position": round(r.get("position") or 0, 1),
                })
            keywords = []
            for r in queries_data.get("rows", []):
                keywords.append({
                    "keyword": r["keys"][0],
                    "clicks": int(r.get("clicks", 0)),
                    "impressions": int(r.get("impressions", 0)),
                    "ctr": round((r.get("ctr") or 0) * 100, 2),
                    "position": round(r.get("position") or 0, 1),
                })
            result["gsc"] = {
                "daily": daily_rows,
                "keywords": keywords,
                "totals": {
                    "impressions": sum(d["impressions"] for d in daily_rows),
                    "clicks": sum(d["clicks"] for d in daily_rows),
                    "avg_position": round(sum(d["position"] for d in daily_rows) / len(daily_rows), 1) if daily_rows else 0,
                    "avg_ctr": round(sum(d["ctr"] for d in daily_rows) / len(daily_rows), 2) if daily_rows else 0,
                },
            }
        except HTTPException:
            raise
        except Exception as exc:
            result["gsc_error"] = f"Erreur Search Console: {exc}"

    # --- GA4 ---
    if ga4_id:
        def _ga4():
            client = BetaAnalyticsDataClient(credentials=creds)
            req = RunReportRequest(
                property=f"properties/{ga4_id}",
                date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
                dimensions=[Dimension(name="date")],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="totalUsers"),
                    Metric(name="bounceRate"),
                    Metric(name="conversions"),
                    Metric(name="engagementRate"),
                ],
            )
            return client.run_report(req)
        try:
            resp = await asyncio.to_thread(_ga4)
            rows = []
            for row in resp.rows:
                d = row.dimension_values[0].value  # YYYYMMDD
                pretty = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
                rows.append({
                    "date": pretty,
                    "sessions": int(float(row.metric_values[0].value or 0)),
                    "users": int(float(row.metric_values[1].value or 0)),
                    "bounce_rate": round(float(row.metric_values[2].value or 0) * 100, 1),
                    "conversions": int(float(row.metric_values[3].value or 0)),
                    "engagement_rate": round(float(row.metric_values[4].value or 0) * 100, 1),
                })
            rows.sort(key=lambda x: x["date"])
            result["ga4"] = {
                "daily": rows,
                "totals": {
                    "sessions": sum(r["sessions"] for r in rows),
                    "users": sum(r["users"] for r in rows),
                    "avg_bounce_rate": round(sum(r["bounce_rate"] for r in rows) / len(rows), 1) if rows else 0,
                    "conversions": sum(r["conversions"] for r in rows),
                },
            }
        except Exception as exc:
            result["ga4_error"] = f"Erreur GA4: {exc}"

    return result


async def _capture_rank_snapshot(user_id: str, site_id: str, lookback_days: int = 7) -> dict:
    """Fetch top GSC queries for the last `lookback_days` and persist a snapshot for today."""
    from googleapiclient.discovery import build
    site = await db.sites.find_one({"id": site_id, "user_id": user_id}, {"_id": 0})
    if not site:
        raise HTTPException(404, "Site introuvable")
    gsc_url = site.get("gsc_site_url")
    if not gsc_url:
        raise HTTPException(400, "Aucune propriété GSC n'est configurée pour ce site.")
    creds = await _get_google_credentials(user_id)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=lookback_days)
    def _query():
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        return svc.searchanalytics().query(siteUrl=gsc_url, body={
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": ["query"],
            "rowLimit": 100,
        }).execute()
    try:
        data = await asyncio.to_thread(_query)
    except HTTPException:
        raise
    except Exception as exc:
        hint = ""
        try:
            def _list():
                svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
                return svc.sites().list().execute()
            listing = await asyncio.to_thread(_list)
            props = [s.get("siteUrl") for s in listing.get("siteEntry", []) if s.get("siteUrl")]
            if props:
                hint = " Propriétés disponibles sur votre compte Google : " + " · ".join(props[:10])
            else:
                hint = " Votre compte Google connecté n'a accès à AUCUNE propriété Search Console — connectez le bon compte ou faites-vous ajouter comme utilisateur dans Search Console."
        except Exception:
            pass
        msg = str(exc)
        if "403" in msg or "permission" in msg.lower():
            raise HTTPException(403, (
                f"Search Console refuse l'accès à « {gsc_url} ». La propriété ne correspond pas exactement "
                f"ou votre compte Google n'y a pas accès.{hint}"
            ))
        raise HTTPException(502, f"Erreur Search Console pour « {gsc_url} » : {msg[:200]}{hint}")
    today_iso = end_date.isoformat()
    # Idempotent: delete today's snapshot for this site before inserting
    await db.rank_snapshots.delete_many({"user_id": user_id, "site_id": site_id, "snapshot_date": today_iso})
    rows = data.get("rows", [])
    docs = []
    for r in rows:
        docs.append({
            "id": gen_id(),
            "user_id": user_id,
            "site_id": site_id,
            "keyword": r["keys"][0],
            "position": round(r.get("position") or 0, 1),
            "clicks": int(r.get("clicks", 0)),
            "impressions": int(r.get("impressions", 0)),
            "ctr": round((r.get("ctr") or 0) * 100, 2),
            "snapshot_date": today_iso,
            "lookback_days": lookback_days,
            "created_at": now_iso(),
        })
    if docs:
        await db.rank_snapshots.insert_many(docs)
    return {"snapshot_date": today_iso, "count": len(docs)}


@api.post("/sites/{site_id}/rank-snapshot")
async def take_rank_snapshot(site_id: str, user=Depends(get_current_user)):
    """Manually trigger a rank snapshot for today."""
    return await _capture_rank_snapshot(user["id"], site_id)


@api.get("/sites/{site_id}/rank-tracking")
async def get_rank_tracking(site_id: str, days: int = 30, top: int = 20, user=Depends(get_current_user)):
    """Return per-keyword time series for the last N days. Returns the top-N keywords by latest clicks."""
    await _get_user_site(site_id, user)
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    cursor = db.rank_snapshots.find(
        {"user_id": user["id"], "site_id": site_id, "snapshot_date": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("snapshot_date", 1)
    snapshots = await cursor.to_list(50000)
    if not snapshots:
        return {"site_id": site_id, "days": days, "snapshots_count": 0, "dates": [], "keywords": []}
    # Distinct dates (sorted)
    dates = sorted({s["snapshot_date"] for s in snapshots})
    # Pick top-N keywords by clicks in the latest snapshot
    latest_date = dates[-1]
    latest_kw = sorted(
        [s for s in snapshots if s["snapshot_date"] == latest_date],
        key=lambda s: -s["clicks"],
    )[:top]
    keyword_list = [k["keyword"] for k in latest_kw]
    # Build per-keyword series
    series = []
    for kw in keyword_list:
        kw_snaps = [s for s in snapshots if s["keyword"] == kw]
        kw_snaps.sort(key=lambda s: s["snapshot_date"])
        oldest = kw_snaps[0]
        newest = kw_snaps[-1]
        delta = round(oldest["position"] - newest["position"], 1)  # positive = improved (lower position = better)
        series.append({
            "keyword": kw,
            "current_position": newest["position"],
            "current_clicks": newest["clicks"],
            "current_impressions": newest["impressions"],
            "current_ctr": newest["ctr"],
            "previous_position": oldest["position"],
            "delta": delta,
            "trend": "up" if delta > 0.5 else "down" if delta < -0.5 else "stable",
            "series": [{"date": s["snapshot_date"], "position": s["position"]} for s in kw_snaps],
        })
    return {
        "site_id": site_id,
        "days": days,
        "snapshots_count": len(dates),
        "dates": dates,
        "latest_date": latest_date,
        "keywords": series,
    }
