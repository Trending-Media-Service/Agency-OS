"use client";

import React, { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { ArrowRight, Server, Activity, AlertCircle, CheckCircle2, Box, Eye, Network, Loader2 } from "lucide-react";

interface Operation {
  op_id: string;
  action: string;
  domain: string;
  brand_id: string;
  preview?: string | null;
  cost_estimate?: string | null;
  state: string;
}

export default function OpsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { request } = useApi();
  const { tenantId, role } = useTenant();

  const [viewMode, setViewMode] = useState<"map" | "list">("map");

  // Fetch Operations
  const { data: ops, isLoading: opsLoading, refetch: refetchOps } = useQuery({
    queryKey: ["ops", tenantId],
    queryFn: () => request("/ops", "get") as Promise<Operation[]>,
    refetchInterval: 5000,
  });

  const getStatusColor = (state: string) => {
    switch (state.toUpperCase()) {
      case "APPROVED":
      case "DONE":
        return "bg-emerald-950/40 text-emerald-400 border-emerald-800/50";
      case "FAILED":
        return "bg-red-950/40 text-red-400 border-red-900/50";
      case "ROLLED_BACK":
        return "bg-blue-950/40 text-blue-400 border-blue-900/50";
      case "EXECUTING":
      case "VERIFYING":
        return "bg-amber-950/40 text-amber-400 border-amber-900/50";
      case "PROPOSED":
      case "PREVIEWED":
        return "bg-zinc-900/60 text-zinc-400 border-zinc-800/60";
      case "AWAITING_APPROVAL":
        return "bg-amber-950/60 text-amber-300 border-amber-800/60 animate-pulse font-bold";
      default:
        return "bg-zinc-800/40 text-zinc-400 border-zinc-800/50";
    }
  };

  // Fake Agents for the Swarm Status Sidebar to match design
  const agents = [
    { name: "Grow Copywriter Agent", status: "Idle - Copy Generated", task: "Personalize ad copy for Ableys sensory blankets", active: false },
    { name: "Build Sentinel Agent", status: "Active - Monitoring Drift", task: "Auditing first-party tags on fitwear.com", active: true },
    { name: "Operator Orchestrator", status: "Active - Governing Saga sg-99238", task: "Coordinating API mutations and safety checks", active: true },
  ];

  return (
    <div className="space-y-6 animate-in fade-in duration-500 font-sans">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-zinc-100 flex items-center gap-2">
            Operator Control Plane
          </h2>
          <p className="text-xs text-zinc-500 mt-1">Govern active sagas, orchestrate agent swarms, and view operations.</p>
        </div>
        <div className="flex bg-[#1c1f2a] border border-[#374151] rounded-lg p-1">
          <button 
            onClick={() => setViewMode("map")}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-2 ${viewMode === "map" ? "bg-[#4d8eff] text-[#001a42]" : "text-[#8c909f] hover:text-[#dfe2f1]"}`}
          >
            <Network className="w-4 h-4" /> Saga Map
          </button>
          <button 
            onClick={() => setViewMode("list")}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-2 ${viewMode === "list" ? "bg-[#4d8eff] text-[#001a42]" : "text-[#8c909f] hover:text-[#dfe2f1]"}`}
          >
            <Activity className="w-4 h-4" /> Queue List
          </button>
        </div>
      </div>

      {viewMode === "map" ? (
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Main Flowmap */}
          <div className="flex-1 space-y-6">
            <div className="bg-[#111827] border border-[#374151] rounded-xl overflow-hidden shadow-xl">
              <div className="p-5 border-b border-[#374151] bg-[#0f131d]">
                <h3 className="text-[#dfe2f1] font-semibold flex items-center gap-2">
                  Saga ID: sg-99238 - Copy <Box className="w-4 h-4 text-[#8c909f]" /> Copywriting &amp; Mutation
                </h3>
                <p className="text-[#8c909f] text-xs mt-1">Saga ID: sg-99238 - Copy Copywriting &amp; Mutation</p>
              </div>
              
              <div className="p-8 bg-[#111827] min-h-[400px] flex items-center justify-center relative">
                {/* Node Flow Representation */}
                <div className="flex flex-wrap items-center justify-center gap-2 max-w-4xl mx-auto">
                  
                  {/* Node 1 */}
                  <div className="w-32 border-2 border-[#00a572] rounded-lg p-3 bg-[#00a572]/10 relative z-10">
                    <div className="text-[10px] text-[#8c909f] font-mono mb-1">Node 1 (Start):</div>
                    <div className="text-xs text-[#dfe2f1] font-medium leading-tight">Merchant Request / Intent</div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-[#00a572]" />

                  {/* Node 2 */}
                  <div className="w-32 border-2 border-[#00a572] rounded-lg p-3 bg-[#00a572]/10 relative z-10">
                    <div className="text-[10px] text-[#8c909f] font-mono mb-1">Node 2 (Plan):</div>
                    <div className="text-xs text-[#dfe2f1] font-medium leading-tight">GrowAdapter Plan generated</div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-[#00a572]" />

                  {/* Node 3 */}
                  <div className="w-32 border-2 border-[#00a572] rounded-lg p-3 bg-[#00a572]/10 relative z-10">
                    <div className="text-[10px] text-[#8c909f] font-mono mb-1">Node 3 (LLM):</div>
                    <div className="text-xs text-[#dfe2f1] font-medium leading-tight">Gemini RAG Context Resolution</div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-[#00a572]" />

                  {/* Node 4 */}
                  <div className="w-32 border-2 border-[#00a572] rounded-lg p-3 bg-[#00a572]/10 relative z-10">
                    <div className="text-[10px] text-[#8c909f] font-mono mb-1">Node 4 (Auth):</div>
                    <div className="text-xs text-[#dfe2f1] font-medium leading-tight">GCP Secret Manager Auth verification</div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-[#4d8eff]" />

                  {/* Node 5 (Active) */}
                  <div className="w-40 border-2 border-[#4d8eff] shadow-[0_0_15px_rgba(77,142,255,0.4)] rounded-lg p-3 bg-[#4d8eff]/10 relative z-10">
                    <div className="text-[10px] text-[#4d8eff] font-mono mb-1 font-bold">Node 5 (API Mutate):</div>
                    <div className="text-xs text-[#dfe2f1] font-medium leading-tight">Google Ads API: Search &amp; Create New RSA</div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-[#8c909f]" />

                  {/* Node 6 (Pending) */}
                  <div className="w-32 border-2 border-dashed border-[#8c909f] rounded-lg p-3 bg-transparent relative z-10">
                    <div className="text-[10px] text-[#8c909f] font-mono mb-1">Node 6 (API Pause):</div>
                    <div className="text-xs text-[#8c909f] font-medium leading-tight">Google Ads API: Pause Old RSA</div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-[#8c909f]" />

                  {/* Node 7 (Pending) */}
                  <div className="w-32 border-2 border-dashed border-[#8c909f] rounded-lg p-3 bg-transparent relative z-10">
                    <div className="text-[10px] text-[#8c909f] font-mono mb-1">Node 7 (Verify):</div>
                    <div className="text-xs text-[#8c909f] font-medium leading-tight">Saga Verification &amp; Health Audit</div>
                  </div>
                </div>

                {/* Compensation Branch */}
                <div className="absolute bottom-16 left-1/2 transform -translate-x-1/2 flex items-center gap-4">
                  <div className="w-32 border-2 border-dashed border-[#424754] rounded-lg p-3 bg-[#1c1f2a] opacity-60">
                    <div className="text-[10px] text-[#8c909f] font-mono mb-1">Compensation Branch</div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-[#424754]" />
                  <div className="w-40 border-2 border-dashed border-red-900 rounded-lg p-3 bg-red-950/20">
                    <div className="text-[10px] text-red-500 font-mono mb-1">Compensate:</div>
                    <div className="text-xs text-red-400 font-medium leading-tight">Delete Created Ad + Unpause Old Ad</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Health & Outbox */}
            <div className="bg-[#111827] border border-[#374151] rounded-xl p-5 shadow-xl">
              <h3 className="text-[#dfe2f1] font-semibold mb-1">System Health &amp; Outbox Lag</h3>
              <p className="text-[#8c909f] text-xs mb-4">High breathing room and smooth modern border radiu.</p>
              
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-[#00a572] rounded-lg p-4 shadow-[0_0_15px_rgba(0,165,114,0.2)]">
                  <div className="text-[#00311f] font-medium text-xs mb-1">Active Connections:</div>
                  <div className="text-white font-bold text-2xl">8 / 8 Active</div>
                </div>
                <div className="bg-[#00a572] rounded-lg p-4 shadow-[0_0_15px_rgba(0,165,114,0.2)]">
                  <div className="text-[#00311f] font-medium text-xs mb-1">Outbox Pending Lag:</div>
                  <div className="text-white font-bold text-2xl">0 Items</div>
                </div>
                <div className="bg-[#00a572] rounded-lg p-4 shadow-[0_0_15px_rgba(0,165,114,0.2)]">
                  <div className="text-[#00311f] font-medium text-xs mb-1">Outbox Dead Queue:</div>
                  <div className="text-white font-bold text-2xl">0 Items</div>
                </div>
              </div>
            </div>
          </div>

          {/* Sidebar */}
          <div className="w-full lg:w-80 space-y-4">
            <div className="bg-[#111827] border border-[#374151] rounded-xl overflow-hidden shadow-xl">
              <div className="p-4 border-b border-[#374151] bg-[#0f131d]">
                <h3 className="text-[#dfe2f1] font-semibold">Agent Swarm Status Queue</h3>
                <p className="text-[#8c909f] text-xs mt-1">Active background AI agents</p>
              </div>
              <div className="p-4 space-y-3">
                {agents.map((agent, i) => (
                  <div key={i} className={`border rounded-lg p-3 ${agent.active ? "border-[#4d8eff]/50 bg-[#4d8eff]/5" : "border-[#00a572]/50 bg-[#00a572]/5"}`}>
                    <div className="flex items-center justify-between mb-2">
                      <div className={`text-xs font-bold ${agent.active ? "text-[#4d8eff]" : "text-[#00a572]"}`}>Agent {i+1}: {agent.name}</div>
                      {agent.active && <Loader2 className="w-3 h-3 text-[#4d8eff] animate-spin" />}
                    </div>
                    <div className="text-[10px] font-mono text-[#8c909f] mb-1">
                      Status: <span className={agent.active ? "text-[#4d8eff]" : "text-[#00a572]"}>{agent.status}</span>
                    </div>
                    <div className="text-[10px] text-[#c2c6d6] leading-tight">
                      Task: {agent.task}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* Legacy Table View */
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg shadow-sm overflow-hidden">
          {opsLoading ? (
            <div className="p-8 text-center text-xs text-zinc-500 flex flex-col items-center">
              <Server className="h-6 w-6 mb-2 animate-pulse text-zinc-600" />
              Loading operations...
            </div>
          ) : !ops || ops.length === 0 ? (
            <div className="p-12 text-center flex flex-col items-center justify-center">
              <div className="h-12 w-12 rounded-full bg-zinc-800/50 flex items-center justify-center mb-4">
                <CheckCircle2 className="h-6 w-6 text-zinc-600" />
              </div>
              <h3 className="text-sm font-semibold text-zinc-300">No Operations Found</h3>
              <p className="text-xs text-zinc-500 mt-1 max-w-sm">The operation outbox is clear. No background jobs or mutations are pending.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm border-collapse">
                <thead>
                  <tr className="border-b border-zinc-800 bg-zinc-950/50">
                    <th className="px-4 py-3 font-semibold text-zinc-400 text-[10px] uppercase tracking-wider">Operation ID</th>
                    <th className="px-4 py-3 font-semibold text-zinc-400 text-[10px] uppercase tracking-wider">Target Domain</th>
                    <th className="px-4 py-3 font-semibold text-zinc-400 text-[10px] uppercase tracking-wider">Action Intent</th>
                    <th className="px-4 py-3 font-semibold text-zinc-400 text-[10px] uppercase tracking-wider">State</th>
                    <th className="px-4 py-3 font-semibold text-zinc-400 text-[10px] uppercase tracking-wider">Preview Synopsis</th>
                    <th className="px-4 py-3 font-semibold text-zinc-400 text-[10px] uppercase tracking-wider text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/50">
                  {ops.map((op) => (
                    <tr key={op.op_id} className="hover:bg-zinc-800/30 transition-colors group">
                      <td className="px-4 py-3 align-top">
                        <div className="font-mono text-[10px] text-zinc-400">{op.op_id}</div>
                      </td>
                      <td className="px-4 py-3 align-top">
                        <div className="flex items-center space-x-2">
                          <Server className="h-3.5 w-3.5 text-zinc-500" />
                          <span className="font-medium text-xs text-zinc-200">{op.domain}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 align-top">
                        <div className="text-xs font-semibold text-emerald-400 font-mono tracking-tight">{op.action}</div>
                      </td>
                      <td className="px-4 py-3 align-top">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[9px] font-mono font-semibold border uppercase ${getStatusColor(op.state)}`}>
                          {op.state}
                        </span>
                      </td>
                      <td className="px-4 py-3 align-top max-w-xs">
                        <div className="text-[11px] text-zinc-400 leading-relaxed">
                          {op.preview || "No preview synopsis attached."}
                        </div>
                      </td>
                      <td className="px-4 py-3 align-top text-right">
                        <Button 
                          size="sm" 
                          variant="ghost" 
                          className="h-7 px-2 text-[10px] text-blue-400 hover:bg-blue-900/30 hover:text-blue-300"
                        >
                          <Eye className="w-3 h-3 mr-1" /> View Full Diff
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
