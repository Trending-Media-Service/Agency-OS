"use client";

import React, { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { ActionPanel } from "@/components/ActionPanel";
import { OpDetailDrawer, OpDetailData } from "@/components/op-detail-drawer";
import { 
  Database, 
  Network, 
  History, 
  Sliders,
  RefreshCw,
  ShieldAlert,
  Compass
} from "lucide-react";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { request } = useApi();
  const {
    tenantId,
    setTenantId,
    activeBrandId,
    setActiveBrandId,
    role,
    setRole,
    operatorToken,
    setOperatorToken,
    knownTenants,
    addKnownTenant
  } = useTenant();

  // Deduplicate brands for the currently selected tenant
  const tenantBrands = knownTenants.filter((t) => t.tenantId === tenantId);
  const uniqueBrands = Array.from(
    new Map(tenantBrands.map((b) => [b.brandId, b])).values()
  );

  const [showCreateTenant, setShowCreateTenant] = useState(false);
  const [newTenantName, setNewTenantName] = useState("");
  const [newBrandName, setNewBrandName] = useState("");
  const [createTenantLoading, setCreateTenantLoading] = useState(false);
  const [createTenantError, setCreateTenantError] = useState<string | null>(null);

  // 1. Fetch Circuit Breakers to show tripped alert banner
  const { data: breakers, refetch: refetchBreakers } = useQuery({
    queryKey: ["breakers", tenantId],
    queryFn: () => request("/circuit-breakers", "get"),
    refetchInterval: 5000,
  });

  // 2. Fetch Audit Verify for security status in tabs
  const { data: auditVerify } = useQuery({
    queryKey: ["auditVerify", tenantId],
    queryFn: () => request("/audit/verify", "get"),
    refetchInterval: 10000,
  });

  // 3. Drawer URL State Integration (?opId=...)
  const selectedOpId = searchParams.get("opId");
  const { data: selectedOp, isLoading: selectedOpLoading } = useQuery({
    queryKey: ["opDetail", selectedOpId],
    queryFn: () => selectedOpId ? request(`/ops/${selectedOpId}` as "/ops/{op_id}", "get") : null,
    enabled: selectedOpId !== null,
  });

  const { refetch: refetchOps } = useQuery({
    queryKey: ["ops", tenantId],
    enabled: false
  });
  const { refetch: refetchConns } = useQuery({
    queryKey: ["connections", tenantId],
    enabled: false
  });
  const { refetch: refetchAudit } = useQuery({
    queryKey: ["auditEvents", tenantId],
    enabled: false
  });

  // Decision mutation for drawer
  const decisionMutation = useMutation({
    mutationFn: ({ opId, decision, reason }: { opId: string, decision: "approve" | "reject" | "modify", reason?: string }) => 
      request(`/ops/${opId}/decision` as "/ops/{op_id}/decision", "post", {
        decision,
        actor: "chandan",
        role: role,
        surface: "web",
        reason
      }),
    onSuccess: () => {
      refetchOps();
      closeDrawer();
    }
  });

  const closeDrawer = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("opId");
    router.push(`${pathname}?${params.toString()}`);
  };

  const handleDecision = (opId: string, decision: "approve" | "reject" | "modify", reason?: string) => {
    decisionMutation.mutate({ opId, decision, reason });
  };

  const handleCreateTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTenantName.trim() || !newBrandName.trim()) return;

    setCreateTenantLoading(true);
    setCreateTenantError(null);
    try {
      const res = await request("/tenants", "post", {
        name: newTenantName.trim(),
        brand_name: newBrandName.trim()
      }) as { tenant_id: string; brand_id: string };
      
      addKnownTenant(res.tenant_id, newTenantName.trim(), res.brand_id, newBrandName.trim());
      setTenantId(res.tenant_id);
      
      setNewTenantName("");
      setNewBrandName("");
      setShowCreateTenant(false);
    } catch (err: unknown) {
      setCreateTenantError(err instanceof Error ? err.message : "Failed to create tenant");
    } finally {
      setCreateTenantLoading(false);
    }
  };

  const syncAll = () => {
    refetchOps();
    refetchConns();
    refetchBreakers();
    refetchAudit();
  };

  const trippedBreakers = breakers?.filter((b) => b.state.toUpperCase() === "OPEN") || [];

  return (
    <div className="flex-1 flex flex-col bg-zinc-950 text-zinc-50 font-sans">
      {/* Global Tripped Circuit Breaker Alert Banner */}
      {trippedBreakers.length > 0 && (
        <div className="bg-red-950/80 border-b border-red-800 text-red-200 px-6 py-3 flex items-center space-x-3 text-xs">
          <ShieldAlert className="h-4 w-4 text-red-400 shrink-0" />
          <div className="flex-1">
            <span className="font-bold uppercase tracking-wider text-red-400 mr-2">[Circuit Breaker Tripped]</span>
            Safety shutdown active on domain(s): <span className="font-semibold">{trippedBreakers.map((b) => `'${b.domain}'`).join(", ")}</span>. Automatic executions are blocked.
          </div>
        </div>
      )}

      {/* Header */}
      <header className="border-b border-zinc-900 px-8 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-6">
          <div className="space-y-0.5">
            <h1 className="text-base font-bold tracking-tight">Governance Console</h1>
            <div className="flex items-center space-x-2 text-[10px] text-zinc-500 font-mono">
              <span>Tenant:</span>
              <select 
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                className="bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-zinc-300 focus:outline-none focus:border-zinc-700 font-sans"
              >
                {Array.from(new Map(knownTenants.map(t => [t.tenantId, t])).values()).map((t) => (
                  <option key={t.tenantId} value={t.tenantId}>
                    {t.tenantName} ({t.tenantId})
                  </option>
                ))}
              </select>

              <span>| Brand:</span>
              <select
                value={activeBrandId || ""}
                onChange={(e) => setActiveBrandId(e.target.value || null)}
                className="bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-zinc-300 focus:outline-none focus:border-zinc-700 font-sans"
              >
                {uniqueBrands.map((b) => (
                  <option key={b.brandId} value={b.brandId}>
                    {b.brandName} ({b.brandId})
                  </option>
                ))}
              </select>

              <span>| Role: {role}</span>
            </div>
          </div>
          
          <Button
            size="sm"
            onClick={() => setShowCreateTenant(true)}
            className="bg-zinc-900 hover:bg-zinc-850 text-zinc-300 border border-zinc-800 text-[10px] h-7 px-2.5 rounded gap-1"
          >
            + New Tenant
          </Button>
        </div>
        
        <div className="flex items-center space-x-3">
          {/* Operator token (authenticates operator-gated calls; stored in this browser only) */}
          <input
            type="password"
            placeholder="Operator token"
            value={operatorToken}
            onChange={(e) => setOperatorToken(e.target.value)}
            title={operatorToken ? "Operator token set" : "Paste your OPERATOR_TOKEN to authenticate operator actions"}
            className={`bg-zinc-900 border rounded px-2 py-1 text-[10px] text-zinc-300 focus:outline-none focus:border-zinc-700 font-mono w-32 ${operatorToken ? "border-emerald-800/60" : "border-zinc-800"}`}
          />

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
            <button 
              onClick={() => setRole("BRAND_VIEWER")}
              className={`px-2 py-1 rounded transition-colors ${role === "BRAND_VIEWER" ? "bg-zinc-800 text-white font-semibold" : "text-zinc-500 hover:text-zinc-300"}`}
            >
              Viewer
            </button>
          </div>

          <Button 
            variant="outline" 
            onClick={syncAll}
            className="border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-[10px] px-2 h-7 gap-1"
          >
            <RefreshCw className="h-3 w-3" />
            Sync
          </Button>
        </div>
      </header>

      {/* Split Layout Container */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* Left Column: explicit Operator Actions panel (replaces the conversational chat) */}
        <div className="w-[380px] border-r border-zinc-900 flex flex-col bg-zinc-900/10 hidden lg:flex shrink-0">
          <ActionPanel />
        </div>

        {/* Right Column: Tabbed Dashboard Main content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Tabs Selector Navigation */}
          <div className="border-b border-zinc-900 px-8 flex space-x-6 text-[11px] bg-zinc-900/5">
            <button
              onClick={() => router.push("/twin")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${pathname === "/twin" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
            >
              <Compass className="h-3.5 w-3.5" />
              Brand Twin
            </button>
            <button
              onClick={() => router.push("/ops")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${pathname === "/ops" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
            >
              <Database className="h-3.5 w-3.5" />
              Operations Queue
            </button>
            <button
              onClick={() => router.push("/connections")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${pathname === "/connections" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
            >
              <Network className="h-3.5 w-3.5" />
              Active Connections
            </button>
            <button
              onClick={() => router.push("/audit")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${pathname === "/audit" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
            >
              <History className="h-3.5 w-3.5" />
              Audit Trail
              {auditVerify?.ok ? (
                <span className="ml-1 px-1.5 py-0.2 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 rounded text-[8px] font-mono uppercase tracking-widest font-bold">Secured</span>
              ) : (
                <span className="ml-1 px-1.5 py-0.2 bg-red-500/10 border border-red-500/30 text-red-400 rounded text-[8px] font-mono uppercase tracking-widest font-bold">Corrupt</span>
              )}
            </button>
            <button
              onClick={() => router.push("/safety")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${pathname === "/safety" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
            >
              <Sliders className="h-3.5 w-3.5" />
              Circuit Breakers
            </button>
          </div>

          {/* Tab Content Area */}
          <main className="flex-1 p-8 overflow-y-auto max-w-5xl w-full mx-auto">
            {children}
          </main>
        </div>

      </div>
      
      {selectedOpId && (
        <OpDetailDrawer
          opId={selectedOpId}
          opData={(selectedOp as OpDetailData) || null}
          loading={selectedOpLoading}
          onClose={closeDrawer}
          onDecision={handleDecision}
          role={role}
        />
      )}

      {showCreateTenant && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-950 border border-zinc-900 rounded-lg p-6 max-w-sm w-full space-y-4 shadow-xl">
            <div className="space-y-1">
              <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">Onboard New Tenant</h3>
              <p className="text-[10px] text-zinc-500">Create a clean tenant namespace and bootstrap its first brand.</p>
            </div>
            
            <form onSubmit={handleCreateTenant} className="space-y-3">
              <div className="space-y-1">
                <label className="text-[9px] uppercase tracking-wider text-zinc-400 font-semibold">Tenant Name</label>
                <input 
                  type="text"
                  required
                  placeholder="e.g. Ableys"
                  value={newTenantName}
                  onChange={(e) => setNewTenantName(e.target.value)}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1.5 text-[11px] text-zinc-200 focus:outline-none focus:border-zinc-700 font-mono"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[9px] uppercase tracking-wider text-zinc-400 font-semibold">First Brand Name</label>
                <input 
                  type="text"
                  required
                  placeholder="e.g. Ableys Retail"
                  value={newBrandName}
                  onChange={(e) => setNewBrandName(e.target.value)}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1.5 text-[11px] text-zinc-200 focus:outline-none focus:border-zinc-700 font-mono"
                />
              </div>

              {createTenantError && (
                <p className="text-[10px] text-red-400 font-mono">{createTenantError}</p>
              )}

              <div className="flex justify-end space-x-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowCreateTenant(false);
                    setCreateTenantError(null);
                  }}
                  className="border-zinc-800 text-zinc-400 hover:bg-zinc-900 text-[10px] h-7 px-3 rounded"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={createTenantLoading}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-[10px] h-7 px-3 rounded disabled:opacity-50"
                >
                  {createTenantLoading ? "Creating..." : "Create Tenant"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
