"""AI Visibility Center — analyse la visibilité d'un site dans les moteurs de réponse IA.

Pipeline :
1. Fetch des pages clés (sitemap ou BFS, fallback Playwright pour les SPA)
2. Analyses déterministes : Schema.org, Knowledge Graph, lisibilité IA, fraîcheur, signaux EEAT
3. Analyse LLM (Claude) : entité, SEO sémantique, EEAT qualitatif, explications, actions prioritaires
4. Tests de citation réels : requêtes envoyées à ChatGPT, Claude et Gemini pour vérifier si la marque est citée
5. Scores composites : AI Trust Score + AI Visibility Score global
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("ai-visibility")

MEASURED_MODELS = [
    {"key": "chatgpt", "name": "ChatGPT", "provider": "openai", "model": "gpt-4o"},
    {"key": "claude", "name": "Claude", "provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
    {"key": "gemini", "name": "Gemini", "provider": "gemini", "model": "gemini-2.5-flash"},
]
ESTIMATED_MODELS = [
    {"key": "perplexity", "name": "Perplexity", "basis": ["chatgpt", "claude", "gemini"]},
    {"key": "copilot", "name": "Copilot", "basis": ["chatgpt"]},
    {"key": "mistral", "name": "Mistral (Le Chat)", "basis": ["chatgpt", "gemini"]},
    {"key": "deepseek", "name": "DeepSeek", "basis": ["chatgpt", "claude"]},
]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 (compatible; LogiSEOBooster/1.0)")
STATIC_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js",
              ".pdf", ".zip", ".mp4", ".mp3", ".avi", ".woff", ".woff2", ".ttf", ".eot",
              ".xml", ".json", ".txt", ".gz")
SKIP_PATH_TOKENS = ("login", "logout", "signin", "signup", "register", "admin", "wp-admin",
                    "cart", "panier", "checkout", "account", "mon-compte", "password")


def normalize_base_url(raw: str) -> str:
    """trim + https:// par défaut + suppression des slashs superflus."""
    u = (raw or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u.lstrip("/")
    parts = urlparse(u)
    path = re.sub(r"/{2,}", "/", parts.path or "").rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def _same_site(netloc: str, host: str) -> bool:
    a, b = netloc.lower(), host.lower()
    a = a[4:] if a.startswith("www.") else a
    b = b[4:] if b.startswith("www.") else b
    return a == b


async def _render_html(url: str) -> Optional[str]:
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=25000)
            html = await page.content()
            await browser.close()
            return html
    except Exception as exc:
        logger.info("Playwright render failed for %s: %s", url, exc)
        return None


def _page_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "lxml")
    for tag in clone(["script", "style", "noscript"]):
        tag.decompose()
    return clone.get_text(" ", strip=True)


PRIORITY_PATTERNS = ["about", "a-propos", "apropos", "qui-sommes", "contact", "service", "prestation", "blog", "faq", "tarif"]


async def fetch_pages(base_url: str, max_pages: int = 6, diag: Optional[dict] = None) -> List[dict]:
    """Récupère les pages publiques d'un site : homepage d'abord, puis sitemap (index inclus), sinon crawl.
    Lève RuntimeError avec un diagnostic précis si le site est réellement inaccessible."""
    base_url = normalize_base_url(base_url)
    if not base_url:
        raise RuntimeError("Aucune URL publique configurée pour ce site.")
    headers = {"User-Agent": BROWSER_UA, "Accept-Language": "fr-CH,fr;q=0.9,en;q=0.7"}

    async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as cli:
        # 1. Homepage FIRST (l'analyse ne doit jamais échouer à cause d'un sitemap absent)
        try:
            r = await cli.get(base_url)
        except httpx.ConnectTimeout:
            raise RuntimeError(f"Timeout de connexion vers {base_url} — le serveur ne répond pas.")
        except httpx.ConnectError as exc:
            m = str(exc).lower()
            if "ssl" in m or "certificate" in m:
                raise RuntimeError(f"Certificat SSL invalide pour {base_url}.")
            if "name" in m or "resolve" in m or "getaddrinfo" in m:
                raise RuntimeError(f"Erreur DNS : le domaine {urlparse(base_url).netloc} est introuvable.")
            raise RuntimeError(f"Domaine inaccessible ({base_url}) — connexion refusée.")
        except httpx.TimeoutException:
            raise RuntimeError(f"Timeout en récupérant {base_url}.")
        except Exception as exc:
            raise RuntimeError(f"Erreur en récupérant {base_url} : {type(exc).__name__}: {str(exc)[:150]}")
        logger.info("fetch_pages: %s -> HTTP %s (final: %s)", base_url, r.status_code, r.url)
        if r.status_code == 403:
            raise RuntimeError(f"Le site {base_url} refuse l'accès (HTTP 403) — protection anti-robot probable.")
        if r.status_code == 404:
            raise RuntimeError(f"Page d'accueil introuvable (HTTP 404) sur {base_url} — vérifiez l'URL publique.")
        if r.status_code >= 500:
            raise RuntimeError(f"Le serveur de {base_url} est en erreur (HTTP {r.status_code}).")
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} en récupérant {base_url}.")
        home_html = r.text
        if "<html" not in home_html.lower()[:3000] and "html" not in r.headers.get("content-type", "").lower():
            raise RuntimeError(f"Aucun contenu HTML exploitable sur {base_url}.")
        # 2. Suivre les redirects : l'URL finale devient la base de crawl (www / sans www)
        base_url = normalize_base_url(str(r.url))
        host = urlparse(base_url).netloc

        urls: List[str] = []
        seen = set()

        def add(u: str):
            u = urljoin(base_url + "/", (u or "").strip())
            low = u.lower()
            if low.startswith(("mailto:", "tel:", "javascript:", "ftp:")):
                return
            u = u.split("#")[0].split("?")[0].rstrip("/")
            if not u or u in seen:
                return
            p = urlparse(u)
            if p.scheme not in ("http", "https") or not _same_site(p.netloc, host):
                return
            path = p.path.lower()
            if path.endswith(STATIC_EXT) or any(tok in path for tok in SKIP_PATH_TOKENS):
                return
            seen.add(u)
            urls.append(u)

        add(base_url)
        used_sitemap = False

        # 3. robots.txt -> sitemaps déclarés
        sitemap_candidates: List[str] = []
        try:
            rob = await cli.get(f"{base_url}/robots.txt")
            if rob.status_code == 200:
                for line in rob.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_candidates.append(line.split(":", 1)[1].strip())
        except Exception:
            pass
        sitemap_candidates.append(f"{base_url}/sitemap.xml")

        # 4. Sitemaps (gestion des index de sitemaps, ex. Wix)
        async def load_sitemap(sm_url: str, depth: int = 0):
            nonlocal used_sitemap
            if depth > 1 or len(urls) >= max_pages * 3:
                return
            try:
                resp = await cli.get(sm_url)
                if resp.status_code != 200:
                    return
                sm_soup = BeautifulSoup(resp.text, "xml")
                if sm_soup.find("sitemapindex"):
                    for loc in sm_soup.find_all("loc")[:6]:
                        await load_sitemap(loc.text.strip(), depth + 1)
                else:
                    locs = [loc.text.strip() for loc in sm_soup.find_all("loc")]
                    if locs:
                        used_sitemap = True
                    for loc in locs[:200]:
                        add(loc)
            except Exception:
                pass

        for sm in list(dict.fromkeys(sitemap_candidates))[:3]:
            if len(urls) >= max_pages * 3:
                break
            await load_sitemap(sm)

        # 5. Fallback : crawl des liens internes de la homepage
        if len(urls) < 2:
            for a in BeautifulSoup(home_html, "lxml").find_all("a", href=True):
                add(a["href"])
                if len(urls) >= 50:
                    break

        if diag is not None:
            diag["method"] = "sitemap" if used_sitemap else "crawl"
            diag["note"] = None if used_sitemap else "Sitemap non disponible — analyse basée sur le crawl du site."
            diag["base_url"] = base_url
            diag["urls_found"] = len(urls)

        # Prioritise homepage + informative pages
        def prio(u: str) -> int:
            if u == base_url:
                return 0
            path = urlparse(u).path.lower()
            for i, pat in enumerate(PRIORITY_PATTERNS):
                if pat in path:
                    return 1 + i
            return 100

        selected = sorted(urls, key=prio)[:max_pages]

        pages: List[dict] = []
        # Homepage : réutiliser le HTML déjà téléchargé (évite le rate-limit Wix 429)
        home_soup = BeautifulSoup(home_html, "lxml")
        pages.append({"url": base_url, "html": home_html, "soup": home_soup, "text": _page_text(home_soup)})
        selected = [u for u in selected if u != base_url]
        sem = asyncio.Semaphore(2)

        async def fetch_one(u: str):
            async with sem:
                try:
                    rr = await cli.get(u)
                    for delay in (3, 6):
                        if rr.status_code != 429:
                            break
                        retry_after = rr.headers.get("retry-after")
                        try:
                            delay = min(10, int(retry_after)) if retry_after else delay
                        except ValueError:
                            pass
                        await asyncio.sleep(delay)
                        rr = await cli.get(u)
                    if rr.status_code >= 400:
                        logger.info("fetch_pages: %s -> HTTP %s (ignoré)", u, rr.status_code)
                        return
                    await asyncio.sleep(0.4)
                    html = rr.text
                    soup = BeautifulSoup(html, "lxml")
                    text = _page_text(soup)
                    words = len(text.split())
                    # SPA fallback : rendered HTML via Playwright
                    if words < 80 and (soup.find(id=re.compile(r"^(root|app|__next)$")) is not None or "react" in html.lower()[:5000]):
                        rendered = await _render_html(u)
                        if rendered:
                            html = rendered
                            soup = BeautifulSoup(html, "lxml")
                            text = _page_text(soup)
                    pages.append({"url": u, "html": html, "soup": soup, "text": text})
                except Exception as exc:
                    logger.info("fetch failed %s: %s", u, exc)

        await asyncio.gather(*[fetch_one(u) for u in selected])
        # Homepage first
        pages.sort(key=lambda p: 0 if p["url"] == base_url else 1)
        return pages


# ---------------------------------------------------------------------------
# Deterministic analyses
# ---------------------------------------------------------------------------
def _extract_jsonld(pages: List[dict]) -> List[dict]:
    blocks: List[dict] = []
    for p in pages:
        for tag in p["soup"].find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict):
                    if "@graph" in it and isinstance(it["@graph"], list):
                        blocks.extend([g for g in it["@graph"] if isinstance(g, dict)])
                    else:
                        blocks.append(it)
    return blocks


def _types(blocks: List[dict]) -> set:
    found = set()
    for b in blocks:
        t = b.get("@type")
        if isinstance(t, list):
            found.update(str(x) for x in t)
        elif t:
            found.add(str(t))
    return found


def analyze_schema(pages: List[dict]) -> dict:
    blocks = _extract_jsonld(pages)
    types = _types(blocks)
    score = 0
    checks = []

    def check(label, ok, pts):
        nonlocal score
        if ok:
            score += pts
        checks.append({"label": label, "ok": bool(ok), "points": pts})

    org = types & {"Organization", "LocalBusiness", "RealEstateAgent", "ProfessionalService", "Corporation"}
    check("Organization / LocalBusiness", bool(org), 25)
    check("WebSite", "WebSite" in types, 10)
    check("FAQPage", "FAQPage" in types, 20)
    check("Article / BlogPosting", bool(types & {"Article", "BlogPosting", "NewsArticle"}), 15)
    check("BreadcrumbList", "BreadcrumbList" in types, 10)
    check("Service / Product / Offer", bool(types & {"Service", "Product", "Offer"}), 10)
    has_sameas = any(b.get("sameAs") for b in blocks)
    check("Liens sameAs (profils officiels)", has_sameas, 10)
    return {"score": min(100, score), "found_types": sorted(types), "checks": checks, "blocks_count": len(blocks)}


def analyze_knowledge_graph(pages: List[dict]) -> dict:
    blocks = _extract_jsonld(pages)
    sameas: List[str] = []
    for b in blocks:
        sa = b.get("sameAs")
        if isinstance(sa, str):
            sameas.append(sa)
        elif isinstance(sa, list):
            sameas.extend(str(x) for x in sa)
    all_links = set(sameas)
    # Social/authority links even outside schema
    for p in pages:
        for a in p["soup"].find_all("a", href=True):
            h = a["href"]
            if any(d in h for d in ["wikipedia.org", "wikidata.org", "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com"]):
                all_links.add(h)
    score = 0
    signals = []
    if any("wikipedia.org" in l or "wikidata.org" in l for l in all_links):
        score += 30
        signals.append("Présence Wikipedia/Wikidata détectée")
    if any("linkedin.com" in l for l in all_links):
        score += 15
        signals.append("Profil LinkedIn lié")
    socials = sum(1 for d in ["facebook.com", "instagram.com", "youtube.com", "x.com", "twitter.com"] if any(d in l for l in all_links))
    score += min(20, socials * 7)
    if socials:
        signals.append(f"{socials} réseau(x) social(aux) lié(s)")
    has_org = bool(_types(blocks) & {"Organization", "LocalBusiness", "RealEstateAgent", "ProfessionalService"})
    if has_org:
        score += 15
        signals.append("Entité Organization déclarée en JSON-LD")
        org_blocks = [b for b in blocks if str(b.get("@type")) in ("Organization", "LocalBusiness", "RealEstateAgent", "ProfessionalService")]
        if any(b.get("logo") for b in org_blocks):
            score += 10
            signals.append("Logo d'entité déclaré")
        if any(b.get("address") for b in org_blocks):
            score += 10
            signals.append("Adresse structurée déclarée")
    return {"score": min(100, score), "signals": signals, "sameas_count": len(sameas)}


def analyze_readability(pages: List[dict]) -> dict:
    if not pages:
        return {"score": 0, "details": []}
    per_page = []
    for p in pages:
        soup = p["soup"]
        h1s = soup.find_all("h1")
        h2s = soup.find_all("h2")
        words = len(p["text"].split())
        paras = [x.get_text(strip=True) for x in soup.find_all("p") if x.get_text(strip=True)]
        avg_para = (sum(len(x.split()) for x in paras) / len(paras)) if paras else 0
        lists = len(soup.find_all(["ul", "ol"]))
        q_headings = sum(1 for h in h2s + soup.find_all("h3") if "?" in h.get_text())
        s = 0
        s += 15 if len(h1s) == 1 else (5 if len(h1s) > 1 else 0)
        s += 20 if (len(h2s) >= 2 and words and words / max(1, len(h2s)) < 400) else (10 if len(h2s) >= 1 else 0)
        s += 15 if lists >= 1 else 0
        s += 20 if 0 < avg_para <= 80 else (10 if 0 < avg_para <= 120 else 0)
        s += 10 if q_headings >= 1 else 0
        s += 20 if words >= 300 else (10 if words >= 150 else 0)
        per_page.append({"url": p["url"], "score": min(100, s), "words": words, "h2": len(h2s), "lists": lists, "question_headings": q_headings})
    avg = round(sum(x["score"] for x in per_page) / len(per_page))
    return {"score": avg, "details": per_page}


DATE_RE = re.compile(r"20(1\d|2\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")


def analyze_freshness(pages: List[dict]) -> dict:
    dates = []
    blocks = _extract_jsonld(pages)
    for b in blocks:
        for k in ("dateModified", "datePublished"):
            v = b.get(k)
            if isinstance(v, str) and DATE_RE.search(v):
                dates.append(DATE_RE.search(v).group(0))
    for p in pages:
        for m in p["soup"].find_all("meta"):
            v = m.get("content") or ""
            if ("date" in str(m.get("property", "")).lower() or "date" in str(m.get("name", "")).lower()) and DATE_RE.search(v):
                dates.append(DATE_RE.search(v).group(0))
    if not dates:
        return {"score": 25, "latest_date": None, "note": "Aucune date de publication/modification détectée — les IA ne peuvent pas évaluer la fraîcheur."}
    latest = max(dates)
    try:
        dt = datetime.strptime(latest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt).days
    except Exception:
        age_days = 999
    if age_days <= 90:
        score = 95
    elif age_days <= 180:
        score = 75
    elif age_days <= 365:
        score = 55
    else:
        score = 35
    return {"score": score, "latest_date": latest, "age_days": age_days, "note": None}


def analyze_eeat_signals(pages: List[dict], base_url: str) -> dict:
    if not pages:
        return {"score": 0, "signals": [], "missing": []}
    all_text = " ".join(p["text"] for p in pages).lower()
    all_urls = " ".join(p["url"] for p in pages).lower()
    host = urlparse(base_url).netloc
    signals, missing = [], []
    score = 0
    if base_url.startswith("https"):
        score += 10
        signals.append("HTTPS actif")
    if re.search(r"(à propos|a propos|qui sommes|about|notre équipe|notre histoire)", all_text) or re.search(r"(about|a-propos|qui-sommes)", all_urls):
        score += 15
        signals.append("Page/section « À propos » détectée")
    else:
        missing.append("Page « À propos » (histoire, équipe, expertise)")
    if re.search(r"(contact|nous contacter)", all_text + all_urls):
        score += 10
        signals.append("Informations de contact présentes")
    else:
        missing.append("Page contact claire")
    if re.search(r"(\+41|\+33|0\d[\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}|\d{3}[\s.]\d{3}[\s.]\d{2}[\s.]\d{2})", all_text):
        score += 10
        signals.append("Numéro de téléphone visible (signal de confiance)")
    else:
        missing.append("Numéro de téléphone visible")
    if re.search(r"(par [A-ZÀ-Ü][a-zà-ü]+|auteur|rédigé par|written by|author)", " ".join(p["text"] for p in pages)):
        score += 15
        signals.append("Attribution d'auteur détectée")
    else:
        missing.append("Attribution d'auteur sur les contenus (byline)")
    ext_domains = set()
    for p in pages:
        for a in p["soup"].find_all("a", href=True):
            n = urlparse(urljoin(base_url, a["href"])).netloc
            if n and n != host and not any(s in n for s in ["facebook", "instagram", "linkedin", "twitter", "x.com", "youtube"]):
                ext_domains.add(n)
    if len(ext_domains) >= 2:
        score += 10
        signals.append(f"Citations de sources externes ({len(ext_domains)} domaines)")
    else:
        missing.append("Citations de sources externes fiables")
    if re.search(r"(mentions légales|politique de confidentialité|cgv|conditions générales|privacy)", all_text + all_urls):
        score += 10
        signals.append("Mentions légales / confidentialité présentes")
    else:
        missing.append("Mentions légales et politique de confidentialité")
    if re.search(r"(avis|témoignage|review|note de|étoiles|clients satisfaits)", all_text):
        score += 10
        signals.append("Avis / témoignages clients détectés")
    else:
        missing.append("Avis et témoignages clients visibles")
    if re.search(r"(certifi|agréé|membre de|partenaire officiel|diplôm|accrédit)", all_text):
        score += 10
        signals.append("Certifications / affiliations mentionnées")
    return {"score": min(100, score), "signals": signals, "missing": missing}


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------
def _repair_json(s: str) -> str:
    """Répare un JSON tronqué : ferme les chaînes/brackets ouverts, retire les fragments incomplets."""
    stack = []
    in_str = esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]" and stack:
                stack.pop()
    if in_str:
        s += '"'
    s = re.sub(r"[,\s]+$", "", s)
    s = re.sub(r',?\s*"[^"]*"\s*:\s*$', "", s)
    s = re.sub(r',\s*"[^"]*"\s*$', "", s)
    s += "".join("}" if c == "{" else "]" for c in reversed(stack))
    return s


def _parse_llm_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*", cleaned, re.DOTALL)
    if not m:
        raise ValueError("Aucun JSON dans la réponse IA")
    candidate = m.group(0)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(_repair_json(candidate))


async def llm_qualitative_analysis(site: dict, pages: List[dict], det: dict, llm_key: str) -> dict:
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    excerpts = []
    for p in pages[:3]:
        excerpts.append(f"URL: {p['url']}\n{p['text'][:1600]}")
    prompt = f"""Tu es un expert en GEO (Generative Engine Optimization) — l'optimisation de la visibilité dans les moteurs de réponse IA (ChatGPT, Perplexity, Gemini, etc.).

SITE ANALYSÉ : {site.get('name')} — {site.get('base_url')}

EXTRAITS DE CONTENU :
{chr(10).join(excerpts)}

SIGNAUX TECHNIQUES DÉJÀ MESURÉS :
- Schema.org : {det['schema']['score']}/100 (types trouvés : {', '.join(det['schema']['found_types']) or 'aucun'})
- Knowledge Graph : {det['kg']['score']}/100 ({'; '.join(det['kg']['signals']) or 'aucun signal'})
- Lisibilité IA : {det['readability']['score']}/100
- Fraîcheur : {det['freshness']['score']}/100
- Signaux EEAT détectés : {'; '.join(det['eeat']['signals']) or 'aucun'}
- Signaux EEAT manquants : {'; '.join(det['eeat']['missing']) or 'aucun'}

Réponds en JSON STRICT (aucun texte hors JSON) :
{{
  "business_summary": "résumé de l'activité en 1-2 phrases",
  "activity": "activité principale en 3-5 mots",
  "location": "ville/région principale ou 'non précisé'",
  "entity_score": <0-100, clarté de l'entité : la marque, son activité, sa zone sont-elles évidentes pour une IA ?>,
  "semantic_seo_score": <0-100, couverture thématique, réponses aux questions des utilisateurs, profondeur>,
  "eeat_score": <0-100, en tenant compte des signaux mesurés ci-dessus>,
  "test_queries": ["4 requêtes en français qu'un utilisateur poserait à ChatGPT et pour lesquelles ce site DEVRAIT être recommandé (ex: 'Quelle entreprise recommandes-tu pour X à Y ?')"],
  "why_visible": ["2-4 raisons pour lesquelles ce site PEUT apparaître dans les réponses IA"],
  "why_not_visible": ["2-5 raisons concrètes pour lesquelles ce site risque de NE PAS être cité par les IA"],
  "priority_actions": [
    {{"action": "titre court", "details": "explication concrète et actionnable", "impact": "élevé|moyen|faible", "effort": "faible|moyen|élevé", "estimated_gain": "+X pts sur [score concerné]", "category": "schema|eeat|contenu|entité|technique"}}
  ],
  "summary": "diagnostic global en 2-3 phrases : pourquoi ce site est ou n'est pas visible dans les IA et le potentiel de gain"
}}
Donne 4 à 6 priority_actions triées par impact décroissant."""
    chat = LlmChat(
        api_key=llm_key,
        session_id=f"aivis-{site.get('id')}",
        system_message="Tu es un expert GEO/SEO. Tu réponds uniquement en JSON strict valide.",
    ).with_model("anthropic", "claude-sonnet-4-5-20250929").with_params(max_tokens=8000)
    resp = await chat.send_message(UserMessage(text=prompt))
    return _parse_llm_json(resp if isinstance(resp, str) else str(resp))


def _brand_tokens(site: dict) -> List[str]:
    tokens = set()
    name = (site.get("name") or "").lower()
    label = (site.get("label") or "").lower()
    for t in [name, label]:
        if t and len(t) >= 3:
            tokens.add(t)
    host = urlparse(site.get("base_url") or "").netloc.lower()
    if host:
        core = host.replace("www.", "").split(".")[0]
        if len(core) >= 3:
            tokens.add(core)
        tokens.add(host.replace("www.", ""))
    return list(tokens)


async def run_citation_tests(site: dict, queries: List[str], llm_key: str) -> dict:
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    brand = _brand_tokens(site)
    sem = asyncio.Semaphore(4)
    results = {m["key"]: {"tests": 0, "mentions": 0, "errors": 0} for m in MEASURED_MODELS}

    async def one(model_cfg: dict, query: str):
        async with sem:
            try:
                chat = LlmChat(
                    api_key=llm_key,
                    session_id=f"cit-{model_cfg['key']}-{abs(hash(query)) % 99999}",
                    system_message="Tu es un assistant IA. Réponds de manière concise (max 150 mots) en recommandant des entreprises, marques ou sites web concrets et nommés quand la question s'y prête.",
                ).with_model(model_cfg["provider"], model_cfg["model"])
                resp = await asyncio.wait_for(chat.send_message(UserMessage(text=query)), timeout=60)
                text = (resp if isinstance(resp, str) else str(resp)).lower()
                results[model_cfg["key"]]["tests"] += 1
                if any(tok in text for tok in brand):
                    results[model_cfg["key"]]["mentions"] += 1
            except Exception as exc:
                results[model_cfg["key"]]["errors"] += 1
                logger.info("Citation test failed (%s): %s", model_cfg["key"], exc)

    tasks = [one(m, q) for m in MEASURED_MODELS for q in queries[:4]]
    await asyncio.gather(*tasks)

    models_out = []
    rates = {}
    for m in MEASURED_MODELS:
        r = results[m["key"]]
        rate = (r["mentions"] / r["tests"]) if r["tests"] else None
        rates[m["key"]] = rate
        models_out.append({
            "key": m["key"], "name": m["name"], "measured": True,
            "visible": bool(rate and rate > 0), "mention_rate": round(rate * 100) if rate is not None else None,
            "tests": r["tests"], "mentions": r["mentions"], "unavailable": r["tests"] == 0,
        })
    valid = [v for v in rates.values() if v is not None]
    avg = sum(valid) / len(valid) if valid else 0
    for em in ESTIMATED_MODELS:
        basis = [rates[b] for b in em["basis"] if rates.get(b) is not None]
        est = sum(basis) / len(basis) if basis else avg
        models_out.append({
            "key": em["key"], "name": em["name"], "measured": False,
            "visible": est > 0, "mention_rate": round(est * 100),
            "tests": 0, "mentions": 0, "unavailable": False,
        })
    return {"models": models_out, "citation_score": round(avg * 100), "brand_tokens": brand}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def _clamp(v, lo=0, hi=100):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except Exception:
        return 0


async def run_ai_visibility_analysis(site: dict, llm_key: str) -> dict:
    base_url = site.get("base_url") or ""
    fetch_diag: dict = {}
    pages = await fetch_pages(base_url, diag=fetch_diag)
    if not pages:
        raise RuntimeError(f"Impossible de récupérer les pages de {base_url or 'ce site'} — vérifiez l'URL publique du site.")

    schema = analyze_schema(pages)
    kg = analyze_knowledge_graph(pages)
    readability = analyze_readability(pages)
    freshness = analyze_freshness(pages)
    eeat_sig = analyze_eeat_signals(pages, base_url)
    det = {"schema": schema, "kg": kg, "readability": readability, "freshness": freshness, "eeat": eeat_sig}

    try:
        llm = await llm_qualitative_analysis(site, pages, det, llm_key)
    except Exception as exc:
        logger.exception("LLM qualitative analysis failed")
        raise RuntimeError(f"L'analyse IA a échoué : {exc}")

    queries = llm.get("test_queries") or [f"Quelle entreprise recommandes-tu pour {llm.get('activity', 'ce service')} ?"]
    citation = await run_citation_tests(site, queries, llm_key)

    eeat_final = _clamp((eeat_sig["score"] + _clamp(llm.get("eeat_score", eeat_sig["score"]))) / 2)
    scores = {
        "ai_citation_score": _clamp(citation["citation_score"]),
        "eeat_score": eeat_final,
        "schema_score": _clamp(schema["score"]),
        "entity_score": _clamp(llm.get("entity_score", 50)),
        "semantic_seo_score": _clamp(llm.get("semantic_seo_score", 50)),
        "ai_readability_score": _clamp(readability["score"]),
        "knowledge_graph_score": _clamp(kg["score"]),
        "freshness_score": _clamp(freshness["score"]),
    }
    scores["ai_trust_score"] = _clamp(
        0.4 * scores["eeat_score"] + 0.25 * scores["schema_score"] + 0.2 * scores["ai_citation_score"] + 0.15 * scores["knowledge_graph_score"]
    )
    global_score = _clamp(
        0.22 * scores["ai_citation_score"] + 0.13 * scores["eeat_score"] + 0.12 * scores["schema_score"]
        + 0.11 * scores["semantic_seo_score"] + 0.10 * scores["entity_score"] + 0.10 * scores["ai_readability_score"]
        + 0.08 * scores["knowledge_graph_score"] + 0.07 * scores["freshness_score"] + 0.07 * scores["ai_trust_score"]
    )

    return {
        "global_score": global_score,
        "scores": scores,
        "models": citation["models"],
        "queries_tested": queries[:4],
        "business": {
            "summary": llm.get("business_summary"),
            "activity": llm.get("activity"),
            "location": llm.get("location"),
        },
        "explanations": {
            "summary": llm.get("summary"),
            "why_visible": llm.get("why_visible") or [],
            "why_not_visible": llm.get("why_not_visible") or [],
        },
        "priority_actions": llm.get("priority_actions") or [],
        "technical": {
            "schema": {k: v for k, v in schema.items() if k != "blocks_count"},
            "knowledge_graph": kg,
            "readability": readability,
            "freshness": freshness,
            "eeat_signals": eeat_sig,
        },
        "pages_analyzed": [p["url"] for p in pages],
        "fetch_diagnostic": fetch_diag,
    }
