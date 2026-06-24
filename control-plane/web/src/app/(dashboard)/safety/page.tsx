"use client";

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { CheckCircle2, ShieldAlert, Activity, Server, ArrowRight, Play, Terminal, Box } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function SafetyPage() {
  const { request } = useApi();
  const { tenantId } = useTenant();
  const [isAuditing, setIsAuditing] = useState(false);

  const handleRunAudit = () => {
    setIsAuditing(true);
    setTimeout(() => setIsAuditing(false), 2000);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-500 font-sans">
      <div className="flex items-center justify-between border-b border-[#374151] pb-6">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[#dfe2f1]">
            Build Sentinel: sGTM &amp; CAPI Gateway
          </h2>
          <p className="text-sm text-[#8c909f] mt-1">Monitoring first-party signals and self-healing tracking infrastructure.</p>
        </div>
        <div className="flex items-center gap-2 border border-[#8c909f]/30 bg-[#ffb95f]/10 px-4 py-1.5 rounded-full">
          <span className="text-[10px] font-bold text-[#ffb95f] uppercase tracking-wider">Sentinel Status:</span>
          <span className="text-sm font-bold text-[#ffb95f] uppercase">Drift Detected</span>
          <span className="ml-2 bg-[#ffb95f]/20 text-[#ffb95f] text-[10px] px-2 py-0.5 rounded-full font-bold">Amber</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Main Content Area */}
        <div className="lg:col-span-3 space-y-6">
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* sGTM Gateway Health */}
            <div className="bg-[#111827] border border-[#374151] rounded-xl p-6 shadow-xl">
              <h3 className="text-[#8c909f] text-sm font-medium mb-1">sGTM Gateway Health</h3>
              <h4 className="text-lg font-bold text-[#dfe2f1] mb-6">Server-Side Google Tag Manager (sGTM)</h4>
              
              <div className="flex gap-12 mb-6">
                <div>
                  <div className="text-sm text-[#8c909f] mb-1">Uptime:</div>
                  <div className="text-4xl font-bold text-[#00a572]">100%</div>
                </div>
                <div>
                  <div className="text-sm text-[#8c909f] mb-1">Latency:</div>
                  <div className="text-4xl font-bold text-[#4d8eff]">22ms</div>
                </div>
              </div>

              <div className="text-xs text-[#c2c6d6] mb-4 flex items-center gap-2">
                Cloud Run Service: <span className="font-mono text-[#8c909f]">sgtm-container-123.run.app</span>
              </div>

              <div className="h-24 w-full bg-[#1c1f2a] border border-[#424754] rounded-lg relative overflow-hidden flex items-end">
                <div className="absolute top-2 left-3 text-[10px] text-[#8c909f] font-mono">API Request Volume</div>
                {/* Fake line chart using SVG */}
                <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="w-full h-16 text-[#4d8eff] fill-current opacity-20">
                  <path d="M0,30 L0,25 L10,24 L20,28 L30,22 L40,26 L50,15 L60,10 L70,18 L80,5 L90,12 L100,10 L100,30 Z" />
                </svg>
                <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="w-full h-16 text-[#4d8eff] stroke-current absolute bottom-0 fill-transparent stroke-2">
                  <path d="M0,25 L10,24 L20,28 L30,22 L40,26 L50,15 L60,10 L70,18 L80,5 L90,12 L100,10" strokeLinejoin="round" />
                </svg>
                <div className="absolute bottom-1 left-0 w-full flex justify-between px-2 text-[8px] text-[#424754]">
                  <span>08 hrs</span><span>10 hrs</span><span>12 hrs</span><span>14 hrs</span><span>16 hrs</span><span>24 hrs</span>
                </div>
              </div>
            </div>

            {/* DNS & SSL Verification */}
            <div className="bg-[#111827] border border-[#374151] rounded-xl p-6 shadow-xl">
              <h3 className="text-[#8c909f] text-sm font-medium mb-1">DNS &amp; SSL Verification</h3>
              <h4 className="text-lg font-bold text-[#dfe2f1] mb-2">First-Party Tracking Domain</h4>
              <p className="text-xs text-[#8c909f] mb-6">CNAME configuration for tracking.fitwear.com</p>
              
              <div className="space-y-3">
                <div className="flex items-center justify-between border border-[#374151] bg-[#1c1f2a] p-3 rounded-lg">
                  <span className="text-sm text-[#c2c6d6]">DNS Record (CNAME → sgtm-gateway)</span>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold text-[#00a572] uppercase tracking-wider">Verified</span>
                    <CheckCircle2 className="w-4 h-4 text-[#00a572]" />
                  </div>
                </div>
                
                <div className="flex items-center justify-between border border-[#374151] bg-[#1c1f2a] p-3 rounded-lg">
                  <span className="text-sm text-[#c2c6d6]">SSL Certificate</span>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold text-[#00a572] uppercase tracking-wider">Active</span>
                    <CheckCircle2 className="w-4 h-4 text-[#00a572]" />
                  </div>
                </div>
                
                <div className="flex items-center justify-between border border-[#374151] bg-[#1c1f2a] p-3 rounded-lg">
                  <span className="text-sm text-[#c2c6d6]">First-Party Cookie Signal Strength</span>
                  <div className="flex items-center gap-2">
                    <span className="bg-[#00a572]/20 text-[#00a572] text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded">Excellent (1st Party Secure)</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* The Deterministic Healer Sentinel Logs */}
          <div className="bg-[#111827] border border-[#374151] rounded-xl overflow-hidden shadow-xl">
            <div className="p-5 border-b border-[#374151] bg-[#0f131d]">
              <h3 className="text-[#8c909f] text-sm font-medium mb-1">The Deterministic Healer Sentinel Logs</h3>
              <h4 className="text-[#dfe2f1] font-bold text-lg">Sentinel Healer Operations Log</h4>
              <p className="text-xs text-[#8c909f]">Live logs showing autonomous signal healing</p>
            </div>
            
            <div className="bg-black p-6 font-mono text-[11px] leading-relaxed h-[200px] overflow-y-auto">
              <div className="text-[#4edea3]">
                <span className="text-[#8c909f]">[04:00:12]</span> <span className="font-bold">[SENTINEL]</span> Running hourly drift audit on tracking gateway...
              </div>
              <div className="text-[#ffb95f]">
                <span className="text-[#8c909f]">[04:00:15]</span> <span className="font-bold">[AUDIT]</span> WARNING: Cloud Run container CPU utilization exceeded 85%.
              </div>
              <div className="text-[#4edea3]">
                <span className="text-[#8c909f]">[04:00:16]</span> <span className="font-bold">[HEALER]</span> Dynamic mitigation triggered: scaling up Cloud Run instances (2 → 4).
              </div>
              <div className="text-[#4edea3]">
                <span className="text-[#8c909f]">[04:00:19]</span> <span className="font-bold">[HEALER]</span> Scaling complete. CPU utilization stabilized at 41%. Status: HEALED.
              </div>
              <div className="text-[#4edea3]">
                <span className="text-[#8c909f]">[04:00:22]</span> <span className="font-bold">[CAPI]</span> Auditing Meta Conversions API gateway signals... Match rate: <span className="text-white">94% (Excellent)</span>.
              </div>
              <div className="animate-pulse text-[#8c909f] mt-2">_</div>
            </div>
          </div>
        </div>

        {/* Right Sidebar Area */}
        <div className="space-y-6">
          
          <div className="bg-[#111827] border border-[#374151] rounded-xl p-5 shadow-xl">
            <h3 className="text-[#dfe2f1] font-bold mb-3">Quick Action Sidebar</h3>
            
            <div className="bg-[#1c1f2a] border border-[#424754] rounded-lg p-4">
              <h4 className="text-sm font-semibold text-[#dfe2f1] mb-2">Manual Diagnostic Audit</h4>
              <p className="text-xs text-[#8c909f] mb-4">Pull up diagnostic audit to see deep manual for a signal audit.</p>
              
              <Button 
                onClick={handleRunAudit}
                disabled={isAuditing}
                className="w-full bg-[#4d8eff] hover:bg-[#4d8eff]/90 text-[#001a42] font-bold shadow-[0_0_15px_rgba(77,142,255,0.4)] transition-all flex items-center justify-center gap-2"
              >
                {isAuditing ? (
                  <>Running Audit...</>
                ) : (
                  <>
                    <Activity className="w-4 h-4" /> Run Deep Signal Audit
                  </>
                )}
              </Button>
            </div>
          </div>

          <div className="bg-[#111827] border border-[#374151] rounded-xl p-5 shadow-xl">
            <h3 className="text-[#dfe2f1] font-bold mb-2">Connection Configs</h3>
            <p className="text-xs text-[#8c909f] mb-4">Check the API endpoints for meta and for your API endpoints.</p>
            
            <div className="space-y-4">
              <div>
                <div className="text-xs font-semibold text-[#dfe2f1] mb-2">GA4</div>
                <div className="space-y-2">
                  <div className="bg-[#1c1f2a] border border-[#424754] rounded p-2 text-[10px] text-[#8c909f] font-mono truncate">
                    https://sgan.fitwear.com/config...
                  </div>
                  <div className="bg-[#1c1f2a] border border-[#424754] rounded p-2 text-[10px] text-[#8c909f] font-mono truncate">
                    https://sga4.fitwear.com/config...
                  </div>
                  <div className="bg-[#1c1f2a] border border-[#424754] rounded p-2 text-[10px] text-[#8c909f] font-mono truncate">
                    https://sgan.fitwear.com/config...
                  </div>
                </div>
              </div>
              
              <div>
                <div className="text-xs font-semibold text-[#dfe2f1] mb-2">Meta Pixels</div>
                <div className="space-y-2">
                  <div className="bg-[#1c1f2a] border border-[#424754] rounded p-2 text-[10px] text-[#8c909f] font-mono truncate">
                    https://meta.pixeler.com/config...
                  </div>
                  <div className="bg-[#1c1f2a] border border-[#424754] rounded p-2 text-[10px] text-[#8c909f] font-mono truncate">
                    https://meta.pixeler.com/config...
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
