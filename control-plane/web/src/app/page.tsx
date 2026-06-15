"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { Button } from "@/components/ui/button";

export default function Home() {
  const { request } = useApi();

  const { data: ops, isLoading, error, refetch } = useQuery({
    queryKey: ["ops"],
    queryFn: () => request("/ops", "get"),
    refetchInterval: 5000, // poll every 5 seconds for updates
  });

  const getStatusColor = (state: string) => {
    switch (state.toUpperCase()) {
      case "APPROVED":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "DONE":
        return "bg-sky-500/10 text-sky-400 border-sky-500/20";
      case "FAILED":
        return "bg-red-500/10 text-red-400 border-red-500/20";
      case "ROLLED_BACK":
        return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      case "EXECUTING":
      case "VERIFYING":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      case "PROPOSED":
      case "PREVIEWED":
        return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
      default:
        return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
    }
  };

  return (
    <div className="flex-1 flex flex-col bg-zinc-950 text-zinc-50">
      <header className="border-b border-zinc-800 px-8 py-6 flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-xl font-bold tracking-tight">Operations Console</h1>
          <p className="text-xs text-zinc-400">Governed microkernel execution audit queue</p>
        </div>
        <Button 
          variant="outline" 
          onClick={() => refetch()}
          className="border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-xs px-3 h-8"
        >
          Refresh Now
        </Button>
      </header>

      <main className="flex-1 p-8 overflow-y-auto max-w-6xl w-full mx-auto">
        {isLoading && (
          <div className="flex items-center justify-center py-20">
            <span className="text-sm text-zinc-400">Loading operations...</span>
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-6 text-sm text-red-400">
            Failed to load operations: {error instanceof Error ? error.message : "Unknown error"}
          </div>
        )}

        {!isLoading && !error && (!ops || ops.length === 0) && (
          <div className="text-center py-20 border border-dashed border-zinc-800 rounded-lg">
            <p className="text-sm text-zinc-400">No operations found for this tenant context.</p>
            <p className="text-xs text-zinc-500 mt-1">Submit an intent to see active or proposed saga operations.</p>
          </div>
        )}

        {ops && ops.length > 0 && (
          <div className="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-900/50">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-zinc-800 bg-zinc-900 text-zinc-400 font-semibold uppercase tracking-wider">
                  <th className="px-6 py-4">Op ID / Action</th>
                  <th className="px-6 py-4">Domain / Brand</th>
                  <th className="px-6 py-4">Preview Summary</th>
                  <th className="px-6 py-4">Cost</th>
                  <th className="px-6 py-4">State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {ops.map((op: any) => (
                  <tr key={op.op_id} className="hover:bg-zinc-900/30 transition-colors">
                    <td className="px-6 py-4 space-y-0.5">
                      <code className="text-zinc-300 font-mono text-[11px] block">{op.op_id.substring(0, 8)}...</code>
                      <span className="font-semibold text-zinc-200 block text-[11px]">{op.action}</span>
                    </td>
                    <td className="px-6 py-4 space-y-0.5">
                      <span className="text-zinc-300 block font-medium">{op.domain}</span>
                      <span className="text-zinc-500 block text-[10px]">Brand: {op.brand_id}</span>
                    </td>
                    <td className="px-6 py-4 text-zinc-400 max-w-xs truncate">
                      {op.preview || "No preview summary"}
                    </td>
                    <td className="px-6 py-4 text-zinc-300 font-mono">
                      {op.cost_estimate || "Free / NA"}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full border text-[10px] font-semibold tracking-wide uppercase ${getStatusColor(op.state)}`}>
                        {op.state}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
