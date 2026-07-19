import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { toast } from "sonner";
import { Users, Globe, FileText, Euro, ShieldCheck, Mail } from "lucide-react";

const PLAN_LABELS = { free: "Free", pro: "Pro", business: "Business", agency: "Agency" };

function StatCard({ icon: Icon, label, value, sub, testid }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4" data-testid={testid}>
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className="font-display text-2xl font-bold text-slate-950">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function TestEmailCard() {
  const [to, setTo] = useState("");
  const [sending, setSending] = useState(false);

  const sendTest = async (e) => {
    e.preventDefault();
    setSending(true);
    try {
      const { data } = await api.post("/admin/test-email", { to });
      toast.success(`Email de test envoyé via ${data.method.toUpperCase()} ✓`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'envoi");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5 mb-8" data-testid="admin-test-email-card">
      <div className="text-sm font-semibold text-slate-900 mb-1 flex items-center gap-2">
        <Mail className="w-4 h-4 text-[#002FA7]" /> Test d'envoi d'email
      </div>
      <p className="text-xs text-slate-500 mb-3">
        Vérifie votre configuration SMTP (ou Resend en secours) — invitations et réinitialisations de mot de passe.
      </p>
      <form onSubmit={sendTest} className="flex flex-col sm:flex-row gap-3">
        <input
          type="email"
          required
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="destinataire@exemple.ch"
          data-testid="admin-test-email-input"
          className="flex-1 border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#002FA7]/30 focus:border-[#002FA7]"
        />
        <button
          type="submit"
          disabled={sending}
          data-testid="admin-test-email-button"
          className="bg-[#002FA7] hover:bg-[#001D6B] disabled:opacity-60 text-white rounded-md px-5 py-2 text-sm font-medium transition-colors"
        >
          {sending ? "Envoi…" : "Envoyer un test"}
        </button>
      </form>
    </div>
  );
}

export default function Admin() {
  const [overview, setOverview] = useState(null);
  const [users, setUsers] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const [o, u] = await Promise.all([api.get("/admin/overview"), api.get("/admin/users")]);
      setOverview(o.data);
      setUsers(u.data.users || []);
    } catch (err) {
      setError(err?.response?.data?.detail || "Accès refusé");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const changePlan = async (userId, plan) => {
    try {
      const { data } = await api.patch(`/admin/users/${userId}/plan`, { plan });
      toast.success(`Plan changé en ${data.plan_name}`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  if (error) {
    return (
      <div className="p-8" data-testid="admin-access-denied">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 max-w-md">{error}</div>
      </div>
    );
  }
  if (!overview) return <div className="p-8 text-sm text-slate-500">Chargement…</div>;

  return (
    <div className="p-8 max-w-5xl" data-testid="admin-page">
      <PageHeader
        overline="Administration"
        title="Panneau Admin"
        description="Vue d'ensemble de la plateforme : utilisateurs, plans, consommation et revenus."
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard icon={Users} label="Utilisateurs" value={overview.total_users} testid="admin-stat-users" />
        <StatCard icon={Globe} label="Sites" value={overview.total_sites} testid="admin-stat-sites" />
        <StatCard
          icon={FileText}
          label="Articles"
          value={overview.total_drafts}
          sub={`${overview.drafts_this_month} ce mois · ${overview.published_drafts} publiés`}
          testid="admin-stat-drafts"
        />
        <StatCard
          icon={Euro}
          label="Revenus"
          value={`${overview.revenue_eur.toFixed(0)} €`}
          sub={`${overview.payments_count} paiement(s)`}
          testid="admin-stat-revenue"
        />
      </div>

      <TestEmailCard />

      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-200 text-sm font-semibold text-slate-900 flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-[#002FA7]" /> Utilisateurs ({users.length})
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
                <th className="px-5 py-2.5 font-semibold">Utilisateur</th>
                <th className="px-3 py-2.5 font-semibold">Plan</th>
                <th className="px-3 py-2.5 font-semibold text-center">Articles / mois</th>
                <th className="px-3 py-2.5 font-semibold text-center">Sites</th>
                <th className="px-5 py-2.5 font-semibold text-right">Inscrit le</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/50" data-testid={`admin-user-row-${u.email}`}>
                  <td className="px-5 py-3">
                    <div className="font-medium text-slate-900 flex items-center gap-1.5">
                      {u.full_name}
                      {u.is_admin && (
                        <span className="text-[10px] font-semibold text-[#002FA7] bg-[#002FA7]/10 border border-[#002FA7]/20 rounded px-1.5 py-0.5">
                          ADMIN
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500">{u.email}</div>
                  </td>
                  <td className="px-3 py-3">
                    {u.is_admin ? (
                      <span className="text-xs font-medium text-slate-600">Illimité</span>
                    ) : (
                      <select
                        value={u.plan}
                        onChange={(e) => changePlan(u.id, e.target.value)}
                        data-testid={`admin-plan-select-${u.email}`}
                        className="border border-slate-300 rounded-md px-2 py-1 text-xs bg-white"
                      >
                        {Object.entries(PLAN_LABELS).map(([k, v]) => (
                          <option key={k} value={k}>{v}</option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td className="px-3 py-3 text-center text-slate-700">{u.articles_this_month}</td>
                  <td className="px-3 py-3 text-center text-slate-700">{u.sites_count}</td>
                  <td className="px-5 py-3 text-right text-xs text-slate-500">
                    {new Date(u.created_at).toLocaleDateString("fr-FR")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
