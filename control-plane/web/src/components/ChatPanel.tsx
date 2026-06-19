"use client";

import React, { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { 
  AlertTriangle, 
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

export function ChatPanel() {
  const { request } = useApi();
  const { activeBrandId, role, tenantId } = useTenant();
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    {
      sender: "agent",
      text: "Hello! I am your Agency OS partner agent. You can ask me to provision resources, check budgets, pause campaigns, or trigger diagnostics.",
    }
  ]);

  // Refetch operations query from cache to update queue
  const { refetch: refetchOps } = useQuery({
    queryKey: ["ops", tenantId],
    enabled: false // Only used to trigger refetch
  });

  // Decision mutation for cards
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
    }
  });

  // Chat submission mutation
  const chatMutation = useMutation({
    mutationFn: async (text: string) => {
      const res = await request("/chat", "post", {
        brand_id: activeBrandId || "brand-bootstrap",
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
      refetchOps();
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

  const handleDecision = (opId: string, decision: "approve" | "reject") => {
    decisionMutation.mutate({ opId, decision });
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

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
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

            {/* Render cards */}
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

                    {/* Interactive Approve/Reject buttons */}
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
  );
}
