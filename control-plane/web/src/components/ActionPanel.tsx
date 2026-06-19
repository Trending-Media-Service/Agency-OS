"use client";

import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Zap, X } from "lucide-react";

// /actions and /actions/catalog are not in the generated OpenAPI `paths` types,
// so call them through a loosely-typed escape hatch over the same request client
// (keeps tenant/auth headers + stays mockable in tests).
type LooseCall = (path: string, method: string, body?: unknown) => Promise<unknown>;

interface ToolSchema {
  name: string;
  description?: string;
  domain?: string;
  parameters?: {
    properties?: Record<string, { type?: string; description?: string }>;
    required?: string[];
  };
}

interface ActionCard {
  op_id: string;
  action: string;
  state: string;
  preview: string | null;
  cost_estimate: string | null;
  violations?: { message: string }[];
}

function titleCase(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function stateColor(state: string): string {
  switch (state.toUpperCase()) {
    case "APPROVED": return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
    case "DONE": return "bg-sky-500/10 text-sky-400 border-sky-500/20";
    case "FAILED": return "bg-red-500/10 text-red-400 border-red-500/20";
    case "EXECUTING":
    case "VERIFYING": return "bg-amber-500/10 text-amber-400 border-amber-500/20";
    case "AWAITING_APPROVAL": return "bg-amber-500/20 text-amber-300 border-amber-500/40";
    default: return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
  }
}

export function ActionPanel() {
  const { request } = useApi();
  const call = request as unknown as LooseCall;
  const { activeBrandId, role } = useTenant();
  const queryClient = useQueryClient();
  const readOnly = role === "BRAND_VIEWER";

  const [selected, setSelected] = useState<ToolSchema | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cards, setCards] = useState<ActionCard[]>([]);

  const { data: catalog } = useQuery({
    queryKey: ["actions-catalog"],
    queryFn: async () => (await call("/actions/catalog", "get")) as { actions: ToolSchema[] },
  });

  const actions = catalog?.actions ?? [];
  // group by domain (falls back to a single group)
  const groups = actions.reduce<Record<string, ToolSchema[]>>((acc, a) => {
    const d = a.domain || "actions";
    (acc[d] ??= []).push(a);
    return acc;
  }, {});

  const openAction = (tool: ToolSchema) => {
    setSelected(tool);
    setValues({});
    setError(null);
  };

  const fields = (selected?.parameters?.properties)
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
      for (const [k, spec] of fields) {
        const raw = values[k];
        if (raw === undefined || raw === "") continue;
        params[k] = spec.type === "INTEGER" ? parseInt(raw, 10) : raw;
      }
      const res = (await call("/actions", "post", {
        tool: selected.name,
        brand_id: activeBrandId || "brand-bootstrap",
        params,
      })) as { cards?: ActionCard[] };
      setCards(res.cards ?? []);
      queryClient.invalidateQueries({ queryKey: ["ops"] });
      setSelected(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <div className="px-6 py-4 border-b border-zinc-900 flex items-center space-x-2">
        <Zap className="h-4 w-4 text-zinc-400" />
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">Operator Actions</h2>
      </div>

      <div className="flex-1 p-4 overflow-y-auto space-y-5 text-xs">
        {readOnly && (
          <p className="text-[10px] text-zinc-500 italic">Read-only context — actions are disabled for this role.</p>
        )}

        {Object.entries(groups).map(([domain, tools]) => (
          <div key={domain} className="space-y-1.5">
            <div className="text-[9px] uppercase tracking-widest text-zinc-600 font-bold px-1">{domain}</div>
            {tools.map((t) => (
              <button
                key={t.name}
                onClick={() => openAction(t)}
                disabled={readOnly}
                title={t.description}
                className="w-full text-left px-3 py-2 rounded border border-zinc-800 bg-zinc-950 hover:border-zinc-700 hover:bg-zinc-900/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <div className="text-[11px] text-zinc-200 font-medium">{titleCase(t.name)}</div>
                {t.description && <div className="text-[9px] text-zinc-500 truncate">{t.description}</div>}
              </button>
            ))}
          </div>
        ))}

        {/* Results of the most recent submission */}
        {cards.length > 0 && (
          <div className="space-y-2 pt-2 border-t border-zinc-900">
            <div className="text-[9px] uppercase tracking-widest text-zinc-600 font-bold px-1">Last submitted</div>
            {cards.map((card) => (
              <div key={card.op_id} className="border border-zinc-800 rounded bg-zinc-950 p-3 space-y-1.5">
                <div className="flex justify-between items-start gap-2">
                  <span className="font-semibold text-zinc-200 text-[10px] truncate">{card.action}</span>
                  <span className={`px-1.5 py-0.2 rounded border text-[8px] uppercase tracking-wider font-semibold ${stateColor(card.state)}`}>
                    {card.state}
                  </span>
                </div>
                {card.preview && <p className="text-[10px] text-zinc-400 line-clamp-3">{card.preview}</p>}
                {card.cost_estimate && <div className="text-[9px] font-mono text-zinc-500">Est: {card.cost_estimate}</div>}
                {card.violations?.map((v, i) => (
                  <div key={i} className="text-[9px] text-red-400 flex items-start gap-1">
                    <AlertTriangle className="h-3 w-3 shrink-0 text-red-500 mt-0.5" />
                    <span>{v.message}</span>
                  </div>
                ))}
                <p className="text-[9px] text-zinc-600 pt-0.5">Track it in the Operations Queue →</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Action form modal (mirrors the New Tenant modal pattern) */}
      {selected && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-950 border border-zinc-900 rounded-lg p-6 max-w-sm w-full space-y-4 shadow-xl">
            <div className="flex justify-between items-start">
              <div className="space-y-1">
                <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">{titleCase(selected.name)}</h3>
                {selected.description && <p className="text-[10px] text-zinc-500">{selected.description}</p>}
              </div>
              <button onClick={() => setSelected(null)} aria-label="Close" className="text-zinc-500 hover:text-zinc-300">
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={submit} className="space-y-3">
              {fields.length === 0 && (
                <p className="text-[10px] text-zinc-500">No parameters — this action runs as-is.</p>
              )}
              {fields.map(([name, spec]) => (
                <div key={name} className="space-y-1">
                  <label className="text-[9px] uppercase tracking-wider text-zinc-400 font-semibold">
                    {titleCase(name)}{required.includes(name) ? " *" : ""}
                  </label>
                  <input
                    type={spec.type === "INTEGER" ? "number" : "text"}
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
                  className="border-zinc-800 text-zinc-400 hover:bg-zinc-900 text-[10px] h-7 px-3 rounded">
                  Cancel
                </Button>
                <Button type="submit" disabled={submitting}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-[10px] h-7 px-3 rounded disabled:opacity-50">
                  {submitting ? "Submitting..." : "Propose Action"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
