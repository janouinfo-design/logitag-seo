import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSites } from "@/contexts/SiteContext";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  BrainCircuit,
  Loader2,
  Sparkles,
  RefreshCw,
  Zap,
  Target,
  FileText,
  MapPin,
  Swords,
  Star,
  TrendingUp,
  Building2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const DIFF_STYLE = {
  low: { label: "Facile", cls: "bg-green-100 text-green-700" },
  medium: { label: "Moyenne", cls: "bg-amber-100 text-amber-700" },
  high: { label: "Difficile", cls: "bg-red-100 text-red-700" },
};
const PROFIT_STYLE = {
  "élevée": "text-green-700",
  moyenne: "text-amber-700",
  faible: "text-slate-500",
};
const INTENT_LABEL = {
  locale: { label: "Locale", cls: "bg-blue-50 text-[#002FA7]" },
  informationnelle: { label: "Informationnelle", cls: "bg-teal-50 text-teal-700" },
  transactionnelle: { label: "Transactionnelle", cls: "bg-purple-50 text-purple-700" },
  navigationnelle: { label: "Marque / Nav.", cls: "bg-slate-100 text-slate-600" },
};
const TYPE_LABEL = {
  article: "Article",
  page_locale: "Page locale",
  faq: "FAQ",
  service_description: "Page service",
};
const IMPACT_STYLE = {
  "élevé": "bg-red-100 text-red-700",
  moyen: "bg-amber-100 text-amber-700",
  faible: "bg-slate-100 text-slate-600",
};

function PotentialBar({ value }) {
  const color = value >= 70 ? "#15803D" : value >= 45 ? "#B45309" : "#64748B";
  return (
    <div className="flex items-center gap-2 min-w-[90px]">
      <div className="h-1.5 flex-1 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${value}%`, background: color }} />
      </div>
      <span className="text-xs font-semibold w-6 text-right" style={{ color }}>{value}</span>
    </div>
  );
}

export default function KeywordIntelligence() {
  const { activeSite } = useSites();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [savingKw, setSavingKw] = useState(null);
  const [generating, setGenerating] = useState(new Set());
  const [genMap, setGenMap] = useState({});
  const pollRef = useRef(null);

  const loadGenerated = useCallback(async () => {
    if (!activeSite) return;
    try {
      const { data } = await api.get(`/sites/${activeSite.id}/generated-suggestions`);
      const map = {};
      (data.generated || []).forEach((g) => { map[g.key] = g; });
      setGenMap(map);
    } catch { /* silent */ }
  }, [activeSite]);

  const loadLatest = useCallback(async () => {
    if (!activeSite) { setLoading(false); return; }
    setLoading(true);
    try {
      const { data } = await api.get(`/sites/${activeSite.id}/keyword-intelligence/latest`);
      setReport(data && data.summary ? data : null);
      loadGenerated();
    } catch {
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [activeSite, loadGenerated]);

  useEffect(() => {
    loadLatest();
    return () => clearInterval(pollRef.current);
  }, [loadLatest]);

  const launch = async () => {
    if (!activeSite) return;
    setRunning(true);
    try {
      const { data } = await api.post(`/sites/${activeSite.id}/keyword-intelligence`);
      toast.info("Analyse Keyword Intelligence lancée — l'IA étudie votre business…");
      let attempts = 0;
      pollRef.current = setInterval(async () => {
        attempts += 1;
        if (attempts > 90) {
          clearInterval(pollRef.current);
          setRunning(false);
          toast.error("L'analyse prend trop de temps. Réessayez.");
          return;
        }
        try {
          const { data: job } = await api.get(`/content/jobs/${data.job_id}`);
          if (job.status === "completed") {
            clearInterval(pollRef.current);
            setReport(job.result);
            setRunning(false);
            toast.success("Analyse Keyword Intelligence terminée !");
          } else if (job.status === "failed") {
            clearInterval(pollRef.current);
            setRunning(false);
            toast.error(job.error || "L'analyse a échoué.");
          }
        } catch { /* keep polling */ }
      }, 4000);
    } catch (e) {
      setRunning(false);
      toast.error(e?.response?.data?.detail || "Impossible de lancer l'analyse.");
    }
  };

  const saveKeyword = async (kw, intent) => {
    setSavingKw(kw.keyword);
    try {
      const priority = kw.potential >= 70 ? "high" : kw.potential >= 45 ? "medium" : "low";
      await api.post("/keywords/saved", {
        site_id: activeSite.id,
        keyword: kw.keyword,
        intent,
        priority,
        notes: kw.reason || null,
      });
      toast.success(`« ${kw.keyword} » ajouté aux mots-clés suivis`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur lors de la sauvegarde");
    } finally {
      setSavingKw(null);
    }
  };

  const generateContent = async (item, genKey, suggestionKey) => {
    setGenerating((s) => new Set(s).add(genKey));
    try {
      const { data } = await api.post("/content/generate-async", {
        site_id: activeSite.id,
        content_type: item.type || "page_locale",
        topic: item.title || item.suggested_title,
        keywords: item.target_keywords || (item.target_keyword ? [item.target_keyword] : []),
        city: item.city || null,
        tone: "professionnel",
        target_length: "moyen",
        suggestion_key: suggestionKey || null,
      });
      toast.info("Génération lancée — le brouillon apparaîtra dans « Brouillons » dans 1-2 min.");
      const jobId = data.job_id;
      const interval = setInterval(async () => {
        try {
          const { data: job } = await api.get(`/content/jobs/${jobId}`);
          if (job.status === "completed") {
            clearInterval(interval);
            setGenerating((s) => { const n = new Set(s); n.delete(genKey); return n; });
            toast.success(`Brouillon « ${job.result?.title || ""} » prêt dans Brouillons !`);
            loadGenerated();
          } else if (job.status === "failed") {
            clearInterval(interval);
            setGenerating((s) => { const n = new Set(s); n.delete(genKey); return n; });
            toast.error(job.error || "Génération échouée");
          }
        } catch { /* keep polling */ }
      }, 5000);
    } catch (e) {
      setGenerating((s) => { const n = new Set(s); n.delete(genKey); return n; });
      toast.error(e?.response?.data?.detail || "Impossible de lancer la génération.");
    }
  };

  if (!activeSite) {
    return (
      <div className="p-8">
        <div className="text-slate-600" data-testid="kwintel-no-site">Connectez d'abord un site pour lancer l'analyse.</div>
      </div>
    );
  }

  const profile = report?.business_profile;

  return (
    <div className="p-8 max-w-6xl" data-testid="kwintel-page">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2.5 mb-1">
            <div className="w-9 h-9 rounded-md bg-[#002FA7] flex items-center justify-center">
              <BrainCircuit className="w-5 h-5 text-white" />
            </div>
            <h1 className="font-display text-2xl font-bold text-slate-950">Keyword Intelligence</h1>
          </div>
          <p className="text-sm text-slate-600 max-w-2xl">
            L'IA analyse votre business puis identifie les mots-clés les plus rentables, les victoires rapides,
            les contenus à créer et les pages locales manquantes — avec génération en 1 clic.
          </p>
        </div>
        <Button
          onClick={launch}
          disabled={running}
          data-testid="kwintel-launch-button"
          className="bg-[#002FA7] hover:bg-[#00248A] text-white"
        >
          {running ? (
            <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Analyse en cours…</>
          ) : report ? (
            <><RefreshCw className="w-4 h-4 mr-2" /> Relancer l'analyse</>
          ) : (
            <><Sparkles className="w-4 h-4 mr-2" /> Lancer l'analyse</>
          )}
        </Button>
      </div>

      {running && (
        <div className="border border-[#002FA7]/20 bg-blue-50/50 rounded-lg p-4 mb-6 flex items-center gap-3" data-testid="kwintel-running-banner">
          <Loader2 className="w-5 h-5 text-[#002FA7] animate-spin flex-shrink-0" />
          <div className="text-sm text-slate-700">
            <span className="font-semibold">Analyse en cours (1-2 min)</span> — crawl du site, compréhension du business,
            puis construction de la stratégie mots-clés complète.
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 py-16 justify-center">
          <Loader2 className="w-5 h-5 animate-spin" /> Chargement…
        </div>
      ) : !report ? (
        !running && (
          <div className="border border-dashed border-slate-300 rounded-lg p-12 text-center" data-testid="kwintel-empty-state">
            <BrainCircuit className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <div className="font-semibold text-slate-900 mb-1">Aucune analyse pour {activeSite.name}</div>
            <div className="text-sm text-slate-500">
              Lancez l'analyse : l'IA comprendra votre business avant de recommander la meilleure stratégie mots-clés.
            </div>
          </div>
        )
      ) : (
        <div className="space-y-6">
          {/* Business profile */}
          {profile && (
            <div className="border border-slate-200 bg-white rounded-lg p-5" data-testid="kwintel-business-profile">
              <div className="flex items-center gap-2 mb-3">
                <Building2 className="w-4 h-4 text-[#002FA7]" />
                <h2 className="text-base font-display font-bold text-slate-950">Ce que l'IA a compris de votre business</h2>
              </div>
              <p className="text-sm text-slate-700 mb-3">{profile.description}</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                <div>
                  <div className="font-semibold text-slate-500 uppercase tracking-wider text-[10px] mb-1">Activité</div>
                  <div className="text-slate-800">{profile.activity}</div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500 uppercase tracking-wider text-[10px] mb-1">Cibles</div>
                  <div className="text-slate-800">{(profile.target_audience || []).join(", ")}</div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500 uppercase tracking-wider text-[10px] mb-1">Zones</div>
                  <div className="text-slate-800">{(profile.cities_zones || []).join(", ")}</div>
                </div>
                <div>
                  <div className="font-semibold text-slate-500 uppercase tracking-wider text-[10px] mb-1">Modèle</div>
                  <div className="text-slate-800">{profile.business_model}</div>
                </div>
              </div>
              {profile.positioning && (
                <div className="mt-3 text-xs text-slate-600 border-t border-slate-100 pt-3">
                  <span className="font-semibold">Positionnement :</span> {profile.positioning}
                </div>
              )}
            </div>
          )}

          {/* Strategic summary */}
          <div className="border border-[#002FA7]/20 bg-blue-50/40 rounded-lg p-5" data-testid="kwintel-summary">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="w-4 h-4 text-[#002FA7]" />
              <div className="text-sm font-semibold text-slate-900">Synthèse stratégique</div>
            </div>
            <p className="text-sm text-slate-700 leading-relaxed">{report.summary}</p>
            <div className="mt-2 text-[11px] text-slate-400">
              Analyse du {new Date(report.created_at).toLocaleString("fr-FR")}
            </div>
          </div>

          {/* Quick wins */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Zap className="w-4 h-4 text-amber-500" />
              <h2 className="text-base font-display font-bold text-slate-950">Victoires rapides — faciles à conquérir</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="kwintel-quickwins">
              {(report.quick_wins || []).map((q, i) => (
                <div key={i} className="border border-amber-200 bg-amber-50/50 rounded-lg p-3.5">
                  <div className="flex items-center justify-between mb-1">
                    <div className="font-semibold text-sm text-slate-900">{q.keyword}</div>
                    <Badge variant="outline" className="text-[9px] border-amber-400 text-amber-700">{q.cluster}</Badge>
                  </div>
                  <p className="text-xs text-slate-600">{q.why}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Top opportunities */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Target className="w-4 h-4 text-[#002FA7]" />
              <h2 className="text-base font-display font-bold text-slate-950">Meilleur potentiel business</h2>
            </div>
            <div className="space-y-2" data-testid="kwintel-opportunities">
              {(report.top_opportunities || []).map((o, i) => (
                <div key={i} className="border border-slate-200 bg-white rounded-lg p-3.5 flex items-center gap-4">
                  <div className="text-lg font-display font-bold text-[#002FA7] w-6">{i + 1}</div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm text-slate-900">{o.keyword}</div>
                    <div className="text-xs text-slate-600">{o.why}</div>
                  </div>
                  <PotentialBar value={o.potential ?? 50} />
                </div>
              ))}
            </div>
          </div>

          {/* Clusters */}
          <div>
            <h2 className="text-base font-display font-bold text-slate-950 mb-3">Clusters de mots-clés</h2>
            <div className="space-y-4" data-testid="kwintel-clusters">
              {(report.clusters || []).map((c, ci) => {
                const intent = INTENT_LABEL[c.intent] || INTENT_LABEL.informationnelle;
                return (
                  <div key={ci} className="border border-slate-200 bg-white rounded-lg overflow-hidden">
                    <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2">
                        <div className="font-semibold text-sm text-slate-900">{c.name}</div>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${intent.cls}`}>{intent.label}</span>
                        {c.priority === "high" && <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-red-100 text-red-700">Priorité élevée</span>}
                      </div>
                      <div className="text-xs text-slate-500">{c.why}</div>
                    </div>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-100">
                          <th className="text-left px-4 py-2 font-semibold">Mot-clé</th>
                          <th className="text-left px-2 py-2 font-semibold w-32">Potentiel</th>
                          <th className="text-left px-2 py-2 font-semibold">Difficulté</th>
                          <th className="text-left px-2 py-2 font-semibold">Rentabilité</th>
                          <th className="text-left px-2 py-2 font-semibold">Volume</th>
                          <th className="px-2 py-2 w-16"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {(c.keywords || []).map((k, ki) => {
                          const diff = DIFF_STYLE[k.difficulty] || DIFF_STYLE.medium;
                          return (
                            <tr key={ki} className="border-b border-slate-50 hover:bg-slate-50/50">
                              <td className="px-4 py-2.5">
                                <div className="font-medium text-slate-900 flex items-center gap-1.5">
                                  {k.keyword}
                                  {k.quick_win && <Zap className="w-3.5 h-3.5 text-amber-500" />}
                                </div>
                              </td>
                              <td className="px-2 py-2.5"><PotentialBar value={k.potential ?? 50} /></td>
                              <td className="px-2 py-2.5"><span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${diff.cls}`}>{diff.label}</span></td>
                              <td className={`px-2 py-2.5 text-xs font-semibold ${PROFIT_STYLE[k.profitability] || "text-slate-500"}`}>{k.profitability}</td>
                              <td className="px-2 py-2.5 text-xs text-slate-600">{k.est_volume}</td>
                              <td className="px-2 py-2.5">
                                <button
                                  onClick={() => saveKeyword(k, c.intent)}
                                  disabled={savingKw === k.keyword}
                                  data-testid={`kwintel-save-${ci}-${ki}`}
                                  title="Suivre ce mot-clé"
                                  className="text-slate-400 hover:text-[#002FA7] transition-colors"
                                >
                                  {savingKw === k.keyword ? <Loader2 className="w-4 h-4 animate-spin" /> : <Star className="w-4 h-4" />}
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Content plan */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <FileText className="w-4 h-4 text-[#002FA7]" />
              <h2 className="text-base font-display font-bold text-slate-950">Plan de contenu recommandé</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="kwintel-content-plan">
              {(report.content_plan || []).map((p, i) => {
                const genKey = `plan-${i}`;
                return (
                  <div key={i} className="border border-slate-200 bg-white rounded-lg p-4 flex flex-col">
                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                      <Badge variant="outline" className="text-[9px] border-[#002FA7] text-[#002FA7]">{TYPE_LABEL[p.type] || p.type}</Badge>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${IMPACT_STYLE[p.expected_impact] || IMPACT_STYLE.faible}`}>
                        Impact {p.expected_impact}
                      </span>
                      {p.city && <span className="text-[10px] text-slate-500 flex items-center gap-0.5"><MapPin className="w-3 h-3" />{p.city}</span>}
                    </div>
                    <div className="font-semibold text-sm text-slate-900 mb-1">{p.title}</div>
                    <p className="text-xs text-slate-600 flex-1">{p.why}</p>
                    <div className="mt-2 text-[11px] text-slate-500">
                      Cibles : {(p.target_keywords || []).join(", ")}
                    </div>
                    {genMap[`plan:${p.title}`] ? (
                      <div className="mt-3 flex items-center gap-2 flex-wrap">
                        <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5" data-testid={`kwintel-plan-done-${i}`}>
                          ✓ Généré
                        </span>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => navigate(`/drafts/${genMap[`plan:${p.title}`].draft_id}`)}
                          data-testid={`kwintel-view-draft-plan-${i}`}
                          className="border-emerald-600 text-emerald-700 hover:bg-emerald-50 w-fit"
                        >
                          Voir le brouillon
                        </Button>
                        <button
                          type="button"
                          title="Re-générer"
                          onClick={() => generateContent(p, genKey, `plan:${p.title}`)}
                          disabled={generating.has(genKey)}
                          data-testid={`kwintel-regen-plan-${i}`}
                          className="text-slate-400 hover:text-[#002FA7] transition-colors"
                        >
                          {generating.has(genKey) ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => generateContent(p, genKey, `plan:${p.title}`)}
                        disabled={generating.has(genKey)}
                        data-testid={`kwintel-generate-plan-${i}`}
                        className="mt-3 border-[#002FA7] text-[#002FA7] hover:bg-blue-50 w-fit"
                      >
                        {generating.has(genKey) ? (
                          <><Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> Génération…</>
                        ) : (
                          <><Sparkles className="w-3.5 h-3.5 mr-1.5" /> Générer ce contenu</>
                        )}
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Missing local pages */}
          {(report.missing_local_pages || []).length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <MapPin className="w-4 h-4 text-[#002FA7]" />
                <h2 className="text-base font-display font-bold text-slate-950">Pages locales manquantes</h2>
              </div>
              <div className="border border-slate-200 bg-white rounded-lg overflow-hidden" data-testid="kwintel-local-pages">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-100">
                      <th className="text-left px-4 py-2 font-semibold">Ville</th>
                      <th className="text-left px-2 py-2 font-semibold">Service</th>
                      <th className="text-left px-2 py-2 font-semibold">Titre suggéré</th>
                      <th className="text-left px-2 py-2 font-semibold">Mot-clé cible</th>
                      <th className="px-2 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.missing_local_pages.map((lp, i) => {
                      const genKey = `local-${i}`;
                      return (
                        <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                          <td className="px-4 py-2.5 font-medium text-slate-900">{lp.city}</td>
                          <td className="px-2 py-2.5 text-slate-700">{lp.service}</td>
                          <td className="px-2 py-2.5 text-xs text-slate-600">{lp.suggested_title}</td>
                          <td className="px-2 py-2.5 text-xs text-slate-600">{lp.target_keyword}</td>
                          <td className="px-2 py-2.5 text-right pr-4">
                            {genMap[`local:${lp.city}:${lp.target_keyword}`] ? (
                              <div className="flex items-center justify-end gap-2">
                                <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5" data-testid={`kwintel-local-done-${i}`}>
                                  ✓ Généré
                                </span>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => navigate(`/drafts/${genMap[`local:${lp.city}:${lp.target_keyword}`].draft_id}`)}
                                  data-testid={`kwintel-view-draft-local-${i}`}
                                  className="border-emerald-600 text-emerald-700 hover:bg-emerald-50"
                                >
                                  Voir le brouillon
                                </Button>
                                <button
                                  type="button"
                                  title="Re-générer"
                                  onClick={() => generateContent({ type: "page_locale", title: lp.suggested_title, target_keywords: [lp.target_keyword], city: lp.city }, genKey, `local:${lp.city}:${lp.target_keyword}`)}
                                  disabled={generating.has(genKey)}
                                  data-testid={`kwintel-regen-local-${i}`}
                                  className="text-slate-400 hover:text-[#002FA7] transition-colors"
                                >
                                  {generating.has(genKey) ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                                </button>
                              </div>
                            ) : (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => generateContent({ type: "page_locale", title: lp.suggested_title, target_keywords: [lp.target_keyword], city: lp.city }, genKey, `local:${lp.city}:${lp.target_keyword}`)}
                                disabled={generating.has(genKey)}
                                data-testid={`kwintel-generate-local-${i}`}
                                className="border-[#002FA7] text-[#002FA7] hover:bg-blue-50"
                              >
                                {generating.has(genKey) ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Générer"}
                              </Button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Competitors */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Swords className="w-4 h-4 text-[#002FA7]" />
              <h2 className="text-base font-display font-bold text-slate-950">Concurrents à surveiller</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="kwintel-competitors">
              {(report.competitors || []).map((c, i) => (
                <div key={i} className="border border-slate-200 bg-white rounded-lg p-4">
                  <div className="font-semibold text-sm text-slate-900 mb-0.5">
                    {c.name}
                    {c.domain && <span className="text-xs text-slate-400 font-normal ml-2">{c.domain}</span>}
                  </div>
                  <div className="text-xs text-slate-600 mb-1.5"><span className="font-semibold">Où il domine :</span> {c.strengths}</div>
                  <div className="text-xs text-green-700"><span className="font-semibold">Comment le dépasser :</span> {c.opportunity}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
