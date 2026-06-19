"use client";

import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/lib/api-client";
import { useTenant } from "@/contexts/TenantContext";
import { Button } from "@/components/ui/button";
import { 
  Search, 
  Plus, 
  Check, 
  Trash2, 
  Settings, 
  ExternalLink, 
  Globe, 
  Sparkles, 
  AlertCircle, 
  X, 
  Key, 
  Loader2,
  Lock
} from "lucide-react";

// 1. Defined Integrations list matching the backend capabilities
interface IntegrationField {
  name: string;
  label: string;
  type: "text" | "password" | "json";
  required: boolean;
  placeholder?: string;
}

interface IntegrationMeta {
  provider: string;
  name: string;
  category: "Marketing & Ads" | "Commerce & Stores" | "Analytics & SEO" | "Operations & MCPs";
  description: string;
  popular: boolean;
  fields: IntegrationField[];
}

const INTEGRATIONS: IntegrationMeta[] = [
  {
    provider: "google-ads",
    name: "Google Ads",
    category: "Marketing & Ads",
    description: "Manage paid search, display, and video campaigns, bids, and budgets.",
    popular: true,
    fields: [
      { name: "client_id", label: "Client ID", type: "text", required: true },
      { name: "client_secret", label: "Client Secret", type: "text", required: true },
      { name: "developer_token", label: "Developer Token", type: "text", required: true },
      { name: "refresh_token", label: "Refresh Token", type: "text", required: true },
    ]
  },
  {
    provider: "meta-ads",
    name: "Meta Ads",
    category: "Marketing & Ads",
    description: "Manage Facebook & Instagram marketing campaigns, audiences, and custom events.",
    popular: true,
    fields: [
      { name: "ad_account_id", label: "Ad Account ID", type: "text", required: true, placeholder: "act_12345678" },
      { name: "app_id", label: "App ID", type: "text", required: false },
      { name: "app_secret", label: "App Secret", type: "text", required: false },
    ]
  },
  {
    provider: "shopify",
    name: "Shopify Store",
    category: "Commerce & Stores",
    description: "Sync storefront products, inventory, orders, and customer data with Agency OS.",
    popular: true,
    fields: [
      { name: "shop_url", label: "Store URL", type: "text", required: true, placeholder: "brand-name.myshopify.com" }
    ]
  },
  {
    provider: "google-merchant-center",
    name: "Merchant Center",
    category: "Commerce & Stores",
    description: "Feed product catalog directly to Google Shopping and Merchant Center.",
    popular: false,
    fields: [
      { name: "merchant_id", label: "Merchant ID", type: "text", required: true }
    ]
  },
  {
    provider: "google-search-console",
    name: "Search Console",
    category: "Analytics & SEO",
    description: "Monitor website search performance, index status, and organic traffic.",
    popular: false,
    fields: [
      { name: "site_url", label: "Website URL", type: "text", required: true, placeholder: "https://example.com" }
    ]
  },
  {
    provider: "stripe",
    name: "Stripe",
    category: "Operations & MCPs",
    description: "Manage billing, subscription lifecycles, and transaction ledgers.",
    popular: true,
    fields: [
      { name: "api_url", label: "API Base URL", type: "text", required: false, placeholder: "https://api.stripe.com/v1" }
    ]
  },
  {
    provider: "razorpay",
    name: "Razorpay",
    category: "Operations & MCPs",
    description: "Process payments, orders, and payouts locally in INR markets.",
    popular: false,
    fields: []
  },
  {
    provider: "jira",
    name: "Jira Software",
    category: "Operations & MCPs",
    description: "Create tracking tickets, manage agile boards, and link tasks to ops.",
    popular: false,
    fields: [
      { name: "domain", label: "Jira Domain Prefix", type: "text", required: true, placeholder: "e.g. trending-media" }
    ]
  },
  {
    provider: "aws",
    name: "AWS Integration",
    category: "Operations & MCPs",
    description: "Access Amazon Web Services buckets, serverless tasks, and cold storage.",
    popular: false,
    fields: [
      { name: "region", label: "AWS Region", type: "text", required: true, placeholder: "ap-south-1" }
    ]
  },
  {
    provider: "directus",
    name: "Directus CMS",
    category: "Operations & MCPs",
    description: "Connect headless CMS data collections, posts, and assets.",
    popular: false,
    fields: [
      { name: "url", label: "Directus API URL", type: "text", required: true, placeholder: "http://localhost:8055" }
    ]
  }
];

export default function ConnectionsPage() {
  const { request } = useApi();
  const { tenantId, activeBrandId } = useTenant();
  const queryClient = useQueryClient();

  // Search & Filter State
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("All");

  // Modal State
  const [activeIntegration, setActiveIntegration] = useState<IntegrationMeta | null>(null);
  const [editingConnection, setEditingConnection] = useState<any | null>(null);
  const [secretRef, setSecretRef] = useState("");
  const [scope, setScope] = useState("read");
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  // Fetch Connections
  const { data: connections, isLoading: connsLoading } = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => request("/connections", "get"),
  });

  // Create Mutation
  const createMutation = useMutation({
    mutationFn: (data: { brand_id: string; provider: string; scope: string; secret_ref: string; config: any }) =>
      request("/connections", "post", data as any),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections", tenantId] });
      closeModal();
    },
    onError: (err: any) => {
      setFormError(err.message || "Failed to create connection");
    }
  });

  // Update Mutation
  const updateMutation = useMutation({
    mutationFn: (data: { id: string; scope: string; secret_ref: string; config: any }) =>
      request(`/connections/${data.id}` as any, "put", {
        scope: data.scope,
        secret_ref: data.secret_ref,
        config: data.config
      } as any),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections", tenantId] });
      closeModal();
    },
    onError: (err: any) => {
      setFormError(err.message || "Failed to update connection");
    }
  });

  // Delete Mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      request(`/connections/${id}` as any, "delete"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections", tenantId] });
      closeModal();
    },
    onError: (err: any) => {
      setFormError(err.message || "Failed to delete connection");
    }
  });

  // Open modal for connecting a new provider
  const handleOpenConnect = (integration: IntegrationMeta) => {
    setActiveIntegration(integration);
    setEditingConnection(null);
    setSecretRef(
      integration.provider === "google-ads" 
        ? "projects/aos-control-plane/secrets/google-ads-token/versions/latest"
        : integration.provider === "shopify"
        ? "projects/aos-control-plane/secrets/shopify-token/versions/latest"
        : `projects/aos-control-plane/secrets/${integration.provider}-token/versions/latest`
    );
    setScope("read");
    const initialConfig: Record<string, string> = {};
    integration.fields.forEach(f => {
      initialConfig[f.name] = "";
    });
    setConfigValues(initialConfig);
    setFormError(null);
  };

  // Open modal for editing an existing connection
  const handleOpenConfigure = (integration: IntegrationMeta, conn: any) => {
    setActiveIntegration(integration);
    setEditingConnection(conn);
    setSecretRef(conn.secret_ref);
    setScope(conn.scope);
    const currentConfig: Record<string, string> = {};
    integration.fields.forEach(f => {
      currentConfig[f.name] = conn.config[f.name] || "";
    });
    setConfigValues(currentConfig);
    setFormError(null);
  };

  const closeModal = () => {
    setActiveIntegration(null);
    setEditingConnection(null);
    setSecretRef("");
    setScope("read");
    setConfigValues({});
    setFormError(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeIntegration) return;

    if (!activeBrandId) {
      setFormError("No active brand selected. Please select a brand in the header first.");
      return;
    }

    if (!secretRef.trim()) {
      setFormError("Secret Reference is required.");
      return;
    }

    // Validate required fields
    for (const field of activeIntegration.fields) {
      if (field.required && !configValues[field.name]?.trim()) {
        setFormError(`${field.label} is required.`);
        return;
      }
    }

    const payload = {
      brand_id: activeBrandId,
      provider: activeIntegration.provider,
      scope,
      secret_ref: secretRef.trim(),
      config: configValues
    };

    if (editingConnection) {
      updateMutation.mutate({
        id: editingConnection.id,
        scope: payload.scope,
        secret_ref: payload.secret_ref,
        config: payload.config
      });
    } else {
      createMutation.mutate(payload);
    }
  };

  const handleDelete = () => {
    if (editingConnection && window.confirm("Are you sure you want to disconnect this integration?")) {
      deleteMutation.mutate(editingConnection.id);
    }
  };

  // Filtered Integrations
  const filteredIntegrations = useMemo(() => {
    return INTEGRATIONS.filter((integration) => {
      const matchesSearch = 
        integration.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        integration.description.toLowerCase().includes(searchQuery.toLowerCase());
      
      const matchesCategory = 
        selectedCategory === "All" || integration.category === selectedCategory;
      
      return matchesSearch && matchesCategory;
    });
  }, [searchQuery, selectedCategory]);

  if (connsLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 space-y-4">
        <Loader2 className="h-6 w-6 text-zinc-500 animate-spin" />
        <div className="text-zinc-500 text-xs font-mono">Loading integrations directory...</div>
      </div>
    );
  }

  // Grouped active connections by provider
  const activeConnMap = new Map<string, any>();
  if (connections) {
    connections.forEach((conn: any) => {
      activeConnMap.set(conn.provider, conn);
    });
  }

  const categories = ["All", "Marketing & Ads", "Commerce & Stores", "Analytics & SEO", "Operations & MCPs"];

  return (
    <div className="space-y-6">
      {/* Intro Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">Integrations Directory</h3>
          <p className="text-[10px] text-zinc-500 mt-0.5">
            Manually connect, authorize, and configure APIs, MCP servers, and cloud platform adapters.
          </p>
        </div>
        <div className="flex items-center space-x-2 text-[9px] font-mono text-zinc-500 bg-zinc-900/40 px-3 py-1.5 border border-zinc-900 rounded-lg">
          <Lock className="h-3 w-3 text-zinc-600 shrink-0" />
          <span>All keys store securely in your brand's GCP Secret Manager</span>
        </div>
      </div>

      {/* Search & Tabs Toolbar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pt-2">
        {/* Category Tabs */}
        <div className="flex space-x-1 bg-zinc-900/60 border border-zinc-900 p-0.5 rounded-lg text-[10px] self-start">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                selectedCategory === cat
                  ? "bg-zinc-800 text-white font-semibold"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Search Bar */}
        <div className="relative max-w-xs w-full">
          <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-zinc-500" />
          <input
            type="text"
            placeholder="Search connectors..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-zinc-900/40 border border-zinc-900 rounded-lg text-[11px] text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-850"
          />
        </div>
      </div>

      {/* Connectors Grid */}
      {filteredIntegrations.length === 0 ? (
        <div className="text-center py-20 border border-dashed border-zinc-900 rounded-xl">
          <AlertCircle className="h-6 w-6 text-zinc-600 mx-auto mb-2" />
          <p className="text-xs text-zinc-400 font-medium">No connectors found</p>
          <p className="text-[10px] text-zinc-600 mt-0.5">Try adjusting your search query or category filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredIntegrations.map((integration) => {
            const activeConn = activeConnMap.get(integration.provider);
            const isConnected = !!activeConn;

            return (
              <div 
                key={integration.provider} 
                className={`border rounded-xl p-5 bg-zinc-900/10 hover:bg-zinc-900/20 transition-all duration-200 flex flex-col justify-between h-48 relative overflow-hidden ${
                  isConnected ? "border-zinc-800/80" : "border-zinc-900"
                }`}
              >
                {/* Popular Badge */}
                {integration.popular && (
                  <div className="absolute top-0 right-0 bg-zinc-900 border-l border-b border-zinc-850 text-zinc-400 text-[8px] font-bold px-2 py-0.5 uppercase tracking-widest rounded-bl-lg flex items-center gap-0.5">
                    <Sparkles className="h-2 w-2 text-zinc-400" />
                    Popular
                  </div>
                )}

                <div className="space-y-2">
                  <div className="flex items-start justify-between">
                    <div className="space-y-1">
                      {/* Name & Category */}
                      <div className="flex items-center gap-2">
                        <h4 className="text-xs font-bold text-zinc-200">{integration.name}</h4>
                        {isConnected ? (
                          <span className="flex items-center gap-1 px-1.5 py-0.2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded text-[8px] font-bold uppercase tracking-wider">
                            <span className="h-1 w-1 bg-emerald-400 rounded-full animate-pulse" />
                            Connected
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.2 bg-zinc-800/60 border border-zinc-900 text-zinc-500 rounded text-[8px] font-bold uppercase tracking-wider">
                            Absent
                          </span>
                        )}
                      </div>
                      <span className="text-[8px] text-zinc-500 font-mono uppercase tracking-wider">{integration.category}</span>
                    </div>
                  </div>

                  {/* Description */}
                  <p className="text-[10px] text-zinc-400 leading-relaxed pr-6">{integration.description}</p>
                </div>

                {/* Footer Actions */}
                <div className="flex items-center justify-between pt-3 border-t border-zinc-900/60 mt-3">
                  <div className="text-[9px] font-mono text-zinc-500 max-w-[200px] truncate">
                    {isConnected ? (
                      <span className="flex items-center gap-1">
                        <Key className="h-2.5 w-2.5 text-zinc-600" />
                        Ref: <code className="text-zinc-400">{activeConn.secret_ref.split('/').pop()}</code>
                      </span>
                    ) : (
                      <span>Unconnected integration</span>
                    )}
                  </div>

                  <div className="flex items-center space-x-1.5">
                    {isConnected ? (
                      <Button
                        size="sm"
                        onClick={() => handleOpenConfigure(integration, activeConn)}
                        className="bg-zinc-900 hover:bg-zinc-850 text-zinc-300 border border-zinc-800 text-[9px] h-7 px-2.5 gap-1 rounded"
                      >
                        <Settings className="h-3 w-3 text-zinc-400" />
                        Configure
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => handleOpenConnect(integration)}
                        className="bg-zinc-100 hover:bg-zinc-200 text-zinc-950 font-semibold text-[9px] h-7 px-2.5 gap-0.5 rounded"
                      >
                        <Plus className="h-3 w-3" />
                        Connect
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Dynamic Connection/Configuration Modal */}
      {activeIntegration && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-950 border border-zinc-900 rounded-xl p-6 max-w-md w-full space-y-5 shadow-2xl">
            {/* Modal Header */}
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">
                  {editingConnection ? "Configure Integration" : "Connect Integration"}
                </h3>
                <h4 className="text-sm font-semibold text-zinc-100">{activeIntegration.name}</h4>
              </div>
              <button 
                onClick={closeModal}
                className="text-zinc-500 hover:text-zinc-300 transition-colors rounded p-1 hover:bg-zinc-900"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Modal Body Form */}
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Secret Reference Field */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-[9px] uppercase tracking-wider text-zinc-400 font-semibold flex items-center gap-1">
                    <Lock className="h-3 w-3 text-zinc-500" />
                    Secret Manager Reference Path
                  </label>
                  <span className="text-[8px] text-red-400 uppercase font-bold font-mono">Required</span>
                </div>
                <input 
                  type="text"
                  required
                  placeholder="projects/.../secrets/.../versions/latest"
                  value={secretRef}
                  onChange={(e) => setSecretRef(e.target.value)}
                  className="w-full bg-zinc-900 border border-zinc-900 rounded-lg px-3 py-2 text-[11px] text-zinc-200 focus:outline-none focus:border-zinc-800 font-mono"
                />
                <p className="text-[9px] text-zinc-500 leading-normal">
                  Reference to the credential stored in your GCP Secret Manager. For local dev, you can use a raw token or mock string.
                </p>
              </div>

              {/* Scope Field */}
              <div className="space-y-1.5">
                <label className="text-[9px] uppercase tracking-wider text-zinc-400 font-semibold">Scope</label>
                <input 
                  type="text"
                  required
                  placeholder="read,write"
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                  className="w-full bg-zinc-900 border border-zinc-900 rounded-lg px-3 py-2 text-[11px] text-zinc-200 focus:outline-none focus:border-zinc-800 font-mono"
                />
              </div>

              {/* Dynamic Config Fields */}
              {activeIntegration.fields.map((field) => (
                <div key={field.name} className="space-y-1.5 border-t border-zinc-900/50 pt-3">
                  <div className="flex items-center justify-between">
                    <label className="text-[9px] uppercase tracking-wider text-zinc-400 font-semibold">{field.label}</label>
                    {field.required ? (
                      <span className="text-[8px] text-red-400 uppercase font-bold font-mono">Required</span>
                    ) : (
                      <span className="text-[8px] text-zinc-600 uppercase font-semibold font-mono">Optional</span>
                    )}
                  </div>
                  <input 
                    type="text"
                    required={field.required}
                    placeholder={field.placeholder || `Enter ${field.label}`}
                    value={configValues[field.name] || ""}
                    onChange={(e) => setConfigValues(prev => ({ ...prev, [field.name]: e.target.value }))}
                    className="w-full bg-zinc-900 border border-zinc-900 rounded-lg px-3 py-2 text-[11px] text-zinc-200 focus:outline-none focus:border-zinc-800 font-mono"
                  />
                </div>
              ))}

              {/* Error Alert */}
              {formError && (
                <div className="bg-red-950/40 border border-red-900/40 text-red-300 rounded-lg p-3 text-[10px] font-mono flex items-start gap-2">
                  <AlertCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
                  <span>{formError}</span>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex items-center justify-between pt-4 border-t border-zinc-900/60 mt-5">
                {editingConnection ? (
                  <Button
                    type="button"
                    onClick={handleDelete}
                    disabled={deleteMutation.isPending}
                    className="bg-red-950/60 hover:bg-red-900 border border-red-900/50 text-red-200 hover:text-white font-medium text-[10px] h-8 px-3 rounded-lg flex items-center gap-1 disabled:opacity-50"
                  >
                    {deleteMutation.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                    Disconnect
                  </Button>
                ) : (
                  <div /> // spacing spacer
                )}

                <div className="flex space-x-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={closeModal}
                    className="border-zinc-900 text-zinc-400 hover:bg-zinc-900 text-[10px] h-8 px-4 rounded-lg"
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={createMutation.isPending || updateMutation.isPending}
                    className="bg-zinc-100 hover:bg-zinc-200 text-zinc-950 font-bold text-[10px] h-8 px-4 rounded-lg flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {(createMutation.isPending || updateMutation.isPending) && (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    )}
                    {editingConnection ? "Save Changes" : "Connect Integration"}
                  </Button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
