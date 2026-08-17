# LOGI SEO Booster — Product Requirements Document

## Original problem statement
Application web "LOGI SEO Booster" compatible avec les sites Wix Logirent et Logitime,
permettant d'analyser, générer, optimiser et publier du contenu SEO afin d'améliorer
le classement Google et la visibilité dans les IA (ChatGPT, Gemini, Perplexity, Google AI Overviews).

## User Personas
- **Propriétaire / dirigeant** (cible primaire) : utilise l'outil pour Logirent et Logitime,
  veut un score SEO clair, des contenus prêts à valider, aucune publication automatique.
- **Rédacteur / content manager** (cible secondaire) : génère et relit les contenus avant publication.

## User Choices (from kickoff)
- Stack : React + FastAPI + MongoDB
- IA : Claude Sonnet 4.5 (Anthropic) via Emergent Universal Key
- Auth : JWT custom (email/password)
- Wix : clé API simple (pas d'OAuth) au MVP, multi-sites
- GSC/GA : mockés pour le MVP, architecture extensible
- Langue : Français

## Architecture
- Backend FastAPI sur `/api`, MongoDB via Motor, JWT auth (bcrypt), httpx pour Wix API.
- Frontend React (CRA), React Router, Tailwind, Shadcn UI, Recharts, Sonner, Lucide.
- Design : Swiss & High-Contrast, bleu #002FA7, fonts Cabinet Grotesk + IBM Plex Sans.
- Génération IA : `emergentintegrations.llm.chat.LlmChat` avec `claude-sonnet-4-5-20250929`.

## Implemented (2026-02-07 — MVP + Phase 2 + Phase 2.5)
- [x] Auth JWT (register, login, /me)
- [x] **Multi-plateformes : Wix API + URL publique (Emergent / WordPress / custom)**
- [x] **Bouton "Ajout rapide" : connecte logirent.ch + logitime.ch en 1 clic**
- [x] **Crawler HTTP réel (sitemap.xml + BFS) sur les vraies URLs publiques**
- [x] **Détection automatique des SPA (sites client-rendered) — issue SEO critique remontée**
- [x] Multi-sites isolés par utilisateur
- [x] Audit SEO automatique sur les vraies données scrapées
- [x] Génération IA Claude Sonnet 4.5 (article, page locale, FAQ, service)
- [x] Recherche IA de mots-clés (clustering par intention)
- [x] Liste de mots-clés cibles sauvegardés
- [x] Optimiseur de pages réelles (comparaison avant/après)
- [x] Application en 1 clic d'une optimisation → brouillon prêt à publier (idempotent)
- [x] Drafts CRUD + versions + rollback
- [x] Publication contextualisée : Wix Blog API (sites Wix) / "Ready for export" (URL publique)
- [x] Historique des publications
- [x] Performance (mock GSC) avec bandeau d'avertissement
- [x] Dashboard avec stats et accès rapides
- [x] UI complète FR, Swiss design, 9 pages
- [x] Export ZIP (HTML SEO + JSON + README) pour upload FTP manuel
- [x] **Publication GitHub** (2026-02-07) : push direct des fichiers HTML/JSON dans le repo du site via PAT — pour sites React/Vite hébergés sur Vercel/Netlify. Endpoints `/api/sites/{id}/test-github` et `/api/drafts/{id}/publish-github`. Dialogue de config par site avec test de connexion.
- [x] **Google Search Console + Analytics (OAuth)** (2026-02-07) : OAuth 2.0 web-server flow avec refresh tokens, scopes `webmasters.readonly` + `analytics.readonly`. Endpoints `/api/google/login`, `/api/google/callback`, `/api/google/status`, `/api/google/disconnect`, `/api/google/gsc-sites`, `/api/sites/{id}/google-settings`, `/api/sites/{id}/performance-real`. Page Performance complètement refondue : sélection propriété GSC depuis liste + GA4 Property ID, affichage temps réel des impressions/clics/CTR/position + sessions/utilisateurs/bounce/conversions. Fallback automatique sur mock si pas connecté.
- [x] **Suivi de classement par mot-clé** (2026-02-07) : snapshots quotidiens auto à 04:00 UTC via APScheduler. Endpoints `/api/sites/{id}/rank-snapshot` (manuel) et `/api/sites/{id}/rank-tracking` (séries temporelles). Bouton "Capturer maintenant" + tableau Δ position vs début dans la page Performance.
- [x] **Auto-update sitemap.xml sur push GitHub** (2026-02-07) : lors d'un `/drafts/{id}/publish-github`, le sitemap est lu, mis à jour (lastmod) ou créé en y ajoutant l'URL de la nouvelle page. Recherche le sitemap dans `folder/sitemap.xml`, `public/sitemap.xml` puis `sitemap.xml`.
- [x] **Chiffrement Fernet at-rest** (2026-02-07) : tous les tokens sensibles (`wix_api_key`, `ftp_password`, `vps_api_token`, `github_token`, `google_oauth.refresh_token` + `access_token`) chiffrés via Fernet avant insertion en MongoDB. Préfixe `enc::` pour permettre la migration progressive (legacy plaintext toujours lisible). `ENCRYPTION_KEY` dans `backend/.env`.
- [x] **Détection de doublons inter-pages** (2026-02-07) : endpoint `POST /api/sites/{id}/duplicate-scan` qui calcule la similarité Jaccard sur bigrams normalisés (titre + meta + body) entre toutes les pages du site + détecte les titres H1 et meta descriptions exactement identiques. Bouton "Détecter doublons" sur la page Audit avec panneau de résultats (paires similaires colorées par sévérité, groupes de titres/metas dupliqués, recommandations IA).
- [x] **Génération asynchrone (jobs)** (2026-02-07) : nouveau endpoint `POST /api/content/generate-async` + `GET /api/content/jobs/{id}` pour bypasser le timeout 60s de l'ingress K8s. Frontend Generator.jsx fait du polling toutes les 3s avec toast "Génération en cours…". Plus de timeout possible.
- [x] **Auto-publish GitHub depuis le Générateur** (2026-02-07) : checkbox "⚡ Publier automatiquement sur GitHub après génération" dans la page Générateur. Quand cochée + site avec GitHub configuré → la génération auto-push le brouillon. Désactivée + grisée si GitHub pas configuré.

## Pivot produit (2026-06) — "Agent Marketing IA d'entreprise"
Le produit pivote d'un outil SEO vers un Directeur Marketing IA autonome.
Nom final : EN RÉFLEXION (l'utilisateur veut analyser 50-100 propositions : domaines .com/.ai/.io,
réseaux sociaux, marques CH/UE/WIPO/US, prononciation, mémorisation). "Vela" DÉCONSEILLÉ
(conflits Vela Systems Inc. ~19 marques logicielles + Vela Software Group). Garder
"LOGI SEO Booster" en placeholder jusqu'à validation explicite.
Critère de décision produit : "Est-ce que cela nous rapproche du meilleur Directeur Marketing IA du marché ?"
Préférence : 20 fonctionnalités exceptionnelles plutôt que 100 moyennes.

- [x] **AI Visibility Center** (2026-06-12) : module GEO complet, remplace le simple "GEO Score".
  Backend `/app/backend/ai_visibility.py` (module séparé) + routes dans server.py :
  `POST /api/sites/{id}/ai-visibility` (job async, poll via /content/jobs/{job_id}),
  `GET .../ai-visibility/latest`, `GET .../ai-visibility/history`. Collection `ai_visibility_reports`.
  Pipeline : crawl pages clés (sitemap/BFS + fallback Playwright SPA) → analyses déterministes
  (Schema.org JSON-LD, Knowledge Graph/sameAs, lisibilité IA/chunking, fraîcheur, signaux EEAT)
  → analyse LLM Claude (entité, SEO sémantique, requêtes de test, explications, actions priorisées
  avec gains estimés) → **tests de citation RÉELS** sur ChatGPT (gpt-4o), Claude et Gemini
  (12 requêtes) ; Perplexity/Copilot/Mistral/DeepSeek estimés (badgés "Estimé").
  10 scores : AI Visibility (global), AI Citation, AI Trust, EEAT, Entity, Schema,
  Knowledge Graph, SEO Sémantique, Lisibilité IA, Fraîcheur.
  Frontend : page `/ai-visibility` (`AIVisibility.jsx`), nav "AI Visibility" (icône Radar).
  Testé e2e sur logirent.ch : score 43/100, diagnostic + 6 actions pertinentes.

## Backlog Sprint 1 (ordre validé par l'utilisateur, 2026-06)
- [x] 🥈 **Keyword Intelligence Engine 2.0** (2026-06-12) : backend `/app/backend/keyword_intelligence.py`
  (réutilise `ai_visibility.fetch_pages`). 2 appels LLM : (1) Business Profile (activité, produits,
  cibles, zones, positionnement, concurrents — stocké dans collection `business_profiles`, brique
  de l'AI Business Analyzer), (2) Intelligence complète : clusters scorés (potentiel 0-100,
  difficulté, rentabilité, volume, quick_win), quick wins, top opportunités, plan de contenu
  (types compatibles générateur), pages locales manquantes, concurrents + comment les dépasser.
  Routes : `POST /api/sites/{id}/keyword-intelligence` (job async), `GET .../latest`.
  Collection `keyword_intelligence_reports`. Frontend : page `/keyword-intelligence`
  (`KeywordIntelligence.jsx`), nav "Keyword Intelligence" (icône BrainCircuit).
  Boutons : ⭐ sauvegarder mot-clé (→ /keywords/saved), "Générer ce contenu" en 1 clic
  (→ /content/generate-async avec polling + toast). Testé e2e sur logirent.ch :
  6 clusters, 8 quick wins, 10 contenus, 5 pages locales, 6 concurrents — l'IA a détecté
  le désalignement stratégique B2C/B2B des mots-clés suivis.
- [x] Identifiants démo affichés sur la page de connexion + bouton "Remplir automatiquement" (2026-06-12).
- [x] 🥉 **AI Business Analyzer** (2026-06-12) : backend `/app/backend/business_analyzer.py`.
  Analyse "directeur marketing" : identité, produits/services, segments cibles (besoins + messages),
  zones, positionnement, value props, 6 concurrents (forces/faiblesses/comment les dépasser),
  SWOT complet, 5 priorités marketing. Routes : `POST /api/sites/{id}/business-analyzer` (job async),
  `GET/PUT /api/sites/{id}/business-profile` (profil éditable par l'utilisateur, flag `edited`,
  merge partiel). Le profil stocké (`business_profiles`) est RÉUTILISÉ par Keyword Intelligence
  (skip du crawl + de l'appel LLM profil si un profil existe — corrections utilisateur prioritaires).
  Frontend : page `/business` (`BusinessAnalyzer.jsx`), nav "Business Analyzer" (icône Building2),
  mode édition (activité, description, positionnement, zones, modèle). Testé e2e sur logirent.ch.
- [x] **Menu Aide** (2026-06-12) : page `/aide` (`Aide.jsx`) — boucle Connecter→Analyser→Générer→
  Publier→Mesurer, parcours 5 étapes avec liens, 13 modules expliqués, 7 FAQ, lien Guide PDF.
- [x] **Analyse concurrentielle automatique** (2026-06-13) : backend `/app/backend/competitor_analysis.py`.
  Utilise les concurrents du profil business (corrigés par l'utilisateur : Myrentcar, Renthub,
  FleetGuru, RentSyst, HQ Rental Software, RENTALL pour Logirent) + snapshot httpx des sites
  concurrents (si domaine connu). LLM → paysage concurrentiel, avantages, par-concurrent
  (mots-clés dominés, forces/faiblesses, comment le battre), 10 content_gaps (génération 1 clic
  via generate-async), plan de bataille 7 actions. Routes : `POST /api/sites/{id}/competitor-analysis`
  (job async), `GET .../latest`. Collection `competitor_analysis_reports`. Page `/competitors`
  (`Competitors.jsx`), nav "Concurrents" (Swords). Testé e2e sur Logirent.
- [x] **Suggestions de sujets Générateur** (2026-06-13) : `GET /api/sites/{id}/content-suggestions?content_type=X`
  → sujets + villes ciblées auto (source 1 : rapport KI filtré par type + pages locales manquantes ;
  source 2 : LLM via profil business si <4 résultats). Bouton "💡 Proposer des sujets" dans Generator.jsx,
  clic = remplit sujet+ville+mots-clés. Testé e2e.
- [x] **Pré-remplissage intelligent page Mots-clés** (2026-06-13) : `GET /api/sites/{id}/keyword-prefill`
  → chips cliquables : thématiques (clusters KI + produits), zones (villes/régions/PAYS), concurrents.
  Champ renommé "Ville / région / pays". Édition des vrais concurrents ajoutée au Business Analyzer
  (textarea un par ligne, merge avec détails existants). Testé e2e.
- [x] **Corrections production** (2026-06-13) : badge "Made with Emergent" + tracking retirés de
  index.html (titre : "LOGI SEO Booster — Agent Marketing IA") ; bug JSON tronqué LLM corrigé
  (max_tokens 8k-16k + _repair_json + retry×2, validé testing agent iteration_5) ;
  identifiants démo affichés sur /login (à retirer/conditionner pour la prod — EN ATTENTE de décision).

## Déploiement VPS (2026-06-13) — EN PRODUCTION ✅
- App déployée sur **https://seo.logitrak.ch** (VPS Ubuntu 83.228.207.198, utilisateur ubuntu).
- Dossier `/opt/logi-seo-booster`, projet Docker `logiseo` (logiseo_frontend:3105, logiseo_backend:8105,
  logiseo_mongodb non exposé), réseau `logiseo_network`, volume `logiseo_mongo_data`,
  vhost `/etc/nginx/sites-available/logiseo.conf`, SSL certbot. Repo GitHub :
  janouinfo-design/seo.logitrak.ch. Isolation stricte des autres apps (logitrak, navixy, protrader, logibus).
- Clé IA sur VPS : clé Anthropic personnelle dans EMERGENT_LLM_KEY (testée, fonctionne avec
  emergentintegrations). Tests citation ChatGPT/Gemini indisponibles sur VPS (clé Anthropic seule).
- Pièges connus : "Save to GitHub" exclut .env* (template = env.production.example) et yarn.lock
  (Dockerfile frontend tolère l'absence) ; requirements.txt contient litellm en URL directe
  (filtré par grep dans backend/Dockerfile).
- Mise à jour VPS : Save to GitHub → `git pull && docker compose -p logiseo build && docker compose -p logiseo up -d`.
- [x] **Repositionnement UI "Agent Marketing IA"** (2026-06-13, testé 13/13) : Dashboard réécrit en
  « Vos 4 agents marketing IA » (Agent SEO / GEO / Contenu / Social) — endpoint `GET /api/agents/overview`
  (agrège audits, ai_visibility, drafts, quota, réseaux sociaux + chutes de position GSC).
  Frontend `Dashboard.jsx` réécrit (4 cartes agents + badges statut + bandeau notifications).
- [x] **Workflow Builder v1** (2026-06-13, testé 13/13) : règles SI→ALORS. Déclencheurs :
  rank_drop (seuil positions), ai_visibility_drop (seuil points), no_publication (jours).
  Actions : notify (notifications in-app), generate_draft (Claude, en arrière-plan sur run manuel
  pour éviter le timeout ingress 60s), run_audit. Cron horaire `_workflow_processor_job`
  (max 1 déclenchement/jour/workflow). Endpoints `/api/workflows` CRUD + `/run`,
  `/api/notifications` + `/read`. Frontend : `Workflows.jsx` (route /workflows, menu Actions),
  bandeau notifications sur Dashboard. Collections : `workflows`, `notifications`.
- [ ] **Workflow Builder v2** : déclencheurs additionnels (concurrent progresse, backlink perdu,
  404, Core Web Vitals, nouvelle tendance, FAQ concurrent) → actions (réécrire, publier, alerter email).
- [x] **Réseaux sociaux Meta + Google Business** (2026-06-13, testé 15/15) : OAuth + publication
  Facebook Pages, Instagram et Google Business Profile. Backend : `social_publishing.py` +
  routes dans server.py (`/api/meta/*`, `/api/gbp/*`, `POST /api/drafts/{id}/publish-facebook|instagram|gbp`).
  Frontend : `SocialPublishPanel.jsx` dans DraftDetail (panneau « Réseaux sociaux »).
  Tokens chiffrés (Fernet) dans `users.meta` (pages + token longue durée) et `users.gbp` (refresh token).
  L'IA (Claude) rédige un post adapté par réseau. Env requis sur VPS : META_APP_ID/SECRET/REDIRECT_URI,
  GBP_CLIENT_ID/SECRET/REDIRECT_URI (fallback sur GOOGLE_OAUTH_CLIENT_ID/SECRET). GBP nécessite
  l'approbation Google « Business Profile APIs access request » + activation des 3 API My Business.
  En preview : clés FACTICES (OAuth complet non testable). Threads non implémenté.
- [x] **Images de couverture automatiques (Pexels)** (2026-06-13) : à chaque génération d'article,
  Claude produit un `image_query` (anglais) et le backend récupère une photo Pexels paysage
  (`_fetch_pexels_cover`, dégradation gracieuse sans clé). Bouton « Régénérer l'image » dans
  DraftDetail (`POST /api/drafts/{id}/generate-image`, page+1 pour varier). Image insérée dans
  le HTML publié (figure + crédit photographe + og:image) et utilisée par défaut pour les posts
  Facebook/Instagram. Champs draft : cover_image_url/alt/credit/credit_url, image_query.
  Env : PEXELS_API_KEY (clé gratuite pexels.com/api) — VIDE en preview, à configurer sur le VPS.
- [x] **Refactoring backend en modules** (2026-06-13, régression 29/30 backend + 100% frontend,
  seul bug trouvé — figure cover manquante dans export.html — corrigé) : server.py (~5000 lignes)
  découpé en 16 fichiers : `app_core.py` (env, db, Fernet, modèles Pydantic, auth JWT) +
  `routes_sites/audit/billing/content/publish/google/linkedin/pipeline/social/dashboard/
  workflows/keywords/optimizer/analysis.py` + `server.py` (entrypoint + scheduler + CORS).
  Tous les modules s'enregistrent sur le router partagé `api` d'app_core, imports en ordre DAG
  (billing avant content pour le quota ; linkedin avant pipeline). 105/105 routes préservées.
  Sauvegarde du monolithe : /tmp/server_monolith.bak (hors repo).
- [x] **Login amélioré + réinitialisation de mot de passe** (2026-06-14, testé 100% back+front) :
  bloc « Compte démo » supprimé de la page login, œil afficher/masquer mot de passe,
  attributs autocomplete/name pour LastPass (login/register/reset), flux « Mot de passe oublié » :
  `POST /api/auth/forgot-password` (anti-énumération, token sha256 1h, collection
  password_reset_tokens) + `POST /api/auth/reset-password`. Email via Resend si RESEND_API_KEY
  (sinon lien dans les logs backend). Pages /forgot-password et /reset-password.
  Env : FRONTEND_URL, RESEND_API_KEY, RESEND_FROM. Backlog mineur : rate-limit forgot-password,
  TTL index sur password_reset_tokens.
- [x] **Fix OAuth Google (VPS)** (2026-06-14, testé 6/6) : (1) redirect_uri_mismatch — le callback
  accepte /api/google/callback ET /api/google/oauth/callback (double décorateur) ; (2) PKCE
  « Missing code verifier » — le code_verifier généré par google-auth-oauthlib au /google/login
  est persisté chiffré dans `google_oauth_states` (sha256(state), upsert, purge 30 min) et
  restauré via find_one_and_delete dans le callback avant fetch_token ; (3) « Scope has changed »
  — scope canonique userinfo.email (au lieu de « email ») + OAUTHLIB_RELAX_TOKEN_SCOPE=1
  (testé 7/7 + régression PKCE 6/6).
- [x] **Fix « Tester la connexion » GitHub + 401 auto-logout** (2026-06-14, testé 100% back+front) :
  (1) diagnostic 404 en 3 branches (repo VIDE → initialiser README / branche manquante / repo
  inaccessible) dans routes_publish.py test-github ; (2) les erreurs de credentials tiers
  (GitHub PAT, Meta, GBP, LinkedIn, Google) renvoient 400 au lieu de 401 — le 401 est réservé
  à la session app ; (3) intercepteur axios (lib/api.js) : auto-logout uniquement sur vrais 401
  session (regex d'exclusion des endpoints tiers). Tests : tests/test_github_test_connection.py,
  tests/test_third_party_credentials_400.py.
- [x] **Fix génération d'article « Expecting ',' delimiter »** (2026-06-14, testé 7/7 unit + E2E
  100%) : réponse Claude tronquée à max_tokens par défaut → routes_content._do_generate_content
  utilise désormais max_tokens=16000 + _parse_llm_json/_repair_json (ai_visibility) + retry
  2 tentatives (y compris erreurs réseau). Tests : tests/test_generation_json_repair.py.
  Note : frontend utilise /content/generate-async (polling) — nginx VPS timeout 120s OK.
- [ ] Recherche de nom : générer 50-100 propositions avec critères (domaines, marques, prononciation).

- [x] **Fix publication GitHub 403 (permissions token)** (2026-06-15, testé 7/7 backend iteration_16) :
  cause = PAT fine-grained sans permission « Contents: Read and write ». Fix dans `routes_publish.py` :
  (1) `_GITHUB_403_MSG` — message français expliquant comment corriger le token, (2) `_github_put_file`
  et `_github_get_file_sha` interceptent 403/404 → HTTPException(403) claire, (3) `test_github_connection`
  vérifie proactivement `permissions.push` via GET /repos/{owner}/{repo} et échoue avec message « ÉCRITURE »
  si le token est read-only. Utilisateur a corrigé son token « LOGI SEO blog » (Contents: R/W + Update).

- [x] **Fix URL publique GitHub + index du blog auto** (2026-06-15, testé 10/10 unit) : (1) `_github_public_page_url`
  construit l'URL finale en incluant le dossier cible (`blog/` → `https://blog.logirent.ch/blog/slug.html`),
  strip le préfixe `public/` (Vite/CRA). Utilisé pour l'URL annoncée, le canonical et le sitemap.
  (2) Sitemap : nettoyage auto des entrées obsolètes du même slug (ancienne URL 404).
  (3) `_github_update_blog_index` : à chaque publication, met à jour `articles.json` (racine repo) et
  injecte les cartes d'articles dans `index.html` (div id="articles") → la page d'accueil du blog liste
  les articles automatiquement. Tests: /app/backend/tests/test_blog_index.py.
  Note utilisateur : HTTPS GitHub Pages activé (cert Let's Encrypt émis après re-save du custom domain),
  token classique `repo` créé (les fine-grained posaient problème). Publication GitHub 100% fonctionnelle E2E.

- [x] **Super admin via ADMIN_EMAILS** (2026-06-15, testé curl) : `routes_billing.py` — var env
  `ADMIN_EMAILS` (liste d'emails séparés par virgules). Emails admin : quota articles illimité
  (`_enforce_plan_quota` bypass), plan affiché "Admin" (999999 articles/mois) dans /api/workspace
  (+ champ `is_admin`) et dashboard agents. contact@logitrak.ch = admin sur le VPS de l'utilisateur.
  VPS : ajouter `ADMIN_EMAILS=contact@logitrak.ch` dans /opt/logi-seo-booster/.env (sed avant echo !).

- [x] **Panneau Admin + Workspaces multi-utilisateurs (RBAC)** (2026-06-15, testé 21/21 backend + frontend E2E) :
  (1) **Panneau Admin** `/admin` (réservé ADMIN_EMAILS) : stats globales (users, sites, articles, revenus,
  répartition plans) + table utilisateurs avec changement de plan manuel. Backend `routes_admin.py`.
  (2) **Équipe** `/team` : invitations par email (3 rôles admin/éditeur/lecteur), lien /register?invite=TOKEN,
  auto-acceptation à l'inscription OU au login (comptes existants, via GET /workspace/memberships).
  Backend `routes_team.py` + `app_core.py` (get_current_user résout l'acting workspace : le membre agit
  avec l'identité data du propriétaire + real_user_id/workspace_role ; RBAC enforcement : viewer=lecture
  seule, editor=pas de sites/billing/team/admin). Sélecteur d'espace de travail dans la sidebar,
  badge de rôle, nav conditionnelle (Facturation/Équipe masqués pour éditeur/lecteur, Admin visible
  pour ADMIN_EMAILS). AuthContext rafraîchit /auth/me après login/register (bugfix rôle).
  ⚠️ Leçon: ne PAS faire plusieurs search_replace sur le MÊME fichier dans un seul batch parallèle (3 éditions perdues).

- [x] **Marquage « ✓ Généré » des suggestions** (2026-06-15, testé E2E screenshot + curl) : quand un contenu
  est généré depuis une suggestion (Keyword Intelligence : pages locales + plan de contenu ; Générateur IA :
  suggestions de sujets), la suggestion est marquée d'un badge vert « ✓ Généré » + bouton « Voir le brouillon »
  + petit bouton re-générer. Backend : champ `suggestion_key` dans ContentGenerateRequest, collection
  `generated_suggestions` (upsert à la fin du job), GET /api/sites/{id}/generated-suggestions.

- [x] **SMTP pour l'envoi d'emails** (2026-06-15, testé unit + curl + UI) : `send_email()` central dans
  app_core.py — SMTP prioritaire (env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
  SMTP_SECURITY=starttls|ssl|none), fallback Resend. Utilisé par reset password + invitations équipe.
  Endpoint POST /api/admin/test-email + carte « Test d'envoi d'email » dans le Panneau Admin.

- [x] **Refonte fetch_pages (AI Visibility / Business Analyzer / Keyword Intelligence)** (2026-06-15, testé live) :
  Causes racines logitag.ch : (1) base_url stockée SANS protocole ("www.logitag.ch") → urlparse netloc vide →
  0 page ; (2) rate-limit Wix HTTP 429 après ~10 requêtes rapides (robots + 8 sitemaps) → tous les fetchs finaux
  échouaient. Fixes dans ai_visibility.py : normalize_base_url (https:// auto, slashs), homepage-first avec
  redirects (URL finale = base de crawl, www/non-www tolérés), réutilisation du HTML homepage déjà téléchargé,
  sitemapindex Wix suivi (sous-sitemaps → vraies pages, .xml exclus des pages), robots.txt Sitemap:, throttle
  (sem 2 + 0.4s) + retry 429 (Retry-After), erreurs diagnostiquables en français (DNS/SSL/timeout/403/404/5xx),
  fallback crawl homepage si sitemap absent (diag.note), diag dans report.fetch_diagnostic.
  routes_sites.py : normalisation base_url à la création ET modification + crawler d'audit.
  Fix test préexistant cassé (import 'from backend' dans test_github_test_connection.py).

- [x] **Open Graph / Twitter Cards / JSON-LD BlogPosting sur les articles publiés** (2026-06-15, 21 checks validés) :
  `_render_html` (routes_publish.py) génère désormais : og:site_name, og:image:width/height/alt (dims parsées
  de l'URL Pexels), twitter:card summary_large_image + title/description/image, JSON-LD BlogPosting complet
  (headline, description, image, datePublished, dateModified, author, publisher, mainEntityOfPage) en plus du
  FAQPage. og:image REFUSE les URLs non-https (base64/blob/relatif omis). Validation post-publication :
  publish-github retourne `social_warnings[]` (image absente / non-HTTPS / HTTP>=400 / meta_description absente /
  URL publique non configurée) — affichés en toasts warning dans DraftDetail. Toast succès mentionne le délai
  GitHub Pages 1-3 min. NOTE logitag.ch : site hébergé chez WIX — la publication GitHub Pages n'y sert rien ;
  l'URL partagée sur LinkedIn était un 404 Wix (vraie cause de l'aperçu sans image). Publication Wix = backlog P2.

- [x] **Publication Wix réelle (Markdown → Ricos → publish)** (2026-06-15, testé unit mocks + régression) :
  `create_wix_draft_post` (routes_sites.py) refondu selon playbook officiel : conversion Markdown via
  POST /ricos/v1/ricos-document/convert/to-ricos (plugins HEADING/LINK/TABLE/DIVIDER/CODE_BLOCK), validation
  fixDocument, memberId auto-résolu via /members/v1/members (caché sur site.wix_member_id), création brouillon
  (excerpt=meta_description, fieldsets URL) puis POST /blog/v3/draft-posts/{id}/publish → postId + URL publique.
  wix_headers corrigé (wix-site-id SEUL, plus de wix-account-id). Erreurs 401/403 → message français actionnable
  (permission Manage Blog). Nouveau POST /api/sites/{id}/test-wix. DraftPublic + drafts : wix_post_id, wix_url.
  Frontend : toast « Article PUBLIÉ sur Wix » avec lien, bandeau avec URL. L'utilisateur doit créer une clé API
  Wix (manage.wix.com/account/api-keys, permission Blog) et configurer le site logitag en type wix.
  LIMITE : image de couverture non envoyée à Wix (nécessite upload Wix Media, à faire si demandé).

## Backlog / Phase 2 (P0)
- [x] Génération en lot (batch) — fait (Automation.jsx)
- [x] Calendrier éditorial cron — fait
- [x] LinkedIn auto-posting — fait
- [ ] Vraie Wix App (App ID + Secret) via Wix Dev Center pour OAuth multi-comptes
- [ ] Alerte email auto si une page tracée chute de >5 positions sur Google
- [ ] Vérification utilisateur du checkout Stripe (carte test 4242…) — toujours en attente

## Backlog / Phase 3 (P1)
- [ ] Comparateur de versions visuel (diff)
- [ ] Notifications email avant publication (validation par responsable)
- [ ] Multi-utilisateurs / rôles par site (admin / rédacteur)
- [ ] Génération en lot (10 pages locales d'un coup)
- [ ] Export PDF des audits
- [ ] Intégration Bing Webmaster Tools

## Phase 4 (P2)
- [ ] Suggestions automatiques de maillage interne
- [ ] Analyse de la concurrence (SERP scraping)
- [ ] Refactorer `server.py` (~990 lignes) en modules : auth/sites/wix/audit/content/drafts/publish

## Known limitations (MVP)
- Wix API key stockée en clair en base — l'UI affiche "Chiffrée" par anticipation. À chiffrer en P0.
- Publication Wix : transmet body_markdown comme texte simple — la mise en forme markdown
  ne sera pas rendue dans Wix tant que la conversion RichContent n'est pas implémentée.
- Données Performance entièrement simulées (mocked: true côté API).

## Test credentials
Voir `/app/memory/test_credentials.md`.
