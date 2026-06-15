import React, { useState } from "react";
import { X } from "lucide-react";
import { Button } from "./ui/button";

interface DiffProps {
  before: unknown;
  after: unknown;
}

export function VisualDiff({ before, after }: DiffProps) {
  const renderDiff = (prev: unknown, curr: unknown, path: string = ""): React.ReactNode => {
    if (prev === curr) return null;

    if (typeof prev !== typeof curr || prev === null || curr === null) {
      return (
        <div key={path} className="grid grid-cols-2 gap-4 py-1.5 border-b border-zinc-900 text-[10px] font-mono leading-relaxed">
          <div className="text-red-400 bg-red-950/20 px-2 py-0.5 rounded truncate">- {path}: {JSON.stringify(prev)}</div>
          <div className="text-emerald-400 bg-emerald-950/20 px-2 py-0.5 rounded truncate">+ {path}: {JSON.stringify(curr)}</div>
        </div>
      );
    }

    if (typeof prev === "object" && typeof curr === "object") {
      const prevObj = prev as Record<string, unknown>;
      const currObj = curr as Record<string, unknown>;
      const keys = Array.from(new Set([...Object.keys(prevObj), ...Object.keys(currObj)]));
      return (
        <div key={path} className="space-y-1 pl-3 border-l border-zinc-800">
          {keys.map(k => {
            const nextPath = path ? `${path}.${k}` : k;
            if (!(k in prevObj)) {
              return (
                <div key={nextPath} className="grid grid-cols-2 gap-4 py-1.5 border-b border-zinc-900 text-[10px] font-mono leading-relaxed">
                  <div></div>
                  <div className="text-emerald-400 bg-emerald-950/20 px-2 py-0.5 rounded truncate">+ {nextPath}: {JSON.stringify(currObj[k])}</div>
                </div>
              );
            }
            if (!(k in currObj)) {
              return (
                <div key={nextPath} className="grid grid-cols-2 gap-4 py-1.5 border-b border-zinc-900 text-[10px] font-mono leading-relaxed">
                  <div className="text-red-400 bg-red-950/20 px-2 py-0.5 rounded truncate">- {nextPath}: {JSON.stringify(prevObj[k])}</div>
                  <div></div>
                </div>
              );
            }
            return renderDiff(prevObj[k], currObj[k], nextPath);
          })}
        </div>
      );
    }

    return (
      <div key={path} className="grid grid-cols-2 gap-4 py-1.5 border-b border-zinc-900 text-[10px] font-mono leading-relaxed">
        <div className="text-red-400 bg-red-950/20 px-2 py-0.5 rounded truncate">- {path}: {JSON.stringify(prev)}</div>
        <div className="text-emerald-400 bg-emerald-950/20 px-2 py-0.5 rounded truncate">+ {path}: {JSON.stringify(curr)}</div>
      </div>
    );
  };

  const diffNode = renderDiff(before, after);
  return (
    <div className="border border-zinc-900 rounded bg-zinc-950/40 p-4 space-y-2">
      <div className="grid grid-cols-2 gap-4 text-[9px] uppercase tracking-wider font-semibold text-zinc-500 pb-2 border-b border-zinc-900">
        <div>Before (Baseline)</div>
        <div>After (Proposed)</div>
      </div>
      {diffNode ? (
        <div className="max-h-60 overflow-y-auto pr-1">{diffNode}</div>
      ) : (
        <div className="text-[10px] text-zinc-500 italic py-1">No modifications.</div>
      )}
    </div>
  );
}

interface OpParams {
  name?: string;
  campaign_id?: string;
  budget_minor?: number;
  bid_minor?: number;
  [key: string]: unknown;
}

interface OpDetailPreviewProps {
  previewKind?: string;
  previewSummary: string | null;
  params: OpParams;
}

export function OpDetailPreview({ previewKind, previewSummary, params }: OpDetailPreviewProps) {
  if (previewKind === "campaign_create_preview") {
    return (
      <div className="bg-zinc-900/40 border border-zinc-800/80 rounded p-4 space-y-3 text-[11px] leading-relaxed">
        <h4 className="font-semibold text-zinc-200 uppercase tracking-wider text-[10px]">Create Google Ads Campaign</h4>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-zinc-400 font-mono">
          <div>Name: <span className="text-zinc-200">{params.name || "N/A"}</span></div>
          <div>Campaign ID: <span className="text-zinc-200">{params.campaign_id || "N/A"}</span></div>
          <div>Budget: <span className="text-zinc-200">{(params.budget_minor || 0) / 100} INR</span></div>
          <div>Bid: <span className="text-zinc-200">{(params.bid_minor || 0) / 100} INR</span></div>
        </div>
      </div>
    );
  }

  if (previewKind === "campaign_delete_preview") {
    return (
      <div className="bg-red-950/10 border border-red-900/40 rounded p-4 space-y-2 text-[11px] leading-relaxed">
        <h4 className="font-semibold text-red-400 uppercase tracking-wider text-[10px]">Danger: Delete Campaign</h4>
        <p className="text-red-300/80">Will delete Google Ads campaign: <span className="font-mono text-white font-bold">{params.campaign_id}</span></p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900/30 border border-zinc-800/50 rounded p-4 text-[11px] text-zinc-300 whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto">
      {previewSummary || "No preview summary available."}
    </div>
  );
}

interface TraceViolation {
  rule_id: string;
  message: string;
}

interface TraceDetail {
  from?: string;
  to?: string;
  actor?: string;
  detail?: {
    reason?: string;
    params_before?: unknown;
  };
  violations?: TraceViolation[];
  requires_human?: boolean;
  kind?: string;
  action?: string;
  [key: string]: unknown;
}

interface TraceItem {
  ts: string;
  kind: string;
  detail: TraceDetail;
}

export function TraceTimeline({ traces }: { traces: TraceItem[] }) {
  const getKindLabel = (kind: string) => {
    switch (kind) {
      case "transition": return "State Transition";
      case "gate": return "Policy Evaluation";
      case "preview": return "Preview Generation";
      case "adapter_call": return "Adapter Invocation";
      case "retry": return "Execution Retry";
      case "compensation_call": return "Compensation Execution";
      default: return kind;
    }
  };

  const getKindColor = (kind: string) => {
    switch (kind) {
      case "transition": return "border-blue-500 text-blue-400";
      case "gate": return "border-purple-500 text-purple-400";
      case "preview": return "border-zinc-500 text-zinc-400";
      case "adapter_call": return "border-emerald-500 text-emerald-400";
      case "retry": return "border-amber-500 text-amber-400";
      case "compensation_call": return "border-red-500 text-red-400";
      default: return "border-zinc-700 text-zinc-500";
    }
  };

  return (
    <div className="relative pl-4 border-l border-zinc-900 space-y-5 text-[11px] py-1 max-h-[300px] overflow-y-auto pr-1">
      {traces.map((t, idx) => (
        <div key={idx} className="relative">
          <div className={`absolute -left-[21px] top-1.5 h-2 w-2 rounded-full border bg-zinc-950 ${getKindColor(t.kind).split(" ")[0]}`} />
          
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[9px]">
              <span className={`font-semibold uppercase tracking-wider ${getKindColor(t.kind).split(" ")[1]}`}>
                {getKindLabel(t.kind)}
              </span>
              <span className="font-mono text-zinc-500">
                {new Date(t.ts).toLocaleTimeString()}
              </span>
            </div>

            {t.kind === "transition" && (
              <p className="text-zinc-300 leading-normal">
                Changed state from <span className="font-mono font-bold text-zinc-400">{t.detail.from || "NULL"}</span> to{" "}
                <span className="font-mono font-bold text-zinc-100">{t.detail.to}</span> by <span className="text-zinc-400">{t.detail.actor}</span>
                {t.detail.detail?.reason && (
                  <span className="block text-[10px] text-zinc-500 italic mt-0.5">Reason: &quot;{t.detail.detail.reason}&quot;</span>
                )}
              </p>
            )}

            {t.kind === "gate" && (
              <div className="text-zinc-300 space-y-1 leading-normal">
                <p>Checked ruleset. Requires human approval: <span className="font-semibold text-zinc-100">{t.detail.requires_human ? "Yes" : "No"}</span></p>
                {t.detail.violations && t.detail.violations.length > 0 ? (
                  <div className="pl-2 space-y-1 border-l border-red-900/50 mt-1">
                    {t.detail.violations.map((v: TraceViolation, vIdx: number) => (
                      <p key={vIdx} className="text-[10px] text-red-400">
                        <span className="font-semibold">{v.rule_id}</span>: {v.message}
                      </p>
                    ))}
                  </div>
                ) : (
                  <p className="text-[10px] text-zinc-500 italic">No policy violations.</p>
                )}
              </div>
            )}

            {t.kind === "preview" && (
              <p className="text-zinc-300">
                Generated preview artifact type: <span className="font-mono text-zinc-100">{t.detail.kind}</span>
              </p>
            )}

            {t.kind === "adapter_call" && (
              <p className="text-zinc-300">
                Invoked adapter action: <span className="font-mono text-zinc-100">{t.detail.action}</span>
              </p>
            )}

            {t.kind !== "transition" && t.kind !== "gate" && t.kind !== "preview" && t.kind !== "adapter_call" && (
              <pre className="text-[9px] text-zinc-500 bg-zinc-950 p-2 rounded overflow-x-auto max-h-24">
                {JSON.stringify(t.detail, null, 2)}
              </pre>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

interface OpDetailData {
  action: string;
  state: string;
  preview: string | null;
  params: OpParams;
  trace: TraceItem[];
}

interface OpDetailDrawerProps {
  opId: string;
  onClose: () => void;
  opData: OpDetailData | null;
  loading: boolean;
  onDecision: (opId: string, decision: "approve" | "reject" | "modify", reason?: string) => void;
  role: string;
}

export function OpDetailDrawer({ opId, onClose, opData, loading, onDecision, role }: OpDetailDrawerProps) {
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [tweakReason, setTweakReason] = useState("");
  const [showTweakForm, setShowTweakForm] = useState(false);

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-end z-50">
        <div className="w-[500px] h-full bg-zinc-950 border-l border-zinc-900 flex flex-col justify-center items-center p-6 text-zinc-400 text-xs">
          <span>Loading operation metadata...</span>
        </div>
      </div>
    );
  }

  if (!opData) return null;

  const previewKind = opData.trace?.find((t) => t.kind === "preview")?.detail?.kind;
  
  let paramsBefore: unknown = null;
  if (opData.trace) {
    for (const t of opData.trace) {
      if (t.kind === "transition" && t.detail?.detail?.params_before) {
        paramsBefore = t.detail.detail.params_before;
      }
    }
  }

  const handleReject = (e: React.FormEvent) => {
    e.preventDefault();
    onDecision(opId, "reject", rejectReason || undefined);
    setShowRejectForm(false);
    setRejectReason("");
  };

  const handleTweak = (e: React.FormEvent) => {
    e.preventDefault();
    if (!tweakReason.trim()) return;
    onDecision(opId, "modify", tweakReason);
    setShowTweakForm(false);
    setTweakReason("");
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-end z-50" onClick={onClose}>
      <div 
        className="w-[500px] h-full bg-zinc-950 border-l border-zinc-900 flex flex-col text-xs p-6 space-y-6 overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-900 pb-4">
          <div className="space-y-0.5">
            <span className="font-mono text-zinc-500 text-[10px] uppercase tracking-wider">Operation Details</span>
            <h3 className="text-sm font-bold text-zinc-100 truncate max-w-[380px]">{opData.action}</h3>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-zinc-900 rounded text-zinc-400 hover:text-zinc-200">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Op Meta */}
        <div className="grid grid-cols-2 gap-4 bg-zinc-900/20 border border-zinc-900 rounded p-4">
          <div className="space-y-0.5">
            <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Operation ID</span>
            <code className="text-zinc-300 font-mono text-[10px]">{opId}</code>
          </div>
          <div className="space-y-0.5">
            <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">State</span>
            <span className="text-zinc-300 font-semibold uppercase">{opData.state}</span>
          </div>
        </div>

        {/* Visual Preview */}
        <div className="space-y-2">
          <h4 className="font-semibold text-zinc-400 uppercase tracking-wider text-[9px]">Visual Preview</h4>
          <OpDetailPreview 
            previewKind={previewKind}
            previewSummary={opData.preview}
            params={opData.params}
          />
        </div>

        {/* Visual Payload Diff */}
        <div className="space-y-2">
          <h4 className="font-semibold text-zinc-400 uppercase tracking-wider text-[9px]">Payload Adjustments</h4>
          <VisualDiff 
            before={paramsBefore || {}}
            after={opData.params}
          />
        </div>

        {/* Timeline */}
        <div className="space-y-2">
          <h4 className="font-semibold text-zinc-400 uppercase tracking-wider text-[9px]">Execution & Audit Log Timeline</h4>
          <TraceTimeline traces={opData.trace || []} />
        </div>

        {/* Actions section */}
        {opData.state === "AWAITING_APPROVAL" && role !== "BRAND_VIEWER" && (
          <div className="border-t border-zinc-900 pt-6 space-y-4">
            {!showRejectForm && !showTweakForm && (
              <div className="grid grid-cols-3 gap-3">
                <Button
                  onClick={() => onDecision(opId, "approve")}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium h-8"
                >
                  Approve
                </Button>
                <Button
                  onClick={() => setShowTweakForm(true)}
                  className="bg-zinc-800 hover:bg-zinc-700 text-zinc-100 font-medium h-8 border border-zinc-700"
                >
                  Modify
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => setShowRejectForm(true)}
                  className="bg-red-950 hover:bg-red-900 text-red-300 font-medium h-8 border border-red-800"
                >
                  Reject
                </Button>
              </div>
            )}

            {showRejectForm && (
              <form onSubmit={handleReject} className="space-y-2 border border-red-900/30 rounded p-4 bg-red-950/5">
                <label className="block text-[10px] uppercase tracking-wider text-red-400 font-medium">Rejection Reason</label>
                <textarea
                  value={rejectReason}
                  onChange={e => setRejectReason(e.target.value)}
                  placeholder="Optional comment explaining rejection"
                  className="w-full min-h-[60px] p-2 bg-zinc-950 border border-zinc-900 rounded focus:outline-none focus:border-zinc-700 text-xs text-zinc-100 placeholder-zinc-600"
                />
                <div className="flex space-x-2 justify-end">
                  <Button
                    type="button"
                    onClick={() => setShowRejectForm(false)}
                    className="bg-transparent hover:bg-zinc-900 text-zinc-400 h-7 text-[10px] px-3 border border-transparent"
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    variant="destructive"
                    className="bg-red-950 hover:bg-red-900 text-red-300 h-7 text-[10px] px-3 border border-red-800"
                  >
                    Confirm Reject
                  </Button>
                </div>
              </form>
            )}

            {showTweakForm && (
              <form onSubmit={handleTweak} className="space-y-2 border border-zinc-800 rounded p-4 bg-zinc-900/10">
                <label className="block text-[10px] uppercase tracking-wider text-zinc-300 font-medium">Modify Instruction (Tweak Reason)</label>
                <input
                  type="text"
                  value={tweakReason}
                  onChange={e => setTweakReason(e.target.value)}
                  placeholder="e.g. increase budget to 5000 INR"
                  required
                  className="w-full p-2 bg-zinc-950 border border-zinc-900 rounded focus:outline-none focus:border-zinc-700 text-xs text-zinc-100 placeholder-zinc-600"
                />
                <div className="flex space-x-2 justify-end">
                  <Button
                    type="button"
                    onClick={() => setShowTweakForm(false)}
                    className="bg-transparent hover:bg-zinc-900 text-zinc-400 h-7 text-[10px] px-3"
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    className="bg-zinc-100 text-zinc-950 hover:bg-zinc-200 h-7 text-[10px] px-3 font-semibold"
                  >
                    Submit Tweak
                  </Button>
                </div>
              </form>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
