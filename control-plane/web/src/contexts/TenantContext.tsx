"use client";

import React, { createContext, useContext, useState, useEffect } from "react";

interface TenantContextType {
  tenantId: string;
  setTenantId: (id: string) => void;
  role: string;
  setRole: (role: string) => void;
}

const TenantContext = createContext<TenantContextType | undefined>(undefined);

export function TenantProvider({ children }: { children: React.ReactNode }) {
  const [tenantId, setTenantIdState] = useState<string>("t1");
  const [role, setRoleState] = useState<string>("AGENCY_OWNER"); // default dev role

  // Load from localStorage on client boot
  useEffect(() => {
    const savedTenant = localStorage.getItem("aos_tenant_id");
    if (savedTenant) {
      setTenantIdState(savedTenant);
    }
    const savedRole = localStorage.getItem("aos_role");
    if (savedRole) {
      setRoleState(savedRole);
    }
  }, []);

  const setTenantId = (id: string) => {
    setTenantIdState(id);
    localStorage.setItem("aos_tenant_id", id);
  };

  const setRole = (r: string) => {
    setRoleState(r);
    localStorage.setItem("aos_role", r);
  };

  return (
    <TenantContext.Provider value={{ tenantId, setTenantId, role, setRole }}>
      {children}
    </TenantContext.Provider>
  );
}

export function useTenant() {
  const context = useContext(TenantContext);
  if (context === undefined) {
    throw new Error("useTenant must be used within a TenantProvider");
  }
  return context;
}
