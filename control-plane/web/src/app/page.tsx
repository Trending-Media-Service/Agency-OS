"use client";

import React, { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { OpDetailDrawer, OpDetailData } from "@/components/op-detail-drawer";
import { 
  AlertTriangle, 
  CheckCircle, 
  XCircle, 
  Database, 
  Network, 
  History, 
  Sliders, 
  RefreshCw,
  ShieldAlert,
  Send,
  MessageSquare,
  Bot,
  User
} from "lucide-react";



interface ChatViolation {
  message: string;
  rule_id?: string;
  limit?: number;
  value?: number;
  delta?: number;
}

interface ChatCard {
  op_id: string;
  action: string;
  state: string;
  requirement: string;
  preview: string | null;
  cost_estimate: string | null;
  violations: ChatViolation[];
}

interface ChatResponse {
  reply: string;
  cards?: ChatCard[];
}

interface Message {
  sender: "user" | "agent";
  text: string;
  cards?: ChatCard[];
}

export default function Home() {
  const { request } = useApi();
  const { tenantId, setTenantId, activeBrandId, role, setRole, knownTenants, addKnownTenant } = useTenant();
  const [activeTab, setActiveTab] = useState<"ops" | "connections" | "audit" | "safety">("ops");
  const [selectedOpId, setSelectedOpId] = useState<string | null>(null);
  
  // Onboarding & Tenant Creation state
  const [showCreateTenant, setShowCreateTenant] = useState(false);
  const [newTenantName, setNewTenantName] = useState("");
  const [newBrandName, setNewBrandName] = useState("");
  const [createTenantLoading, setCreateTenantLoading] = useState(false);
  const [createTenantError, setCreateTenantError] = useState<string | null>(null);

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

  // Chat state
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    {
      sender: "agent",
      text: "Hello! I am your Agency OS partner agent. You can ask me to provision resources, check budgets, pause campaigns, or trigger diagnostics.",
    }
  ]);

  // 1. Fetch Operations
  const { data: ops, isLoading: opsLoading, refetch: refetchOps } = useQuery({
    queryKey: ["ops", tenantId],
    queryFn: () => request("/ops", "get"),
    refetchInterval: 5000,
  });

  // 1.5. Fetch Single Operation detail
  const { data: selectedOp, isLoading: selectedOpLoading } = useQuery({
    queryKey: ["opDetail", selectedOpId],
    queryFn: () => selectedOpId ? request(`/ops/${selectedOpId}` as "/ops/{op_id}", "get") : null,
    enabled: selectedOpId !== null,
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
      setSelectedOpId(null);
    }
  });

  // 7. Chat submission mutation
  const chatMutation = useMutation({
    mutationFn: async (text: string) => {
      const res = await request("/chat", "post", {
        brand_id: activeBrandId || "brand-bootstrap", // Dynamic brand context!
        text
      });
      return res as ChatResponse;
    },
    onSuccess: (data) => {
      setMessages(prev => [
        ...prev,
        {
          sender: "agent",
          text: data.reply,
          cards: data.cards
        }
      ]);
      refetchOps(); // reload queue immediately
    },
    onError: (err: Error) => {
      setMessages(prev => [
        ...prev,
        {
          sender: "agent",
          text: `Error parsing intent: ${err.message}`
        }
      ]);
    }
  });

  const handleDecision = (opId: string, decision: "approve" | "reject" | "modify", reason?: string) => {
    decisionMutation.mutate({ opId, decision, reason });
  };

  const handleChatSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim()) return;

    const userText = chatInput;
    setMessages(prev => [...prev, { sender: "user", text: userText }]);
    setChatInput("");
    
    chatMutation.mutate(userText);
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
                {knownTenants.map((t) => (
                  <option key={t.tenantId} value={t.tenantId}>
                    {t.tenantName} ({t.tenantId})
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

      {/* Split Layout Container */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* Left Column: Conversational Chat Panel */}
        <div className="w-[380px] border-r border-zinc-900 flex flex-col bg-zinc-900/10">
          <div className="px-6 py-4 border-b border-zinc-900 flex items-center space-x-2">
            <MessageSquare className="h-4 w-4 text-zinc-400" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">Partner Chat</h2>
          </div>

          {/* Chat Transcript Area */}
          <div className="flex-1 p-6 overflow-y-auto space-y-4 text-xs">
            {messages.map((m, idx) => (
              <div key={idx} className="space-y-2">
                <div className={`flex items-start gap-2.5 ${m.sender === "user" ? "flex-row-reverse" : ""}`}>
                  <div className={`h-6 w-6 rounded-full flex items-center justify-center shrink-0 ${m.sender === "user" ? "bg-zinc-800" : "bg-emerald-950 border border-emerald-800"}`}>
                    {m.sender === "user" ? (
                      <User className="h-3.5 w-3.5 text-zinc-400" />
                    ) : (
                      <Bot className="h-3.5 w-3.5 text-emerald-400" />
                    )}
                  </div>
                  
                  <div className={`p-3 rounded-lg max-w-[85%] leading-relaxed ${m.sender === "user" ? "bg-zinc-800 text-zinc-100" : "bg-zinc-900/60 border border-zinc-900 text-zinc-300"}`}>
                    {m.text}
                  </div>
                </div>

                {/* Render cards inside the chat stream if any are generated */}
                {m.cards && m.cards.length > 0 && (
                  <div className="pl-8 space-y-2">
                    {m.cards.map((card) => (
                      <div key={card.op_id} className="border border-zinc-800 rounded bg-zinc-950 p-3.5 space-y-2">
                        <div className="flex justify-between items-start">
                          <span className="font-semibold text-zinc-200 block text-[10px] truncate max-w-[180px]">
                            {card.action}
                          </span>
                          <span className={`px-1.5 py-0.2 rounded border text-[8px] uppercase tracking-wider font-semibold ${getStatusColor(card.state)}`}>
                            {card.state}
                          </span>
                        </div>

                        <p className="text-[10px] text-zinc-400">{card.preview}</p>
                        
                        {card.cost_estimate && (
                          <div className="text-[9px] font-mono text-zinc-500">
                            Est: {card.cost_estimate}
                          </div>
                        )}

                        {/* Violations */}
                        {card.violations && card.violations.length > 0 && (
                          <div className="space-y-1 pt-1">
                            {card.violations.map((v, vIdx) => (
                              <div key={vIdx} className="text-[9px] text-red-400 flex items-start gap-1">
                                <AlertTriangle className="h-3 w-3 shrink-0 text-red-500 mt-0.5" />
                                <span>{v.message}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Interactive Approve button inside card */}
                        {card.state === "AWAITING_APPROVAL" && role !== "BRAND_VIEWER" && (
                          <div className="flex space-x-2 pt-1">
                            <Button
                              size="sm"
                              onClick={() => handleDecision(card.op_id, "approve")}
                              className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-[9px] h-5 px-2 rounded w-full"
                            >
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => handleDecision(card.op_id, "reject")}
                              className="bg-red-950 hover:bg-red-900 text-red-300 border border-red-800 text-[9px] h-5 px-2 rounded w-full"
                            >
                              Reject
                            </Button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {chatMutation.isPending && (
              <div className="text-zinc-500 italic text-[10px] pl-8">Planning saga adapters...</div>
            )}
          </div>

          {/* Chat Input form */}
          <form onSubmit={handleChatSubmit} className="p-4 border-t border-zinc-900 bg-zinc-950/20 flex gap-2">
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder={role === "BRAND_VIEWER" ? "Transparency Portal (Read-only context)" : "e.g. configure email dns routing for ableys.in"}
              className="flex-1 px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-md focus:outline-none focus:border-zinc-700 text-xs text-zinc-100 placeholder-zinc-600 disabled:opacity-50"
              disabled={chatMutation.isPending || role === "BRAND_VIEWER"}
            />
            <Button 
              type="submit" 
              aria-label="Send Message"
              className="bg-zinc-100 text-zinc-950 hover:bg-zinc-200 h-8 w-8 p-0 flex items-center justify-center rounded disabled:opacity-30"
              disabled={chatMutation.isPending || !chatInput.trim() || role === "BRAND_VIEWER"}
            >
              <Send className="h-3.5 w-3.5" />
            </Button>
          </form>
        </div>

        {/* Right Column: Tabbed Dashboard Main content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Tabs Selector Navigation */}
          <div className="border-b border-zinc-900 px-8 flex space-x-6 text-[11px] bg-zinc-900/5">
            <button
              onClick={() => setActiveTab("ops")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${activeTab === "ops" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
            >
              <Database className="h-3.5 w-3.5" />
              Operations Queue
            </button>
            <button
              onClick={() => setActiveTab("connections")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${activeTab === "connections" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
            >
              <Network className="h-3.5 w-3.5" />
              Active Connections
            </button>
            <button
              onClick={() => setActiveTab("audit")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${activeTab === "audit" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
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
              onClick={() => setActiveTab("safety")}
              className={`py-3.5 border-b-2 font-medium transition-colors gap-2 flex items-center ${activeTab === "safety" ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}
            >
              <Sliders className="h-3.5 w-3.5" />
              Circuit Breakers
            </button>
          </div>

          {/* Tab Content Area */}
          <main className="flex-1 p-8 overflow-y-auto max-w-5xl w-full mx-auto">
            
            {/* Tab 1: Operations Queue */}
            {activeTab === "ops" && (
              <div className="space-y-6">
                {opsLoading && <div className="text-zinc-500 text-xs py-10 text-center">Loading operations queue...</div>}
                
                {ops && ops.length === 0 && (
                  <div className="text-center py-16 border border-dashed border-zinc-800 rounded-lg max-w-md mx-auto space-y-3 bg-zinc-900/5 my-8">
                    <p className="text-xs font-semibold text-zinc-300">No active or proposed operations</p>
                    <p className="text-[10px] text-zinc-500 leading-relaxed">
                      This governance console is ready! To bootstrap your first brand and spin up its GCP resources, type an onboarding intent in the chat on the left.
                    </p>
                    <div className="pt-2">
                      <span className="text-[9px] uppercase tracking-wider text-zinc-600 font-bold block mb-1.5">Example Intent to Copy:</span>
                      <code className="inline-block p-2 bg-zinc-950 text-emerald-400 rounded text-[9px] font-mono border border-zinc-900 select-all">
                        onboard brand ableys ableys.in
                      </code>
                    </div>
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
                        {ops.map((op) => (
                          <tr 
                            key={op.op_id} 
                            onClick={() => setSelectedOpId(op.op_id)}
                            className="hover:bg-zinc-900/10 cursor-pointer transition-colors"
                          >
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
                              {op.state === "AWAITING_APPROVAL" && role !== "BRAND_VIEWER" && (
                                <div className="flex justify-end space-x-2">
                                  <Button
                                    size="sm"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleDecision(op.op_id, "approve");
                                    }}
                                    className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-[10px] h-6 px-2.5 rounded"
                                  >
                                    Approve
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleDecision(op.op_id, "reject");
                                    }}
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
                <div>
                  <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">Active Brand Connections</h3>
                  <p className="text-[10px] text-zinc-500">Manage credentials mapped from per-brand Secret Manager</p>
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
                          <th className="px-6 py-4">Secret Reference</th>
                          <th className="px-6 py-4">Config Map</th>
                          <th className="px-6 py-4 text-right">Connected At</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-900">
                        {connections.map((c) => (
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
                      {auditEvents.map((ev) => (
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
                  <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">Circuit Breakers</h3>
                  <p className="text-[10px] text-zinc-500">Real-time status of safety circuit breakers guarding adapter invocations</p>
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
                    {breakers.map((cb) => {
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

      </div>
      
      {selectedOpId && (
        <OpDetailDrawer
          opId={selectedOpId}
          opData={(selectedOp as OpDetailData) || null}
          loading={selectedOpLoading}
          onClose={() => setSelectedOpId(null)}
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
