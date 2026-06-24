"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";

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
  
  // Erosion breakdown calculation
  const totalCogs = reports.reduce((acc, r) => acc + r.breakdown.cogs_minor, 0) / 100;
  const totalFulfillment = reports.reduce((acc, r) => acc + r.breakdown.fulfillment_minor, 0) / 100;
  const totalRefunds = reports.reduce((acc, r) => acc + r.breakdown.refunds_minor, 0) / 100;
  const netProfit = totalMargin;
  const netProfitMargin = totalRevenue > 0 ? (netProfit / totalRevenue) * 100 : 0;

  const fmtCurrency = (val: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(val);
  const fmtPercent = (val: number) => `${val.toFixed(1)}%`;
  const fmtMult = (val: number) => `${val.toFixed(2)}x`;

  const getErosionWidth = (val: number) => totalRevenue > 0 ? `${Math.max(2, (val / totalRevenue) * 100)}%` : "0%";

  return (
    <div className="flex-1 w-full text-[#dfe2f1] font-sans animate-in fade-in-50 duration-300">
      {/* Page Header */}
      <div className="mb-8 flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-3xl font-bold text-[#dfe2f1] mb-1">POAS Profit-Ledger &amp; Attribution</h2>
          <p className="text-base text-[#c2c6d6] max-w-2xl">First-party margin analysis and profit-led growth orchestration.</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center bg-[#1c1f2a] border border-[#424754] rounded-lg p-1">
            <button className="px-2 py-1 rounded-md bg-[#353944] text-[#dfe2f1] text-xs font-semibold shadow-sm">Last 30 Days</button>
            <button className="px-2 py-1 rounded-md text-[#c2c6d6] hover:text-[#dfe2f1] text-xs font-semibold transition-colors">QTD</button>
            <button className="px-2 py-1 rounded-md text-[#c2c6d6] hover:text-[#dfe2f1] text-xs font-semibold transition-colors">YTD</button>
          </div>
          <button className="bg-[#4d8eff] text-[#00285d] hover:bg-[#4d8eff]/90 transition-colors px-4 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1 ml-2">
            <span className="material-symbols-outlined text-[18px]">download</span>
            Export
          </button>
        </div>
      </div>

      {/* Bento Grid Layout */}
      <div className="grid grid-cols-12 gap-6">
        
        {/* KPI Cards (Top Row) */}
        <div className="col-span-12 md:col-span-3 bg-[#111827] border border-[#374151] rounded-xl p-6 flex flex-col justify-between">
          <div className="flex justify-between items-start mb-4">
            <h3 className="text-xs text-[#c2c6d6] uppercase tracking-wider font-semibold">Gross Revenue</h3>
            <span className="material-symbols-outlined text-[#8c909f]">payments</span>
          </div>
          <div>
            <div className="text-4xl font-bold text-[#dfe2f1]">{fmtCurrency(totalRevenue)}</div>
            <div className="flex items-center gap-1 mt-1 text-[#00a572]">
              <span className="material-symbols-outlined text-[16px]">arrow_upward</span>
              <span className="text-xs font-semibold">12.4% vs prev</span>
            </div>
          </div>
        </div>
        
        <div className="col-span-12 md:col-span-3 bg-[#111827] border border-[#374151] rounded-xl p-6 flex flex-col justify-between">
          <div className="flex justify-between items-start mb-4">
            <h3 className="text-xs text-[#c2c6d6] uppercase tracking-wider font-semibold">Total Ad Spend</h3>
            <span className="material-symbols-outlined text-[#8c909f]">campaign</span>
          </div>
          <div>
            <div className="text-4xl font-bold text-[#dfe2f1]">{fmtCurrency(totalSpend)}</div>
            <div className="flex items-center gap-1 mt-1 text-[#ffb4ab]">
              <span className="material-symbols-outlined text-[16px]">arrow_upward</span>
              <span className="text-xs font-semibold">8.1% vs prev</span>
            </div>
          </div>
        </div>

        <div className="col-span-12 md:col-span-3 bg-[#111827] border border-[#4d8eff]/30 rounded-xl p-6 flex flex-col justify-between relative overflow-hidden group">
          <div className="absolute inset-0 bg-gradient-to-br from-[#4d8eff]/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500"></div>
          <div className="flex justify-between items-start mb-4 relative z-10">
            <h3 className="text-xs text-[#adc6ff] uppercase tracking-wider font-bold">Blended POAS</h3>
            <span className="material-symbols-outlined text-[#adc6ff]">troubleshoot</span>
          </div>
          <div className="relative z-10">
            <div className="text-4xl font-bold text-[#adc6ff]">{fmtMult(blendedPoas)}</div>
            <div className="flex items-center gap-1 mt-1 text-[#00a572]">
              <span className="material-symbols-outlined text-[16px]">arrow_upward</span>
              <span className="text-xs font-semibold">0.15x vs prev</span>
            </div>
          </div>
        </div>

        <div className="col-span-12 md:col-span-3 bg-[#111827] border border-[#374151] rounded-xl p-6 flex flex-col justify-between">
          <div className="flex justify-between items-start mb-4">
            <h3 className="text-xs text-[#c2c6d6] uppercase tracking-wider font-semibold">Net Profit Margin</h3>
            <span className="material-symbols-outlined text-[#8c909f]">account_balance_wallet</span>
          </div>
          <div>
            <div className="text-4xl font-bold text-[#dfe2f1]">{fmtPercent(netProfitMargin)}</div>
            <div className="flex items-center gap-1 mt-1 text-[#00a572]">
              <span className="material-symbols-outlined text-[16px]">arrow_upward</span>
              <span className="text-xs font-semibold">2.1% bps vs prev</span>
            </div>
          </div>
        </div>

        {/* ROAS vs POAS Contrast Card (Large Chart) */}
        <div className="col-span-12 md:col-span-8 bg-[#111827] border border-[#374151] rounded-xl p-6 flex flex-col min-h-[400px]">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h3 className="text-xl font-medium text-[#dfe2f1]">ROAS vs. Margin-Adjusted POAS</h3>
              <p className="text-sm text-[#c2c6d6] mt-1">Identifying phantom growth where ROAS diverges from true profitability.</p>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 rounded-full bg-[#424754]"></div>
                <span className="text-xs text-[#c2c6d6]">Top-line ROAS</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 rounded-full bg-[#4edea3]"></div>
                <span className="text-xs text-[#c2c6d6]">True POAS</span>
              </div>
            </div>
          </div>
          
          <div className="flex-1 relative w-full h-full mt-4 border-l border-b border-[#424754]/50 ml-6 mb-6">
            <div className="absolute -left-8 top-0 h-full flex flex-col justify-between text-[10px] text-[#c2c6d6] font-mono py-2">
              <span>4.0x</span>
              <span>3.0x</span>
              <span>2.0x</span>
              <span>1.0x</span>
              <span>0.0x</span>
            </div>
            <div className="absolute inset-0 flex flex-col justify-between py-2 pointer-events-none">
              <div className="w-full h-px bg-[#424754]/20"></div>
              <div className="w-full h-px bg-[#424754]/20"></div>
              <div className="w-full h-px bg-[#424754]/20"></div>
              <div className="w-full h-px border-t border-dashed border-[#ffb4ab]/50"></div>
              <div className="w-full h-px bg-[#424754]/20"></div>
            </div>
            
            <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 100">
              <rect fill="url(#warning-gradient)" height="100" opacity="0.4" width="15" x="40" y="0"></rect>
              <rect fill="url(#warning-gradient)" height="100" opacity="0.4" width="10" x="75" y="0"></rect>
              <defs>
                <linearGradient id="warning-gradient" x1="0%" x2="0%" y1="0%" y2="100%">
                  <stop offset="0%" stopColor="#93000a" stopOpacity="0.2"></stop>
                  <stop offset="100%" stopColor="#93000a" stopOpacity="0.0"></stop>
                </linearGradient>
              </defs>
              <path d="M 0,40 Q 10,35 20,30 T 40,25 T 60,35 T 80,20 T 100,25" fill="none" stroke="#424754" strokeLinejoin="round" strokeWidth="2"></path>
              <path d="M 0,60 Q 10,55 20,50 T 40,80 T 60,55 T 80,75 T 100,45" fill="none" stroke="#4edea3" strokeLinejoin="round" strokeWidth="2"></path>
              <circle cx="45" cy="78" fill="#4edea3" r="1.5"></circle>
              <circle cx="82" cy="73" fill="#4edea3" r="1.5"></circle>
            </svg>
            
            <div className="absolute left-[40%] top-[10%] bg-[#262a35] border border-[#424754] rounded px-2 py-1 text-[10px] font-mono text-[#dfe2f1] shadow-lg transform -translate-x-1/2">
              <span className="text-[#ffb4ab] font-bold block mb-1">Warning: Margin Erosion</span>
              Holiday Discount Event<br/>
              ROAS: 3.2x | POAS: 0.8x
            </div>
            
            <div className="absolute -bottom-6 left-0 w-full flex justify-between text-[10px] text-[#c2c6d6] font-mono px-2">
              <span>W1</span><span>W2</span><span>W3</span><span>W4</span><span>W5</span><span>W6</span>
            </div>
          </div>
        </div>

        {/* Margin Erosion Chart (Stacked Bar) */}
        <div className="col-span-12 md:col-span-4 bg-[#111827] border border-[#374151] rounded-xl p-6 flex flex-col">
          <div className="mb-6">
            <h3 className="text-xl font-medium text-[#dfe2f1]">Unit Economics Erosion</h3>
            <p className="text-sm text-[#c2c6d6] mt-1">Deconstructing {fmtCurrency(totalRevenue)} Gross Revenue.</p>
          </div>
          
          <div className="flex-1 flex flex-col justify-center">
            {/* The Bar */}
            <div className="w-full h-8 flex rounded-full overflow-hidden border border-[#424754]/30 mb-8 shadow-[inset_0_2px_4px_rgba(0,0,0,0.3)]">
              <div className="bg-[#313540] h-full flex items-center justify-center text-[10px] font-bold text-[#c2c6d6] border-r border-[#0f131d]/50" style={{width: getErosionWidth(totalCogs)}}>COGS</div>
              <div className="bg-[#313540] h-full flex items-center justify-center text-[10px] font-bold text-[#c2c6d6] border-r border-[#0f131d]/50" style={{width: getErosionWidth(totalFulfillment)}}>Fulf</div>
              <div className="bg-[#93000a] h-full flex items-center justify-center text-[10px] font-bold text-[#ffdad6] border-r border-[#0f131d]/50" style={{width: getErosionWidth(totalRefunds)}}>Ret</div>
              <div className="bg-[#4d8eff] h-full flex items-center justify-center text-[10px] font-bold text-[#00285d] border-r border-[#0f131d]/50" style={{width: getErosionWidth(totalSpend)}}>Ads</div>
              <div className="bg-[#00a572] h-full flex items-center justify-center text-[10px] font-bold text-[#00311f] shadow-[0_0_15px_rgba(0,165,114,0.4)] z-10 relative" style={{width: getErosionWidth(netProfit)}}>Net</div>
            </div>
            
            {/* Legend */}
            <div className="space-y-3 font-mono text-[13px]">
              <div className="flex justify-between items-center group">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded bg-[#313540]"></div>
                  <span className="text-[#c2c6d6] group-hover:text-[#dfe2f1] transition-colors">COGS</span>
                </div>
                <span className="text-[#dfe2f1]">{fmtCurrency(totalCogs)}</span>
              </div>
              <div className="flex justify-between items-center group">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded bg-[#313540]"></div>
                  <span className="text-[#c2c6d6] group-hover:text-[#dfe2f1] transition-colors">Shipping &amp; Pick/Pack</span>
                </div>
                <span className="text-[#dfe2f1]">{fmtCurrency(totalFulfillment)}</span>
              </div>
              <div className="flex justify-between items-center group">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded bg-[#93000a]"></div>
                  <span className="text-[#c2c6d6] group-hover:text-[#dfe2f1] transition-colors">Returns &amp; Refunds</span>
                </div>
                <span className="text-[#ffb4ab]">{fmtCurrency(totalRefunds)}</span>
              </div>
              <div className="flex justify-between items-center group">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded bg-[#4d8eff]"></div>
                  <span className="text-[#c2c6d6] group-hover:text-[#dfe2f1] transition-colors">Ad Spend (CAC)</span>
                </div>
                <span className="text-[#adc6ff]">{fmtCurrency(totalSpend)}</span>
              </div>
              <div className="w-full h-px bg-[#424754]/30 my-2"></div>
              <div className="flex justify-between items-center font-bold">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded bg-[#00a572] shadow-[0_0_8px_rgba(0,165,114,0.6)]"></div>
                  <span className="text-[#dfe2f1]">Net Profit</span>
                </div>
                <span className="text-[#4edea3]">{fmtCurrency(netProfit)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Granular Ledger Table */}
        <div className="col-span-12 bg-[#111827] border border-[#374151] rounded-xl overflow-hidden flex flex-col">
          <div className="p-6 border-b border-[#424754]/50 flex justify-between items-center bg-[#171b26]/50">
            <h3 className="text-xl font-medium text-[#dfe2f1]">Attribution Ledger</h3>
            <div className="flex gap-2">
              <div className="relative">
                <span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-[#c2c6d6] text-[16px]">filter_list</span>
                <select className="bg-[#0f131d] border border-[#424754] rounded-md py-1 pl-8 pr-8 text-xs font-semibold text-[#dfe2f1] focus:border-[#adc6ff] focus:ring-1 focus:ring-[#adc6ff] appearance-none">
                  <option>All Platforms</option>
                  <option>Google Ads</option>
                  <option>Meta Ads</option>
                </select>
              </div>
            </div>
          </div>
          
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-[13px]">
              <thead className="bg-[#171b26] text-[#c2c6d6] border-b border-[#424754]/50 uppercase tracking-wider text-[10px] font-semibold">
                <tr>
                  <th className="px-6 py-3">Campaign Entity</th>
                  <th className="px-6 py-3">Status</th>
                  <th className="px-6 py-3 text-right">Spend</th>
                  <th className="px-6 py-3 text-right">Revenue</th>
                  <th className="px-6 py-3 text-right">CM Margin</th>
                  <th className="px-6 py-3 text-right">ROAS</th>
                  <th className="px-6 py-3 text-right bg-[#4d8eff]/10 text-[#adc6ff]">POAS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#424754]/30 bg-[#111827]">
                {reports.map((report) => (
                  <tr key={report.campaign_id} className="hover:bg-[#171b26] transition-colors">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="w-6 h-6 rounded bg-[#313540] flex items-center justify-center shrink-0">
                          <span className="material-symbols-outlined text-[14px] text-[#c2c6d6]">
                            {report.platform.includes('google') ? 'search' : 'group'}
                          </span>
                        </div>
                        <div>
                          <div className="text-[#dfe2f1] font-sans font-medium">{report.campaign_name}</div>
                          <div className="text-[#8c909f] text-[10px] uppercase">{report.platform}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {report.status.toLowerCase() === 'active' || report.status.toLowerCase() === 'enabled' ? (
                        <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#00a572]/10 border border-[#00a572]/20 text-[#4edea3] text-[10px]">
                          <div className="w-1.5 h-1.5 rounded-full bg-[#4edea3] animate-pulse"></div>
                          ACTIVE
                        </div>
                      ) : (
                        <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#313540] border border-[#424754] text-[#c2c6d6] text-[10px]">
                          <div className="w-1.5 h-1.5 rounded-full bg-[#8c909f]"></div>
                          {report.status}
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right text-[#dfe2f1]">{fmtCurrency(report.spend_minor / 100)}</td>
                    <td className="px-6 py-4 text-right text-[#dfe2f1]">{fmtCurrency(report.breakdown.gross_revenue_minor / 100)}</td>
                    <td className="px-6 py-4 text-right">
                      <div className={`inline-flex px-2 py-0.5 rounded ${report.contribution_margin_minor > 0 ? 'bg-[#00a572]/10 text-[#4edea3]' : 'bg-[#93000a]/10 text-[#ffb4ab]'}`}>
                        {fmtCurrency(report.contribution_margin_minor / 100)}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-right text-[#c2c6d6]">
                      {report.roas ? fmtMult(report.roas) : "N/A"}
                    </td>
                    <td className="px-6 py-4 text-right bg-[#4d8eff]/5 text-[#adc6ff] font-bold">
                      {report.poas ? fmtMult(report.poas) : "N/A"}
                    </td>
                  </tr>
                ))}
                {reports.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-6 py-8 text-center text-[#8c909f]">No active campaigns found.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  );
}
