"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { 
  X, 
  ExternalLink, 
  ShieldAlert, 
  CheckCircle, 
  AlertTriangle, 
  GitBranch, 
  Clock, 
  Coins, 
  HelpCircle,
  FileCode
} from "lucide-react";

interface OperationDetailDrawerProps {
  opId: string;
  onClose: () => void;
  onApprove: (opId: string, cost: string) => void;
  onReject: (opId: string, cost: string) => void;
}

interface TraceItem {
  ts: string;
  kind: string;
  detail: any;
}

interface OperationDetails {
  op_id: string;
  action: string;
  state: string;
  params: any;
  preview: string | null;
  trace: TraceItem[];
  impact: number;
  reversibility: string;
  statutory: boolean;
  cost_estimate: string | null;
}

export default function OperationDetailDrawer({ 
  opId, 
  onClose, 
  onApprove, 
  onReject 
}: OperationDetailDrawerProps) {
  const { request } = useApi();
  const { tenantId, role } = useTenant();

  // Fetch detailed operation data
  const { data: op, isLoading, error } = useQuery<OperationDetails>({
    queryKey: ["op-details", opId, tenantId],
    queryFn: () => request(`/ops/${opId}` as any, "get") as Promise<OperationDetails>,
    refetchInterval: (query: any) => {
      const data = query?.state?.data as OperationDetails | undefined;
      if (data && ["EXECUTING", "VERIFYING"].includes(data.state.toUpperCase())) {
        return 1500;
      }
      return 5000;
    }
  });

  // Color helper for state chips
  const getStatusColor = (state: string) => {
    switch (state.toUpperCase()) {
      case "APPROVED":
        return "bg-emerald-950/40 text-emerald-400 border-emerald-800/50";
      case "DONE":
        return "bg-sky-950/40 text-sky-400 border-sky-800/50";
      case "FAILED":
        return "bg-red-950/40 text-red-400 border-red-900/50";
      case "ROLLED_BACK":
        return "bg-blue-950/40 text-blue-400 border-blue-900/50";
      case "EXECUTING":
      case "VERIFYING":
        return "bg-amber-950/40 text-amber-400 border-amber-900/50";
      case "PROPOSED":
      case "PREVIEWED":
        return "bg-zinc-900/60 text-zinc-400 border-zinc-800/60";
      case "AWAITING_APPROVAL":
        return "bg-amber-950/60 text-amber-300 border-amber-800/60 animate-pulse font-bold";
      default:
        return "bg-zinc-900/60 text-zinc-400 border-zinc-800/60";
    }
  };

  // Structured Diff Renderer matching §4.6
  const renderDiff = (diffText: string | null | undefined) => {
    if (!diffText) return null;
    const lines = diffText.split("\n");
    return (
      <div className="border border-zinc-900 rounded bg-zinc-950 overflow-hidden font-mono text-[10px] leading-relaxed">
        <div className="bg-zinc-900/50 px-3 py-1.5 border-b border-zinc-900 flex items-center gap-1.5 text-zinc-400 text-[9px] uppercase tracking-wider">
          <FileCode className="w-3.5 h-3.5" />
          Structured Interactive Diff
        </div>
        <div className="overflow-x-auto max-h-[280px] p-3 space-y-0.5 scrollbar-thin">
          {lines.map((line, idx) => {
            let className = "text-zinc-500";
            if (line.startsWith("+") && !line.startsWith("+++")) {
              className = "text-emerald-400 bg-emerald-950/20 px-1 -mx-1 rounded-sm";
            } else if (line.startsWith("-") && !line.startsWith("---")) {
              className = "text-rose-400 bg-rose-950/15 px-1 -mx-1 rounded-sm";
            } else if (line.startsWith("@@")) {
              className = "text-cyan-500/80 font-semibold";
            } else if (line.startsWith("diff --git") || line.startsWith("index ")) {
              className = "text-zinc-400 font-semibold border-b border-zinc-900/40 pb-0.5 mt-2 first:mt-0 block";
            }
            return (
              <div key={idx} className={`${className} whitespace-pre`}>
                {line}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // Find OPA violations from the gate trace
  const getGateViolations = () => {
    if (!op) return [];
    const gateTrace = op.trace.find(t => t.kind === "gate");
    return gateTrace?.detail?.violations || [];
  };

  const violations = getGateViolations();
  const stagingUrl = op?.params?.branch_name ? `https://staging-${op.params.branch_name}.run.app` : null;
  const diff = op?.params?.diff;

  return (
    <div className="fixed inset-y-0 right-0 w-[460px] bg-zinc-950 border-l border-zinc-900 shadow-2xl flex flex-col z-40 animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div className="px-6 py-4 border-b border-zinc-900 flex items-center justify-between bg-zinc-900/20">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <code className="text-zinc-600 font-mono text-[9px] bg-zinc-900/60 px-1.5 py-0.5 rounded border border-zinc-800">
              OP-{opId.substring(0, 8).toUpperCase()}
            </code>
            {op && (
              <span className={`px-2 py-0.5 rounded-full border text-[8px] font-bold tracking-wider uppercase ${getStatusColor(op.state)}`}>
                {op.state}
              </span>
            )}
          </div>
          <h2 className="text-xs font-bold text-zinc-200 uppercase tracking-wide truncate max-w-[320px]" title={op?.action}>
            {op ? op.action : "Loading details..."}
          </h2>
        </div>
        <button 
          onClick={onClose} 
          className="text-zinc-500 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-zinc-900"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body Content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 scrollbar-thin">
        {isLoading && (
          <div className="space-y-4 py-8">
            <div className="h-4 bg-zinc-900 rounded animate-pulse w-1/3"></div>
            <div className="h-20 bg-zinc-900 rounded animate-pulse"></div>
            <div className="h-32 bg-zinc-900 rounded animate-pulse"></div>
          </div>
        )}

        {error && (
          <div className="border border-red-900/40 bg-red-950/10 p-4 rounded text-center space-y-2">
            <AlertTriangle className="w-6 h-6 text-red-500 mx-auto" />
            <p className="text-[10px] font-semibold text-red-400">Failed to load operation details</p>
          </div>
        )}

        {op && (
          <>
            {/* Staging Preview Card (Slice 2 Golden Template Output) */}
            {stagingUrl && op.state !== "PROPOSED" && (
              <div className="border border-sky-900/40 rounded bg-sky-950/5 overflow-hidden p-4 space-y-3">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <span className="text-[9px] font-bold tracking-wider text-sky-400 uppercase block">Staging Environment</span>
                    <h4 className="text-[11px] font-semibold text-zinc-200">Staging Preview deployment is active</h4>
                    <p className="text-[9px] text-zinc-500 leading-normal">
                      Fully isolated staging environment hosting your Next.js Shopify storefront code changes.
                    </p>
                  </div>
                  <GitBranch className="w-5 h-5 text-sky-500/80" />
                </div>
                <a 
                  href={stagingUrl} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-1.5 w-full py-1.5 bg-sky-600 hover:bg-sky-700 text-white text-[10px] font-bold rounded shadow-sm transition-colors"
                >
                  Open Staging Preview
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            )}

            {/* OPA Gate Violations Block */}
            {violations.length > 0 && (
              <div className="border border-red-900/50 bg-red-950/10 rounded p-4 space-y-3">
                <div className="flex items-center gap-2 text-red-400">
                  <ShieldAlert className="w-4 h-4" />
                  <span className="text-[10px] font-bold uppercase tracking-wider">OPA Gate Violations Detected</span>
                </div>
                <div className="space-y-2.5 divide-y divide-red-950/30">
                  {violations.map((v: any, idx: number) => (
                    <div key={idx} className="text-[9px] pt-2.5 first:pt-0 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[8px] bg-red-950/30 border border-red-900/45 px-1.5 py-0.5 rounded text-red-300">
                          {v.rule_id}
                        </span>
                        {v.limit && <span className="text-zinc-500 font-mono text-[8px]">Limit: {v.limit}</span>}
                      </div>
                      <p className="text-zinc-300 font-medium leading-normal">{v.message}</p>
                      {v.attempted && (
                        <div className="text-zinc-500 font-mono text-[8px] truncate">
                          Attempted: <span className="text-red-400/80">{v.attempted}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Invariants & Meta Info */}
            <div className="grid grid-cols-2 gap-4 border border-zinc-900 rounded p-4 bg-zinc-900/10 text-[10px] font-mono leading-relaxed">
              <div className="space-y-1.5">
                <div>
                  <span className="text-zinc-500 block text-[9px] uppercase tracking-wider">Severity impact</span>
                  <span className="text-zinc-300 font-bold">{op.impact} / 5</span>
                </div>
                <div>
                  <span className="text-zinc-500 block text-[9px] uppercase tracking-wider">Reversibility</span>
                  <span className="text-zinc-300 font-semibold capitalize">{op.reversibility.toLowerCase()}</span>
                </div>
              </div>
              <div className="space-y-1.5 border-l border-zinc-900/60 pl-4">
                <div>
                  <span className="text-zinc-500 block text-[9px] uppercase tracking-wider">Statutory operation</span>
                  <span className={`font-semibold ${op.statutory ? "text-amber-400" : "text-zinc-500"}`}>
                    {op.statutory ? "YES (Statutory GST)" : "NO"}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-500 block text-[9px] uppercase tracking-wider">Est. Monthly Cost</span>
                  <span className="text-emerald-400 font-bold">{op.cost_estimate || "0.00 INR"}</span>
                </div>
              </div>
            </div>

            {/* Interactive Git Diff */}
            {renderDiff(diff)}

            {/* Audit Log Timeline */}
            <div className="space-y-3">
              <div className="text-zinc-400 text-[9px] uppercase tracking-wider font-semibold flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-zinc-500" />
                Audit Trail Timeline
              </div>
              <div className="relative border-l border-zinc-900 ml-2 pl-4 py-1 space-y-4">
                {op.trace.map((t, idx) => (
                  <div key={idx} className="relative text-[9px] leading-relaxed">
                    {/* Timeline dot */}
                    <div className="absolute -left-[21px] top-1 w-2 h-2 rounded-full border border-zinc-950 bg-zinc-800"></div>
                    
                    <div className="flex items-center justify-between text-zinc-500 text-[8px] font-mono">
                      <span>{new Date(t.ts).toLocaleTimeString()}</span>
                      <span className="uppercase tracking-wider">{t.kind}</span>
                    </div>
                    <div className="text-zinc-300 font-medium">
                      {t.kind === "transition" && (
                        <span>
                          State transitioned to <span className="font-bold text-zinc-100">{t.detail.state}</span> by <span className="text-zinc-400">{t.detail.actor}</span>
                        </span>
                      )}
                      {t.kind === "preview" && (
                        <span>Staging preview generated (artifact: {t.detail.kind})</span>
                      )}
                      {t.kind === "gate" && (
                        <span>
                          Policy gates evaluated. {t.detail.violations.length} violations, requires human: {t.detail.requires_human ? "YES" : "NO"}
                        </span>
                      )}
                      {t.kind === "adapter_call" && (
                        <span>
                          Adapter executed {t.detail.action} ({t.detail.phase}). Success: {t.detail.ok ? "YES" : "NO"}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Footer / Awaiting Approval Controls */}
      {op && op.state === "AWAITING_APPROVAL" && role !== "BRAND_VIEWER" && (
        <div className="p-6 border-t border-zinc-900 bg-zinc-900/30 flex justify-end gap-3">
          <Button
            variant="destructive"
            onClick={() => onReject(op.op_id, op.cost_estimate || "0.00 INR")}
            className="flex-1 bg-red-950/20 hover:bg-red-900/30 text-red-400 border border-red-900/60 font-semibold text-[10px] h-9 rounded transition-colors"
          >
            Reject Operation
          </Button>
          <Button
            onClick={() => onApprove(op.op_id, op.cost_estimate || "0.00 INR")}
            className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-[10px] h-9 rounded shadow-sm transition-colors"
          >
            Approve & Ship
          </Button>
        </div>
      )}
    </div>
  );
}
