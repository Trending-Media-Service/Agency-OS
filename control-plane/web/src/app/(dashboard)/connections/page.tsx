"use client";

import React, { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { Search, Check, X, Plug } from "lucide-react";

// /actions and /actions/catalog aren't in the generated OpenAPI `paths` types;
// call them via a loosely-typed escape hatch over the same request client.
type LooseCall = (path: string, method: string, body?: unknown) => Promise<unknown>;

interface ToolSchema {
  name: string;
  title?: string;
  description?: string;
  parameters?: { properties?: Record<string, { type?: string; description?: string }>; required?: string[] };
}

// Directory presentation for the connect tools (label/category/provider/icon are UI concerns).
const CONNECTOR_META: Record<string, { label: string; category: string; provider: string; popular?: boolean }> = {
  manage_shopify_connect:     { label: "Shopify",                          category: "Commerce & Stores", provider: "shopify",    popular: true },
  grow_google_ads_connect:    { label: "Google Ads",                       category: "Marketing & Ads",   provider: "google-ads", popular: true },
  grow_meta_connect:          { label: "Meta Ads",                         category: "Marketing & Ads",   provider: "meta-ads",   popular: true },
  presence_google_connect:    { label: "Search Console & Merchant Center", category: "Analytics & SEO",   provider: "google" },
  presence_wordpress_connect: { label: "WordPress",                        category: "Analytics & SEO",   provider: "wordpress" },
  presence_web_connect:       { label: "Website / Headless App",           category: "Analytics & SEO",   provider: "web" },
};

const CATEGORY_ORDER = ["Marketing & Ads", "Commerce & Stores", "Analytics & SEO", "Operations & MCPs", "Other"];

interface ConnectionRow {
  id: string; provider: string; scope: string; credential: string | null; config: Record<string, unknown>; created_at: string;
}

export default function ConnectionsPage() {
  const { request } = useApi();
  const call = request as unknown as LooseCall;
  const { tenantId, activeBrandId, role } = useTenant();
  const queryClient = useQueryClient();
  const readOnly = role === "BRAND_VIEWER";

  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<ToolSchema | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: catalog } = useQuery({
    queryKey: ["actions-catalog"],
    queryFn: async () => (await call("/actions/catalog", "get")) as { actions: ToolSchema[] },
  });
  const { data: connections } = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => request("/connections", "get"),
    refetchInterval: 10000,
  });

  const connectedProviders = new Set((connections as ConnectionRow[] | undefined)?.map((c) => c.provider) ?? []);

  // Only the connect tools belong in the directory (operations live in the Action Panel).
  const connectors = useMemo(() => {
    const all = (catalog?.actions ?? []).filter((t) => CONNECTOR_META[t.name] || t.name.endsWith("_connect"));
    const q = search.trim().toLowerCase();
    return all.filter((t) => {
      const meta = CONNECTOR_META[t.name];
      const label = meta?.label ?? t.name;
      return !q || label.toLowerCase().includes(q) || (t.description ?? "").toLowerCase().includes(q);
    });
  }, [catalog, search]);

  const grouped = useMemo(() => {
    const g: Record<string, ToolSchema[]> = {};
    for (const t of connectors) {
      const cat = CONNECTOR_META[t.name]?.category ?? "Other";
      (g[cat] ??= []).push(t);
    }
    return g;
  }, [connectors]);

  const fields = selected?.parameters?.properties
    ? Object.entries(selected.parameters.properties).filter(([k]) => k !== "brand_id" && k !== "tenant_id")
    : [];
  const required = selected?.parameters?.required ?? [];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    try {
      const params: Record<string, unknown> = {};
      for (const [k] of fields) {
        if (values[k]) params[k] = values[k];
      }
      await call("/actions", "post", { tool: selected.name, brand_id: activeBrandId || "brand-bootstrap", params });
      queryClient.invalidateQueries({ queryKey: ["connections", tenantId] });
      queryClient.invalidateQueries({ queryKey: ["ops"] });
      setSelected(null);
      setValues({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connect failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">Connector Directory</h3>
          <p className="text-[10px] text-zinc-500">Connect provider APIs — each connect is a governed, audited operation.</p>
        </div>
        <div className="relative w-64">
          <Search className="h-3.5 w-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search connectors..."
            className="w-full bg-zinc-950 border border-zinc-800 rounded-lg pl-8 pr-3 py-1.5 text-[11px] text-zinc-200 focus:outline-none focus:border-zinc-700"
          />
        </div>
      </div>

      {CATEGORY_ORDER.filter((c) => grouped[c]?.length).map((category) => (
        <div key={category} className="space-y-2">
          <div className="text-[10px] uppercase tracking-widest text-zinc-600 font-bold">{category}</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {grouped[category].map((t) => {
              const meta = CONNECTOR_META[t.name];
              const label = meta?.label ?? t.title ?? t.name;
              const connected = meta ? connectedProviders.has(meta.provider) : false;
              return (
                <div key={t.name} className="border border-zinc-800 rounded-lg bg-zinc-950 p-4 flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <div className="h-9 w-9 rounded-lg bg-zinc-900 border border-zinc-800 flex items-center justify-center shrink-0 text-zinc-300 font-bold text-sm">
                      {label.charAt(0)}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[12px] font-semibold text-zinc-200 truncate">{label}</span>
                        {meta?.popular && <span className="text-[8px] uppercase tracking-wider text-emerald-400 border border-emerald-500/30 rounded px-1">Popular</span>}
                      </div>
                      <p className="text-[10px] text-zinc-500 leading-relaxed">{t.description}</p>
                    </div>
                  </div>
                  {connected ? (
                    <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-semibold shrink-0">
                      <Check className="h-3.5 w-3.5" /> Connected
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      disabled={readOnly}
                      onClick={() => { setSelected(t); setValues({}); setError(null); }}
                      className="bg-zinc-100 text-zinc-950 hover:bg-zinc-200 text-[10px] h-7 px-3 rounded shrink-0 disabled:opacity-40"
                    >
                      Connect
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* Active connections */}
      <div className="space-y-2 pt-2">
        <div className="text-[10px] uppercase tracking-widest text-zinc-600 font-bold">Active Connections</div>
        {connections && (connections as unknown as ConnectionRow[]).length === 0 ? (
          <p className="text-[10px] text-zinc-600 border border-dashed border-zinc-800 rounded-lg py-6 text-center">
            No active connections yet — connect a provider above.
          </p>
        ) : (
          <div className="border border-zinc-900 rounded-lg overflow-hidden bg-zinc-900/20">
            <table className="w-full text-left border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-zinc-900 bg-zinc-900/60 text-zinc-400 font-semibold uppercase tracking-wider text-[10px]">
                  <th className="px-6 py-3">Provider</th>
                  <th className="px-6 py-3">Scope</th>
                  <th className="px-6 py-3">Credential Reference</th>
                  <th className="px-6 py-3 text-right">Connected At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-900">
                {(connections as unknown as ConnectionRow[] | undefined)?.map((c) => (
                  <tr key={c.id} className="hover:bg-zinc-900/10 transition-colors">
                    <td className="px-6 py-3 font-semibold text-zinc-200 uppercase">{c.provider}</td>
                    <td className="px-6 py-3"><span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono text-[9px] uppercase">{c.scope}</span></td>
                    <td className="px-6 py-3"><code className="text-zinc-400 font-mono text-[10px]">{c.credential || "****"}</code></td>
                    <td className="px-6 py-3 text-right text-zinc-500">{new Date(c.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Connect modal — governed: submits to /actions (propose -> gate -> audit) */}
      {selected && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-950 border border-zinc-900 rounded-lg p-6 max-w-sm w-full space-y-4 shadow-xl">
            <div className="flex justify-between items-start">
              <div className="space-y-1">
                <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider flex items-center gap-1.5">
                  <Plug className="h-3.5 w-3.5" /> Connect {CONNECTOR_META[selected.name]?.label ?? selected.name}
                </h3>
                <p className="text-[10px] text-zinc-500">Creates a governed Connection (proposed for approval, then audited).</p>
              </div>
              <button onClick={() => setSelected(null)} aria-label="Close" className="text-zinc-500 hover:text-zinc-300"><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="space-y-3">
              {fields.map(([name, spec]) => (
                <div key={name} className="space-y-1">
                  <label className="text-[9px] uppercase tracking-wider text-zinc-400 font-semibold">
                    {name.replace(/_/g, " ")}{required.includes(name) ? " *" : ""}
                  </label>
                  <input
                    type={name.toLowerCase().includes("secret") ? "password" : "text"}
                    required={required.includes(name)}
                    placeholder={spec.description || ""}
                    value={values[name] ?? ""}
                    onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))}
                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1.5 text-[11px] text-zinc-200 focus:outline-none focus:border-zinc-700 font-mono"
                  />
                </div>
              ))}
              {error && <p className="text-[10px] text-red-400 font-mono">{error}</p>}
              <div className="flex justify-end space-x-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setSelected(null)}
                  className="border-zinc-800 text-zinc-400 hover:bg-zinc-900 text-[10px] h-7 px-3 rounded">Cancel</Button>
                <Button type="submit" disabled={submitting}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-[10px] h-7 px-3 rounded disabled:opacity-50">
                  {submitting ? "Submitting..." : "Propose Connection"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
