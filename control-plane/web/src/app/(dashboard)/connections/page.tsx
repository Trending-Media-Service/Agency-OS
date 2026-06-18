"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";

export default function ConnectionsPage() {
  const { request } = useApi();
  const { tenantId } = useTenant();

  // Fetch Connections
  const { data: connections, isLoading: connsLoading } = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => request("/connections", "get"),
    refetchInterval: 10000,
  });

  if (connsLoading) {
    return <div className="text-zinc-500 text-xs py-10 text-center">Loading connection maps...</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">Active Brand Connections</h3>
        <p className="text-[10px] text-zinc-500">Manage credentials mapped from per-brand Secret Manager</p>
      </div>

      {connections && connections.length === 0 && (
        <div className="text-center py-16 border border-dashed border-zinc-800 rounded-lg">
          <p className="text-xs text-zinc-400">No active integrations connected.</p>
          <p className="text-[10px] text-zinc-600 mt-1">Connect provider APIs via chat interface to fetch connection metadata.</p>
        </div>
      )}

      {connections && connections.length > 0 && (
        <div className="border border-zinc-900 rounded-lg overflow-hidden bg-zinc-900/20">
          <table className="w-full text-left border-collapse text-[11px]">
            <thead>
              <tr className="border-b border-zinc-900 bg-zinc-900/60 text-zinc-400 font-semibold uppercase tracking-wider text-[10px]">
                <th className="px-6 py-4">Provider</th>
                <th className="px-6 py-4">Scope</th>
                <th className="px-6 py-4">Secret Reference</th>
                <th className="px-6 py-4">Config Map</th>
                <th className="px-6 py-4 text-right">Connected At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-900">
              {connections.map((c) => (
                <tr key={c.id} className="hover:bg-zinc-900/10 transition-colors">
                  <td className="px-6 py-4 space-y-0.5">
                    <span className="font-semibold text-zinc-200 uppercase">{c.provider}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono text-[9px] uppercase">{c.scope}</span>
                  </td>
                  <td className="px-6 py-4">
                    <code className="text-zinc-400 font-mono text-[10px]">{c.secret_ref}</code>
                  </td>
                  <td className="px-6 py-4 text-zinc-500 font-mono text-[10px]">
                    {JSON.stringify(c.config)}
                  </td>
                  <td className="px-6 py-4 text-right text-zinc-500">
                    {new Date(c.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
