"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { CheckCircle, XCircle } from "lucide-react";

export default function SafetyPage() {
  const { request } = useApi();
  const { tenantId } = useTenant();

  // Fetch Circuit Breakers
  const { data: breakers, isLoading: breakersLoading } = useQuery({
    queryKey: ["breakers", tenantId],
    queryFn: () => request("/circuit-breakers", "get"),
    refetchInterval: 5000,
  });

  if (breakersLoading) {
    return <div className="text-zinc-500 text-xs py-10 text-center">Loading safety status...</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">Circuit Breakers</h3>
        <p className="text-[10px] text-zinc-500">Real-time status of safety circuit breakers guarding adapter invocations</p>
      </div>

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
  );
}
