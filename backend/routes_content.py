from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
import asyncio
import httpx
import os
import re
from app_core import ContentGenerateRequest, DraftCreate, DraftPublic, DraftUpdate, EMERGENT_LLM_KEY, api, db, gen_id, get_current_user, logger, now_iso
from routes_sites import _get_user_site
from routes_billing import _enforce_plan_quota

# ---------------------------------------------------------------------------
# AI Content generator (Claude Sonnet 4.5)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """Tu es un rédacteur SEO senior spécialisé immobilier et services aux entreprises.
Tu écris en français, ton professionnel, naturel, jamais spammy.
Tu structures tes contenus pour Google ET pour les IA (ChatGPT, Gemini, Perplexity, Google AI Overviews).

RÈGLES OBLIGATOIRES pour chaque contenu :
1. Commencer par une "réponse courte" de 2-3 phrases (résumé direct, factuel) — utile pour AI Overviews.
2. Paragraphes courts (3-4 lignes max), titres H2/H3 hiérarchisés.
3. Inclure une section FAQ avec 4-6 questions/réponses naturelles.
4. Inclure au moins 1 tableau comparatif ou liste structurée en markdown.
5. Mentionner des données locales (ville/région) si fournies.
6. Style crédible, factuel, sans superlatifs creux.
7. Densité de mots-clés naturelle (3-5 mentions du keyword principal).
8. Toujours répondre en JSON valide.

FORMAT DE RÉPONSE OBLIGATOIRE (JSON strict, aucun texte avant/après) :
{
  "title": "Titre H1 du contenu",
  "meta_title": "Titre SEO 50-60 caractères",
  "meta_description": "Méta description 140-160 caractères",
  "body_markdown": "Contenu complet en markdown avec H2/H3, paragraphes, listes, tableaux",
  "faq": [{"question": "...", "answer": "..."}],
  "keywords": ["mot-clé 1", "mot-clé 2", ...],
  "image_query": "2-4 English words describing the ideal cover photo for this article (stock photo search)"
}"""


def _length_hint(length: str) -> str:
    return {"court": "500-700 mots", "moyen": "900-1200 mots", "long": "1500-2000 mots"}.get(length, "900-1200 mots")


def _type_hint(t: str) -> str:
    return {
        "article": "Article de blog SEO",
        "page_locale": "Page locale SEO (ciblage géographique)",
        "faq": "Page FAQ exhaustive (10-15 Q/R)",
        "service_description": "Description de service commercial optimisée SEO",
    }.get(t, "Contenu SEO")


# --- Cover images (Pexels stock photos) ---
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")


async def _fetch_pexels_cover(query: str, page: int = 1) -> Optional[dict]:
    """Search Pexels for a landscape cover photo. Returns draft cover fields or None."""
    if not PEXELS_API_KEY or not query:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "orientation": "landscape", "size": "large",
                        "per_page": 1, "page": page},
            )
        if r.status_code != 200:
            logger.warning("Pexels search failed (%s): %s", r.status_code, r.text[:200])
            return None
        photos = r.json().get("photos") or []
        if not photos:
            return None
        p = photos[0]
        src = p.get("src") or {}
        url = src.get("large2x") or src.get("large") or src.get("original")
        if not url:
            return None
        return {
            "cover_image_url": url,
            "cover_image_alt": p.get("alt") or query,
            "cover_image_credit": f"Photo par {p.get('photographer', 'Pexels')} sur Pexels",
            "cover_image_credit_url": p.get("url"),
            "cover_image_page": page,
            "image_query": query,
        }
    except Exception as exc:
        logger.warning("Pexels fetch error: %s", exc)
        return None


async def _derive_image_query(draft: dict) -> str:
    """Derive a short English stock-photo query from the article title via Claude."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"imgq-{draft.get('id')}",
            system_message="Tu réponds uniquement avec 2-4 mots ANGLAIS pour une recherche de photo de stock. Rien d'autre.",
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        resp = await chat.send_message(UserMessage(
            text=f"2-4 mots-clés anglais de photo de stock pour illustrer cet article : {draft.get('title', '')}"
        ))
        q = (resp or "").strip().strip('"').strip("'")
        if q and len(q) <= 60:
            return q
    except Exception as exc:
        logger.warning("Image query derivation failed: %s", exc)
    return (draft.get("title") or "business")[:50]


@api.post("/content/generate", response_model=DraftPublic)
async def generate_content(req: ContentGenerateRequest, user=Depends(get_current_user)):
    """Synchronous generation (kept for backward compat, may timeout for long content)."""
    return await _do_generate_content(req, user["id"])


@api.post("/content/generate-async")
async def generate_content_async(req: ContentGenerateRequest, user=Depends(get_current_user)):
    """Start generation in background. Returns job_id to poll via /content/jobs/{id}."""
    job_id = gen_id()
    await db.generation_jobs.insert_one({
        "id": job_id,
        "user_id": user["id"],
        "status": "pending",
        "params": req.model_dump(),
        "result": None,
        "error": None,
        "created_at": now_iso(),
        "completed_at": None,
    })

    async def _bg():
        try:
            draft = await _do_generate_content(req, user["id"])
            await db.generation_jobs.update_one(
                {"id": job_id},
                {"$set": {"status": "completed", "result": draft.model_dump(), "completed_at": now_iso()}},
            )
            if req.suggestion_key:
                await db.generated_suggestions.update_one(
                    {"user_id": user["id"], "site_id": req.site_id, "key": req.suggestion_key},
                    {"$set": {"draft_id": draft.id, "title": draft.title, "created_at": now_iso()},
                     "$setOnInsert": {"id": gen_id(), "user_id": user["id"], "site_id": req.site_id, "key": req.suggestion_key}},
                    upsert=True,
                )
        except HTTPException as exc:
            await db.generation_jobs.update_one(
                {"id": job_id},
                {"$set": {"status": "failed", "error": str(exc.detail), "completed_at": now_iso()}},
            )
        except Exception as exc:
            logger.exception("Async generation failed")
            await db.generation_jobs.update_one(
                {"id": job_id},
                {"$set": {"status": "failed", "error": f"Erreur inattendue : {exc}", "completed_at": now_iso()}},
            )

    asyncio.create_task(_bg())
    return {"job_id": job_id, "status": "pending"}


@api.get("/sites/{site_id}/generated-suggestions")
async def list_generated_suggestions(site_id: str, user=Depends(get_current_user)):
    """Suggestions already turned into drafts — lets the UI mark them as done."""
    items = await db.generated_suggestions.find(
        {"user_id": user["id"], "site_id": site_id}, {"_id": 0}
    ).to_list(500)
    return {"generated": items}


@api.get("/content/jobs/{job_id}")
async def get_generation_job(job_id: str, user=Depends(get_current_user)):
    job = await db.generation_jobs.find_one(
        {"id": job_id, "user_id": user["id"]}, {"_id": 0, "user_id": 0, "params": 0}
    )
    if not job:
        raise HTTPException(404, "Job introuvable")
    return job


async def _do_generate_content(req: ContentGenerateRequest, user_id: str) -> DraftPublic:
    user = {"id": user_id}
    # Enforce plan quota
    full_user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if full_user:
        await _enforce_plan_quota(full_user)
    site = await _get_user_site(req.site_id, user)

    # Lazy import emergentintegrations to avoid load failures at startup
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore

    user_prompt = f"""Génère un contenu SEO pour le site "{site['name']}" ({site['label']}).

Type de contenu : {_type_hint(req.content_type)}
Sujet : {req.topic}
Ville / zone : {req.city or 'France (national)'}
Mots-clés cibles : {', '.join(req.keywords) if req.keywords else '(à déterminer)'}
Ton : {req.tone}
Longueur visée : {_length_hint(req.target_length)}
Instructions supplémentaires : {req.extra_instructions or '(aucune)'}

Réponds en JSON strict selon le format imposé."""

    from ai_visibility import _parse_llm_json

    response = None
    data = None
    last_err = None
    for attempt in range(2):
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"gen-{user['id']}-{gen_id()}",
            system_message=SYSTEM_PROMPT,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929").with_params(max_tokens=16000)
        try:
            response = await chat.send_message(UserMessage(text=user_prompt))
        except Exception as exc:
            last_err = exc
            logger.warning("LLM call failed (tentative %s/2) : %s", attempt + 1, exc)
            continue
        try:
            data = _parse_llm_json(response if isinstance(response, str) else str(response))
            break
        except Exception as exc:
            last_err = exc
            logger.warning("Génération : JSON invalide (tentative %s/2) : %s", attempt + 1, exc)
    if data is None:
        raise HTTPException(502, f"Réponse IA non parsable après 2 tentatives : {last_err}")

    draft = {
        "id": gen_id(),
        "user_id": user["id"],
        "site_id": req.site_id,
        "content_type": req.content_type,
        "title": data.get("title") or req.topic,
        "meta_title": data.get("meta_title"),
        "meta_description": data.get("meta_description"),
        "body_markdown": data.get("body_markdown") or "",
        "keywords": data.get("keywords") or req.keywords,
        "faq": data.get("faq") or [],
        "status": "draft",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "wix_draft_id": None,
        "wix_published_at": None,
    }
    cover = await _fetch_pexels_cover(data.get("image_query") or draft["title"])
    if cover:
        draft.update(cover)
    await db.drafts.insert_one(draft)
    return DraftPublic(**{k: v for k, v in draft.items() if k != "user_id"})


@api.post("/drafts/{draft_id}/generate-image")
async def generate_draft_cover(draft_id: str, user=Depends(get_current_user)):
    """Fetch (or refresh) the Pexels cover image for a draft."""
    if not PEXELS_API_KEY:
        raise HTTPException(503, "Pexels non configuré. Ajoutez PEXELS_API_KEY dans backend/.env (clé gratuite sur pexels.com/api).")
    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    query = d.get("image_query") or await _derive_image_query(d)
    page = int(d.get("cover_image_page") or 0) + 1
    cover = await _fetch_pexels_cover(query, page=page)
    if not cover and page > 1:
        cover = await _fetch_pexels_cover(query, page=1)
    if not cover:
        raise HTTPException(404, f"Aucune photo trouvée pour « {query} ». Réessayez plus tard ou modifiez le titre.")
    await db.drafts.update_one({"id": draft_id}, {"$set": {**cover, "updated_at": now_iso()}})
    return cover


# ---------------------------------------------------------------------------
# Drafts CRUD
# ---------------------------------------------------------------------------
def _draft_public(d: dict) -> DraftPublic:
    return DraftPublic(**{k: v for k, v in d.items() if k in DraftPublic.model_fields})


@api.get("/drafts", response_model=List[DraftPublic])
async def list_drafts(site_id: Optional[str] = None, user=Depends(get_current_user)):
    query: Dict[str, Any] = {"user_id": user["id"]}
    if site_id:
        query["site_id"] = site_id
    items = await db.drafts.find(query, {"_id": 0}).sort("updated_at", -1).to_list(200)
    return [_draft_public(d) for d in items]


@api.get("/drafts/{draft_id}", response_model=DraftPublic)
async def get_draft(draft_id: str, user=Depends(get_current_user)):
    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    return _draft_public(d)


@api.post("/drafts", response_model=DraftPublic)
async def create_draft(payload: DraftCreate, user=Depends(get_current_user)):
    await _get_user_site(payload.site_id, user)
    d = {
        "id": gen_id(),
        "user_id": user["id"],
        **payload.model_dump(),
        "status": "draft",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "wix_draft_id": None,
        "wix_published_at": None,
    }
    await db.drafts.insert_one(d)
    return _draft_public(d)


@api.patch("/drafts/{draft_id}", response_model=DraftPublic)
async def update_draft(draft_id: str, payload: DraftUpdate, user=Depends(get_current_user)):
    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    # Save version snapshot
    snapshot = {
        "id": gen_id(),
        "draft_id": draft_id,
        "user_id": user["id"],
        "snapshot": {k: d.get(k) for k in ("title", "meta_title", "meta_description", "body_markdown", "keywords", "faq")},
        "created_at": now_iso(),
    }
    await db.versions.insert_one(snapshot)
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    updates["updated_at"] = now_iso()
    await db.drafts.update_one({"id": draft_id}, {"$set": updates})
    d = await db.drafts.find_one({"id": draft_id}, {"_id": 0})
    return _draft_public(d)


@api.delete("/drafts/{draft_id}")
async def delete_draft(draft_id: str, user=Depends(get_current_user)):
    res = await db.drafts.delete_one({"id": draft_id, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Brouillon introuvable")
    return {"ok": True}


class BatchIdsRequest(BaseModel):
    ids: List[str]


@api.post("/drafts/batch-delete")
async def batch_delete_drafts(payload: BatchIdsRequest, user=Depends(get_current_user)):
    res = await db.drafts.delete_many({"id": {"$in": payload.ids}, "user_id": user["id"]})
    return {"deleted": res.deleted_count}


@api.post("/keywords/saved/batch-delete")
async def batch_delete_keywords(payload: BatchIdsRequest, user=Depends(get_current_user)):
    res = await db.saved_keywords.delete_many({"id": {"$in": payload.ids}, "user_id": user["id"]})
    return {"deleted": res.deleted_count}


@api.get("/drafts/{draft_id}/versions")
async def list_draft_versions(draft_id: str, user=Depends(get_current_user)):
    versions = await db.versions.find(
        {"draft_id": draft_id, "user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    return {"versions": versions}


@api.post("/drafts/{draft_id}/rollback/{version_id}", response_model=DraftPublic)
async def rollback_draft(draft_id: str, version_id: str, user=Depends(get_current_user)):
    v = await db.versions.find_one({"id": version_id, "draft_id": draft_id, "user_id": user["id"]})
    if not v:
        raise HTTPException(404, "Version introuvable")
    snap = v["snapshot"]
    snap["updated_at"] = now_iso()
    await db.drafts.update_one({"id": draft_id, "user_id": user["id"]}, {"$set": snap})
    d = await db.drafts.find_one({"id": draft_id}, {"_id": 0})
    return _draft_public(d)


