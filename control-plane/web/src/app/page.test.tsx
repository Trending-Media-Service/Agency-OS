import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DashboardLayout from "./(dashboard)/layout";
import OpsPage from "./(dashboard)/ops/page";

// Mock Tenant Context
let mockRole = "AGENCY_OWNER";
const mockSetRole = vi.fn();
vi.mock("@/contexts/TenantContext", () => ({
  useTenant: () => ({
    tenantId: "t1",
    setTenantId: vi.fn(),
    activeBrandId: "brand-bootstrap",
    setActiveBrandId: vi.fn(),
    role: mockRole,
    setRole: mockSetRole,
    operatorToken: "",
    setOperatorToken: vi.fn(),
    knownTenants: [
      { tenantId: "t1", tenantName: "Bootstrap Developer", brandId: "brand-bootstrap", brandName: "Bootstrap Brand" },
    ],
    addKnownTenant: vi.fn(),
  }),
}));

// Mock Next.js Navigation
vi.mock("next/navigation", () => ({
  usePathname: () => "/ops",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

// Mock API client
const mockRequest = vi.fn();
vi.mock("@/lib/api-client", () => ({
  useApi: () => ({ request: mockRequest }),
}));

const CATALOG = {
  actions: [
    {
      name: "provision_web_host",
      title: "Provision Web Host",
      description: "domain to host",
      domain: "provision",
      parameters: { properties: { domain: { type: "STRING", description: "domain to host" } }, required: ["domain"] },
    },
  ],
};

describe("Operator Actions panel (explicit controls, no chat)", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    mockRole = "AGENCY_OWNER";
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.clearAllMocks();
  });

  const renderWithProviders = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <DashboardLayout>
          <OpsPage />
        </DashboardLayout>
      </QueryClientProvider>
    );

  it("renders the actions panel and submits a structured action to /actions", async () => {
    mockRequest.mockImplementation((path: string, method?: string) => {
      if (path === "/ops") return Promise.resolve([]);
      if (path === "/connections") return Promise.resolve([]);
      if (path === "/circuit-breakers") return Promise.resolve([]);
      if (path === "/audit/events") return Promise.resolve([]);
      if (path === "/audit/verify") return Promise.resolve({ ok: true });
      if (path === "/actions/catalog" && method === "get") return Promise.resolve(CATALOG);
      if (path === "/actions" && method === "post") {
        return Promise.resolve({
          cards: [{ op_id: "op-1", action: "provision.web_host.create", state: "AWAITING_APPROVAL", preview: "plan", cost_estimate: "2500.00 INR/mo", violations: [] }],
        });
      }
      return Promise.resolve(null);
    });

    renderWithProviders();

    expect(screen.getByRole("heading", { name: /Operator Actions/i })).toBeTruthy();

    // The catalog action button renders, then opens a modal on click.
    const actionBtn = await screen.findByRole("button", { name: /Provision Web Host/i });
    fireEvent.click(actionBtn);

    const input = await screen.findByPlaceholderText(/domain to host/i);
    fireEvent.change(input, { target: { value: "ableys.in" } });
    fireEvent.click(screen.getByRole("button", { name: /Propose Action/i }));

    await waitFor(() => {
      expect(mockRequest).toHaveBeenCalledWith("/actions", "post", {
        tool: "provision_web_host",
        brand_id: "brand-bootstrap",
        params: { domain: "ableys.in" },
      });
    });
  });

  it("disables actions and hides approve/reject for BRAND_VIEWER", async () => {
    mockRole = "BRAND_VIEWER";
    mockRequest.mockImplementation((path: string, method?: string) => {
      if (path === "/ops") return Promise.resolve([
        { op_id: "op-v", action: "grow.bid.adjust", state: "AWAITING_APPROVAL", domain: "grow", brand_id: "b1", preview: "x", cost_estimate: "100 INR" },
      ]);
      if (path === "/connections") return Promise.resolve([]);
      if (path === "/circuit-breakers") return Promise.resolve([]);
      if (path === "/audit/events") return Promise.resolve([]);
      if (path === "/audit/verify") return Promise.resolve({ ok: true });
      if (path === "/actions/catalog" && method === "get") return Promise.resolve(CATALOG);
      return Promise.resolve(null);
    });

    renderWithProviders();

    // Action button renders but is disabled for the read-only role.
    const actionBtn = await screen.findByRole("button", { name: /Provision Web Host/i });
    expect((actionBtn as HTMLButtonElement).disabled).toBe(true);

    // Operations queue shows no approve/reject for the viewer.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    });
  });
});
