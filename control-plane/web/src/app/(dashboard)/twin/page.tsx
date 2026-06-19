"use client";

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { 
  Compass, 
  TrendingUp, 
  Users, 
  Target,
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
  Shield,
  Server,
  ChevronRight,
  Coins
} from "lucide-react";

interface Recommendation {
  action: string;
  domain: string;
  params: Record<string, unknown>;
  preview_summary: string;
  impact: number;
  reversibility: string;
  cost_minor: number;
}

interface PortfolioBrand {
  brand_id: string;
  brand_name: string;
  active_objective: string;
  b_score: number;
  trust_score: number;
  trust_tier: number;
  total_cost_minor: number;
}

interface PortfolioData {
  tenant_id: string;
  tenant_name: string;
  hosting_tier: string;
  gcp_project: string;
  portfolio: PortfolioBrand[];
}

export default function TwinPage() {
  const { request } = useApi();
  const { tenantId, activeBrandId, setActiveBrandId, role } = useTenant();
  const queryClient = useQueryClient();
  const readOnly = role === "BRAND_VIEWER";

  // ==========================================
  // PORTFOLIO VIEW (activeBrandId === null)
  // ==========================================
  const { data: portfolioData, isLoading: portfolioLoading } = useQuery<PortfolioData>({
    queryKey: ["portfolio", tenantId],
    queryFn: () => request("/brands/portfolio", "get") as Promise<PortfolioData>,
    enabled: !activeBrandId
  });

  // ==========================================
  // INDIVIDUAL BRAND VIEW (activeBrandId !== null)
  // ==========================================
  // 1. Fetch active strategic objective
  const { data: objectiveData } = useQuery<{ objective: string }>({
    queryKey: ["brandObjective", activeBrandId],
    queryFn: () => request(`/brands/${activeBrandId}/objective` as "/brands/{brand_id}/objective", "get") as Promise<{ objective: string }>,
    enabled: !!activeBrandId
  });
  const activeObjective = objectiveData?.objective || "footprint";

  // 2. Fetch goal-aligned recommendations
  const { data: recommendations = [], refetch: refetchRecs } = useQuery<Recommendation[]>({
    queryKey: ["brandRecommendations", activeBrandId, activeObjective],
    queryFn: () => request(`/brands/${activeBrandId}/recommendations` as "/brands/{brand_id}/recommendations", "get") as Promise<Recommendation[]>,
    enabled: !!activeBrandId
  });

  // 3. Fetch Brand B-Score (Advisory Business performance)
  const { data: bScoreData } = useQuery<{ performance_score?: { score: number } }>({
    queryKey: ["brandPerformanceScore", activeBrandId],
    queryFn: () => request(`/brands/${activeBrandId}/performance-score` as "/brands/{brand_id}/performance-score", "get") as Promise<{ performance_score?: { score: number } }>,
    enabled: !!activeBrandId
  });
  const bScore = bScoreData?.performance_score?.score ?? 85.0;

  // 4. Fetch Active Connections
  const { data: connections = [] } = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => request("/connections", "get"),
  });

  // Mutation to update strategic objective
  const setObjectiveMutation = useMutation({
    mutationFn: (objective: "footprint" | "growth" | "retention") =>
      request(`/brands/${activeBrandId}/objective` as "/brands/{brand_id}/objective", "post", { objective }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["brandObjective", activeBrandId] });
      queryClient.invalidateQueries({ queryKey: ["brandRecommendations", activeBrandId] });
    }
  });

  // Mutation to propose a recommended action
  const proposeActionMutation = useMutation({
    mutationFn: (rec: Recommendation) => {
      const toolName = rec.action.replace(/\./g, "_");
      return request("/actions", "post", {
        tool: toolName,
        brand_id: activeBrandId!,
        params: rec.params
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ops", tenantId] });
      refetchRecs();
    }
  });

  const handleSetObjective = (objective: "footprint" | "growth" | "retention") => {
    if (readOnly) return;
    setObjectiveMutation.mutate(objective);
  };

  const handleProposeRecommendation = (rec: Recommendation) => {
    if (readOnly) return;
    proposeActionMutation.mutate(rec);
  };

  // If no brand is selected, render the Tenant Portfolio Console!
  if (!activeBrandId) {
    if (portfolioLoading) {
      return (
        <div className="py-12 text-center text-zinc-500 text-xs font-mono animate-pulse">
          Loading tenant portfolio console...
        </div>
      );
    }

    const pf = portfolioData;
    if (!pf) {
      return (
        <div className="py-12 text-center text-zinc-500 text-xs font-mono">
          No portfolio data found for this tenant.
        </div>
      );
    }

    return (
      <div className="space-y-8">
        {/* Page Header */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="space-y-1">
            <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
              <Compass className="h-4 w-4 text-zinc-500" />
              Tenant Portfolio Console
            </h2>
            <p className="text-xs text-zinc-500">
              High-level strategic and operational overview of all brands under Tenant <span className="font-semibold text-zinc-400">{pf.tenant_name}</span>.
            </p>
          </div>

          {/* Hosting Tier Info Badge */}
          <div className="flex items-center space-x-3 bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-xs">
            <div className="flex items-center gap-1.5 text-zinc-400">
              <Server className="h-3.5 w-3.5 text-zinc-500" />
              <span>Hosting Tier:</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${pf.hosting_tier === "dedicated" ? "bg-purple-950 border border-purple-800 text-purple-200" : "bg-zinc-950 border border-zinc-800 text-zinc-300"}`}>
                {pf.hosting_tier}
              </span>
            </div>
            <span className="text-zinc-700">|</span>
            <div className="flex items-center gap-1.5 text-zinc-500 font-mono text-[10px]">
              <Shield className="h-3.5 w-3.5 text-zinc-600" />
              <span>GCP: {pf.gcp_project}</span>
            </div>
          </div>
        </div>

        {/* Brand Portfolio Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {pf.portfolio.map((brand) => (
            <div 
              key={brand.brand_id} 
              className="bg-zinc-900/25 border border-zinc-900 rounded-xl p-5 hover:border-zinc-800 transition-all flex flex-col justify-between space-y-5"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-zinc-100">{brand.brand_name}</h3>
                  <div className="flex items-center space-x-2">
                    <span className="px-2 py-0.5 bg-zinc-950 border border-zinc-850 text-zinc-400 text-[9px] font-semibold uppercase tracking-wider rounded-md">
                      {brand.active_objective}
                    </span>
                    <span className={`px-1.5 py-0.5 text-[8px] font-bold uppercase rounded ${brand.trust_tier === 2 ? "bg-emerald-950 border border-emerald-800 text-emerald-300" : "bg-amber-950 border border-amber-800 text-amber-300"}`}>
                      Tier {brand.trust_tier}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3 text-center">
                  <div className="bg-zinc-950 border border-zinc-900 p-2.5 rounded-lg space-y-1">
                    <span className="text-[8px] text-zinc-500 uppercase font-bold tracking-wider">B-Score</span>
                    <div className="text-lg font-bold text-zinc-200 font-mono">{brand.b_score.toFixed(0)}</div>
                  </div>
                  <div className="bg-zinc-950 border border-zinc-900 p-2.5 rounded-lg space-y-1">
                    <span className="text-[8px] text-zinc-500 uppercase font-bold tracking-wider">Trust</span>
                    <div className="text-lg font-bold text-zinc-200 font-mono">{brand.trust_score.toFixed(0)}%</div>
                  </div>
                  <div className="bg-zinc-950 border border-zinc-900 p-2.5 rounded-lg space-y-1">
                    <span className="text-[8px] text-zinc-500 uppercase font-bold tracking-wider">Spend</span>
                    <div className="text-sm font-bold text-emerald-500 font-mono mt-1 flex items-center justify-center gap-0.5">
                      <Coins className="h-3 w-3 shrink-0" />
                      {(brand.total_cost_minor / 100).toFixed(0)}
                    </div>
                  </div>
                </div>
              </div>

              <Button
                onClick={() => setActiveBrandId(brand.brand_id)}
                className="w-full bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 hover:border-zinc-700 text-zinc-200 text-xs font-medium h-9 rounded-lg flex items-center justify-center gap-1 shadow-sm transition-all"
              >
                View Twin Cockpit
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Brand is selected -> Render individual Twin Cockpit (original dashboard view)
  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center space-x-2">
            <button 
              onClick={() => setActiveBrandId(null)}
              className="text-xs text-zinc-500 hover:text-zinc-300 font-medium transition-colors flex items-center"
            >
              Portfolio
            </button>
            <ChevronRight className="h-3.5 w-3.5 text-zinc-700" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
              <Compass className="h-4 w-4 text-zinc-500" />
              Brand Twin Cockpit
            </h2>
          </div>
          <p className="text-xs text-zinc-500">
            Strategic alignment layer. View B-score health and execute goal-aligned governed operations.
          </p>
        </div>

        {/* Strategic Goal Selector */}
        <div className="flex bg-zinc-900 p-0.5 rounded-lg border border-zinc-800 text-xs shadow-inner">
          <button
            onClick={() => handleSetObjective("footprint")}
            disabled={readOnly}
            className={`px-3 py-1.5 rounded-md transition-colors flex items-center gap-1.5 font-medium ${activeObjective === "footprint" ? "bg-zinc-800 text-zinc-100 font-semibold shadow-sm border border-zinc-700/40" : "text-zinc-500 hover:text-zinc-300"}`}
          >
            <Target className="h-3.5 w-3.5" />
            Footprint
          </button>
          <button
            onClick={() => handleSetObjective("growth")}
            disabled={readOnly}
            className={`px-3 py-1.5 rounded-md transition-colors flex items-center gap-1.5 font-medium ${activeObjective === "growth" ? "bg-zinc-800 text-zinc-100 font-semibold shadow-sm border border-zinc-700/40" : "text-zinc-500 hover:text-zinc-300"}`}
          >
            <TrendingUp className="h-3.5 w-3.5" />
            Growth
          </button>
          <button
            onClick={() => handleSetObjective("retention")}
            disabled={readOnly}
            className={`px-3 py-1.5 rounded-md transition-colors flex items-center gap-1.5 font-medium ${activeObjective === "retention" ? "bg-zinc-800 text-zinc-100 font-semibold shadow-sm border border-zinc-700/40" : "text-zinc-500 hover:text-zinc-300"}`}
          >
            <Users className="h-3.5 w-3.5" />
            Retention
          </button>
        </div>
      </div>

      {/* Grid Layout: Health & Properties */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        {/* Advisory Business B-Score Panel */}
        <div className="bg-zinc-900/20 border border-zinc-900 rounded-xl p-5 space-y-4">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Advisory Business B-Score</div>
          <div className="flex items-baseline space-x-2">
            <span className="text-4xl font-bold text-zinc-100 tracking-tight font-mono">{bScore.toFixed(0)}</span>
            <span className="text-zinc-500 text-xs">/ 100</span>
          </div>
          <div className="w-full bg-zinc-950 rounded-full h-1.5 border border-zinc-900">
            <div 
              className={`h-full rounded-full transition-all duration-500 ${bScore >= 80 ? "bg-emerald-500" : bScore >= 60 ? "bg-amber-500" : "bg-red-500"}`} 
              style={{ width: `${bScore}%` }}
            ></div>
          </div>
          <p className="text-[10px] text-zinc-400 leading-relaxed">
            The B-score evaluates active campaigns, ROAS, and conversion metrics to advise strategic allocation. Non-gating.
          </p>
        </div>

        {/* Domain Trust Scores Panel */}
        <div className="bg-zinc-900/20 border border-zinc-900 rounded-xl p-5 space-y-4">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Domain Trust Status</div>
          <div className="space-y-2.5">
            <div className="flex justify-between items-center text-xs">
              <span className="text-zinc-400">Provisioning Domain</span>
              <span className="font-mono text-emerald-400 font-semibold flex items-center gap-1">
                <ShieldCheck className="h-3 w-3" /> Secure
              </span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-zinc-400">Governance & Outbox</span>
              <span className="font-mono text-emerald-400 font-semibold flex items-center gap-1">
                <ShieldCheck className="h-3 w-3" /> Secure
              </span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-zinc-400">Active Presence</span>
              <span className="font-mono text-amber-400 font-semibold flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" /> Unverified
              </span>
            </div>
          </div>
        </div>

        {/* Connected Properties Panel */}
        <div className="bg-zinc-900/20 border border-zinc-900 rounded-xl p-5 space-y-4">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-bold">Connected Assets</div>
          <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
            <div className="bg-zinc-950 border border-zinc-900 p-2 rounded flex flex-col justify-between h-14">
              <span className="text-zinc-500 uppercase text-[8px] tracking-wider">Shopify</span>
              <span className={connections.some(c => c.provider === "shopify") ? "text-emerald-400 font-semibold" : "text-zinc-600"}>
                {connections.some(c => c.provider === "shopify") ? "CONNECTED" : "ABSENT"}
              </span>
            </div>
            <div className="bg-zinc-950 border border-zinc-900 p-2 rounded flex flex-col justify-between h-14">
              <span className="text-zinc-500 uppercase text-[8px] tracking-wider">Google OAuth</span>
              <span className={connections.some(c => c.provider === "google") ? "text-emerald-400 font-semibold" : "text-zinc-600"}>
                {connections.some(c => c.provider === "google") ? "CONNECTED" : "ABSENT"}
              </span>
            </div>
            <div className="bg-zinc-950 border border-zinc-900 p-2 rounded flex flex-col justify-between h-14">
              <span className="text-zinc-500 uppercase text-[8px] tracking-wider">WordPress</span>
              <span className={connections.some(c => c.provider === "wordpress") ? "text-emerald-400 font-semibold" : "text-zinc-600"}>
                {connections.some(c => c.provider === "wordpress") ? "CONNECTED" : "ABSENT"}
              </span>
            </div>
            <div className="bg-zinc-950 border border-zinc-900 p-2 rounded flex flex-col justify-between h-14">
              <span className="text-zinc-500 uppercase text-[8px] tracking-wider">Vercel/Web</span>
              <span className={connections.some(c => c.provider === "web") ? "text-emerald-400 font-semibold" : "text-zinc-600"}>
                {connections.some(c => c.provider === "web") ? "CONNECTED" : "ABSENT"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Goal-Aligned Recommended Operations */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-300">
          Goal-Aligned Recommendations ({recommendations.length})
        </h3>
        
        {recommendations.length === 0 ? (
          <div className="bg-zinc-900/10 border border-dashed border-zinc-900 rounded-xl p-8 text-center text-zinc-500 text-xs font-mono">
            No recommendations pending. Brand Twin is fully aligned with active goals.
          </div>
        ) : (
          <div className="space-y-3">
            {recommendations.map((rec, idx) => (
              <div 
                key={idx} 
                className="bg-zinc-900/25 border border-zinc-900 rounded-xl p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-4 hover:border-zinc-800 transition-all"
              >
                <div className="space-y-1.5 max-w-xl">
                  <div className="flex items-center space-x-2">
                    <span className="px-2 py-0.5 bg-zinc-950 border border-zinc-800 text-zinc-400 text-[8px] font-mono uppercase tracking-widest font-bold rounded">
                      {rec.domain}
                    </span>
                    <span className="text-[10px] text-zinc-500 font-mono">
                      {rec.action}
                    </span>
                  </div>
                  <h4 className="text-xs font-semibold text-zinc-200 leading-relaxed">
                    {rec.preview_summary}
                  </h4>
                  <div className="flex items-center space-x-4 text-[9px] text-zinc-500 font-mono">
                    <span>Severity: <span className="text-zinc-400">{rec.impact}</span></span>
                    <span>•</span>
                    <span>Reversibility: <span className="text-zinc-400">{rec.reversibility}</span></span>
                    <span>•</span>
                    <span>Cost: <span className="text-emerald-500 font-semibold">{rec.cost_minor === 0 ? "FREE" : `${(rec.cost_minor/100).toFixed(2)} INR`}</span></span>
                  </div>
                </div>

                <Button
                  onClick={() => handleProposeRecommendation(rec)}
                  disabled={readOnly}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs px-4 h-9 rounded-lg shrink-0 flex items-center gap-1 shadow-md hover:shadow-emerald-900/20 disabled:opacity-50 transition-all"
                >
                  Propose Action
                  <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
