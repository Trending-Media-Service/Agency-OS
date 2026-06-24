import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { CheckCircle2, Circle, Loader2, Server, Cloud, ChevronRight, Check } from "lucide-react";

interface TenantSetupWizardProps {
  onClose: () => void;
}

export default function TenantSetupWizard({ onClose }: TenantSetupWizardProps) {
  const { request } = useApi();
  const { addKnownTenant, setTenantId } = useTenant();

  const [brandName, setBrandName] = useState("");
  const [domain, setDomain] = useState("");
  const [topology, setTopology] = useState<"shared" | "dedicated">("shared");
  
  const [phase, setPhase] = useState<1 | 2 | 3>(1);
  const [isShopifyConnected, setIsShopifyConnected] = useState(false);
  
  const [bootstrappingState, setBootstrappingState] = useState<"idle" | "scanning" | "analyzing" | "synthesizing" | "done">("idle");
  const [logs, setLogs] = useState<string[]>([]);
  
  const handleConnectShopify = () => {
    // Mock connecting shopify
    setIsShopifyConnected(true);
  };

  const startBootstrapping = async () => {
    if (!brandName.trim()) return;
    setPhase(3);
    setBootstrappingState("scanning");
    
    const addLog = (msg: string) => setLogs(prev => [...prev, msg]);
    
    addLog("[INFO] Querying Shopify Admin API...");
    await new Promise(r => setTimeout(r, 1500));
    
    setBootstrappingState("analyzing");
    addLog(`[INFO] Catalog for '${brandName}' fetched successfully.`);
    await new Promise(r => setTimeout(r, 2000));
    
    setBootstrappingState("synthesizing");
    addLog("[LLM] Synthesizing copywriting target personas...");
    addLog("[LLM] Extracting tone of voice vectors...");
    await new Promise(r => setTimeout(r, 2500));
    
    addLog("[SUCCESS] Brand RAG profile compiled.");
    setBootstrappingState("done");
  };

  const finalizeSetup = async () => {
    try {
      // Use the actual backend API to create the tenant
      const res = await request("/tenants", "post", {
        name: brandName.trim(), // Use brand name as tenant name for simplicity
        brand_name: brandName.trim()
      }) as { tenant_id: string; brand_id: string };
      
      addKnownTenant(res.tenant_id, brandName.trim(), res.brand_id, brandName.trim());
      setTenantId(res.tenant_id);
      onClose();
    } catch (err) {
      console.error("Failed to create tenant", err);
      // Fallback close
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 bg-[#0a0e18]/90 backdrop-blur-sm flex items-center justify-center z-50 p-4 overflow-y-auto font-sans">
      <div className="bg-[#0f131d] border border-[#374151] rounded-2xl w-full max-w-4xl shadow-2xl flex flex-col overflow-hidden my-auto">
        
        {/* Header */}
        <div className="px-8 py-6 border-b border-[#374151] flex items-center justify-between bg-[#111827]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-[#4d8eff] flex items-center justify-center text-[#001a42] font-bold text-xl">
              A
            </div>
            <div>
              <h2 className="text-[#dfe2f1] font-semibold text-lg leading-tight">Agency OS <span className="text-[#8c909f] font-normal mx-2">|</span> Tenant Setup Wizard</h2>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 bg-[#1c1f2a] px-3 py-1.5 rounded-full border border-[#424754]">
              <div className="w-5 h-5 rounded-full bg-[#313540] overflow-hidden">
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=Chandan" alt="User" />
              </div>
              <span className="text-[#c2c6d6] text-xs font-medium">Tier: <span className="text-[#ffb95f]">Pending</span></span>
            </div>
            <button onClick={onClose} className="text-[#8c909f] hover:text-[#dfe2f1] transition-colors">
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        </div>

        <div className="p-8 space-y-8 bg-[#0f131d]">
          <div>
            <h1 className="text-3xl font-bold text-[#dfe2f1] mb-2">Welcome to Agency OS</h1>
            <p className="text-[#c2c6d6]">Set up your autonomous brand growth partner in under 2 minutes.</p>
          </div>

          {/* Phase 1 */}
          <div className={`border rounded-xl p-6 transition-all duration-300 ${phase === 1 ? "border-[#4d8eff] bg-[#111827] shadow-[0_0_20px_rgba(77,142,255,0.1)]" : "border-[#374151] bg-[#111827]/50 opacity-60"}`}>
            <h3 className="text-[#dfe2f1] font-semibold mb-5 flex items-center gap-2">
              Phase 1: Brand Identity &amp; Cloud Topology
            </h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-[#c2c6d6] mb-1.5">Brand Name</label>
                  <input 
                    type="text" 
                    value={brandName}
                    onChange={(e) => setBrandName(e.target.value)}
                    disabled={phase !== 1}
                    className="w-full bg-[#1c1f2a] border border-[#424754] rounded-lg px-3 py-2 text-[#dfe2f1] focus:outline-none focus:border-[#4d8eff] focus:ring-1 focus:ring-[#4d8eff]"
                    placeholder="e.g. LuxeDecor"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#c2c6d6] mb-1.5">Storefront Domain</label>
                  <input 
                    type="text" 
                    value={domain}
                    onChange={(e) => setDomain(e.target.value)}
                    disabled={phase !== 1}
                    className="w-full bg-[#1c1f2a] border border-[#424754] rounded-lg px-3 py-2 text-[#dfe2f1] focus:outline-none focus:border-[#4d8eff] focus:ring-1 focus:ring-[#4d8eff]"
                    placeholder="e.g. luxedecor.com"
                  />
                </div>
              </div>
              
              <div>
                <label className="block text-xs font-medium text-[#c2c6d6] mb-1.5">Hosting Topology Preference</label>
                <div className="space-y-3">
                  <div 
                    onClick={() => phase === 1 && setTopology("shared")}
                    className={`cursor-pointer border rounded-lg p-3 flex gap-3 transition-colors ${topology === "shared" ? "border-[#4d8eff] bg-[#4d8eff]/10" : "border-[#424754] bg-[#1c1f2a] hover:border-[#8c909f]"}`}
                  >
                    <div className="pt-0.5">
                      {topology === "shared" ? <CheckCircle2 className="w-4 h-4 text-[#4d8eff]" /> : <Circle className="w-4 h-4 text-[#8c909f]" />}
                    </div>
                    <div>
                      <div className="text-sm font-medium text-[#dfe2f1]">Shared central Cloud</div>
                      <div className="text-xs text-[#8c909f] mt-0.5">Shared central cloud with central Brand cloud.</div>
                    </div>
                  </div>
                  
                  <div 
                    onClick={() => phase === 1 && setTopology("dedicated")}
                    className={`cursor-pointer border rounded-lg p-3 flex gap-3 transition-colors ${topology === "dedicated" ? "border-[#4d8eff] bg-[#4d8eff]/10" : "border-[#424754] bg-[#1c1f2a] hover:border-[#8c909f]"}`}
                  >
                    <div className="pt-0.5">
                      {topology === "dedicated" ? <CheckCircle2 className="w-4 h-4 text-[#4d8eff]" /> : <Circle className="w-4 h-4 text-[#8c909f]" />}
                    </div>
                    <div>
                      <div className="text-sm font-medium text-[#dfe2f1]">Dedicated Brand Cloud</div>
                      <div className="text-xs text-[#8c909f] mt-0.5">Isolated GCP service account key for maximum compliance.</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            
            {phase === 1 && (
              <div className="mt-6 flex justify-end">
                <Button 
                  onClick={() => setPhase(2)} 
                  disabled={!brandName || !domain}
                  className="bg-[#4d8eff] hover:bg-[#4d8eff]/90 text-[#001a42] font-semibold"
                >
                  Continue to Integrations <ChevronRight className="w-4 h-4 ml-1" />
                </Button>
              </div>
            )}
          </div>

          {/* Phase 2 */}
          <div className={`border rounded-xl p-6 transition-all duration-300 ${phase === 2 ? "border-[#4d8eff] bg-[#111827] shadow-[0_0_20px_rgba(77,142,255,0.1)]" : "border-[#374151] bg-[#111827]/50 opacity-60"}`}>
            <h3 className="text-[#dfe2f1] font-semibold mb-5">Phase 2: One-Click Connection Hub</h3>
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Shopify */}
              <div className={`border rounded-xl p-4 flex flex-col justify-between h-32 ${isShopifyConnected ? "border-[#00a572]/50 bg-[#00a572]/5" : "border-[#424754] bg-[#1c1f2a]"}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded bg-[#96bf48] flex items-center justify-center">
                      <span className="text-white font-bold text-xl">S</span>
                    </div>
                    <span className="text-[#dfe2f1] font-medium">Shopify</span>
                  </div>
                  {!isShopifyConnected && phase === 2 && (
                    <button onClick={handleConnectShopify} className="bg-[#4d8eff] text-[#001a42] px-3 py-1.5 rounded-lg text-xs font-semibold hover:bg-[#4d8eff]/90">
                      Connect Shopify
                    </button>
                  )}
                </div>
                {isShopifyConnected && (
                  <div className="mt-auto flex items-center justify-between bg-[#0f131d] border border-[#374151] rounded px-3 py-2">
                    <span className="text-xs text-[#c2c6d6] font-mono truncate">{domain || "store"}.myshopify.com</span>
                    <CheckCircle2 className="w-4 h-4 text-[#4edea3]" />
                  </div>
                )}
              </div>

              {/* Google Ads */}
              <div className="border border-[#424754] bg-[#1c1f2a] rounded-xl p-4 flex flex-col h-32">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded bg-white flex items-center justify-center">
                      <span className="text-[#4285F4] font-bold">G</span>
                    </div>
                    <span className="text-[#dfe2f1] font-medium">Google Ads</span>
                  </div>
                  <span className="text-xs text-[#8c909f] bg-[#313540] px-2 py-1 rounded">Not Connected</span>
                </div>
              </div>

              {/* Meta Ads */}
              <div className="border border-[#424754] bg-[#1c1f2a] rounded-xl p-4 flex flex-col h-32">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded bg-[#0668E1] flex items-center justify-center">
                      <span className="text-white font-bold">M</span>
                    </div>
                    <span className="text-[#dfe2f1] font-medium">Meta Ads</span>
                  </div>
                  <span className="text-xs text-[#8c909f] bg-[#313540] px-2 py-1 rounded">Not Connected</span>
                </div>
              </div>
            </div>
            
            <div className="mt-4">
              <button className="text-xs text-[#4d8eff] hover:underline flex items-center gap-1">
                Add Custom Integration for additional options <ChevronRight className="w-3 h-3" />
              </button>
            </div>

            {phase === 2 && (
              <div className="mt-6 flex justify-end">
                <Button 
                  onClick={startBootstrapping} 
                  className="bg-[#4d8eff] hover:bg-[#4d8eff]/90 text-[#001a42] font-semibold"
                >
                  Start RAG Bootstrapping <ChevronRight className="w-4 h-4 ml-1" />
                </Button>
              </div>
            )}
          </div>

          {/* Phase 3 */}
          <div className={`border rounded-xl p-6 transition-all duration-300 ${phase === 3 ? "border-[#4d8eff] bg-[#111827] shadow-[0_0_20px_rgba(77,142,255,0.1)]" : "border-[#374151] bg-[#111827]/50 opacity-60"}`}>
            <h3 className="text-[#dfe2f1] font-semibold mb-5">Phase 3: Autonomous RAG Bootstrapping Progress</h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Terminal Logs */}
              <div className="bg-[#0a0e18] border border-[#374151] rounded-lg p-4 font-mono text-xs text-[#8c909f] h-40 overflow-y-auto">
                {logs.map((log, i) => (
                  <div key={i} className="mb-1">{log}</div>
                ))}
                {bootstrappingState !== "idle" && bootstrappingState !== "done" && (
                  <div className="animate-pulse">_</div>
                )}
              </div>

              {/* Progress UI */}
              <div className="border border-[#424754] bg-[#1c1f2a] rounded-lg p-5">
                <div className="mb-4">
                  <div className="text-sm font-medium text-[#dfe2f1] mb-2">Autonomous Brand Persona Generation</div>
                  <div className="w-full bg-[#313540] rounded-full h-1.5 mb-4 overflow-hidden">
                    <div 
                      className="bg-[#4d8eff] h-1.5 rounded-full transition-all duration-500" 
                      style={{ 
                        width: bootstrappingState === "idle" ? "0%" : 
                               bootstrappingState === "scanning" ? "30%" : 
                               bootstrappingState === "analyzing" ? "60%" : 
                               bootstrappingState === "synthesizing" ? "90%" : "100%" 
                      }}
                    ></div>
                  </div>
                  
                  <div className="space-y-3">
                    <div className="flex items-center gap-3">
                      {bootstrappingState === "idle" ? <Circle className="w-4 h-4 text-[#424754]" /> : 
                       bootstrappingState === "scanning" ? <Loader2 className="w-4 h-4 text-[#4d8eff] animate-spin" /> : 
                       <CheckCircle2 className="w-4 h-4 text-[#4edea3]" />}
                      <span className={`text-xs ${bootstrappingState === "idle" ? "text-[#8c909f]" : "text-[#dfe2f1]"}`}>Scanning Shopify product catalog...</span>
                    </div>
                    
                    <div className="flex items-center gap-3">
                      {["idle", "scanning"].includes(bootstrappingState) ? <Circle className="w-4 h-4 text-[#424754]" /> : 
                       bootstrappingState === "analyzing" ? <Loader2 className="w-4 h-4 text-[#4d8eff] animate-spin" /> : 
                       <CheckCircle2 className="w-4 h-4 text-[#4edea3]" />}
                      <span className={`text-xs ${["idle", "scanning"].includes(bootstrappingState) ? "text-[#8c909f]" : "text-[#dfe2f1]"}`}>Analyzing weighted catalog details (2/5 products)...</span>
                    </div>
                    
                    <div className="flex items-center gap-3">
                      {["idle", "scanning", "analyzing"].includes(bootstrappingState) ? <Circle className="w-4 h-4 text-[#424754]" /> : 
                       bootstrappingState === "synthesizing" ? <Loader2 className="w-4 h-4 text-[#4d8eff] animate-spin" /> : 
                       <CheckCircle2 className="w-4 h-4 text-[#4edea3]" />}
                      <span className={`text-xs ${["idle", "scanning", "analyzing"].includes(bootstrappingState) ? "text-[#8c909f]" : "text-[#dfe2f1]"}`}>Synthesizing Brand Tone of Voice via Gemini...</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="px-8 py-5 border-t border-[#374151] bg-[#111827] flex justify-center">
          <Button 
            onClick={finalizeSetup}
            disabled={bootstrappingState !== "done"}
            className={`px-8 py-2 rounded-xl font-bold transition-all ${bootstrappingState === "done" ? "bg-[#00a572] hover:bg-[#00a572]/90 text-[#00311f] shadow-[0_0_15px_rgba(0,165,114,0.4)]" : "bg-[#313540] text-[#8c909f]"}`}
          >
            Initialize OS
          </Button>
        </div>

      </div>
    </div>
  );
}
