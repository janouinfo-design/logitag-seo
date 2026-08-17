import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Facebook, Instagram, MapPin, Loader2, ExternalLink, CheckCircle2, Share2 } from "lucide-react";
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

function PostedLine({ label, date, url, testId }) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-green-700 mt-1.5" data-testid={testId}>
      <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />
      <span>{label} · {date && new Date(date).toLocaleString("fr-FR")}</span>
      {url && (
        <a href={url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 hover:underline">
          <ExternalLink className="w-3 h-3" /> Voir
        </a>
      )}
    </div>
  );
}

export default function SocialPublishPanel({ draft, onPublished }) {
  const [meta, setMeta] = useState(null);
  const [gbp, setGbp] = useState(null);
  const [fbPage, setFbPage] = useState("");
  const [igPage, setIgPage] = useState("");
  const [igImage, setIgImage] = useState("");
  const [gbpLocations, setGbpLocations] = useState(null);
  const [gbpLoc, setGbpLoc] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.get("/meta/status").then(({ data }) => {
      setMeta(data);
      if (data.pages?.length) {
        setFbPage(data.pages[0].id);
        const ig = data.pages.find((p) => p.instagram_id);
        if (ig) setIgPage(ig.id);
      }
    }).catch(() => {});
    api.get("/gbp/status").then(({ data }) => setGbp(data)).catch(() => {});
  }, []);

  useEffect(() => {
    if (draft?.cover_image_url) setIgImage(draft.cover_image_url);
  }, [draft?.cover_image_url]);

  const connect = async (path) => {
    try {
      const { data } = await api.get(path);
      window.location.href = data.authorization_url;
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Connexion impossible");
    }
  };

  const loadGbpLocations = async () => {
    if (gbpLocations) return;
    try {
      const { data } = await api.get("/gbp/locations");
      setGbpLocations(data.locations);
      if (data.locations?.length) setGbpLoc(data.locations[0].location);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Impossible de charger vos établissements");
    }
  };

  const publish = async (network) => {
    setBusy(network);
    try {
      let data;
      if (network === "facebook") {
        ({ data } = await api.post(`/drafts/${draft.id}/publish-facebook`, { page_id: fbPage || undefined }));
        toast.success(`Publié sur Facebook (${data.page}) ✓`, {
          action: data.post_url ? { label: "Voir le post", onClick: () => window.open(data.post_url, "_blank") } : undefined,
        });
      } else if (network === "instagram") {
        ({ data } = await api.post(`/drafts/${draft.id}/publish-instagram`, { page_id: igPage || undefined, image_url: igImage }));
        toast.success(`Publié sur Instagram (@${data.account}) ✓`, {
          action: data.post_url ? { label: "Voir le post", onClick: () => window.open(data.post_url, "_blank") } : undefined,
        });
      } else {
        ({ data } = await api.post(`/drafts/${draft.id}/publish-gbp`, { location: gbpLoc || undefined }));
        toast.success("Publié sur Google Business Profile ✓", {
          action: data.post_url ? { label: "Voir le post", onClick: () => window.open(data.post_url, "_blank") } : undefined,
        });
      }
      onPublished?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de la publication");
    } finally {
      setBusy("");
    }
  };

  const igPages = meta?.pages?.filter((p) => p.instagram_id) || [];

  const rowCls = "flex items-center justify-between gap-2";
  const btnConnect = "text-xs font-medium border px-2.5 py-1.5 rounded-md transition-colors";
  const btnPublish = "inline-flex items-center gap-1.5 text-xs font-medium text-white px-2.5 py-1.5 rounded-md transition-colors disabled:bg-slate-300 disabled:cursor-not-allowed";
  const notConfigured = <span className="text-xs text-slate-400">Non configuré (.env)</span>;

  return (
    <div className="border border-slate-200 bg-white rounded-md p-5" data-testid="social-publish-panel">
      <div className="overline mb-1 flex items-center gap-1.5">
        <Share2 className="w-3 h-3" /> Réseaux sociaux
      </div>
      <p className="text-xs text-slate-500 mb-4">L&apos;IA rédige un post adapté à chaque réseau et le publie en 1 clic.</p>

      <div className="space-y-3.5">
        {/* Facebook */}
        <div>
          <div className={rowCls}>
            <span className="inline-flex items-center gap-1.5 text-sm text-slate-800">
              <Facebook className="w-4 h-4 text-[#1877F2]" /> Facebook
            </span>
            {!meta ? null : !meta.server_configured ? notConfigured : !meta.connected ? (
              <button onClick={() => connect("/meta/login")} data-testid="social-connect-meta-button"
                className={`${btnConnect} border-[#1877F2] text-[#1877F2] hover:bg-[#1877F2]/5`}>
                Connecter
              </button>
            ) : (
              <button onClick={() => publish("facebook")} disabled={!!busy} data-testid="social-publish-facebook-button"
                className={`${btnPublish} bg-[#1877F2] hover:bg-[#0e5fc7]`}>
                {busy === "facebook" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Facebook className="w-3.5 h-3.5" />}
                Publier
              </button>
            )}
          </div>
          {meta?.connected && meta.pages?.length > 1 && (
            <select value={fbPage} onChange={(e) => setFbPage(e.target.value)} data-testid="social-facebook-page-select"
              className="mt-1.5 w-full border border-slate-200 rounded px-2 py-1 text-xs text-slate-700 bg-white">
              {meta.pages.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          {draft.facebook_posted_at && <PostedLine label="Publié sur Facebook" date={draft.facebook_posted_at} url={draft.facebook_post_url} testId="draft-facebook-confirmation" />}
        </div>

        {/* Instagram */}
        <div>
          <div className={rowCls}>
            <span className="inline-flex items-center gap-1.5 text-sm text-slate-800">
              <Instagram className="w-4 h-4 text-[#E4405F]" /> Instagram
            </span>
            {!meta ? null : !meta.server_configured ? notConfigured : !meta.connected ? (
              <button onClick={() => connect("/meta/login")} data-testid="social-connect-instagram-button"
                className={`${btnConnect} border-[#E4405F] text-[#E4405F] hover:bg-[#E4405F]/5`}>
                Connecter
              </button>
            ) : igPages.length === 0 ? (
              <span className="text-xs text-slate-400" title="Liez un compte Instagram professionnel à votre Page Facebook">Aucun compte IG lié</span>
            ) : (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <button disabled={!!busy} data-testid="social-publish-instagram-button"
                    className={`${btnPublish} bg-[#E4405F] hover:bg-[#c22b48]`}>
                    {busy === "instagram" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Instagram className="w-3.5 h-3.5" />}
                    Publier
                  </button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle className="flex items-center gap-2"><Instagram className="w-5 h-5 text-[#E4405F]" /> Publier sur Instagram ?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Instagram exige une image. {draft.cover_image_url ? "L'image de couverture de l'article est pré-remplie — vous pouvez la remplacer." : "Collez l'URL publique d'une image (JPEG recommandé)."} L&apos;IA génèrera la légende automatiquement.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  {igPages.length > 1 && (
                    <select value={igPage} onChange={(e) => setIgPage(e.target.value)} data-testid="social-instagram-page-select"
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm bg-white">
                      {igPages.map((p) => <option key={p.id} value={p.id}>@{p.instagram_username || p.name}</option>)}
                    </select>
                  )}
                  <input
                    value={igImage}
                    onChange={(e) => setIgImage(e.target.value)}
                    placeholder="https://exemple.com/image.jpg"
                    data-testid="social-instagram-image-input"
                    className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#E4405F]/30"
                  />
                  <AlertDialogFooter>
                    <AlertDialogCancel>Annuler</AlertDialogCancel>
                    <AlertDialogAction onClick={() => publish("instagram")} disabled={!igImage} data-testid="social-publish-instagram-confirm"
                      className="bg-[#E4405F] hover:bg-[#c22b48]">
                      Publier maintenant
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
          {draft.instagram_posted_at && <PostedLine label="Publié sur Instagram" date={draft.instagram_posted_at} url={draft.instagram_post_url} testId="draft-instagram-confirmation" />}
        </div>

        {/* Google Business Profile */}
        <div>
          <div className={rowCls}>
            <span className="inline-flex items-center gap-1.5 text-sm text-slate-800">
              <MapPin className="w-4 h-4 text-[#34A853]" /> Google Business
            </span>
            {!gbp ? null : !gbp.server_configured ? notConfigured : !gbp.connected ? (
              <button onClick={() => connect("/gbp/login")} data-testid="social-connect-gbp-button"
                className={`${btnConnect} border-[#34A853] text-[#34A853] hover:bg-[#34A853]/5`}>
                Connecter
              </button>
            ) : gbp.scope_ok === false ? (
              <button
                onClick={async () => { try { await api.post("/gbp/disconnect"); } catch (e) { /* ignore */ } connect("/gbp/login"); }}
                data-testid="social-reconnect-gbp-button"
                title="L'ancienne connexion n'a pas la permission Google Business (business.manage). Cliquez pour vous reconnecter."
                className={`${btnConnect} border-amber-500 text-amber-600 hover:bg-amber-50`}>
                Reconnecter (permission manquante)
              </button>
            ) : (
              <AlertDialog onOpenChange={(open) => open && loadGbpLocations()}>
                <AlertDialogTrigger asChild>
                  <button disabled={!!busy} data-testid="social-publish-gbp-button"
                    className={`${btnPublish} bg-[#34A853] hover:bg-[#2a8743]`}>
                    {busy === "gbp" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <MapPin className="w-3.5 h-3.5" />}
                    Publier
                  </button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle className="flex items-center gap-2"><MapPin className="w-5 h-5 text-[#34A853]" /> Publier sur Google Business Profile ?</AlertDialogTitle>
                    <AlertDialogDescription>
                      L&apos;IA génèrera un post local (max 1500 caractères) visible sur votre fiche Google (Search + Maps), avec un bouton « En savoir plus » vers l&apos;article si disponible.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  {!gbpLocations ? (
                    <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="w-4 h-4 animate-spin" /> Chargement de vos établissements…</div>
                  ) : (
                    <select value={gbpLoc} onChange={(e) => setGbpLoc(e.target.value)} data-testid="social-gbp-location-select"
                      className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm bg-white">
                      {gbpLocations.map((l) => <option key={l.location} value={l.location}>{l.title}</option>)}
                    </select>
                  )}
                  <AlertDialogFooter>
                    <AlertDialogCancel>Annuler</AlertDialogCancel>
                    <AlertDialogAction onClick={() => publish("gbp")} disabled={!gbpLoc} data-testid="social-publish-gbp-confirm"
                      className="bg-[#34A853] hover:bg-[#2a8743]">
                      Publier maintenant
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
          {draft.gbp_posted_at && <PostedLine label="Publié sur Google Business" date={draft.gbp_posted_at} url={draft.gbp_post_url} testId="draft-gbp-confirmation" />}
        </div>
      </div>
    </div>
  );
}
