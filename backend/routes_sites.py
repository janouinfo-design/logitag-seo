from bs4 import BeautifulSoup
from fastapi import Depends
from fastapi import HTTPException
from typing import Dict
from typing import List
from typing import Optional
from urllib.parse import urljoin
from urllib.parse import urlparse
import asyncio
import httpx
import re
from ai_visibility import normalize_base_url
from app_core import SiteCreate, SitePublic, SiteUpdate, api, db, dec, enc, gen_id, get_current_user, logger, now_iso

# ---------------------------------------------------------------------------
# Sites (Wix) endpoints
# ---------------------------------------------------------------------------
def site_to_public(site: dict) -> SitePublic:
    return SitePublic(
        id=site["id"],
        label=site["label"],
        name=site["name"],
        site_type=site.get("site_type", "wix"),
        wix_site_id=site.get("wix_site_id"),
        wix_account_id=site.get("wix_account_id"),
        base_url=site.get("base_url"),
        vps_api_url=site.get("vps_api_url"),
        ftp_host=site.get("ftp_host"),
        ftp_port=site.get("ftp_port"),
        ftp_user=site.get("ftp_user"),
        ftp_remote_path=site.get("ftp_remote_path"),
        ftp_public_url=site.get("ftp_public_url"),
        github_owner=site.get("github_owner"),
        github_repo=site.get("github_repo"),
        github_branch=site.get("github_branch"),
        github_folder=site.get("github_folder"),
        github_public_url=site.get("github_public_url"),
        has_github_token=bool(site.get("github_token")),
        gsc_site_url=site.get("gsc_site_url"),
        ga4_property_id=site.get("ga4_property_id"),
        has_api_key=bool(site.get("wix_api_key")),
        has_vps_token=bool(site.get("vps_api_token")),
        has_ftp_password=bool(site.get("ftp_password")),
        created_at=site["created_at"],
    )


@api.post("/sites", response_model=SitePublic)
async def create_site(payload: SiteCreate, user=Depends(get_current_user)):
    site_type = payload.site_type
    if site_type == "wix":
        if not (payload.wix_site_id and payload.wix_account_id and payload.wix_api_key):
            raise HTTPException(422, "Pour un site Wix, wix_site_id, wix_account_id et wix_api_key sont requis.")
    elif site_type == "vps_api":
        if not (payload.base_url and payload.vps_api_url and payload.vps_api_token):
            raise HTTPException(422, "Pour un site VPS API, base_url, vps_api_url et vps_api_token sont requis.")
    elif site_type == "ftp":
        if not (payload.ftp_host and payload.ftp_user and payload.ftp_password and payload.ftp_remote_path):
            raise HTTPException(422, "Pour un site FTP, ftp_host, ftp_user, ftp_password et ftp_remote_path sont requis.")
    else:  # url_crawl
        if not payload.base_url:
            raise HTTPException(422, "Pour un site URL publique, base_url est requis.")
    site = {
        "id": gen_id(),
        "user_id": user["id"],
        "label": payload.label,
        "name": payload.name.strip(),
        "site_type": site_type,
        "wix_site_id": (payload.wix_site_id or "").strip() or None,
        "wix_account_id": (payload.wix_account_id or "").strip() or None,
        "wix_api_key": enc((payload.wix_api_key or "").strip()) or None,
        "base_url": normalize_base_url(payload.base_url or "") or None,
        "vps_api_url": (payload.vps_api_url or "").strip() or None,
        "vps_api_token": enc((payload.vps_api_token or "").strip()) or None,
        "ftp_host": (payload.ftp_host or "").strip() or None,
        "ftp_port": payload.ftp_port or 21,
        "ftp_user": (payload.ftp_user or "").strip() or None,
        "ftp_password": enc(payload.ftp_password) or None,
        "ftp_remote_path": (payload.ftp_remote_path or "").strip() or None,
        "ftp_public_url": (payload.ftp_public_url or "").strip() or None,
        "github_token": enc((payload.github_token or "").strip()) or None,
        "github_owner": (payload.github_owner or "").strip() or None,
        "github_repo": (payload.github_repo or "").strip() or None,
        "github_branch": (payload.github_branch or "main").strip() or "main",
        "github_folder": (payload.github_folder or "").strip().strip("/") or None,
        "github_public_url": (payload.github_public_url or "").strip().rstrip("/") or None,
        "created_at": now_iso(),
    }
    await db.sites.insert_one(site)
    return site_to_public(site)


@api.get("/sites", response_model=List[SitePublic])
async def list_sites(user=Depends(get_current_user)):
    sites = await db.sites.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    return [site_to_public(s) for s in sites]


@api.get("/sites/{site_id}", response_model=SitePublic)
async def get_site(site_id: str, user=Depends(get_current_user)):
    site = await db.sites.find_one({"id": site_id, "user_id": user["id"]}, {"_id": 0})
    if not site:
        raise HTTPException(404, "Site introuvable")
    return site_to_public(site)


@api.patch("/sites/{site_id}", response_model=SitePublic)
async def update_site(site_id: str, payload: SiteUpdate, user=Depends(get_current_user)):
    site = await db.sites.find_one({"id": site_id, "user_id": user["id"]})
    if not site:
        raise HTTPException(404, "Site introuvable")
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if updates.get("base_url"):
        updates["base_url"] = normalize_base_url(updates["base_url"])
    # Encrypt sensitive fields before persisting
    for sensitive in ("wix_api_key", "vps_api_token", "ftp_password", "github_token"):
        if sensitive in updates and updates[sensitive]:
            updates[sensitive] = enc(updates[sensitive])
    if updates:
        await db.sites.update_one({"id": site_id}, {"$set": updates})
    site = await db.sites.find_one({"id": site_id}, {"_id": 0})
    return site_to_public(site)


@api.delete("/sites/{site_id}")
async def delete_site(site_id: str, user=Depends(get_current_user)):
    res = await db.sites.delete_one({"id": site_id, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Site introuvable")
    return {"ok": True}


@api.post("/sites/quick-add-emergent")
async def quick_add_emergent_sites(user=Depends(get_current_user)):
    """One-click: add logirent.ch and logitime.ch as url_crawl sites if not already present."""
    presets = [
        {"label": "Logirent", "name": "Logirent (logirent.ch)", "base_url": "https://www.logirent.ch"},
        {"label": "Logitime", "name": "Logitime (logitime.ch)", "base_url": "https://www.logitime.ch"},
    ]
    added: List[SitePublic] = []
    skipped: List[str] = []
    for p in presets:
        existing = await db.sites.find_one({
            "user_id": user["id"],
            "base_url": p["base_url"],
        })
        if existing:
            skipped.append(p["name"])
            continue
        site = {
            "id": gen_id(),
            "user_id": user["id"],
            "label": p["label"],
            "name": p["name"],
            "site_type": "url_crawl",
            "wix_site_id": None,
            "wix_account_id": None,
            "wix_api_key": None,
            "base_url": p["base_url"],
            "created_at": now_iso(),
        }
        await db.sites.insert_one(site)
        added.append(site_to_public(site))
    return {"added": added, "skipped": skipped}


async def _get_user_site(site_id: str, user: dict) -> dict:
    site = await db.sites.find_one({"id": site_id, "user_id": user["id"]}, {"_id": 0})
    if not site:
        raise HTTPException(404, "Site introuvable")
    return site


# ---------------------------------------------------------------------------
# Wix API helpers (with graceful fallback to mock data for MVP)
# ---------------------------------------------------------------------------
def wix_headers(site: dict) -> Dict[str, str]:
    return {
        "Authorization": dec(site["wix_api_key"]),
        "wix-account-id": site["wix_account_id"],
        "wix-site-id": site["wix_site_id"],
        "Content-Type": "application/json",
    }


def _mock_pages(site: dict) -> List[dict]:
    label = site["label"]
    city_hint = "Paris" if label == "Logirent" else "Lyon"
    base = site.get("base_url") or f"https://www.{label.lower()}.fr"
    return [
        {
            "id": f"page-home-{site['id']}",
            "title": f"Accueil - {site['name']}",
            "url": f"{base}/",
            "meta_title": f"{site['name']} | Location et gestion immobilière",
            "meta_description": "Service professionnel.",  # trop court
            "h1": [f"Bienvenue chez {site['name']}"],
            "h2": ["Nos services", "Pourquoi nous choisir"],
            "word_count": 180,
            "images_total": 5,
            "images_without_alt": 3,
        },
        {
            "id": f"page-services-{site['id']}",
            "title": "Nos Services",
            "url": f"{base}/services",
            "meta_title": "Services",
            "meta_description": None,
            "h1": ["Services"],
            "h2": [],
            "word_count": 420,
            "images_total": 2,
            "images_without_alt": 1,
        },
        {
            "id": f"page-contact-{site['id']}",
            "title": "Contact",
            "url": f"{base}/contact",
            "meta_title": f"Contact | {site['name']}",
            "meta_description": f"Contactez {site['name']} pour toute demande concernant nos services à {city_hint} et alentours.",
            "h1": ["Nous contacter"],
            "h2": ["Adresse", "Téléphone"],
            "word_count": 95,
            "images_total": 1,
            "images_without_alt": 0,
        },
        {
            "id": f"page-blog-{site['id']}",
            "title": "Blog",
            "url": f"{base}/blog",
            "meta_title": "Blog",
            "meta_description": "Articles.",
            "h1": ["Blog"],
            "h2": [],
            "word_count": 60,
            "images_total": 0,
            "images_without_alt": 0,
        },
        {
            "id": f"page-tarifs-{site['id']}",
            "title": "Tarifs",
            "url": f"{base}/tarifs",
            "meta_title": f"Tarifs {site['name']} | Devis personnalisé",
            "meta_description": f"Découvrez nos tarifs transparents pour {site['name']}. Demandez un devis personnalisé adapté à vos besoins.",
            "h1": ["Nos tarifs"],
            "h2": ["Formules", "Devis gratuit"],
            "word_count": 540,
            "images_total": 3,
            "images_without_alt": 0,
        },
    ]


async def crawl_public_site(site: dict, max_pages: int = 12, render_js: bool = True) -> List[dict]:
    """Crawl a public site by URL.
    Strategy:
      1. Try sitemap.xml for URL discovery
      2. Otherwise BFS from base_url (also using rendered JS if render_js=True)
      3. For each URL, fetch with httpx; if it looks like a SPA AND render_js=True, re-fetch with Playwright (headless Chromium) to see the JS-rendered content.
    Extracts per-page: title, meta description, H1/H2 list, word count, images_total, images_without_alt.
    Also detects the framework (Next.js / React CRA / Vite / Vue / static) and reports a `stack_hint`.
    """
    base_url = normalize_base_url(site.get("base_url") or "")
    if not base_url:
        return []
    try:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return []
    except Exception:
        return []
    host = parsed.netloc

    def normalize(u: str) -> str:
        u = u.split("#")[0].rstrip("/")
        return u or u

    urls_to_visit: List[str] = []
    seen: set = set()
    headers = {"User-Agent": "LogiSEOBooster/1.0 (+https://emergent.sh)"}

    def add_url(u: str):
        n = normalize(u)
        if n and n not in seen and urlparse(n).netloc == host:
            seen.add(n)
            urls_to_visit.append(n)

    def detect_stack(raw_html: str) -> Optional[str]:
        lower = raw_html.lower()
        if "/_next/" in lower or '"__next"' in lower or '<div id="__next"' in lower:
            return "Next.js"
        if 'id="root"' in lower and "react" in lower[:8000]:
            return "React (CRA / Vite)"
        if "data-v-app" in lower or "vue" in lower[:5000]:
            return "Vue.js"
        if "/wp-content/" in lower or "wp-includes" in lower:
            return "WordPress"
        if "wix.com" in lower or "_wixCIDX" in lower:
            return "Wix"
        return None

    async with httpx.AsyncClient(timeout=12, headers=headers, follow_redirects=True) as cli:
        try:
            r = await cli.get(f"{base_url}/sitemap.xml")
            if r.status_code == 200 and "xml" in r.headers.get("content-type", "").lower():
                soup = BeautifulSoup(r.text, "xml")
                for loc in soup.find_all("loc"):
                    add_url(loc.text.strip())
                    if len(urls_to_visit) >= max_pages:
                        break
        except Exception as exc:
            logger.info("sitemap fetch failed for %s: %s", base_url, exc)

        # If no sitemap, BFS — but for SPA we may need playwright to extract links
        if not urls_to_visit:
            add_url(base_url)
            try:
                r = await cli.get(base_url)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "lxml")
                    for a in soup.find_all("a", href=True):
                        full = urljoin(base_url, a["href"])
                        add_url(full)
                        if len(urls_to_visit) >= max_pages:
                            break
                    # If still very few URLs and content is small (SPA), use Playwright to discover links
                    if render_js and len(urls_to_visit) <= 1:
                        rendered_links = await _playwright_discover_links(base_url, host, max_pages)
                        for u in rendered_links:
                            add_url(u)
                            if len(urls_to_visit) >= max_pages:
                                break
            except Exception as exc:
                logger.info("home crawl failed for %s: %s", base_url, exc)

        results: List[dict] = []
        sem = asyncio.Semaphore(4)

        async def fetch_one(u: str) -> Optional[dict]:
            async with sem:
                try:
                    rr = await cli.get(u)
                    if rr.status_code >= 400:
                        return None
                    raw_html = rr.text
                    stack = detect_stack(raw_html)
                    soup = BeautifulSoup(raw_html, "lxml")
                    page_title = (soup.title.string or "").strip() if soup.title else ""
                    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
                    meta_desc = (meta_desc_tag.get("content") or "").strip() if meta_desc_tag else None
                    h1s = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
                    h2s = [h.get_text(strip=True) for h in soup.find_all("h2") if h.get_text(strip=True)]
                    body_soup = BeautifulSoup(raw_html, "lxml")
                    for tag in body_soup(["script", "style", "noscript"]):
                        tag.decompose()
                    body_text = body_soup.get_text(" ", strip=True)
                    word_count = len([w for w in re.split(r"\s+", body_text) if w])
                    imgs = soup.find_all("img")
                    imgs_total = len(imgs)
                    imgs_no_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())
                    spa_markers = bool(soup.find(id=re.compile(r"^(root|app|__next)$"))) or "react" in raw_html.lower()[:5000]
                    is_spa = spa_markers and word_count < 100 and len(h1s) == 0

                    # If SPA, re-fetch with Playwright to see real content
                    rendered = False
                    if is_spa and render_js:
                        try:
                            rendered_data = await _playwright_render_page(u)
                            if rendered_data:
                                rendered = True
                                page_title = rendered_data.get("title") or page_title
                                meta_desc = rendered_data.get("meta_description") or meta_desc
                                h1s = rendered_data.get("h1") or h1s
                                h2s = rendered_data.get("h2") or h2s
                                word_count = max(word_count, rendered_data.get("word_count", 0))
                                imgs_total = max(imgs_total, rendered_data.get("images_total", 0))
                                imgs_no_alt = rendered_data.get("images_without_alt", imgs_no_alt)
                        except Exception as exc:
                            logger.info("playwright render failed for %s: %s", u, exc)
                    return {
                        "id": "crawl-" + str(abs(hash(u))),
                        "title": page_title or u,
                        "url": u,
                        "meta_title": page_title or None,
                        "meta_description": meta_desc,
                        "h1": h1s,
                        "h2": h2s,
                        "word_count": word_count,
                        "images_total": imgs_total,
                        "images_without_alt": imgs_no_alt,
                        "spa_detected": is_spa,
                        "js_rendered": rendered,
                        "stack_hint": stack,
                    }
                except Exception as exc:
                    logger.info("crawl page failed %s: %s", u, exc)
                    return None

        tasks = [fetch_one(u) for u in urls_to_visit[:max_pages]]
        for res in await asyncio.gather(*tasks):
            if res:
                results.append(res)
        return results


async def _playwright_discover_links(base_url: str, host: str, max_pages: int) -> List[str]:
    """Render the base URL with headless Chromium and return internal links."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return []
    links: List[str] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                ctx = await browser.new_context(user_agent="LogiSEOBooster/1.0")
                page = await ctx.new_page()
                await page.goto(base_url, wait_until="networkidle", timeout=15000)
                hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                for h in hrefs:
                    if urlparse(h).netloc == host and h not in links:
                        links.append(h.split("#")[0].rstrip("/"))
                        if len(links) >= max_pages:
                            break
            finally:
                await browser.close()
    except Exception as exc:
        logger.info("playwright discover failed: %s", exc)
    return links


async def _playwright_render_page(url: str) -> Optional[dict]:
    """Render a single URL with headless Chromium and extract SEO data after JS execution."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                ctx = await browser.new_context(user_agent="LogiSEOBooster/1.0")
                page = await ctx.new_page()
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(800)  # allow late hydration
                html = await page.content()
            finally:
                await browser.close()
        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string or "").strip() if soup.title else ""
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = (meta_desc_tag.get("content") or "").strip() if meta_desc_tag else None
        h1s = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
        h2s = [h.get_text(strip=True) for h in soup.find_all("h2") if h.get_text(strip=True)]
        body = BeautifulSoup(html, "lxml")
        for tag in body(["script", "style", "noscript"]):
            tag.decompose()
        text = body.get_text(" ", strip=True)
        wc = len([w for w in re.split(r"\s+", text) if w])
        imgs = soup.find_all("img")
        imgs_no_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())
        return {
            "title": title or None,
            "meta_description": meta_desc,
            "h1": h1s,
            "h2": h2s,
            "word_count": wc,
            "images_total": len(imgs),
            "images_without_alt": imgs_no_alt,
        }
    except Exception as exc:
        logger.info("playwright render error %s: %s", url, exc)
        return None


async def fetch_wix_pages(site: dict) -> List[dict]:
    """Dispatcher: routes to Wix API or URL crawl depending on site_type. Falls back to mock if both fail."""
    site_type = site.get("site_type", "wix")
    if site_type in ("url_crawl", "vps_api", "ftp"):
        # All non-Wix types are crawled by URL
        pages = await crawl_public_site(site)
        if pages:
            return pages
        return _mock_pages(site)
    # Default Wix API path
    url = "https://www.wixapis.com/site-pages/v2/pages/query"
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(url, headers=wix_headers(site), json={"query": {"paging": {"limit": 50}}})
        if r.status_code == 200:
            data = r.json()
            pages = []
            for p in data.get("pages", []) or []:
                seo = p.get("seo", {}) or {}
                pages.append({
                    "id": p.get("id", gen_id()),
                    "title": p.get("title") or p.get("pageName") or "Sans titre",
                    "url": p.get("url") or "",
                    "meta_title": seo.get("title"),
                    "meta_description": seo.get("description"),
                    "h1": [],
                    "h2": [],
                    "word_count": 0,
                    "images_total": 0,
                    "images_without_alt": 0,
                })
            if pages:
                return pages
        logger.info("Wix pages API returned %s — using mock data", r.status_code)
    except Exception as exc:
        logger.info("Wix pages API unreachable (%s) — using mock data", exc)
    return _mock_pages(site)


async def fetch_wix_blog_posts(site: dict) -> List[dict]:
    """Try Wix Blog API; fall back to small mock list."""
    url = "https://www.wixapis.com/blog/v3/posts/query"
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(url, headers=wix_headers(site), json={"query": {"paging": {"limit": 25}}})
        if r.status_code == 200:
            data = r.json()
            posts = []
            for p in data.get("posts", []) or []:
                posts.append({
                    "id": p.get("id"),
                    "title": p.get("title", ""),
                    "slug": p.get("slug", ""),
                    "url": p.get("url", {}).get("base", "") + p.get("url", {}).get("path", "") if isinstance(p.get("url"), dict) else "",
                    "first_published_date": p.get("firstPublishedDate"),
                    "excerpt": p.get("excerpt", ""),
                })
            return posts
    except Exception as exc:
        logger.info("Wix blog API unreachable (%s) — using mock data", exc)
    base = site.get("base_url") or f"https://www.{site['label'].lower()}.fr"
    return [
        {"id": "post-1", "title": "Comment optimiser votre bail locatif", "slug": "optimiser-bail-locatif",
         "url": f"{base}/blog/optimiser-bail-locatif", "first_published_date": "2025-09-12", "excerpt": "Guide complet…"},
        {"id": "post-2", "title": "Gestion locative à distance : 5 conseils", "slug": "gestion-locative-distance",
         "url": f"{base}/blog/gestion-locative-distance", "first_published_date": "2025-10-04", "excerpt": "Astuces et bonnes pratiques."},
    ]


async def create_wix_draft_post(site: dict, title: str, body_markdown: str, seo_title: Optional[str],
                                seo_description: Optional[str]) -> Optional[str]:
    """Try to create a draft post on Wix. Returns Wix draft id or None on failure."""
    url = "https://www.wixapis.com/blog/v3/draft-posts"
    rich_content = {
        "nodes": [
            {
                "type": "PARAGRAPH",
                "id": gen_id(),
                "nodes": [{"type": "TEXT", "id": gen_id(), "textData": {"text": body_markdown}}],
            }
        ]
    }
    payload = {
        "draftPost": {
            "title": title,
            "richContent": rich_content,
            "seoData": {
                "tags": [
                    {"type": "title", "children": seo_title or title},
                    {"type": "meta", "props": {"name": "description", "content": seo_description or ""}},
                ]
            },
        }
    }
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(url, headers=wix_headers(site), json=payload)
        if r.status_code in (200, 201):
            data = r.json()
            return data.get("draftPost", {}).get("id")
        logger.warning("Wix create draft failed: %s %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("Wix create draft error: %s", exc)
    return None


@api.get("/sites/{site_id}/pages")
async def list_site_pages(site_id: str, user=Depends(get_current_user)):
    site = await _get_user_site(site_id, user)
    pages = await fetch_wix_pages(site)
    return {"pages": pages}


@api.get("/sites/{site_id}/blog-posts")
async def list_site_blog_posts(site_id: str, user=Depends(get_current_user)):
    site = await _get_user_site(site_id, user)
    posts = await fetch_wix_blog_posts(site)
    return {"posts": posts}


