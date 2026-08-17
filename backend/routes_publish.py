from datetime import datetime
from datetime import timezone
from fastapi import Depends
from fastapi import HTTPException
from typing import Any
from typing import Dict
from typing import Optional
import asyncio
import httpx
import re
from app_core import DraftPublic, PublishRequest, api, db, dec, gen_id, get_current_user, logger, now_iso
from routes_sites import _get_user_site, create_wix_draft_post
from routes_content import _draft_public

# ---------------------------------------------------------------------------
# Publish to Wix
# ---------------------------------------------------------------------------
async def publish_to_vps_api(site: dict, draft: dict) -> Optional[dict]:
    """POST the draft content to the VPS mini-API. Returns the JSON response on success."""
    url = (site.get("vps_api_url") or "").rstrip("/") + "/api/seo/publish"
    token = dec(site.get("vps_api_token")) or ""
    payload = {
        "content_type": draft.get("content_type"),
        "title": draft.get("title"),
        "meta_title": draft.get("meta_title"),
        "meta_description": draft.get("meta_description"),
        "body_markdown": draft.get("body_markdown"),
        "keywords": draft.get("keywords", []),
        "faq": draft.get("faq", []),
        "source": "logi-seo-booster",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload)
        if r.status_code in (200, 201):
            return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"ok": True}
        logger.warning("VPS API publish failed: %s %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("VPS API publish error: %s", exc)
    return None


# ---------- FTP publication --------------------------------------------------
def _slugify(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:80] or gen_id()[:8]


def _markdown_to_html(md: str) -> str:
    """Tiny markdown→HTML converter (headings, paragraphs, lists, tables, bold/italic)."""
    s = (md or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    def table_repl(m):
        lines = m.group(0).strip().split("\n")
        if len(lines) < 2:
            return m.group(0)
        cells = lambda l: [c.strip() for c in l.strip("|").split("|")]
        header = cells(lines[0])
        rows = [cells(l) for l in lines[2:]]
        thead = "<thead><tr>" + "".join(f"<th>{h}</th>" for h in header) + "</tr></thead>"
        tbody = "<tbody>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody>"
        return f"<table>{thead}{tbody}</table>"
    s = re.sub(r"((?:^\|.*\|\s*\n)+)", table_repl, s, flags=re.MULTILINE)
    s = re.sub(r"^### (.+)$", r"<h3>\1</h3>", s, flags=re.MULTILINE)
    s = re.sub(r"^## (.+)$", r"<h2>\1</h2>", s, flags=re.MULTILINE)
    s = re.sub(r"^# (.+)$", r"<h1>\1</h1>", s, flags=re.MULTILINE)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
    def ul_repl(m):
        items = m.group(0).strip().split("\n")
        cleaned = [re.sub(r"^\s*[-*] ", "", l) for l in items]
        lis = "".join(f"<li>{c}</li>" for c in cleaned)
        return f"<ul>{lis}</ul>"
    s = re.sub(r"((?:^\s*[-*] .+\n?)+)", ul_repl, s, flags=re.MULTILINE)
    out = []
    for block in re.split(r"\n{2,}", s):
        b = block.strip()
        if not b:
            continue
        if re.match(r"^<(h\d|ul|ol|table|p|li)", b):
            out.append(b)
        else:
            out.append(f"<p>{b.replace(chr(10), '<br/>')}</p>")
    return "\n".join(out)


def _github_public_page_url(site: dict, slug: str) -> Optional[str]:
    """Build the final public URL of a page published on GitHub, including the target folder.
    Strips a leading 'public/' segment (Vite/CRA/Next serve public/ at the web root)."""
    base = (site.get("github_public_url") or "").rstrip("/")
    if not base:
        return None
    web_path = (site.get("github_folder") or "").strip("/")
    if web_path == "public":
        web_path = ""
    elif web_path.startswith("public/"):
        web_path = web_path[len("public/"):]
    if web_path and not base.endswith("/" + web_path):
        return f"{base}/{web_path}/{slug}.html"
    return f"{base}/{slug}.html"


def _render_html(draft: dict, site: dict) -> str:
    import json as _json
    title = draft.get("title", "")
    meta_title = draft.get("meta_title") or title
    meta_desc = draft.get("meta_description") or ""
    body_html = _markdown_to_html(draft.get("body_markdown", ""))
    faq = draft.get("faq", []) or []
    keywords = draft.get("keywords", []) or []
    slug = _slugify(title)
    canonical = _github_public_page_url(site, slug)
    if not canonical:
        canonical_base = (site.get("ftp_public_url") or site.get("base_url") or "").rstrip("/")
        canonical = f"{canonical_base}/{slug}.html" if canonical_base else f"{slug}.html"
    faq_html = ""
    faq_jsonld = ""
    if faq:
        items = "".join(
            f'<details class="faq-item"><summary>{q.get("question","")}</summary>'
            f'<p>{q.get("answer","")}</p></details>'
            for q in faq
        )
        faq_html = f'<section class="faq"><h2>Questions fréquentes</h2>{items}</section>'
        jsonld_obj = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q.get("question", ""),
                 "acceptedAnswer": {"@type": "Answer", "text": q.get("answer", "")}}
                for q in faq
            ],
        }
        faq_jsonld = f'<script type="application/ld+json">{_json.dumps(jsonld_obj, ensure_ascii=False)}</script>'
    cover_html = ""
    og_image = ""
    twitter_image = ""
    cover_url = draft.get("cover_image_url") or ""
    _alt = (draft.get("cover_image_alt") or title).replace('"', "'")
    if cover_url and cover_url.startswith("https://"):
        _cu = cover_url
        _credit = draft.get("cover_image_credit") or ""
        _credit_url = draft.get("cover_image_credit_url") or "#"
        cover_html = (
            f'<figure class="cover"><img src="{_cu}" alt="{_alt}" loading="eager">'
            f'<figcaption><a href="{_credit_url}" rel="noopener nofollow" target="_blank">{_credit}</a></figcaption></figure>'
        )
        _wm = re.search(r"[?&]w=(\d+)", _cu)
        _hm = re.search(r"[?&]h=(\d+)", _cu)
        _w, _h = (_wm.group(1) if _wm else "1200"), (_hm.group(1) if _hm else "630")
        og_image = (
            f'\n  <meta property="og:image" content="{_cu}">'
            f'\n  <meta property="og:image:width" content="{_w}">'
            f'\n  <meta property="og:image:height" content="{_h}">'
            f'\n  <meta property="og:image:alt" content="{_alt}">'
        )
        twitter_image = f'\n  <meta name="twitter:image" content="{_cu}">'
    site_name = (site.get("name") or "").replace('"', "'")
    published_at = draft.get("published_at") or draft.get("created_at") or datetime.now(timezone.utc).isoformat()
    article_jsonld_obj = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": meta_desc,
        "datePublished": published_at,
        "dateModified": draft.get("updated_at") or published_at,
        "author": {"@type": "Organization", "name": site_name or "Rédaction"},
        "publisher": {"@type": "Organization", "name": site_name or "Rédaction"},
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
    }
    if cover_url.startswith("https://"):
        article_jsonld_obj["image"] = cover_url
    article_jsonld = f'<script type="application/ld+json">{_json.dumps(article_jsonld_obj, ensure_ascii=False)}</script>'
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{meta_title}</title>
  <meta name="description" content="{meta_desc}">
  <meta name="keywords" content="{', '.join(keywords)}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:site_name" content="{site_name}">
  <meta property="og:title" content="{meta_title}">
  <meta property="og:description" content="{meta_desc}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="{canonical}">{og_image}
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{meta_title}">
  <meta name="twitter:description" content="{meta_desc}">{twitter_image}
  <meta name="generator" content="LOGI SEO Booster">
  {article_jsonld}
  {faq_jsonld}
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;line-height:1.65;color:#020617}}
    h1{{font-size:2.2rem;line-height:1.2;letter-spacing:-0.01em;margin-bottom:1rem}}
    h2{{font-size:1.5rem;margin-top:2rem;color:#0f172a}}
    h3{{font-size:1.2rem;margin-top:1.4rem;color:#1e293b}}
    p{{margin:0.7rem 0}}
    a{{color:#002FA7}}
    table{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.95rem}}
    th,td{{border:1px solid #e2e8f0;padding:.5rem .75rem;text-align:left}}
    th{{background:#f8fafc;font-weight:600}}
    .faq-item{{border:1px solid #e2e8f0;border-radius:6px;padding:.75rem 1rem;margin:.5rem 0}}
    .faq-item summary{{cursor:pointer;font-weight:600;color:#020617}}
    .faq-item p{{margin-top:.5rem;color:#334155}}
    .meta{{color:#64748b;font-size:.85rem;margin-bottom:1.5rem;padding-bottom:1rem;border-bottom:1px solid #e2e8f0}}
    .cover{{margin:0 0 1.5rem}}
    .cover img{{width:100%;height:auto;border-radius:10px;display:block}}
    .cover figcaption{{font-size:.7rem;color:#94a3b8;margin-top:.35rem;text-align:right}}
    .cover figcaption a{{color:#94a3b8;text-decoration:none}}
  </style>
</head>
<body>
  <article>
    <h1>{title}</h1>
    <div class="meta">Publié le {datetime.now(timezone.utc).strftime("%d/%m/%Y")} · {site.get("name","")}</div>
    {cover_html}
    {body_html}
    {faq_html}
  </article>
</body>
</html>
"""


async def publish_to_ftp(site: dict, draft: dict) -> Optional[dict]:
    """Upload HTML + JSON files to the configured FTP server."""
    import json as _json
    from ftplib import FTP, error_perm
    from io import BytesIO

    host = site.get("ftp_host")
    port = site.get("ftp_port") or 21
    user = site.get("ftp_user")
    pwd = dec(site.get("ftp_password"))
    remote_path = (site.get("ftp_remote_path") or "/").rstrip("/") + "/"
    if not all((host, user, pwd, remote_path)):
        return None

    slug = _slugify(draft.get("title", ""))
    html_bytes = _render_html(draft, site).encode("utf-8")
    json_bytes = _json.dumps({
        "id": draft.get("id"),
        "slug": slug,
        "title": draft.get("title"),
        "meta_title": draft.get("meta_title"),
        "meta_description": draft.get("meta_description"),
        "content_type": draft.get("content_type"),
        "body_markdown": draft.get("body_markdown"),
        "keywords": draft.get("keywords", []),
        "faq": draft.get("faq", []),
        "published_at": now_iso(),
    }, ensure_ascii=False, indent=2).encode("utf-8")

    def _do_upload() -> dict:
        ftp = FTP()
        ftp.connect(host, port, timeout=15)
        ftp.login(user, pwd)
        # Ensure remote_path exists
        parts = [p for p in remote_path.strip("/").split("/") if p]
        cur = ""
        for p in parts:
            cur = (cur + "/" + p) if cur else "/" + p
            try:
                ftp.cwd(cur)
            except error_perm:
                try:
                    ftp.mkd(cur)
                    ftp.cwd(cur)
                except error_perm:
                    pass
        ftp.storbinary(f"STOR {slug}.html", BytesIO(html_bytes))
        ftp.storbinary(f"STOR {slug}.json", BytesIO(json_bytes))
        ftp.quit()
        return {"slug": slug, "files": [f"{slug}.html", f"{slug}.json"], "remote_path": remote_path}

    try:
        return await asyncio.to_thread(_do_upload)
    except Exception as exc:
        logger.warning("FTP publish error: %s", exc)
        return None


@api.post("/sites/{site_id}/test-ftp")
async def test_ftp_connection(site_id: str, user=Depends(get_current_user)):
    """Test FTP credentials without uploading anything."""
    from ftplib import FTP
    site = await _get_user_site(site_id, user)
    if site.get("site_type") != "ftp":
        raise HTTPException(400, "Ce site n'est pas configuré en FTP.")
    def _do_test() -> dict:
        ftp = FTP()
        ftp.connect(site["ftp_host"], site.get("ftp_port") or 21, timeout=10)
        ftp.login(site["ftp_user"], dec(site["ftp_password"]))
        try:
            ftp.cwd(site.get("ftp_remote_path") or "/")
            cwd = ftp.pwd()
        except Exception:
            cwd = "?"
        ftp.quit()
        return {"ok": True, "cwd": cwd}
    try:
        return await asyncio.to_thread(_do_test)
    except Exception as exc:
        raise HTTPException(502, f"Connexion FTP impossible : {exc}")


# ---------------------------------------------------------------------------
# GitHub publishing (commit HTML files to a repo via PAT)
# ---------------------------------------------------------------------------
GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
_GITHUB_403_MSG = (
    "Permission d'écriture refusée par GitHub (403). Votre token n'a pas la permission "
    "« Contents : Read and write » sur ce repo. Sur GitHub : Settings → Developer settings → "
    "Personal access tokens → Fine-grained tokens → votre token → Permissions → Contents → "
    "« Read and write », puis cliquez Update. Le token reste le même, pas besoin de le re-saisir."
)


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "LOGI-SEO-Booster",
    }


async def _github_get_file_sha(client: httpx.AsyncClient, token: str, owner: str, repo: str, path: str, branch: str) -> Optional[str]:
    """Return the SHA of an existing file, or None if it does not exist."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    resp = await client.get(url, headers=_github_headers(token), params={"ref": branch})
    if resp.status_code == 200:
        return resp.json().get("sha")
    if resp.status_code == 404:
        return None
    if resp.status_code == 403:
        raise HTTPException(403, _GITHUB_403_MSG)
    raise HTTPException(
        502,
        f"GitHub GET contents a échoué ({resp.status_code}): {resp.text[:200]}"
    )


async def _github_put_file(
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo: str,
    path: str,
    branch: str,
    message: str,
    content_text: str,
    sha: Optional[str],
) -> dict:
    """Create or update a file via the GitHub contents API. Returns {commit_sha, commit_url, html_url}."""
    import base64
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    encoded = base64.b64encode(content_text.encode("utf-8")).decode("utf-8")
    payload = {"message": message, "content": encoded, "branch": branch}
    if sha:
        payload["sha"] = sha
    resp = await client.put(url, headers=_github_headers(token), json=payload)
    if resp.status_code == 403:
        raise HTTPException(403, _GITHUB_403_MSG)
    if resp.status_code == 404:
        raise HTTPException(403, _GITHUB_403_MSG + " (GitHub renvoie 404 quand le token n'a pas accès en écriture à ce repo.)")
    if resp.status_code not in (200, 201):
        raise HTTPException(
            502,
            f"GitHub PUT contents a échoué ({resp.status_code}): {resp.text[:300]}"
        )
    data = resp.json()
    commit = data.get("commit") or {}
    content = data.get("content") or {}
    return {
        "commit_sha": commit.get("sha"),
        "commit_url": commit.get("html_url"),
        "file_url": content.get("html_url"),
        "path": content.get("path") or path,
    }


@api.post("/sites/{site_id}/test-github")
async def test_github_connection(site_id: str, user=Depends(get_current_user)):
    """Verify GitHub PAT + repo + branch are valid by listing the target folder."""
    site = await _get_user_site(site_id, user)
    token = dec(site.get("github_token"))
    owner = site.get("github_owner")
    repo = site.get("github_repo")
    branch = site.get("github_branch") or "main"
    folder = (site.get("github_folder") or "").strip("/")
    if not (token and owner and repo):
        raise HTTPException(400, "Configurez d'abord github_token, github_owner et github_repo sur ce site.")
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Check repo + branch exists
        repo_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/branches/{branch}",
            headers=_github_headers(token),
        )
        if repo_resp.status_code == 401:
            raise HTTPException(400, "Token GitHub invalide ou expiré.")
        if repo_resp.status_code == 403:
            raise HTTPException(403, _GITHUB_403_MSG)
        if repo_resp.status_code == 404:
            # Distinguish: repo missing vs repo exists but empty / branch missing
            check = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", headers=_github_headers(token))
            if check.status_code == 200:
                if check.json().get("size", 0) == 0:
                    raise HTTPException(404, (
                        f"Le repo '{owner}/{repo}' existe mais est VIDE (aucun commit) — la branche '{branch}' "
                        f"n'existe donc pas encore. Sur GitHub, cliquez « creating a new file » (ou « Add a README ») "
                        f"pour créer un premier fichier et initialiser la branche, puis retestez."
                    ))
                raise HTTPException(404, (
                    f"Le repo '{owner}/{repo}' existe mais la branche '{branch}' est introuvable. "
                    f"Vérifiez le nom de la branche (Settings → Branches sur GitHub) ou utilisez la branche par défaut."
                ))
            raise HTTPException(404, f"Repo '{owner}/{repo}' introuvable ou inaccessible avec ce token. Vérifiez owner/repo et que le token a bien accès à ce repo (Contents: Read & write).")
        if repo_resp.status_code != 200:
            raise HTTPException(502, f"Erreur GitHub ({repo_resp.status_code}): {repo_resp.text[:200]}")
        repo_data = repo_resp.json()
        # 2. Verify WRITE permission (Contents: Read and write) on the repo
        perm_resp = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", headers=_github_headers(token))
        can_write = False
        if perm_resp.status_code == 200:
            perms = perm_resp.json().get("permissions") or {}
            can_write = bool(perms.get("push") or perms.get("maintain") or perms.get("admin"))
        if not can_write:
            raise HTTPException(403, (
                "Connexion OK en LECTURE, mais le token n'a PAS la permission d'ÉCRITURE sur "
                f"'{owner}/{repo}' — la publication échouera (403). " + _GITHUB_403_MSG
            ))
        # 3. List target folder (if specified) to confirm path
        listing = []
        if folder:
            list_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{folder}",
                headers=_github_headers(token),
                params={"ref": branch},
            )
            if list_resp.status_code == 200:
                items = list_resp.json()
                if isinstance(items, list):
                    listing = [{"name": i.get("name"), "type": i.get("type")} for i in items[:20]]
            elif list_resp.status_code == 404:
                listing = []  # folder doesn't exist yet — will be created on first commit
            else:
                raise HTTPException(502, f"Erreur GitHub ({list_resp.status_code}): {list_resp.text[:200]}")
        else:
            # List root
            list_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents",
                headers=_github_headers(token),
                params={"ref": branch},
            )
            if list_resp.status_code == 200:
                items = list_resp.json()
                if isinstance(items, list):
                    listing = [{"name": i.get("name"), "type": i.get("type")} for i in items[:20]]
        return {
            "ok": True,
            "write_access": True,
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "folder": folder or "(racine)",
            "commit_sha": (repo_data.get("commit") or {}).get("sha", "")[:7],
            "listing": listing,
        }


@api.post("/drafts/{draft_id}/publish-github")
async def publish_draft_to_github(draft_id: str, user=Depends(get_current_user)):
    """Commit the draft's HTML file (and JSON) to the configured GitHub repo."""
    import json as _json
    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    site = await db.sites.find_one({"id": d["site_id"], "user_id": user["id"]}, {"_id": 0}) or {}
    token = dec(site.get("github_token"))
    owner = site.get("github_owner")
    repo = site.get("github_repo")
    branch = site.get("github_branch") or "main"
    folder = (site.get("github_folder") or "").strip("/")
    if not (token and owner and repo):
        raise HTTPException(400, "GitHub n'est pas configuré pour ce site. Configurez le token, owner et repo dans la page Sites.")

    slug = _slugify(d.get("title", ""))
    html_str = _render_html(d, site)
    json_str = _json.dumps({
        "id": d.get("id"),
        "slug": slug,
        "title": d.get("title"),
        "meta_title": d.get("meta_title"),
        "meta_description": d.get("meta_description"),
        "content_type": d.get("content_type"),
        "body_markdown": d.get("body_markdown"),
        "keywords": d.get("keywords", []),
        "faq": d.get("faq", []),
        "published_at": now_iso(),
    }, ensure_ascii=False, indent=2)

    html_path = f"{folder}/{slug}.html" if folder else f"{slug}.html"
    json_path = f"{folder}/{slug}.json" if folder else f"{slug}.json"
    commit_msg = f"LOGI SEO: publish {slug} ({d.get('content_type','article')})"

    results = []
    sitemap_result = None
    blog_index_result = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for path, content in ((html_path, html_str), (json_path, json_str)):
            existing_sha = await _github_get_file_sha(client, token, owner, repo, path, branch)
            res = await _github_put_file(client, token, owner, repo, path, branch, commit_msg, content, existing_sha)
            res["updated"] = existing_sha is not None
            results.append(res)
        # Update sitemap.xml + blog index if public URL is configured
        page_url = _github_public_page_url(site, slug)
        if page_url:
            try:
                sitemap_result = await _github_update_sitemap(client, token, owner, repo, branch, folder, page_url, slug)
            except Exception as exc:
                logger.warning("Sitemap update failed: %s", exc)
                sitemap_result = {"error": str(exc)}
            try:
                blog_index_result = await _github_update_blog_index(client, token, owner, repo, branch, d, slug, page_url)
            except Exception as exc:
                logger.warning("Blog index update failed: %s", exc)
                blog_index_result = {"error": str(exc)}

    # Update draft status
    public_url = _github_public_page_url(site, slug)
    await db.drafts.update_one(
        {"id": draft_id},
        {"$set": {
            "status": "published",
            "github_commit_sha": results[0].get("commit_sha"),
            "github_committed_at": now_iso(),
            "github_public_url": public_url,
        }},
    )
    # --- Validation aperçu social (Open Graph) avant de conclure ---
    social_warnings = []
    cov = d.get("cover_image_url") or ""
    if not cov:
        social_warnings.append("Article publié, mais aperçu social incomplet : image Open Graph manquante.")
    elif not cov.startswith("https://"):
        social_warnings.append("Article publié, mais l'image de couverture n'est pas une URL HTTPS absolue — LinkedIn n'affichera pas d'image.")
    else:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as _c:
                ir = await _c.head(cov)
                if ir.status_code >= 400:
                    ir = await _c.get(cov)
            if ir.status_code >= 400:
                social_warnings.append(f"Article publié, mais l'image de couverture répond HTTP {ir.status_code} — l'aperçu social sera sans image.")
        except Exception:
            social_warnings.append("Article publié, mais l'image de couverture est inaccessible publiquement — l'aperçu social sera sans image.")
    if not (d.get("meta_description") or "").strip():
        social_warnings.append("Meta description absente — l'aperçu social sera incomplet.")
    if not public_url:
        social_warnings.append("URL publique non configurée sur ce site (canonical/og:url absents) — renseignez « URL publique du dossier ».")

    return {
        "ok": True,
        "files": results,
        "sitemap": sitemap_result,
        "blog_index": blog_index_result,
        "public_url": public_url,
        "social_warnings": social_warnings,
        "commit_sha": results[0].get("commit_sha"),
        "commit_url": results[0].get("commit_url"),
    }


async def _github_update_sitemap(client, token, owner, repo, branch, folder, page_url, slug):
    """Add page_url to sitemap.xml in the repo. Looks for sitemap at known locations.
    Strategy: try `public/sitemap.xml`, then `sitemap.xml`, then `folder/sitemap.xml`.
    If not found, create a minimal sitemap.xml in the same folder as the page.
    """
    import base64
    candidate_paths = ["public/sitemap.xml", "sitemap.xml"]
    if folder:
        candidate_paths.insert(0, f"{folder}/sitemap.xml")
        # Also check for sitemap at the root of public/ inferred from folder
        if "/" in folder:
            root = folder.split("/")[0]
            candidate_paths.insert(0, f"{root}/sitemap.xml")
    seen = set()
    candidate_paths = [p for p in candidate_paths if not (p in seen or seen.add(p))]

    existing_sha = None
    existing_xml = None
    existing_path = None
    for path in candidate_paths:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        r = await client.get(url, headers=_github_headers(token), params={"ref": branch})
        if r.status_code == 200:
            data = r.json()
            existing_sha = data.get("sha")
            try:
                existing_xml = base64.b64decode(data.get("content", "")).decode("utf-8")
            except Exception:
                existing_xml = None
            existing_path = path
            break

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_entry = f'  <url>\n    <loc>{page_url}</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>0.7</priority>\n  </url>'

    if existing_xml and "<urlset" in existing_xml:
        # If URL already present, just update the lastmod via simple regex
        import re
        if page_url in existing_xml:
            new_xml = re.sub(
                r"(<url>\s*<loc>" + re.escape(page_url) + r"</loc>\s*<lastmod>)[^<]*(</lastmod>)",
                rf"\g<1>{today}\g<2>",
                existing_xml,
            )
            action = "updated_existing_entry"
        else:
            # Remove stale entries for the same slug (e.g. old URL without the folder), then append
            stale_pattern = re.compile(r"\s*<url>(?:(?!</url>).)*?/" + re.escape(slug) + r"\.html</loc>(?:(?!</url>).)*?</url>", re.DOTALL)
            existing_xml = stale_pattern.sub("", existing_xml)
            new_xml = existing_xml.replace("</urlset>", f"{new_entry}\n</urlset>")
            action = "appended_entry"
        target_path = existing_path
    else:
        # Create a new minimal sitemap
        new_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{new_entry}\n"
            "</urlset>\n"
        )
        target_path = f"{folder}/sitemap.xml" if folder else "public/sitemap.xml"
        action = "created_new"
        existing_sha = None

    msg = f"LOGI SEO: sitemap.xml — {action} ({slug})"
    res = await _github_put_file(client, token, owner, repo, target_path, branch, msg, new_xml, existing_sha)
    return {"path": target_path, "action": action, "commit_sha": res.get("commit_sha"), "commit_url": res.get("commit_url")}


async def _github_update_blog_index(client, token, owner, repo, branch, draft, slug, page_url):
    """Maintain articles.json + inject article cards into the blog's index.html (id="articles")."""
    import base64
    import html as _html
    import json as _json
    aj_path = "articles.json"
    r = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{aj_path}",
                         headers=_github_headers(token), params={"ref": branch})
    articles, aj_sha = [], None
    if r.status_code == 200:
        aj_sha = r.json().get("sha")
        try:
            articles = _json.loads(base64.b64decode(r.json().get("content", "")).decode("utf-8"))
            if not isinstance(articles, list):
                articles = []
        except Exception:
            articles = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    articles = [a for a in articles if a.get("slug") != slug]
    articles.insert(0, {
        "slug": slug,
        "title": draft.get("title") or "",
        "description": draft.get("meta_description") or "",
        "url": page_url,
        "date": today,
        "cover": draft.get("cover_image_url") or "",
    })
    articles.sort(key=lambda a: a.get("date", ""), reverse=True)
    await _github_put_file(client, token, owner, repo, aj_path, branch,
                           f"LOGI SEO: articles.json ({slug})",
                           _json.dumps(articles, ensure_ascii=False, indent=2), aj_sha)

    idx_path = "index.html"
    r2 = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{idx_path}",
                          headers=_github_headers(token), params={"ref": branch})
    if r2.status_code != 200:
        return {"action": "articles_json_only", "count": len(articles)}
    idx_sha = r2.json().get("sha")
    try:
        idx_html = base64.b64decode(r2.json().get("content", "")).decode("utf-8")
    except Exception:
        return {"action": "articles_json_only", "count": len(articles)}
    if 'id="articles"' not in idx_html:
        return {"action": "articles_json_only", "count": len(articles)}

    def _fmt_date(dd):
        try:
            return datetime.strptime(dd, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return dd
    cards = "\n".join(
        f'        <a class="article" href="{a["url"]}">'
        f'<h2>{_html.escape(a.get("title", ""))}</h2>'
        f'<p style="color:#94a3b8;font-size:13px;margin-bottom:6px">{_fmt_date(a.get("date", ""))}</p>'
        f'<p>{_html.escape(a.get("description", ""))}</p></a>'
        for a in articles
    )
    new_idx = re.sub(
        r'(<div class="articles" id="articles">).*?(</div>\s*</main>)',
        lambda m: m.group(1) + "\n" + cards + "\n      " + m.group(2),
        idx_html, flags=re.DOTALL,
    )
    if new_idx != idx_html:
        await _github_put_file(client, token, owner, repo, idx_path, branch,
                               f"LOGI SEO: index.html ({slug})", new_idx, idx_sha)
    return {"action": "index_updated", "count": len(articles)}


@api.get("/drafts/{draft_id}/export")
async def export_draft(draft_id: str, user=Depends(get_current_user)):
    """Generate and return a ZIP file with HTML + JSON ready to FTP-upload manually."""
    from fastapi.responses import Response
    import json as _json
    import zipfile
    from io import BytesIO

    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    site = await db.sites.find_one({"id": d["site_id"], "user_id": user["id"]}, {"_id": 0}) or {}

    slug = _slugify(d.get("title", ""))
    html_str = _render_html(d, site)
    json_str = _json.dumps({
        "id": d.get("id"),
        "slug": slug,
        "title": d.get("title"),
        "meta_title": d.get("meta_title"),
        "meta_description": d.get("meta_description"),
        "content_type": d.get("content_type"),
        "body_markdown": d.get("body_markdown"),
        "keywords": d.get("keywords", []),
        "faq": d.get("faq", []),
        "published_at": now_iso(),
    }, ensure_ascii=False, indent=2)

    readme = f"""LOGI SEO Booster — Export manuel
================================

Contenu généré le {datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")}

Fichiers inclus :
- {slug}.html : page HTML complète, optimisée SEO (canonical, Open Graph,
  JSON-LD FAQ schema, mobile-friendly). Indexable directement par Google.
- {slug}.json : données structurées (à consommer côté React/JS si besoin).

Comment publier :
1. Connectez-vous à votre FTP (FileZilla, Cyberduck, WinSCP, etc.)
2. Naviguez vers votre dossier web (ex: /public_html/blog ou /var/www/.../blog)
3. Uploadez les 2 fichiers
4. Votre contenu sera accessible à :
     https://VOTRE-DOMAINE/blog/{slug}.html

Astuce SEO : ajoutez ce nouveau lien à votre sitemap.xml et soumettez-le
dans Google Search Console pour accélérer l'indexation.
"""

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{slug}.html", html_str)
        zf.writestr(f"{slug}.json", json_str)
        zf.writestr("README.txt", readme)
    buf.seek(0)
    filename = f"logi-seo-{slug}.zip"
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.get("/drafts/{draft_id}/export.html")
async def export_draft_html(draft_id: str, user=Depends(get_current_user)):
    """Return just the HTML file for direct download."""
    from fastapi.responses import Response

    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    site = await db.sites.find_one({"id": d["site_id"], "user_id": user["id"]}, {"_id": 0}) or {}
    slug = _slugify(d.get("title", ""))
    return Response(
        content=_render_html(d, site),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.html"'},
    )


# ---------- end FTP helpers --------------------------------------------------


@api.post("/drafts/{draft_id}/publish", response_model=DraftPublic)
async def publish_draft(draft_id: str, payload: PublishRequest, user=Depends(get_current_user)):
    d = await db.drafts.find_one({"id": draft_id, "user_id": user["id"]})
    if not d:
        raise HTTPException(404, "Brouillon introuvable")
    site = await _get_user_site(d["site_id"], user)

    site_type = site.get("site_type", "wix")
    wix_draft_id: Optional[str] = None
    wix_post_id: Optional[str] = None
    wix_url: Optional[str] = None
    vps_published_id: Optional[str] = None
    ftp_published_slug: Optional[str] = None
    status_label: str

    if site_type == "wix":
        wix_result = await create_wix_draft_post(
            site=site,
            title=d["title"],
            body_markdown=d["body_markdown"],
            seo_title=d.get("meta_title"),
            seo_description=d.get("meta_description"),
        ) or {}
        wix_draft_id = wix_result.get("draft_id")
        wix_post_id = wix_result.get("post_id")
        wix_url = wix_result.get("url")
        status_label = "success" if wix_post_id else ("wix_draft_only" if wix_draft_id else "wix_unavailable")
    elif site_type == "vps_api":
        vps_resp = await publish_to_vps_api(site, d)
        if vps_resp:
            vps_published_id = vps_resp.get("id") or vps_resp.get("slug") or "published"
            status_label = "vps_success"
        else:
            status_label = "vps_unavailable"
    elif site_type == "ftp":
        ftp_resp = await publish_to_ftp(site, d)
        if ftp_resp:
            ftp_published_slug = ftp_resp.get("slug")
            status_label = "ftp_success"
        else:
            status_label = "ftp_unavailable"
    else:
        status_label = "ready_for_export"

    log_entry = {
        "id": gen_id(),
        "user_id": user["id"],
        "site_id": d["site_id"],
        "draft_id": draft_id,
        "title": d["title"],
        "action": "publish_attempt",
        "wix_draft_id": wix_draft_id,
        "wix_post_id": wix_post_id,
        "wix_url": wix_url,
        "vps_published_id": vps_published_id,
        "ftp_published_slug": ftp_published_slug,
        "status": status_label,
        "site_type": site_type,
        "created_at": now_iso(),
    }
    await db.publish_logs.insert_one(log_entry)

    is_published = bool(wix_post_id or wix_draft_id or vps_published_id or ftp_published_slug)
    updates = {
        "wix_draft_id": wix_draft_id,
        "wix_post_id": wix_post_id,
        "wix_url": wix_url,
        "status": "published" if is_published else "ready",
        "updated_at": now_iso(),
    }
    if is_published:
        updates["wix_published_at"] = now_iso()
    await db.drafts.update_one({"id": draft_id}, {"$set": updates})
    d = await db.drafts.find_one({"id": draft_id}, {"_id": 0})
    return _draft_public(d)


@api.get("/publish-logs")
async def list_publish_logs(site_id: Optional[str] = None, user=Depends(get_current_user)):
    q: Dict[str, Any] = {"user_id": user["id"]}
    if site_id:
        q["site_id"] = site_id
    logs = await db.publish_logs.find(q, {"_id": 0, "user_id": 0}).sort("created_at", -1).to_list(200)
    return {"logs": logs}


# ---------------------------------------------------------------------------
