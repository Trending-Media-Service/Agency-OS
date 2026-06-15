"use client";

import React, { useState, useEffect } from "react";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";

export function DevGate({ children }: { children: React.ReactNode }) {
  const { tenantId, setTenantId, role, setRole } = useTenant();
  const [entered, setEntered] = useState<boolean>(false);
  const [inputTenant, setInputTenant] = useState(tenantId);
  const [inputRole, setInputRole] = useState(role);

  useEffect(() => {
    const savedEntered = localStorage.getItem("aos_dev_gate_entered");
    if (savedEntered === "true") {
      setEntered(true);
    }
  }, []);

  const handleEnter = (e: React.FormEvent) => {
    e.preventDefault();
    setTenantId(inputTenant);
    setRole(inputRole);
    setEntered(true);
    localStorage.setItem("aos_dev_gate_entered", "true");
  };

  const handleSignOut = () => {
    setEntered(false);
    localStorage.setItem("aos_dev_gate_entered", "false");
  };

  if (!entered) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-950 text-zinc-50 p-6">
        <form onSubmit={handleEnter} className="w-full max-w-sm bg-zinc-900 border border-zinc-800 rounded-lg p-8 space-y-6 shadow-xl">
          <div className="space-y-2 text-center">
            <h1 className="text-2xl font-bold tracking-tight">Agency OS Gateway</h1>
            <p className="text-sm text-zinc-400">Dev mode authentication & context bypass</p>
          </div>
          
          <div className="space-y-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-zinc-400">Tenant ID</label>
              <input
                type="text"
                value={inputTenant}
                onChange={(e) => setInputTenant(e.target.value)}
                className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-md focus:outline-none focus:border-zinc-700 text-sm"
                required
              />
            </div>
            
            <div className="space-y-1">
              <label className="text-xs font-semibold text-zinc-400">Role Authority</label>
              <select
                value={inputRole}
                onChange={(e) => setInputRole(e.target.value)}
                className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-md focus:outline-none focus:border-zinc-700 text-sm text-zinc-300"
              >
                <option value="AGENCY_OWNER">AGENCY_OWNER</option>
                <option value="OPERATOR">OPERATOR</option>
                <option value="BRAND_VIEWER">BRAND_VIEWER</option>
              </select>
            </div>
          </div>

          <Button type="submit" className="w-full bg-zinc-100 text-zinc-950 hover:bg-zinc-200">
            Enter Dashboard
          </Button>
        </form>
      </div>
    );
  }

  return (
    <>
      {/* Dev Bar at the top of the shell */}
      <div className="bg-zinc-900 border-b border-zinc-800 px-4 py-2 flex items-center justify-between text-xs text-zinc-400">
        <div className="flex items-center space-x-4">
          <span>Active Tenant: <strong className="text-zinc-200">{tenantId}</strong></span>
          <span>Role: <strong className="text-zinc-200">{role}</strong></span>
        </div>
        <button 
          onClick={handleSignOut}
          className="text-zinc-400 hover:text-zinc-200 underline"
        >
          Change Context / Exit
        </button>
      </div>
      {children}
    </>
  );
}
