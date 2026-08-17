import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, API } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { toast } from "sonner";
import { Save, Send, ArrowLeft, History, Eye, Pencil, CheckCircle2, AlertCircle, Loader2, X, Download, FileCode, Github, ExternalLink, Linkedin, Image as ImageIcon, RefreshCw } from "lucide-react";
import { useSites } from "@/contexts/SiteContext";
import SocialPublishPanel from "@/components/SocialPublishPanel";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

function MarkdownView({ md }) {
  // Very small markdown renderer (headings, paragraphs, lists, tables)
  const html = renderMarkdown(md || "");
  return <div className="prose-logi" dangerouslySetInnerHTML={{ __html: html }} />;
}

function renderMarkdown(src) {
  // Escape HTML
  let s = src.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // Tables
  s = s.replace(/((?:^\|.*\|\s*\n)+)/gm, (block) => {
    const lines = block.trim().split("\n");
    if (lines.length < 2) return block;
    const cells = (l) => l.split("|").slice(1, -1).map((c) => c.trim());
    const header = cells(lines[0]);
    const rows = lines.slice(2).map(cells);
    return `<table><thead><tr>${header.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows
      .map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  });
  // Headings
  s = s.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  s = s.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  s = s.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  // Bold + italic
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  // Lists
  s = s.replace(/((?:^\s*[-*] .+\n?)+)/gm, (m) => {
    const items = m.trim().split("\n").map((l) => `<li>${l.replace(/^\s*[-*] /, "")}</li>`).join("");
    return `<ul>${items}</ul>`;
  });
  s = s.replace(/((?:^\s*\d+\. .+\n?)+)/gm, (m) => {
    const items = m.trim().split("\n").map((l) => `<li>${l.replace(/^\s*\d+\. /, "")}</li>`).join("");
    return `<ol>${items}</ol>`;
  });
  // Paragraphs (lines not already wrapped)
  s = s.split(/\n{2,}/).map((para) => {
    if (/^<(h\d|ul|ol|table|li|p|blockquote)/.test(para.trim())) return para;
    if (!para.trim()) return "";
    return `<p>${para.replace(/\n/g, "<br/>")}</p>`;
  }).join("\n");
  return s;
}

export default function DraftDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { sites } = useSites();
  const [draft, setDraft] = useState(null);
  const [editing, setEditing] = useState({});
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishingGh, setPublishingGh] = useState(false);
  const [publishingLi, setPublishingLi] = useState(false);
  const [liStatus, setLiStatus] = useState(null);
  const [coverBusy, setCoverBusy] = useState(false);
  const [versions, setVersions] = useState([]);

  const draftSite = sites.find((s) => s.id === draft?.site_id);
  const ghReady = !!draftSite?.has_github_token;

  // Load LinkedIn status once
  useEffect(() => {
    api.get("/linkedin/status").then(({ data }) => setLiStatus(data)).catch(() => {});
  }, []);

  const load = async () => {
    const { data } = await api.get(`/drafts/${id}`);
    setDraft(data);
    setEditing({
      title: data.title,
      meta_title: data.meta_title || "",
      meta_description: data.meta_description || "",
      body_markdown: data.body_markdown,
    });
    const v = await api.get(`/drafts/${id}/versions`);
    setVersions(v.data.versions);
  };

  useEffect(() => { load(); }, [id]);

  const onSave = async () => {
    setSaving(true);
    try {
      await api.patch(`/drafts/${id}`, editing);
      toast.success("Modifications enregistrées");
      load();
    } catch {
      toast.error("Échec de la sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  const onPublish = async () => {
    setPublishing(true);
    try {
      const { data } = await api.post(`/drafts/${id}/publish`, { publish_immediately: false });
      if (data.wix_post_id) {
        toast.success("Article PUBLIÉ sur votre blog Wix 🎉", {
          description: data.wix_url ? `En ligne : ${data.wix_url}` : "Visible dans Wix → Blog → Posts",
          action: data.wix_url ? { label: "Ouvrir", onClick: () => window.open(data.wix_url, "_blank") } : undefined,
          duration: 9000,
        });
      } else if (data.wix_draft_id) {
        toast.success("Brouillon créé sur Wix — publiez-le depuis le dashboard Wix");
      } else if (data.status === "ready") {
        toast.success("Brouillon validé · prêt à exporter ou copier-coller");
      } else {
        toast.warning("Wix indisponible — brouillon marqué prêt à publier");
      }
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de la publication");
    } finally {
      setPublishing(false);
    }
  };

  const onPublishGitHub = async () => {
    setPublishingGh(true);
    try {
      const { data } = await api.post(`/drafts/${id}/publish-github`);
      toast.success(`Publié sur GitHub · commit ${data.commit_sha?.slice(0, 7)}`, {
        description: data.public_url ? `⏱️ En ligne dans 1 à 3 minutes (déploiement GitHub Pages) : ${data.public_url}` : "Push effectué",
        action: data.commit_url ? { label: "Voir commit", onClick: () => window.open(data.commit_url, "_blank") } : undefined,
      });
      (data.social_warnings || []).forEach((w) => toast.warning(w, { duration: 9000 }));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du push GitHub");
    } finally {
      setPublishingGh(false);
    }
  };

  const connectLinkedIn = async () => {
    try {
      const { data } = await api.get("/linkedin/login");
      window.location.href = data.authorization_url;
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de connexion LinkedIn");
    }
  };

  const onPublishLinkedIn = async () => {
    setPublishingLi(true);
    try {
      const { data } = await api.post(`/drafts/${id}/publish-linkedin`);
      toast.success("Publié sur LinkedIn ✓", {
        description: data.article_url ? "Avec aperçu de l'article" : "Post texte",
        action: data.post_url ? { label: "Voir le post", onClick: () => window.open(data.post_url, "_blank") } : undefined,
      });
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du post LinkedIn");
    } finally {
      setPublishingLi(false);
    }
  };

  const onRollback = async (versionId) => {
    try {
      await api.post(`/drafts/${id}/rollback/${versionId}`);
      toast.success("Version restaurée");
      load();
    } catch {
      toast.error("Échec du rollback");
    }
  };

  const onGenerateImage = async () => {
    setCoverBusy(true);
    try {
      await api.post(`/drafts/${id}/generate-image`);
      toast.success("Image de couverture mise à jour ✓");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de génération de l'image");
    } finally {
      setCoverBusy(false);
    }
  };

  if (!draft) {
    return (
      <div className="p-6 md:p-8 max-w-5xl">
        <div className="text-sm text-slate-500">Chargement…</div>
      </div>
    );
  }

  const charLen = (s) => (s || "").length;
  const titleLen = charLen(editing.meta_title);
  const descLen = charLen(editing.meta_description);

  return (
    <div className="p-6 md:p-8 max-w-6xl">
      <button
        onClick={() => navigate("/drafts")}
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 mb-4"
        data-testid="draft-back-button"
      >
        <ArrowLeft className="w-4 h-4" /> Retour aux brouillons
      </button>

      <PageHeader
        overline={`${draft.content_type === "article" ? "Article" : draft.content_type === "page_locale" ? "Page locale" : draft.content_type === "faq" ? "FAQ" : "Service"} · Statut ${draft.status}`}
        title={draft.title}
        action={
          <div className="flex items-center gap-2">
            <a
              href={`${API}/drafts/${draft.id}/export?token=${localStorage.getItem("logi_token")}`}
              onClick={async (e) => {
                e.preventDefault();
                try {
                  const res = await api.get(`/drafts/${draft.id}/export`, { responseType: "blob" });
                  const url = URL.createObjectURL(res.data);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `logi-seo-${draft.id}.zip`;
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                  URL.revokeObjectURL(url);
                  toast.success("ZIP téléchargé — uploadez-le sur votre FTP");
                } catch (err) {
                  toast.error("Échec du téléchargement");
                }
              }}
              data-testid="draft-download-zip"
              className="inline-flex items-center gap-2 bg-white border border-slate-300 hover:border-[#002FA7] hover:text-[#002FA7] text-slate-700 px-4 py-2 rounded-md text-sm font-medium transition-colors"
            >
              <Download className="w-4 h-4" /> ZIP (HTML+JSON)
            </a>
            <a
              href="#"
              onClick={async (e) => {
                e.preventDefault();
                try {
                  const res = await api.get(`/drafts/${draft.id}/export.html`, { responseType: "blob" });
                  const url = URL.createObjectURL(res.data);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `${draft.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 80)}.html`;
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                  URL.revokeObjectURL(url);
                  toast.success("HTML téléchargé");
                } catch (err) {
                  toast.error("Échec du téléchargement");
                }
              }}
              data-testid="draft-download-html"
              className="inline-flex items-center gap-2 bg-white border border-slate-300 hover:border-[#002FA7] hover:text-[#002FA7] text-slate-700 px-4 py-2 rounded-md text-sm font-medium transition-colors"
            >
              <FileCode className="w-4 h-4" /> HTML seul
            </a>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button
                  data-testid="draft-publish-github-button"
                  disabled={!ghReady || publishingGh}
                  title={ghReady ? "Pousser sur votre repo GitHub" : "Configurez GitHub dans la page Sites d'abord"}
                  className="inline-flex items-center gap-2 bg-slate-900 hover:bg-black disabled:bg-slate-300 disabled:cursor-not-allowed text-white px-4 py-2 rounded-md text-sm font-medium transition-colors shadow-sm"
                >
                  {publishingGh ? <Loader2 className="w-4 h-4 animate-spin" /> : <Github className="w-4 h-4" />}
                  Publier sur GitHub
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle className="flex items-center gap-2"><Github className="w-5 h-5" /> Publier sur GitHub ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {draftSite && ghReady ? (
                      <>Push de <code className="bg-slate-100 px-1 rounded">{draftSite.github_folder || "(racine)"}/&lt;slug&gt;.html</code> vers <strong>{draftSite.github_owner}/{draftSite.github_repo}</strong> · branche <strong>{draftSite.github_branch || "main"}</strong>. Vercel/Netlify redéploiera automatiquement votre site.</>
                    ) : (
                      <>GitHub n&apos;est pas configuré pour ce site. Ouvrez la page <strong>Sites</strong> et configurez votre Personal Access Token.</>
                    )}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Annuler</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={onPublishGitHub}
                    disabled={!ghReady || publishingGh}
                    data-testid="draft-publish-github-confirm"
                    className="bg-slate-900 hover:bg-black"
                  >
                    {publishingGh ? "Push en cours…" : "Confirmer le push"}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            {liStatus?.server_configured && (
              liStatus.connected ? (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button
                      data-testid="draft-publish-linkedin-button"
                      disabled={publishingLi}
                      title={`Publier sur LinkedIn (connecté : ${liStatus.name || liStatus.email})`}
                      className="inline-flex items-center gap-2 bg-[#0A66C2] hover:bg-[#004182] disabled:bg-slate-300 disabled:cursor-not-allowed text-white px-4 py-2 rounded-md text-sm font-medium transition-colors shadow-sm"
                    >
                      {publishingLi ? <Loader2 className="w-4 h-4 animate-spin" /> : <Linkedin className="w-4 h-4" />}
                      Publier sur LinkedIn
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle className="flex items-center gap-2"><Linkedin className="w-5 h-5 text-[#0A66C2]" /> Publier sur LinkedIn ?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Claude va générer automatiquement un post LinkedIn pro (800-1300 caractères) à partir de votre article et le publier sur votre profil <strong>{liStatus.name || liStatus.email}</strong>.
                        {draft?.github_public_url && <><br /><br />✅ L&apos;article sera lié à <code className="text-xs bg-slate-100 px-1 rounded">{draft.github_public_url}</code> avec aperçu automatique.</>}
                        {!draft?.github_public_url && <><br /><br />⚠️ Cet article n&apos;est pas encore publié sur GitHub — le post LinkedIn n&apos;aura pas d&apos;aperçu d&apos;article. Publiez d&apos;abord sur GitHub pour un meilleur engagement.</>}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Annuler</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={onPublishLinkedIn}
                        disabled={publishingLi}
                        data-testid="draft-publish-linkedin-confirm"
                        className="bg-[#0A66C2] hover:bg-[#004182]"
                      >
                        {publishingLi ? "Publication…" : "Publier maintenant"}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              ) : (
                <button
                  onClick={connectLinkedIn}
                  data-testid="draft-connect-linkedin-button"
                  title="Connecter votre compte LinkedIn pour activer la publication automatique"
                  className="inline-flex items-center gap-2 bg-white border border-[#0A66C2] hover:bg-[#0A66C2]/5 text-[#0A66C2] px-4 py-2 rounded-md text-sm font-medium transition-colors"
                >
                  <Linkedin className="w-4 h-4" />
                  Connecter LinkedIn
                </button>
              )
            )}
            <button
              onClick={onSave}
              disabled={saving}
              data-testid="draft-save-button"
              className="inline-flex items-center gap-2 bg-white border border-slate-300 hover:bg-slate-50 px-4 py-2 rounded-md text-sm font-medium text-slate-700 transition-colors"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Enregistrer
            </button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button
                  data-testid="draft-publish-button"
                  className="inline-flex items-center gap-2 bg-[#002FA7] hover:bg-[#001D6B] text-white px-4 py-2 rounded-md text-sm font-medium shadow-sm"
                >
                  <Send className="w-4 h-4" /> Publier
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Confirmer la publication ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Selon le type du site actif : Wix → crée un brouillon dans Wix · VPS API → POST vers votre serveur · FTP → upload des fichiers HTML+JSON dans le dossier configuré · URL publique → marque le brouillon comme prêt à exporter.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Annuler</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={onPublish}
                    disabled={publishing}
                    data-testid="draft-publish-confirm"
                    className="bg-[#002FA7] hover:bg-[#001D6B]"
                  >
                    {publishing ? "Publication…" : "Confirmer"}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        }
      />

      {draft.wix_draft_id && (
        <div className="mb-5 p-3 border border-green-200 bg-green-50 rounded-md flex items-center gap-2 text-sm text-green-800" data-testid="draft-wix-confirmation">
          <CheckCircle2 className="w-4 h-4 text-green-600 flex-shrink-0" />
          {draft.wix_post_id ? "Article publié sur Wix" : "Brouillon créé sur Wix"} · ID <code className="font-mono text-xs">{draft.wix_post_id || draft.wix_draft_id}</code>
          {draft.wix_url && (
            <a href={draft.wix_url} target="_blank" rel="noreferrer" className="underline font-medium ml-1" data-testid="draft-wix-url-link">
              Voir l'article
            </a>
          )}
        </div>
      )}

      {draft.github_commit_sha && (
        <div className="mb-5 p-3 border border-slate-200 bg-slate-50 rounded-md flex items-center gap-2 text-sm text-slate-800" data-testid="draft-github-confirmation">
          <Github className="w-4 h-4 text-slate-700 flex-shrink-0" />
          <span>Publié sur GitHub · commit <code className="font-mono text-xs">{draft.github_commit_sha.slice(0, 7)}</code></span>
          {draft.github_public_url && (
            <a href={draft.github_public_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-[#002FA7] hover:underline text-xs">
              <ExternalLink className="w-3 h-3" /> Voir la page publique
            </a>
          )}
        </div>
      )}

      {draft.linkedin_post_urn && (
        <div className="mb-5 p-3 border border-[#0A66C2]/20 bg-[#0A66C2]/5 rounded-md flex items-center gap-2 text-sm text-[#004182]" data-testid="draft-linkedin-confirmation">
          <Linkedin className="w-4 h-4 text-[#0A66C2] flex-shrink-0" />
          <span>Publié sur LinkedIn · {draft.linkedin_posted_at && new Date(draft.linkedin_posted_at).toLocaleString("fr-FR")}</span>
          {draft.linkedin_post_url && (
            <a href={draft.linkedin_post_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-[#0A66C2] hover:underline text-xs">
              <ExternalLink className="w-3 h-3" /> Voir le post
            </a>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Main editor */}
        <div className="lg:col-span-2 border border-slate-200 bg-white rounded-md p-5">
          <Tabs defaultValue="edit">
            <TabsList className="bg-transparent border-b border-slate-200 rounded-none p-0 h-auto w-full justify-start gap-6 mb-4">
              <TabsTrigger value="edit" className="rounded-none border-b-2 border-transparent data-[state=active]:border-[#002FA7] data-[state=active]:bg-transparent px-0 py-3 text-sm">
                <Pencil className="w-3.5 h-3.5 mr-1.5" /> Éditeur
              </TabsTrigger>
              <TabsTrigger value="preview" className="rounded-none border-b-2 border-transparent data-[state=active]:border-[#002FA7] data-[state=active]:bg-transparent px-0 py-3 text-sm">
                <Eye className="w-3.5 h-3.5 mr-1.5" /> Aperçu
              </TabsTrigger>
            </TabsList>
            <TabsContent value="edit" className="mt-0 space-y-3">
              <div>
                <label className="text-xs font-medium text-slate-700 mb-1.5 block">Titre H1</label>
                <input
                  data-testid="draft-title-input"
                  value={editing.title}
                  onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                  className="w-full border border-slate-300 rounded-md px-3 py-2 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#002FA7]/30 focus:border-[#002FA7]"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-700 mb-1.5 block">Contenu (markdown)</label>
                <textarea
                  data-testid="draft-body-input"
                  rows={22}
                  value={editing.body_markdown}
                  onChange={(e) => setEditing({ ...editing, body_markdown: e.target.value })}
                  className="w-full border border-slate-300 rounded-md px-3 py-2.5 bg-white text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-[#002FA7]/30 focus:border-[#002FA7] resize-y"
                />
              </div>
            </TabsContent>
            <TabsContent value="preview" className="mt-0">
              <div className="max-h-[600px] overflow-y-auto px-2">
                <h1 className="prose-logi"><span style={{ fontFamily: "Cabinet Grotesk", fontSize: "1.875rem", fontWeight: 700 }}>{editing.title}</span></h1>
                <MarkdownView md={editing.body_markdown} />
              </div>
            </TabsContent>
          </Tabs>
        </div>

        {/* Side panel */}
        <div className="space-y-4">
          <div className="border border-slate-200 bg-white rounded-md p-5" data-testid="draft-cover-panel">
            <div className="overline mb-3 flex items-center gap-1.5">
              <ImageIcon className="w-3 h-3" /> Image de couverture
            </div>
            {draft.cover_image_url ? (
              <>
                <img
                  src={draft.cover_image_url}
                  alt={draft.cover_image_alt || draft.title}
                  className="w-full rounded-md mb-1.5 object-cover max-h-44"
                  data-testid="draft-cover-image"
                />
                {draft.cover_image_credit && (
                  <a
                    href={draft.cover_image_credit_url || "#"}
                    target="_blank"
                    rel="noreferrer nofollow"
                    className="text-[10px] text-slate-400 hover:underline block mb-2 text-right"
                  >
                    {draft.cover_image_credit}
                  </a>
                )}
              </>
            ) : (
              <p className="text-xs text-slate-500 mb-3">
                Aucune image. Générez-en une automatiquement selon le sujet (photo pro Pexels) — insérée dans l&apos;article publié et utilisée pour Facebook/Instagram.
              </p>
            )}
            <button
              onClick={onGenerateImage}
              disabled={coverBusy}
              data-testid="draft-generate-image-button"
              className="w-full inline-flex items-center justify-center gap-2 border border-slate-300 hover:border-[#002FA7] hover:text-[#002FA7] text-slate-700 px-3 py-2 rounded-md text-xs font-medium transition-colors"
            >
              {coverBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              {draft.cover_image_url ? "Régénérer l'image" : "Générer une image"}
            </button>
          </div>
          <SocialPublishPanel draft={draft} onPublished={load} />
          <div className="border border-slate-200 bg-white rounded-md p-5">
            <div className="overline mb-3">Métadonnées SEO</div>
            <label className="text-xs font-medium text-slate-700 mb-1.5 flex justify-between">
              <span>Meta title</span>
              <span className={titleLen > 65 ? "text-red-600" : titleLen < 30 && titleLen > 0 ? "text-amber-600" : "text-slate-500"}>{titleLen}/60</span>
            </label>
            <input
              data-testid="draft-meta-title-input"
              value={editing.meta_title}
              onChange={(e) => setEditing({ ...editing, meta_title: e.target.value })}
              className="w-full border border-slate-300 rounded-md px-3 py-2 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#002FA7]/30 focus:border-[#002FA7] mb-3"
            />
            <label className="text-xs font-medium text-slate-700 mb-1.5 flex justify-between">
              <span>Meta description</span>
              <span className={descLen > 165 ? "text-red-600" : descLen < 80 && descLen > 0 ? "text-amber-600" : "text-slate-500"}>{descLen}/160</span>
            </label>
            <textarea
              data-testid="draft-meta-desc-input"
              rows={3}
              value={editing.meta_description}
              onChange={(e) => setEditing({ ...editing, meta_description: e.target.value })}
              className="w-full border border-slate-300 rounded-md px-3 py-2 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#002FA7]/30 focus:border-[#002FA7] resize-none"
            />
          </div>

          {draft.keywords?.length > 0 && (
            <div className="border border-slate-200 bg-white rounded-md p-5">
              <div className="overline mb-3">Mots-clés</div>
              <div className="flex flex-wrap gap-1.5">
                {draft.keywords.map((k) => (
                  <span key={k} className="bg-slate-100 text-slate-800 text-xs px-2 py-1 rounded">{k}</span>
                ))}
              </div>
            </div>
          )}

          {draft.faq?.length > 0 && (
            <div className="border border-slate-200 bg-white rounded-md p-5">
              <div className="overline mb-3">FAQ générée ({draft.faq.length})</div>
              <div className="space-y-2.5">
                {draft.faq.map((q, i) => (
                  <details key={i} className="border border-slate-100 rounded-md p-2.5">
                    <summary className="text-xs font-medium text-slate-900 cursor-pointer">{q.question}</summary>
                    <p className="text-xs text-slate-600 mt-2 leading-relaxed">{q.answer}</p>
                  </details>
                ))}
              </div>
            </div>
          )}

          <div className="border border-slate-200 bg-white rounded-md p-5">
            <div className="overline mb-3 flex items-center gap-1.5">
              <History className="w-3 h-3" /> Versions ({versions.length})
            </div>
            {versions.length === 0 ? (
              <p className="text-xs text-slate-500">Aucune version précédente.</p>
            ) : (
              <ul className="space-y-2">
                {versions.slice(0, 10).map((v) => (
                  <li key={v.id} className="flex items-center justify-between text-xs">
                    <span className="text-slate-600">{new Date(v.created_at).toLocaleString("fr-FR")}</span>
                    <button
                      onClick={() => onRollback(v.id)}
                      data-testid={`rollback-${v.id}`}
                      className="text-[#002FA7] hover:underline font-medium"
                    >
                      Restaurer
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
