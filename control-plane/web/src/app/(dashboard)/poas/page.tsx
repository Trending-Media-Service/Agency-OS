"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { 
  BarChart3, 
  TrendingUp, 
  Coins, 
  TrendingDown, 
  ShoppingBag,
  Sparkles
} from "lucide-react";
import { Button } from "@/components/ui/button";

interface CampaignReport {
  campaign_id: string;
  campaign_name: string;
  platform: string;
  status: string;
  spend_minor: number;
  contribution_margin_minor: number;
  poas: number | null;
  roas: number | null;
  ipoas: number | null;
  alpha_inc: number;
  breakdown: {
    gross_revenue_minor: number;
    discount_minor: number;
    cogs_minor: number;
    fulfillment_minor: number;
    marketplace_fee_minor: number;
    refunds_minor: number;
    contribution_margin_minor: number;
  };
  clicks: number;
  orders: number;
}

interface PoasResponse {
  brand_id: string;
  reports: CampaignReport[];
}

export default function PoasPage() {
  const { request } = useApi();
  const { activeBrandId } = useTenant();

  // Fetch POAS report from FastAPI backend
  const { data: poasData, isLoading } = useQuery<PoasResponse>({
    queryKey: ["brandPoas", activeBrandId],
    queryFn: () => request(`/brands/${activeBrandId}/poas` as "/brands/{brand_id}/poas", "get") as Promise<PoasResponse>,
    enabled: !!activeBrandId
  });

  if (!activeBrandId) {
    return (
      <div className="py-12 text-center text-zinc-500 text-xs font-mono">
        Please select a Brand Cockpit in the header to view campaign-level POAS analytics.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="py-12 text-center text-zinc-500 text-xs font-mono animate-pulse">
        Calculating brand contribution margins and POAS...
      </div>
    );
  }

  const reports = poasData?.reports || [];

  // Calculate Rollup Metrics
  const totalSpend = reports.reduce((acc, r) => acc + r.spend_minor, 0) / 100;
  const totalMargin = reports.reduce((acc, r) => acc + r.contribution_margin_minor, 0) / 100;
  const totalRevenue = reports.reduce((acc, r) => acc + r.breakdown.gross_revenue_minor, 0) / 100;
  const blendedPoas = totalSpend > 0 ? totalMargin / totalSpend : 0;
  const totalOrders = reports.reduce((acc, r) => acc + r.orders, 0);

  // Identify worst performing campaign (POAS < 1.0)
  const bleedingCampaigns = reports.filter(r => r.poas !== null && r.poas < 1.0);

  return (
    <div className="space-y-8 animate-in fade-in-50 duration-300">
      {/* Header */}
      <div className="space-y-1">
        <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
          <BarChart3 className="h-4 w-4 text-zinc-500" />
          Campaign POAS Cockpit
        </h2>
        <p className="text-xs text-zinc-500">
          Line-item contribution margins, fulfillment overhead, and incrementality-adjusted Profit on Ad Spend.
        </p>
      </div>

      {/* KPI Rollup Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-zinc-900/25 border border-zinc-900 rounded-xl p-4 space-y-1.5">
          <span className="text-[8px] text-zinc-500 uppercase font-bold tracking-wider flex items-center gap-1">
            <Coins className="h-3.5 w-3.5" /> Total Ad Spend
          </span>
          <div className="text-xl font-bold text-zinc-100 font-mono">
            {totalSpend.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })}
          </div>
        </div>

        <div className="bg-zinc-900/25 border border-zinc-900 rounded-xl p-4 space-y-1.5">
          <span className="text-[8px] text-zinc-500 uppercase font-bold tracking-wider flex items-center gap-1">
            <TrendingUp className="h-3.5 w-3.5 text-emerald-500" /> Net Contribution Margin
          </span>
          <div className={`text-xl font-bold font-mono ${totalMargin >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {totalMargin.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })}
          </div>
        </div>

        <div className="bg-zinc-900/25 border border-zinc-900 rounded-xl p-4 space-y-1.5">
          <span className="text-[8px] text-zinc-500 uppercase font-bold tracking-wider flex items-center gap-1">
            <Sparkles className="h-3.5 w-3.5 text-purple-400" /> Blended POAS
          </span>
          <div className={`text-xl font-bold font-mono ${blendedPoas >= 1.2 ? "text-emerald-400" : blendedPoas >= 1.0 ? "text-zinc-200" : "text-red-400"}`}>
            {blendedPoas.toFixed(2)}x
          </div>
        </div>

        <div className="bg-zinc-900/25 border border-zinc-900 rounded-xl p-4 space-y-1.5">
          <span className="text-[8px] text-zinc-500 uppercase font-bold tracking-wider flex items-center gap-1">
            <ShoppingBag className="h-3.5 w-3.5" /> Attributed Sales
          </span>
          <div className="text-xl font-bold text-zinc-100 font-mono">
            {totalOrders} <span className="text-[10px] text-zinc-500 font-sans font-normal">conversions</span>
          </div>
        </div>
      </div>

      {/* Bleeding Campaign Alert Banner */}
      {bleedingCampaigns.length > 0 && (
        <div className="bg-red-950/30 border border-red-900/60 rounded-xl p-4 flex items-start gap-3">
          <TrendingDown className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="text-xs font-bold text-red-200">Bleeding Campaigns Detected</h4>
            <p className="text-[10px] text-red-400 leading-relaxed">
              There are {bleedingCampaigns.length} campaigns generating negative contribution margins or a POAS below 1.0x (meaning you are losing money on every order attributed to them). We recommend proposing a budget trim or an audience signal swap.
            </p>
          </div>
        </div>
      )}

      {/* Main Campaign Analytics Table */}
      <div className="bg-zinc-900/10 border border-zinc-900 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-zinc-900 text-zinc-500 font-mono text-[9px] uppercase tracking-wider bg-zinc-900/5">
              <th className="px-6 py-3.5">Campaign Name</th>
              <th className="px-6 py-3.5">Platform</th>
              <th className="px-6 py-3.5 text-right">Ad Spend</th>
              <th className="px-6 py-3.5 text-right">Gross Sales</th>
              <th className="px-6 py-3.5 text-right">Refunds & COGS</th>
              <th className="px-6 py-3.5 text-right">Net Margin</th>
              <th className="px-6 py-3.5 text-right">POAS</th>
              <th className="px-6 py-3.5 text-center">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-900/60 font-mono text-[11px] text-zinc-300">
            {reports.map((report) => {
              const isBleeding = report.poas !== null && report.poas < 1.0;
              const spend = report.spend_minor / 100;
              const revenue = report.breakdown.gross_revenue_minor / 100;
              const margin = report.contribution_margin_minor / 100;
              const overhead = (report.breakdown.cogs_minor + report.breakdown.refunds_minor + report.breakdown.fulfillment_minor + report.breakdown.marketplace_fee_minor) / 100;

              return (
                <tr 
                  key={report.campaign_id} 
                  className={`hover:bg-zinc-900/20 transition-all ${isBleeding ? "bg-red-950/5" : ""}`}
                >
                  <td className="px-6 py-4 font-sans font-medium text-zinc-100 max-w-xs truncate">
                    {report.campaign_name}
                  </td>
                  <td className="px-6 py-4 text-zinc-500 uppercase text-[9px]">
                    {report.platform}
                  </td>
                  <td className="px-6 py-4 text-right">
                    {spend.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-6 py-4 text-right text-zinc-400">
                    {revenue.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-6 py-4 text-right text-zinc-600">
                    {overhead.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })}
                  </td>
                  <td className={`px-6 py-4 text-right font-bold ${margin >= 0 ? "text-emerald-500/90" : "text-red-400"}`}>
                    {margin.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })}
                  </td>
                  <td className={`px-6 py-4 text-right font-bold text-xs ${report.poas === null ? "text-zinc-600" : isBleeding ? "text-red-400" : "text-emerald-400"}`}>
                    {report.poas !== null ? `${report.poas.toFixed(2)}x` : "n/a"}
                  </td>
                  <td className="px-6 py-4 text-center">
                    <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold uppercase ${report.status === "active" ? "bg-emerald-950 border border-emerald-900 text-emerald-400" : "bg-zinc-950 border border-zinc-850 text-zinc-600"}`}>
                      {report.status}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
