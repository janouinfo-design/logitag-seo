import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useSites } from "@/contexts/SiteContext";
import PageHeader from "@/components/PageHeader";
import { FileText, Trash2, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Checkbox } from "@/components/ui/checkbox";
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

const statusBadge = (s) => {
  const map = {
    draft: { color: "#64748B", bg: "#F1F5F9", label: "Brouillon" },
    ready: { color: "#D97706", bg: "#FEF3C7", label: "Prêt" },
    published: { color: "#16A34A", bg: "#DCFCE7", label: "Publié" },
    archived: { color: "#475569", bg: "#E2E8F0", label: "Archivé" },
  };
  return map[s] || map.draft;
};

const typeLabel = {
  article: "Article de blog",
  page_locale: "Page locale",
  faq: "FAQ",
  service_description: "Service",
};

export default function Drafts() {
  const { activeSite } = useSites();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(new Set());

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/drafts", {
        params: activeSite ? { site_id: activeSite.id } : {},
      });
      setItems(data);
      setSelected(new Set());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [activeSite?.id]);

  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    let changed = false;
    if (searchParams.get("linkedin") === "connected") {
      toast.success("Compte LinkedIn connecté ✓");
      searchParams.delete("linkedin");
      changed = true;
    }
    if (searchParams.get("meta") === "connected") {
      toast.success("Compte Facebook / Instagram connecté ✓");
      searchParams.delete("meta");
      changed = true;
    }
    if (searchParams.get("gbp") === "connected") {
      toast.success("Google Business Profile connecté ✓ (scope business.manage vérifié, comptes accessibles)");
      searchParams.delete("gbp");
    } else if (searchParams.get("gbp") === "connected_quota_pending") {
      toast.warning("Google Business connecté avec le bon scope, mais l'API refuse encore l'accès — quota GBP probablement en attente d'approbation Google.", { duration: 10000 });
      searchParams.delete("gbp");
      changed = true;
    }
    if (changed) setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams]);

  const remove = async (id) => {
    try {
      await api.delete(`/drafts/${id}`);
      toast.success("Brouillon supprimé");
      load();
    } catch {
      toast.error("Échec");
    }
  };

  const toggleOne = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const isAllSelected = items.length > 0 && selected.size === items.length;
  const toggleAll = () => {
    if (isAllSelected) setSelected(new Set());
    else setSelected(new Set(items.map((d) => d.id)));
  };

  const onDeleteSelected = async () => {
    if (selected.size === 0) return;
    try {
      const { data } = await api.post("/drafts/batch-delete", { ids: Array.from(selected) });
      toast.success(`${data.deleted} brouillon(s) supprimé(s)`);
      load();
    } catch {
      toast.error("Échec");
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl">
      <PageHeader
        overline={activeSite ? `Bibliothèque · ${activeSite.label}` : "Bibliothèque"}
        title="Brouillons"
        description="Tous vos contenus générés. Relisez, modifiez, puis publiez sur Wix après validation humaine."
        action={
          <Link
            to="/generator"
            data-testid="drafts-new-button"
            className="inline-flex items-center gap-2 bg-[#002FA7] hover:bg-[#001D6B] text-white px-4 py-2 rounded-md text-sm font-medium transition-colors shadow-sm"
          >
            <FileText className="w-4 h-4" /> Nouveau contenu
          </Link>
        }
      />

      {loading ? (
        <div className="text-sm text-slate-500">Chargement…</div>
      ) : items.length === 0 ? (
        <div className="border border-dashed border-slate-300 bg-white rounded-md p-10 text-center" data-testid="drafts-empty">
          <FileText className="w-8 h-8 text-slate-400 mx-auto mb-3" />
          <p className="text-sm text-slate-600 mb-4">Aucun brouillon pour ce site.</p>
          <Link
            to="/generator"
            className="inline-flex items-center gap-2 bg-[#002FA7] hover:bg-[#001D6B] text-white px-4 py-2 rounded-md text-sm font-medium"
          >
            Générer un premier contenu
          </Link>
        </div>
      ) : (
        <>
          <div className="border border-slate-200 bg-white rounded-md p-3 mb-3 flex items-center justify-between" data-testid="drafts-bulk-actions">
            <label className="flex items-center gap-2.5 cursor-pointer">
              <Checkbox
                checked={isAllSelected}
                onCheckedChange={toggleAll}
                data-testid="drafts-select-all"
              />
              <span className="text-sm font-medium text-slate-900">
                Tout sélectionner <span className="text-slate-500 font-normal">({items.length})</span>
              </span>
              {selected.size > 0 && (
                <span className="text-xs text-[#002FA7] ml-2">· {selected.size} sélectionné(s)</span>
              )}
            </label>
            <button
              onClick={onDeleteSelected}
              disabled={selected.size === 0}
              data-testid="drafts-delete-selected"
              className="inline-flex items-center gap-1.5 bg-red-600 hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed text-white px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors shadow-sm"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Supprimer {selected.size > 0 ? `(${selected.size})` : "la sélection"}
            </button>
          </div>
          <div className="border border-slate-200 bg-white rounded-md overflow-hidden" data-testid="drafts-list">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="w-10 px-3 py-2.5"></th>
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">Titre</th>
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">Type</th>
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">Statut</th>
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">Mis à jour</th>
                <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => {
                const b = statusBadge(d.status);
                const isChecked = selected.has(d.id);
                return (
                  <tr key={d.id} className={`border-b border-slate-100 ${isChecked ? "bg-blue-50/40" : "hover:bg-slate-50"}`} data-testid={`draft-row-${d.id}`}>
                    <td className="px-3 py-3 align-middle">
                      <Checkbox
                        checked={isChecked}
                        onCheckedChange={() => toggleOne(d.id)}
                        data-testid={`draft-check-${d.id}`}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <Link to={`/drafts/${d.id}`} className="font-medium text-slate-900 hover:text-[#002FA7]">
                        {d.title}
                      </Link>
                      <div className="text-xs text-slate-500 truncate max-w-[400px]">{d.meta_description || "—"}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{typeLabel[d.content_type] || d.content_type}</td>
                    <td className="px-4 py-3">
                      <span
                        className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                        style={{ background: b.bg, color: b.color }}
                      >
                        {b.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 text-xs">
                      {new Date(d.updated_at).toLocaleString("fr-FR")}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex items-center gap-1">
                        <Link
                          to={`/drafts/${d.id}`}
                          data-testid={`draft-open-${d.id}`}
                          className="p-2 text-slate-500 hover:text-[#002FA7] hover:bg-slate-100 rounded transition-colors"
                        >
                          <ExternalLink className="w-4 h-4" />
                        </Link>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <button
                              data-testid={`draft-delete-${d.id}`}
                              className="p-2 text-slate-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Supprimer ce brouillon ?</AlertDialogTitle>
                              <AlertDialogDescription>
                                Cette action est définitive. L&apos;historique des versions sera également perdu.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Annuler</AlertDialogCancel>
                              <AlertDialogAction
                                onClick={() => remove(d.id)}
                                className="bg-red-600 hover:bg-red-700"
                              >
                                Supprimer
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </>
      )}
    </div>
  );
}
