"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { AlertTriangle, CheckCircle } from "lucide-react";

export default function AuditPage() {
  const { request } = useApi();
  const { tenantId } = useTenant();

  // 1. Fetch Audit Log Events
  const { data: auditEvents, isLoading: auditLoading } = useQuery({
    queryKey: ["auditEvents", tenantId],
    queryFn: () => request("/audit/events", "get"),
    refetchInterval: 5000,
  });

  // 2. Fetch Audit Chain Integrity verification
  const { data: auditVerify } = useQuery({
    queryKey: ["auditVerify", tenantId],
    queryFn: () => request("/audit/verify", "get"),
    refetchInterval: 10000,
  });

  if (auditLoading) {
    return <div className="text-zinc-500 text-xs py-10 text-center">Loading audit log events...</div>;
  }

  return (
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
  );
}
