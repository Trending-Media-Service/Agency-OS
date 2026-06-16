"use client";

import React, { createContext, useContext, useState, useEffect } from "react";

export interface KnownTenant {
  tenantId: string;
  tenantName: string;
  brandId: string;
  brandName: string;
}

interface TenantContextType {
  tenantId: string;
  setTenantId: (id: string) => void;
  activeBrandId: string | null;
  setActiveBrandId: (id: string | null) => void;
  role: string;
  setRole: (role: string) => void;
  knownTenants: KnownTenant[];
  addKnownTenant: (tenantId: string, tenantName: string, brandId: string, brandName: string) => void;
}

const TenantContext = createContext<TenantContextType | undefined>(undefined);

const DEFAULT_TENANTS: KnownTenant[] = [
  {
    tenantId: "t1",
    tenantName: "Bootstrap Developer",
    brandId: "brand-bootstrap",
    brandName: "Bootstrap Brand"
  }
];

export function TenantProvider({ children }: { children: React.ReactNode }) {
  const [tenantId, setTenantIdState] = useState<string>("t1");
  const [activeBrandId, setActiveBrandIdState] = useState<string | null>("brand-bootstrap");
  const [role, setRoleState] = useState<string>("AGENCY_OWNER"); // default dev role
  const [knownTenants, setKnownTenants] = useState<KnownTenant[]>(DEFAULT_TENANTS);

  // Load from localStorage on client boot
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Loaded on client mount to prevent SSR hydration mismatch */
    const savedTenant = localStorage.getItem("aos_tenant_id");
    if (savedTenant) {
      setTenantIdState(savedTenant);
    }
    const savedBrand = localStorage.getItem("aos_brand_id");
    if (savedBrand) {
      setActiveBrandIdState(savedBrand);
    }
    const savedRole = localStorage.getItem("aos_role");
    if (savedRole) {
      setRoleState(savedRole);
    }
    
    const savedKnownTenants = localStorage.getItem("aos_known_tenants");
    if (savedKnownTenants) {
      try {
        setKnownTenants(JSON.parse(savedKnownTenants));
      } catch {
        setKnownTenants(DEFAULT_TENANTS);
      }
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const setTenantId = (id: string) => {
    setTenantIdState(id);
    localStorage.setItem("aos_tenant_id", id);
    
    // Also auto-select the first brand of this tenant if found in known tenants
    const tenantObj = knownTenants.find(t => t.tenantId === id);
    if (tenantObj) {
      setActiveBrandId(tenantObj.brandId);
    }
  };

  const setActiveBrandId = (id: string | null) => {
    setActiveBrandIdState(id);
    if (id) {
      localStorage.setItem("aos_brand_id", id);
    } else {
      localStorage.removeItem("aos_brand_id");
    }
  };

  const setRole = (r: string) => {
    setRoleState(r);
    localStorage.setItem("aos_role", r);
  };

  const addKnownTenant = (tId: string, tName: string, bId: string, bName: string) => {
    setKnownTenants(prev => {
      // Prevent duplicates
      if (prev.some(t => t.tenantId === tId)) return prev;
      const updated = [...prev, { tenantId: tId, tenantName: tName, brandId: bId, brandName: bName }];
      localStorage.setItem("aos_known_tenants", JSON.stringify(updated));
      return updated;
    });
  };

  return (
    <TenantContext.Provider value={{ 
      tenantId, 
      setTenantId, 
      activeBrandId, 
      setActiveBrandId, 
      role, 
      setRole, 
      knownTenants, 
      addKnownTenant 
    }}>
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
