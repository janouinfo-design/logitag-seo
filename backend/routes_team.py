from fastapi import Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Literal, Optional
import os
import secrets
import httpx
from app_core import FRONTEND_URL, api, db, gen_id, get_current_user, logger, now_iso, send_email

ROLE_LABELS = {"admin": "Admin", "editor": "Éditeur", "viewer": "Lecteur"}


def _real_id(user: dict) -> str:
    return user.get("real_user_id") or user["id"]


def _real_email(user: dict) -> str:
    return (user.get("real_email") or user["email"]).lower()


def _require_manager(user: dict) -> None:
    if user.get("workspace_role") not in (None, "admin"):
        raise HTTPException(403, "Seul le propriétaire ou un membre Admin peut gérer l'équipe.")


async def _current_workspace(user: dict) -> dict:
    from routes_billing import _get_or_create_workspace
    return await _get_or_create_workspace(user)


async def _send_invite_email(to_email: str, invite_link: str, workspace_name: str, role: str) -> bool:
    method = await send_email(
        to_email,
        f"Invitation à rejoindre {workspace_name} — LOGI SEO Booster",
        (
            f"<p>Bonjour,</p><p>Vous êtes invité(e) à rejoindre l'espace de travail "
            f"<strong>{workspace_name}</strong> en tant que <strong>{ROLE_LABELS.get(role, role)}</strong>.</p>"
            f"<p><a href=\"{invite_link}\">Cliquez ici pour créer votre compte et rejoindre l'équipe</a>.</p>"
        ),
    )
    return method is not None


class InviteCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "editor", "viewer"] = "editor"


@api.post("/team/invites")
async def create_invite(payload: InviteCreate, user=Depends(get_current_user)):
    _require_manager(user)
    ws = await _current_workspace(user)
    email = payload.email.lower()
    if email == (user.get("email") or "").lower() or email == _real_email(user):
        raise HTTPException(400, "Vous ne pouvez pas vous inviter vous-même.")
    existing_member = await db.workspace_members.find_one({"workspace_id": ws["id"], "email": email})
    if existing_member:
        raise HTTPException(409, "Cette personne est déjà membre de l'équipe.")
    existing_invite = await db.workspace_invites.find_one({"workspace_id": ws["id"], "email": email, "status": "pending"})
    if existing_invite:
        raise HTTPException(409, "Une invitation est déjà en attente pour cet email.")
    token = secrets.token_urlsafe(24)
    invite = {
        "id": gen_id(),
        "workspace_id": ws["id"],
        "owner_id": ws["owner_id"],
        "email": email,
        "role": payload.role,
        "token": token,
        "status": "pending",
        "invited_by": _real_email(user),
        "created_at": now_iso(),
        "accepted_at": None,
    }
    await db.workspace_invites.insert_one({**invite})
    base = (FRONTEND_URL or "").rstrip("/")
    invite_link = f"{base}/register?invite={token}" if base else f"/register?invite={token}"
    email_sent = await _send_invite_email(email, invite_link, ws.get("name", "l'équipe"), payload.role)
    logger.info("WORKSPACE INVITE LINK for %s: %s", email, invite_link)
    invite.pop("token", None)
    return {"invite": invite, "invite_link": invite_link, "email_sent": email_sent}


@api.get("/team/invites")
async def list_invites(user=Depends(get_current_user)):
    ws = await _current_workspace(user)
    invites = await db.workspace_invites.find(
        {"workspace_id": ws["id"], "status": "pending"}, {"_id": 0, "token": 0}
    ).sort("created_at", -1).to_list(50)
    return {"invites": invites}


@api.get("/team/invites/{invite_id}/link")
async def get_invite_link(invite_id: str, user=Depends(get_current_user)):
    _require_manager(user)
    ws = await _current_workspace(user)
    inv = await db.workspace_invites.find_one({"id": invite_id, "workspace_id": ws["id"], "status": "pending"}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invitation introuvable")
    base = (FRONTEND_URL or "").rstrip("/")
    return {"invite_link": f"{base}/register?invite={inv['token']}" if base else f"/register?invite={inv['token']}"}


@api.delete("/team/invites/{invite_id}")
async def revoke_invite(invite_id: str, user=Depends(get_current_user)):
    _require_manager(user)
    ws = await _current_workspace(user)
    res = await db.workspace_invites.delete_one({"id": invite_id, "workspace_id": ws["id"], "status": "pending"})
    if res.deleted_count == 0:
        raise HTTPException(404, "Invitation introuvable")
    return {"ok": True}


@api.get("/team/invite-info")
async def invite_info(token: str):
    """Public endpoint used by the register page to display invite context."""
    inv = await db.workspace_invites.find_one({"token": token, "status": "pending"}, {"_id": 0})
    if not inv:
        return {"valid": False}
    ws = await db.workspaces.find_one({"id": inv["workspace_id"]}, {"_id": 0, "name": 1})
    return {
        "valid": True,
        "email": inv["email"],
        "role": inv["role"],
        "role_label": ROLE_LABELS.get(inv["role"], inv["role"]),
        "workspace_name": (ws or {}).get("name", "Espace de travail"),
    }


@api.get("/team/members")
async def list_members(user=Depends(get_current_user)):
    ws = await _current_workspace(user)
    owner = await db.users.find_one({"id": ws["owner_id"]}, {"_id": 0, "email": 1, "full_name": 1})
    members = await db.workspace_members.find({"workspace_id": ws["id"]}, {"_id": 0}).sort("joined_at", 1).to_list(100)
    for m in members:
        u = await db.users.find_one({"id": m["user_id"]}, {"_id": 0, "full_name": 1})
        m["full_name"] = (u or {}).get("full_name", "")
    return {
        "workspace": {"id": ws["id"], "name": ws.get("name", "")},
        "owner": {"email": (owner or {}).get("email", ""), "full_name": (owner or {}).get("full_name", "")},
        "members": members,
        "my_role": user.get("workspace_role") or "owner",
        "can_manage": user.get("workspace_role") in (None, "admin"),
    }


class RoleUpdate(BaseModel):
    role: Literal["admin", "editor", "viewer"]


@api.patch("/team/members/{member_id}")
async def update_member_role(member_id: str, payload: RoleUpdate, user=Depends(get_current_user)):
    _require_manager(user)
    ws = await _current_workspace(user)
    res = await db.workspace_members.update_one(
        {"id": member_id, "workspace_id": ws["id"]}, {"$set": {"role": payload.role}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Membre introuvable")
    return {"ok": True, "role": payload.role}


@api.delete("/team/members/{member_id}")
async def remove_member(member_id: str, user=Depends(get_current_user)):
    _require_manager(user)
    ws = await _current_workspace(user)
    member = await db.workspace_members.find_one({"id": member_id, "workspace_id": ws["id"]}, {"_id": 0})
    if not member:
        raise HTTPException(404, "Membre introuvable")
    await db.workspace_members.delete_one({"id": member_id})
    await db.users.update_one(
        {"id": member["user_id"], "active_workspace_id": ws["id"]},
        {"$unset": {"active_workspace_id": ""}},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Workspace memberships + switch
# ---------------------------------------------------------------------------
@api.get("/workspace/memberships")
async def list_memberships(user=Depends(get_current_user)):
    from routes_billing import _get_or_create_workspace
    rid, remail = _real_id(user), _real_email(user)
    # Auto-accept pending invites for accounts that already existed at invite time
    pending = await db.workspace_invites.find({"email": remail, "status": "pending"}, {"_id": 0}).to_list(20)
    for inv in pending:
        exists = await db.workspace_members.find_one({"workspace_id": inv["workspace_id"], "user_id": rid})
        if not exists:
            await db.workspace_members.insert_one({
                "id": gen_id(),
                "workspace_id": inv["workspace_id"],
                "owner_id": inv["owner_id"],
                "user_id": rid,
                "email": remail,
                "role": inv.get("role", "viewer"),
                "joined_at": now_iso(),
            })
        await db.workspace_invites.update_one(
            {"id": inv["id"]},
            {"$set": {"status": "accepted", "accepted_at": now_iso(), "accepted_by": rid}},
        )
    real_user = await db.users.find_one({"id": rid}, {"_id": 0, "password_hash": 0})
    own_ws = await _get_or_create_workspace(real_user)
    active_id = real_user.get("active_workspace_id")
    out = [{
        "workspace_id": own_ws["id"],
        "name": own_ws.get("name", ""),
        "role": "owner",
        "is_own": True,
        "active": not active_id or active_id == own_ws["id"],
    }]
    mems = await db.workspace_members.find({"user_id": rid}, {"_id": 0}).to_list(50)
    for m in mems:
        ws = await db.workspaces.find_one({"id": m["workspace_id"]}, {"_id": 0, "id": 1, "name": 1})
        if ws:
            out.append({
                "workspace_id": ws["id"],
                "name": ws.get("name", ""),
                "role": m.get("role", "viewer"),
                "is_own": False,
                "active": active_id == ws["id"],
            })
    return {"memberships": out}


class SwitchRequest(BaseModel):
    workspace_id: Optional[str] = None


@api.post("/workspace/switch")
async def switch_workspace(payload: SwitchRequest, user=Depends(get_current_user)):
    rid = _real_id(user)
    if not payload.workspace_id:
        await db.users.update_one({"id": rid}, {"$unset": {"active_workspace_id": ""}})
        return {"ok": True, "workspace_id": None}
    ws = await db.workspaces.find_one({"id": payload.workspace_id}, {"_id": 0})
    if not ws:
        raise HTTPException(404, "Espace de travail introuvable")
    if ws["owner_id"] != rid:
        mem = await db.workspace_members.find_one({"workspace_id": ws["id"], "user_id": rid})
        if not mem:
            raise HTTPException(403, "Vous n'êtes pas membre de cet espace de travail.")
    await db.users.update_one({"id": rid}, {"$set": {"active_workspace_id": ws["id"]}})
    return {"ok": True, "workspace_id": ws["id"]}
