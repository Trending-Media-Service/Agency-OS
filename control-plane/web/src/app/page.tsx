"use client";

import React, { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { 
  AlertTriangle, 
  CheckCircle, 
  XCircle, 
  Database, 
  Network, 
  History, 
  Sliders, 
  RefreshCw,
  Lock,
  Unlock,
  ShieldAlert
} from "lucide-react";

export default function Home() {
  const { request } = useApi();
  const { tenantId, role, setRole } = useTenant();
  const [activeTab, setActiveTab] = useState<"ops" | "connections" | "audit" | "safety">("ops");

  // 1. Fetch Operations
  const { data: ops, isLoading: opsLoading, error: opsError, refetch: refetchOps } = useQuery({
    queryKey: ["ops", tenantId],
    queryFn: () => request("/ops", "get"),
    refetchInterval: 5000,
  });

  // 2. Fetch Connections
  const { data: connections, isLoading: connsLoading, refetch: refetchConns } = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => request("/connections", "get"),
    refetchInterval: 10000,
  });

  // 3. Fetch Circuit Breakers
  const { data: breakers, isLoading: breakersLoading, refetch: refetchBreakers } = useQuery({
    queryKey: ["breakers", tenantId],
    queryFn: () => request("/circuit-breakers", "get"),
    refetchInterval: 5000,
  });

  // 4. Fetch Audit Log Events
  const { data: auditEvents, isLoading: auditLoading, refetch: refetchAudit } = useQuery({
    queryKey: ["auditEvents", tenantId],
    queryFn: () => request("/audit/events", "get"),
    refetchInterval: 5000,
  });

  // 5. Fetch Audit Chain Integrity verification
  const { data: auditVerify } = useQuery({
    queryKey: ["auditVerify", tenantId],
    queryFn: () => request("/audit/verify", "get"),
    refetchInterval: 10000,
  });

  // 6. Mutate decision
  const decisionMutation = useMutation({
    mutationFn: ({ opId, decision }: { opId: string, decision: "approve" | "reject" }) => 
      request(`/ops/${opId}/decision` as any, "post", {
        decision,
        actor: "chandan",
        role: role as any,
        surface: "web"
      } as any),
    onSuccess: () => {
      refetchOps();
    }
  });

  const handleDecision = (opId: string, decision: "approve" | "reject") => {
    decisionMutation.mutate({ opId, decision });
  };

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
      case "AWAITING_APPROVAL":
        return "bg-amber-500/20 text-amber-300 border-amber-500/40 animate-pulse";
      default:
        return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
    }
  };

  // Find any tripped circuit breakers to show global banner
  const trippedBreakers = breakers?.filter((b: any) => b.state.toUpperCase() === "OPEN") || [];

  return (
    <div className="flex-1 flex flex-col bg-zinc-950 text-zinc-50 font-sans">
      {/* Global Tripped Circuit Breaker Alert Banner */}
      {trippedBreakers.length > 0 && (
        <div className="bg-red-950/80 border-b border-red-800 text-red-200 px-6 py-3 flex items-center space-x-3 text-xs">
          <ShieldAlert className="h-4 w-4 text-red-400 shrink-0" />
          <div className="flex-1">
            <span className="font-bold uppercase tracking-wider text-red-400 mr-2">[Circuit Breaker Tripped]</span>
            Safety shutdown active on domain(s): <span className="font-semibold">{trippedBreakers.map((b: any) => `'${b.domain}'`).join(", ")}</span>. Automatic executions are blocked.
          </div>
        </div>
      )}

      {/* Header */}
      <header className="border-b border-zinc-900 px-8 py-6 flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-lg font-bold tracking-tight">Governance Console</h1>
          <p className="text-[11px] text-zinc-400 font-mono">Tenant Context: {tenantId} | Role: {role}</p>
        </div>
        
        <div className="flex items-center space-x-3">
          {/* Quick Dev Role Switcher */}
          <div className="flex bg-zinc-900 p-0.5 rounded border border-zinc-800 text-[10px]">
            <button 
              onClick={() => setRole("AGENCY_OWNER")}
              className={`px-2 py-1 rounded transition-colors ${role === "AGENCY_OWNER" ? "bg-zinc-800 text-white font-semibold" : "text-zinc-500 hover:text-zinc-300"}`}
            >
              Owner
            </button>
            <button 
              onClick={() => setRole("OPERATOR")}
              className={`px-2 py-1 rounded transition-colors ${role === "OPERATOR" ? "bg-zinc-800 text-white font-semibold" : "text-zinc-500 hover:text-zinc-300"}`}
            >
              Operator
            </button>
          </div>

          <Button 
            variant="outline" 
            onClick={() => {
              refetchOps();
              refetchConns();
              refetchBreakers();
              refetchAudit();
            }}
            className="border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-[10px] px-2 h-7 gap-1"
          >
            <RefreshCw className="h-3 w-3" />
            Sync
          </Button>
        </div>
      </header>

      {/* Tabs Selector Navigation */}
      <div className="border-b border-zinc-900 px-8 flex space-x-6 text-xs bg-zinc-900/10">
        <button
          onClick={() => setActiveTab("ops")}
          className={`py-4 border-b-2 font-medium transition-colors gap-2 flex items-center ${activeTab === "ops" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
        >
          <Database className="h-3.5 w-3.5" />
          Operations Queue
        </button>
        <button
          onClick={() => setActiveTab("connections")}
          className={`py-4 border-b-2 font-medium transition-colors gap-2 flex items-center ${activeTab === "connections" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
        >
          <Network className="h-3.5 w-3.5" />
          Active Connections
        </button>
        <button
          onClick={() => setActiveTab("audit")}
          className={`py-4 border-b-2 font-medium transition-colors gap-2 flex items-center ${activeTab === "audit" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
        >
          <History className="h-3.5 w-3.5" />
          Audit Trail
          {auditVerify?.ok ? (
            <span className="ml-1 px-1.5 py-0.2 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 rounded text-[9px] font-mono uppercase tracking-widest font-bold">Secured</span>
          ) : (
            <span className="ml-1 px-1.5 py-0.2 bg-red-500/10 border border-red-500/30 text-red-400 rounded text-[9px] font-mono uppercase tracking-widest font-bold">Corrupt</span>
          )}
        </button>
        <button
          onClick={() => setActiveTab("safety")}
          className={`py-4 border-b-2 font-medium transition-colors gap-2 flex items-center ${activeTab === "safety" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
        >
          <Sliders className="h-3.5 w-3.5" />
          Circuit Breakers
        </button>
      </div>

      {/* Main Content Area */}
      <main className="flex-1 p-8 overflow-y-auto max-w-6xl w-full mx-auto">
        
        {/* Tab 1: Operations Queue */}
        {activeTab === "ops" && (
          <div className="space-y-6">
            {opsLoading && <div className="text-zinc-500 text-xs py-10 text-center">Loading operations queue...</div>}
            
            {ops && ops.length === 0 && (
              <div className="text-center py-16 border border-dashed border-zinc-800 rounded-lg">
                <p className="text-xs text-zinc-400">No active or proposed operations found.</p>
                <p className="text-[10px] text-zinc-600 mt-1">Submit an intent via conversational interface to see executions.</p>
              </div>
            )}

            {ops && ops.length > 0 && (
              <div className="border border-zinc-900 rounded-lg overflow-hidden bg-zinc-900/20">
                <table className="w-full text-left border-collapse text-[11px]">
                  <thead>
                    <tr className="border-b border-zinc-900 bg-zinc-900/60 text-zinc-400 font-semibold uppercase tracking-wider text-[10px]">
                      <th className="px-6 py-4">Op ID / Action</th>
                      <th className="px-6 py-4">Domain / Brand</th>
                      <th className="px-6 py-4">Preview Summary</th>
                      <th className="px-6 py-4">Cost</th>
                      <th className="px-6 py-4">State</th>
                      <th className="px-6 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-900">
                    {ops.map((op: any) => (
                      <tr key={op.op_id} className="hover:bg-zinc-900/10 transition-colors">
                        <td className="px-6 py-4 space-y-0.5">
                          <code className="text-zinc-500 font-mono text-[10px] block">{op.op_id.substring(0, 8)}...</code>
                          <span className="font-semibold text-zinc-300 block">{op.action}</span>
                        </td>
                        <td className="px-6 py-4 space-y-0.5">
                          <span className="text-zinc-300 block font-medium capitalize">{op.domain}</span>
                          <span className="text-zinc-600 block text-[9px]">Brand: {op.brand_id}</span>
                        </td>
                        <td className="px-6 py-4 text-zinc-400 max-w-xs truncate">
                          {op.preview || "No preview summary"}
                        </td>
                        <td className="px-6 py-4 text-zinc-300 font-mono text-[10px]">
                          {op.cost_estimate || "0.00 INR"}
                        </td>
                        <td className="px-6 py-4">
                          <span className={`px-2 py-0.5 rounded-full border text-[9px] font-semibold tracking-wide uppercase ${getStatusColor(op.state)}`}>
                            {op.state}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-right">
                          {op.state === "AWAITING_APPROVAL" && (
                            <div className="flex justify-end space-x-2">
                              <Button
                                size="sm"
                                onClick={() => handleDecision(op.op_id, "approve")}
                                className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-[10px] h-6 px-2.5 rounded"
                              >
                                Approve
                              </Button>
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handleDecision(op.op_id, "reject")}
                                className="bg-red-950 hover:bg-red-900 text-red-300 border border-red-800 text-[10px] h-6 px-2.5 rounded"
                              >
                                Reject
                              </Button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Active Connections */}
        {activeTab === "connections" && (
          <div className="space-y-6">
            <div className="flex justify-between items-center mb-4">
              <div>
                <h3 className="text-sm font-semibold text-zinc-200">Active Brand Connections</h3>
                <p className="text-[10px] text-zinc-500">Manage pillar API credentials mapped from per-brand Secret Manager</p>
              </div>
            </div>

            {connsLoading && <div className="text-zinc-500 text-xs py-10 text-center">Loading connection maps...</div>}

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
                      <th className="px-6 py-4">Secret Reference (GCPSM)</th>
                      <th className="px-6 py-4">Config Map</th>
                      <th className="px-6 py-4 text-right">Connected At</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-900">
                    {connections.map((c: any) => (
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
        )}

        {/* Tab 3: Audit Trail */}
        {activeTab === "audit" && (
          <div className="space-y-6">
            <div className="bg-zinc-900/25 border border-zinc-900 rounded-lg p-5 flex items-start space-x-4">
              {auditVerify?.ok ? (
                <>
                  <CheckCircle className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Audit Trail Integrity Proven</h4>
                    <p className="text-[10px] text-zinc-400 mt-1">
                      The hash-chain has been verified end-to-end. Every operation transition is linked back to the genesis block via SHA256 integrity trees.
                    </p>
                  </div>
                </>
              ) : (
                <>
                  <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
                  <div>
                    <h4 className="text-xs font-semibold text-red-400 uppercase tracking-wider">Chain Corruption Detected</h4>
                    <p className="text-[10px] text-zinc-400 mt-1">
                      Warning: The hash-chained audit integrity validation has failed! Unlinked block found at ID: <code className="text-red-400 font-mono">{auditVerify?.first_bad_id}</code>. Database was mutated outside the kernel guardrails!
                    </p>
                  </div>
                </>
              )}
            </div>

            {auditLoading && <div className="text-zinc-500 text-xs py-10 text-center">Loading audit log events...</div>}

            {auditEvents && auditEvents.length > 0 && (
              <div className="space-y-3">
                <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Latest Audit Blocks</h4>
                <div className="space-y-2.5">
                  {auditEvents.map((ev: any) => (
                    <div key={ev.id} className="border border-zinc-900 rounded-lg p-4 bg-zinc-900/10 font-mono text-[10px] space-y-2 hover:bg-zinc-900/20 transition-colors">
                      <div className="flex items-center justify-between text-zinc-500">
                        <span>Block #{ev.id} | {new Date(ev.ts).toLocaleString()}</span>
                        <code className="text-zinc-600 text-[9px]">Hash: {ev.hash.substring(0, 16)}...</code>
                      </div>
                      
                      <div className="flex items-baseline space-x-2">
                        <span className="text-emerald-400 font-bold">{ev.actor}</span>
                        <span className="text-zinc-300">triggered action:</span>
                        <span className="text-zinc-100 font-semibold">{ev.action}</span>
                        {ev.op_id && (
                          <span className="text-zinc-500 text-[9px]">(Op ID: `{ev.op_id.substring(0, 8)}...`)</span>
                        )}
                      </div>

                      {ev.payload && Object.keys(ev.payload).length > 0 && (
                        <div className="bg-zinc-950 p-2.5 rounded border border-zinc-900 text-zinc-400 overflow-x-auto text-[9px]">
                          <pre>{JSON.stringify(ev.payload, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Safety Control (Circuit Breakers) */}
        {activeTab === "safety" && (
          <div className="space-y-6">
            <div>
              <h3 className="text-sm font-semibold text-zinc-200">Circuit Breakers</h3>
              <p className="text-[10px] text-zinc-500">Real-time status of safety circuit breakers guarding adapter invocations (§4.4)</p>
            </div>

            {breakersLoading && <div className="text-zinc-500 text-xs py-10 text-center">Loading safety status...</div>}

            {breakers && breakers.length === 0 && (
              <div className="text-center py-16 border border-dashed border-zinc-800 rounded-lg">
                <p className="text-xs text-zinc-400">No active circuit breakers defined.</p>
                <p className="text-[10px] text-zinc-600 mt-1">Circuit breakers trip dynamically when adapter calls trigger repeated failures.</p>
              </div>
            )}

            {breakers && breakers.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {breakers.map((cb: any) => {
                  const isOpen = cb.state.toUpperCase() === "OPEN";
                  return (
                    <div 
                      key={`${cb.brand_id}-${cb.domain}`} 
                      className={`border rounded-lg p-5 space-y-4 ${isOpen ? "bg-red-950/10 border-red-900" : "bg-zinc-900/20 border-zinc-900"}`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="space-y-0.5">
                          <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-200">{cb.domain}</h4>
                          <p className="text-[9px] text-zinc-500">Brand Context: {cb.brand_id}</p>
                        </div>
                        
                        <div className="flex items-center space-x-1.5">
                          {isOpen ? (
                            <>
                              <XCircle className="h-4 w-4 text-red-500" />
                              <span className="text-red-400 text-[10px] font-bold uppercase tracking-wider">OPEN (TRIPPED)</span>
                            </>
                          ) : (
                            <>
                              <CheckCircle className="h-4 w-4 text-emerald-400" />
                              <span className="text-emerald-400 text-[10px] font-bold uppercase tracking-wider">CLOSED (HEALTHY)</span>
                            </>
                          )}
                        </div>
                      </div>

                      <div className="border-t border-zinc-900/60 pt-3 space-y-2 text-[10px] text-zinc-400 font-mono">
                        <div className="flex justify-between">
                          <span>Consecutive Failures:</span>
                          <span className={cb.consecutive_failures > 0 ? "text-amber-400 font-bold" : "text-zinc-500"}>
                            {cb.consecutive_failures} / 3
                          </span>
                        </div>
                        {cb.tripped_at && (
                          <div className="flex justify-between">
                            <span>Tripped Timestamp:</span>
                            <span>{new Date(cb.tripped_at).toLocaleString()}</span>
                          </div>
                        )}
                        {cb.last_failure_at && (
                          <div className="flex justify-between">
                            <span>Last Failure Occurred:</span>
                            <span>{new Date(cb.last_failure_at).toLocaleString()}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

      </main>
    </div>
  );
}
