"use client";

import React from "react";
import { useTenant } from "@/contexts/TenantContext";

export default function GrowPage() {
  const { activeBrandId } = useTenant();

  if (!activeBrandId) {
    return (
      <div className="py-12 text-center text-zinc-500 text-xs font-mono">
        Please select a Brand Cockpit in the header to view the Grow Optimizer.
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 relative bg-[#0B0F19] text-[#dfe2f1] font-sans -m-8 h-[calc(100vh-130px)]">
      {/* Header Section */}
      <header className="px-8 py-6 border-b border-[#374151] flex flex-col sm:flex-row sm:items-center justify-between gap-4 sticky top-0 bg-[#0B0F19]/90 backdrop-blur-sm z-30">
        <div>
          <h2 className="text-3xl font-semibold flex items-center gap-3">
            Grow &amp; Copywriting Optimizer
          </h2>
          <p className="text-[#c2c6d6] mt-1 text-sm">Autonomous ad copy personalization governed by brand RAG and LoRA models.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {/* Status Pills */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#00a572]/10 border border-[#00a572]/20">
            <span className="material-symbols-outlined text-[#4edea3] text-[16px]">sync_alt</span>
            <span className="text-[#4edea3] text-xs font-semibold tracking-wider">Connected Ads: Google, Meta</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#00a572]/10 border border-[#00a572]/20">
            <div className="w-2 h-2 rounded-full bg-[#4edea3] animate-pulse"></div>
            <span className="text-[#4edea3] text-xs font-semibold tracking-wider">Model Mode: Tenant LoRA Active</span>
          </div>
        </div>
      </header>

      {/* Main Dashboard Grid (Bentogrid 3 Columns) */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 max-w-7xl mx-auto">
          
          {/* Column 1: Metadata RAG Context Card (Col span 3) */}
          <div className="lg:col-span-3 flex flex-col gap-6">
            <div className="bg-[#111827] border border-[#374151] rounded-xl p-6 flex flex-col h-full">
              <div className="mb-6">
                <h3 className="text-xl font-medium text-[#dfe2f1]">Brand Identity RAG Profile</h3>
                <p className="text-[#c2c6d6] text-sm mt-1 flex items-center gap-1">
                  <span className="material-symbols-outlined text-[14px]">public</span>
                  Dynamically scraped from Shopify catalog
                </p>
              </div>
              
              {/* Tone of Voice */}
              <div className="mb-5">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-[#c2c6d6] uppercase tracking-wider font-semibold">Tone of Voice</span>
                  <button className="text-[#adc6ff] hover:text-[#d8e2ff] transition-colors">
                    <span className="material-symbols-outlined text-[16px]">edit</span>
                  </button>
                </div>
                <div className="bg-[#0B0F19] rounded-lg p-3 border border-[#374151] text-sm text-[#dfe2f1] font-mono">
                  Empathetic, sensory-friendly, clinical
                </div>
              </div>
              
              {/* Target Audience */}
              <div className="mb-5">
                <span className="text-xs text-[#c2c6d6] uppercase tracking-wider font-semibold mb-2 block">Target Audience Personas</span>
                <ul className="space-y-2">
                  <li className="flex items-start gap-2">
                    <span className="material-symbols-outlined text-[#adc6ff] text-[16px] mt-0.5">group</span>
                    <span className="text-sm text-[#dfe2f1]">Parents of sensory-seeking children</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="material-symbols-outlined text-[#adc6ff] text-[16px] mt-0.5">group</span>
                    <span className="text-sm text-[#dfe2f1]">Neurodivergent families</span>
                  </li>
                </ul>
              </div>
              
              {/* Past Performance Log */}
              <div className="mt-auto border border-[#ffb95f]/40 bg-[#ca8100]/10 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="material-symbols-outlined text-[#ffb95f] text-[16px]">history</span>
                  <span className="text-xs font-semibold text-[#ffb95f]">Past Performance Log</span>
                </div>
                <p className="text-sm text-[#c2c6d6] leading-relaxed">
                  Historical: Using the word <span className="text-[#dfe2f1] font-mono bg-[#1c1f2a] px-1 rounded">Discounts</span> in ad copy decreased conversions by 8%.
                </p>
              </div>
            </div>
          </div>

          {/* Column 2: Omnichannel Copywriting Deck (Col span 6) */}
          <div className="lg:col-span-6 flex flex-col gap-6">
            <div className="bg-[#111827] border border-[#374151] rounded-xl p-6 flex-1 flex flex-col">
              <div className="mb-6 flex justify-between items-start">
                <div>
                  <h3 className="text-xl font-medium text-[#dfe2f1]">Active Copywriting Proposals</h3>
                  <p className="text-[#c2c6d6] text-sm mt-1">Pending merchant approval for campaign mutation</p>
                </div>
                <div className="px-2 py-1 bg-[#1c1f2a] rounded border border-[#424754]/30 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#adc6ff] animate-pulse"></span>
                  <span className="text-xs font-mono text-[#adc6ff]">Awaiting Approval</span>
                </div>
              </div>

              {/* The Visual Preview Card */}
              <div className="bg-[#0B0F19] rounded-xl border border-[#374151] overflow-hidden flex flex-col">
                {/* Mockup Header */}
                <div className="bg-[#262a35] px-4 py-3 border-b border-[#374151] flex items-center gap-2">
                  <svg className="w-4 h-4 text-[#dfe2f1]" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12.545,10.239v3.821h5.445c-0.712,2.315-2.647,3.972-5.445,3.972c-3.332,0-6.033-2.701-6.033-6.032s2.701-6.032,6.033-6.032c1.498,0,2.866,0.549,3.921,1.453l2.814-2.814C17.503,2.988,15.139,2,12.545,2C7.021,2,2.543,6.477,2.543,12s4.478,10,10.002,10c8.396,0,10.249-7.85,9.426-11.748L12.545,10.239z"></path>
                  </svg>
                  <span className="text-xs font-semibold tracking-wider text-[#dfe2f1]">Google Ads Responsive Search Ad</span>
                </div>
                
                {/* Ad Mockup Content */}
                <div className="p-5 bg-white space-y-1">
                  <div className="text-[12px] text-[#006621] font-mono flex items-center gap-1">
                    Ad <span className="text-gray-400">·</span> www.fitwear.com/sensory-blanket
                  </div>
                  <div className="text-[20px] text-[#1a0dab] font-sans hover:underline cursor-pointer leading-tight relative inline-block">
                    <span className="bg-[#4d8eff]/20 rounded-sm outline outline-1 outline-[#4d8eff]/50 relative z-10 px-1 -ml-1">Weighted Sensory Blanket | Sensory-Friendly Calming</span>
                    <div className="absolute -top-3 -right-2 transform translate-x-full bg-[#262a35] text-[#c2c6d6] text-[9px] px-1.5 py-0.5 rounded border border-[#424754] whitespace-nowrap z-20 shadow-md">
                      Pinned: HEADLINE_1
                    </div>
                  </div>
                  <div className="text-[14px] text-[#545454] font-sans mt-1 leading-snug">
                    Empathy-centered calming blanket for sensory seeking toddlers. Soft, breathable, and designed for neurodivergent children.
                  </div>
                </div>

                {/* Change Diff Panel */}
                <div className="border-t border-[#374151] bg-[#0B0F19] p-4 font-mono text-sm">
                  <div className="text-[#c2c6d6] mb-2 text-xs uppercase tracking-wider">Mutation Diff</div>
                  <div className="space-y-1">
                    <div className="flex items-start text-[#ffb4ab]/80 bg-[#ffb4ab]/5 px-2 py-1 rounded">
                      <span className="mr-2 select-none">-</span>
                      <span className="line-through">Buy Weighted Blankets Now (Save 10%!)</span>
                    </div>
                    <div className="flex items-start text-[#4edea3] bg-[#4edea3]/5 px-2 py-1 rounded">
                      <span className="mr-2 select-none">+</span>
                      <span>Weighted Sensory Blanket | Sensory-Friendly Calming</span>
                    </div>
                  </div>
                </div>

                {/* Routing Indicator */}
                <div className="bg-[#171b26] px-4 py-2 border-t border-[#374151] flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-[#4edea3]"></div>
                  <span className="text-xs text-[#c2c6d6] font-mono">LoRA Reroute: us-central1-endpoints/t2-lora-endpoint</span>
                </div>
              </div>
            </div>
          </div>

          {/* Column 3: Performance & Approval Queue (Col span 3) */}
          <div className="lg:col-span-3 flex flex-col gap-6">
            {/* Card A: Quick Stats */}
            <div className="bg-[#111827] border border-[#374151] rounded-xl p-6">
              <h4 className="text-xs text-[#c2c6d6] uppercase tracking-wider font-semibold mb-4 flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px]">analytics</span>
                Impact Prediction
              </h4>
              <div className="space-y-4">
                <div>
                  <div className="text-xs text-[#c2c6d6] mb-1">Campaign</div>
                  <div className="text-sm font-medium text-[#dfe2f1] bg-[#171b26] px-2 py-1 rounded border border-[#424754]/30 inline-block">Summer Calming Drive</div>
                </div>
                <div>
                  <div className="text-xs text-[#c2c6d6] mb-1">Ad Group</div>
                  <div className="text-sm font-medium text-[#dfe2f1] bg-[#171b26] px-2 py-1 rounded border border-[#424754]/30 inline-block">Sensory Weighted</div>
                </div>
                <div className="pt-3 border-t border-[#374151]">
                  <div className="flex justify-between items-end mb-1">
                    <div className="text-xs text-[#c2c6d6]">Current CTR</div>
                    <div className="text-xs text-[#4edea3] font-medium">Predicted CTR</div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-lg text-[#dfe2f1] font-mono">1.8%</span>
                    <span className="material-symbols-outlined text-[#8c909f] text-[18px]">arrow_forward</span>
                    <span className="text-2xl text-[#4edea3] font-mono font-bold">3.4%</span>
                  </div>
                  <div className="mt-2 text-xs text-[#4edea3] bg-[#4edea3]/10 px-2 py-1 rounded inline-flex items-center gap-1">
                    <span className="material-symbols-outlined text-[14px]">trending_up</span>
                    +88% expected lift
                  </div>
                </div>
              </div>
            </div>

            {/* Card B: Actions */}
            <div className="bg-[#111827] border border-[#adc6ff]/30 rounded-xl p-6 mt-auto bg-[#4d8eff]/5 relative overflow-hidden">
              <div className="absolute -top-10 -right-10 w-32 h-32 bg-[#4edea3]/10 rounded-full blur-2xl pointer-events-none"></div>
              <h4 className="text-xs text-[#c2c6d6] uppercase tracking-wider font-semibold mb-4">Required Action</h4>
              <div className="flex flex-col gap-3">
                <button className="w-full bg-[#4edea3] text-[#005236] hover:bg-[#6ffbbe] py-3 px-4 rounded-xl text-xs font-semibold shadow-[0_0_15px_rgba(78,222,163,0.3)] transition-all active:scale-95 flex items-center justify-center gap-2">
                  <span className="material-symbols-outlined text-[18px]">check_circle</span>
                  Approve and Mutate
                </button>
                <button className="w-full border border-[#adc6ff] text-[#adc6ff] hover:bg-[#adc6ff]/10 py-2.5 px-4 rounded-xl text-xs font-semibold transition-colors active:scale-95 flex items-center justify-center gap-2">
                  <span className="material-symbols-outlined text-[18px]">autorenew</span>
                  Regenerate
                </button>
                <button className="w-full text-[#ffb4ab] hover:text-[#93000a] hover:bg-[#ffb4ab]/5 py-2 px-4 rounded-xl text-xs font-semibold transition-colors flex items-center justify-center gap-1 mt-1">
                  <span className="material-symbols-outlined text-[14px]">close</span>
                  Reject Proposal
                </button>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
