"use client";

import React from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { OpDetailDrawer, OpDetailData } from "@/components/op-detail-drawer";

export function DashboardDrawer() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { request } = useApi();
  const { tenantId, role } = useTenant();

  const selectedOpId = searchParams.get("opId");

  const { data: selectedOp, isLoading: selectedOpLoading } = useQuery({
    queryKey: ["opDetail", selectedOpId],
    queryFn: () => selectedOpId ? request(`/ops/${selectedOpId}` as "/ops/{op_id}", "get") : null,
    enabled: selectedOpId !== null,
  });

  const { refetch: refetchOps } = useQuery({
    queryKey: ["ops", tenantId],
    enabled: false
  });

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
      closeDrawer();
    }
  });

  const closeDrawer = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("opId");
    router.push(`${pathname}?${params.toString()}`);
  };

  const handleDecision = (opId: string, decision: "approve" | "reject" | "modify", reason?: string) => {
    decisionMutation.mutate({ opId, decision, reason });
  };

  if (!selectedOpId) return null;

  return (
    <OpDetailDrawer
      opId={selectedOpId}
      opData={(selectedOp as OpDetailData) || null}
      loading={selectedOpLoading}
      onClose={closeDrawer}
      onDecision={handleDecision}
      role={role}
    />
  );
}
