from datetime import datetime, timezone
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from typing import Literal
from app_core import PLATFORM_ADMIN_EMAILS, api, db, get_current_user, now_iso
from routes_billing import PLANS, _get_or_create_workspace


async def require_platform_admin(user=Depends(get_current_user)) -> dict:
    email = (user.get("real_email") or user.get("email") or "").lower()
    if email not in PLATFORM_ADMIN_EMAILS:
        raise HTTPException(403, "Accès réservé à l'administrateur de la plateforme.")
    return user


def _month_start() -> str:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


@api.get("/admin/overview")
async def admin_overview(admin=Depends(require_platform_admin)):
    ms = _month_start()
    total_users = await db.users.count_documents({})
    total_sites = await db.sites.count_documents({})
    total_drafts = await db.drafts.count_documents({})
    drafts_month = await db.drafts.count_documents({"created_at": {"$gte": ms}})
    published = await db.drafts.count_documents({"status": "published"})
    agg = await db.payment_transactions.aggregate([
        {"$match": {"payment_status": "paid"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    revenue = round((agg[0]["total"] if agg else 0) or 0, 2)
    payments_count = agg[0]["count"] if agg else 0
    plans_agg = await db.workspaces.aggregate([
        {"$group": {"_id": "$plan", "count": {"$sum": 1}}},
    ]).to_list(20)
    return {
        "total_users": total_users,
        "total_sites": total_sites,
        "total_drafts": total_drafts,
        "drafts_this_month": drafts_month,
        "published_drafts": published,
        "revenue_eur": revenue,
        "payments_count": payments_count,
        "plan_distribution": {(p["_id"] or "free"): p["count"] for p in plans_agg},
    }


@api.get("/admin/users")
async def admin_users(admin=Depends(require_platform_admin)):
    ms = _month_start()
    users = await db.users.find(
        {}, {"_id": 0, "id": 1, "email": 1, "full_name": 1, "created_at": 1}
    ).sort("created_at", -1).to_list(500)
    out = []
    for u in users:
        ws = await db.workspaces.find_one({"owner_id": u["id"]}, {"_id": 0, "plan": 1})
        articles = await db.drafts.count_documents({"user_id": u["id"], "created_at": {"$gte": ms}})
        sites = await db.sites.count_documents({"user_id": u["id"]})
        out.append({
            **u,
            "plan": (ws or {}).get("plan", "free"),
            "is_admin": u["email"].lower() in PLATFORM_ADMIN_EMAILS,
            "articles_this_month": articles,
            "sites_count": sites,
        })
    return {"users": out}


class TestEmailRequest(BaseModel):
    to: str


@api.post("/admin/test-email")
async def admin_test_email(payload: TestEmailRequest, admin=Depends(require_platform_admin)):
    from app_core import RESEND_API_KEY, SMTP_HOST, send_email
    if not SMTP_HOST and not RESEND_API_KEY:
        raise HTTPException(400, "Aucun envoi d'email configuré. Ajoutez SMTP_HOST/SMTP_USER/SMTP_PASSWORD (ou RESEND_API_KEY) dans le .env puis redémarrez le backend.")
    method = await send_email(
        payload.to,
        "Email de test — LOGI SEO Booster",
        "<p>✅ Votre configuration d'envoi d'emails fonctionne correctement.</p><p>— LOGI SEO Booster</p>",
    )
    if not method:
        raise HTTPException(502, "Échec de l'envoi. Vérifiez SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD et SMTP_SECURITY dans le .env (voir logs backend pour le détail).")
    return {"ok": True, "method": method}


class PlanChange(BaseModel):
    plan: Literal["free", "pro", "business", "agency"]


@api.patch("/admin/users/{user_id}/plan")
async def admin_set_plan(user_id: str, payload: PlanChange, admin=Depends(require_platform_admin)):
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    ws = await _get_or_create_workspace(target)
    await db.workspaces.update_one(
        {"id": ws["id"]},
        {"$set": {
            "plan": payload.plan,
            "plan_started_at": now_iso(),
            "plan_expires_at": None,
            "plan_granted_by_admin": True,
        }},
    )
    return {"ok": True, "plan": payload.plan, "plan_name": PLANS[payload.plan]["name"]}
