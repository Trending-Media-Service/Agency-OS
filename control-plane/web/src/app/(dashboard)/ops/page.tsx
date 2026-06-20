"use client";

import React, { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import OperationDetailDrawer from "@/components/OperationDetailDrawer";

export default function OpsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { request } = useApi();
  const { tenantId, role } = useTenant();

  // Confirmation Modal State
  const [confirmDecision, setConfirmDecision] = useState<{
    opId: string;
    action: string;
    domain: string;
    cost: string;
    decision: "approve" | "reject";
  } | null>(null);

  // Helper to strip newlines and format a single clean preview line for the table
  const formatPreviewLine = (preview: string | null | undefined): string => {
    if (!preview) return "No preview summary";
    const flat = preview.replace(/\s+/g, " ").trim();
    return flat.length > 55 ? flat.substring(0, 55) + "..." : flat;
  };

  // 1. Fetch Operations
  const { data: ops, isLoading: opsLoading, refetch: refetchOps } = useQuery({
    queryKey: ["ops", tenantId],
    queryFn: () => request("/ops", "get"),
    refetchInterval: 5000,
  });

  // 2. Mutate decision
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

  const handleDecision = (opId: string, decision: "approve" | "reject") => {
    decisionMutation.mutate({ opId, decision });
  };

  const handleRowClick = (opId: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("opId", opId);
    router.push(`/ops?${params.toString()}`);
  };

  const selectedOpId = searchParams.get("opId");

  const handleCloseDrawer = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("opId");
    router.push(`/ops?${params.toString()}`);
  };

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

  if (opsLoading) {
    return <div className="text-zinc-500 text-xs py-10 text-center">Loading operations queue...</div>;
  }

  if (ops && ops.length === 0) {
    return (
      <div className="text-center py-16 border border-dashed border-zinc-800 rounded-lg max-w-md mx-auto space-y-3 bg-zinc-900/5 my-8">
        <p className="text-xs font-semibold text-zinc-300">No active or proposed operations</p>
        <p className="text-[10px] text-zinc-500 leading-relaxed">
          This governance console is ready! Pick an action from the <span className="text-zinc-300 font-semibold">Operator Actions</span> panel on the left
          (e.g. <span className="text-zinc-300">Provision Web Host</span>) to propose a governed operation — it will appear here for review and approval.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
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
                  onClick={() => handleRowClick(op.op_id)}
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
                  <td className="px-6 py-4 max-w-xs">
                    <div className="text-zinc-400 font-mono text-[10px] truncate" title={op.preview || ""}>
                      {formatPreviewLine(op.preview)}
                    </div>
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
                      <div className="flex justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                        <Button
                          size="sm"
                          onClick={() => {
                            setConfirmDecision({
                              opId: op.op_id,
                              action: op.action,
                              domain: op.domain,
                              cost: op.cost_estimate || "0.00 INR",
                              decision: "approve"
                            });
                          }}
                          className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-[10px] h-6 px-3 rounded shadow-sm transition-colors"
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => {
                            setConfirmDecision({
                              opId: op.op_id,
                              action: op.action,
                              domain: op.domain,
                              cost: op.cost_estimate || "0.00 INR",
                              decision: "reject"
                            });
                          }}
                          className="bg-red-950/25 hover:bg-red-900/40 text-red-400 border border-red-900/60 font-semibold text-[10px] h-6 px-3 rounded transition-colors"
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

      {/* Accidental Approval/Rejection Gate Modal */}
      {confirmDecision && (
        <div className="fixed inset-0 bg-black/85 flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-950 border border-zinc-900 rounded-lg p-6 max-w-sm w-full space-y-4 shadow-2xl">
            <div className="space-y-1">
              <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">
                Confirm Operation {confirmDecision.decision === "approve" ? "Approval" : "Rejection"}
              </h3>
              <p className="text-[10px] text-zinc-500 leading-relaxed">
                Are you sure you want to <span className="font-semibold text-zinc-300">{confirmDecision.decision}</span> the following governed operation?
              </p>
            </div>
            
            <div className="bg-zinc-900/30 border border-zinc-900 rounded p-3.5 space-y-2 text-[10px] font-mono leading-relaxed">
              <div><span className="text-zinc-500">Action:</span> <span className="text-zinc-200 font-semibold">{confirmDecision.action}</span></div>
              <div><span className="text-zinc-500">Domain/Brand:</span> <span className="text-zinc-200">{confirmDecision.domain}</span></div>
              {confirmDecision.decision === "approve" && (
                <div><span className="text-zinc-500">Estimated Cost:</span> <span className="text-emerald-400 font-bold">{confirmDecision.cost}</span></div>
              )}
            </div>

            {confirmDecision.decision === "approve" && (
              <p className="text-[9px] text-amber-400/80 leading-normal border-l border-amber-500/40 pl-2">
                ⚠️ Warning: Approving this operation will immediately apply infrastructure modifications and may incur live cloud costs.
              </p>
            )}

            <div className="flex justify-end space-x-2 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setConfirmDecision(null)}
                className="border-zinc-850 text-zinc-400 hover:bg-zinc-900 text-[10px] h-7 px-3 rounded"
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={() => {
                  handleDecision(confirmDecision.opId, confirmDecision.decision);
                  setConfirmDecision(null);
                }}
                className={`text-white font-semibold text-[10px] h-7 px-3.5 rounded transition-colors ${
                  confirmDecision.decision === "approve" 
                    ? "bg-emerald-600 hover:bg-emerald-700" 
                    : "bg-red-800 hover:bg-red-900"
                }`}
              >
                Confirm {confirmDecision.decision === "approve" ? "Approve" : "Reject"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {selectedOpId && (
        <OperationDetailDrawer
          opId={selectedOpId}
          onClose={handleCloseDrawer}
          onApprove={(opId, cost) => {
            const localOp = ops?.find((o: any) => o.op_id === opId);
            setConfirmDecision({
              opId,
              action: localOp?.action || "build.deliver",
              domain: localOp?.domain || "build",
              cost,
              decision: "approve"
            });
          }}
          onReject={(opId, cost) => {
            const localOp = ops?.find((o: any) => o.op_id === opId);
            setConfirmDecision({
              opId,
              action: localOp?.action || "build.deliver",
              domain: localOp?.domain || "build",
              cost,
              decision: "reject"
            });
          }}
        />
      )}
    </div>
  );
}
