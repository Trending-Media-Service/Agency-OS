"use client";

import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";

export default function OpsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { request } = useApi();
  const { tenantId, role } = useTenant();

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
  );
}
