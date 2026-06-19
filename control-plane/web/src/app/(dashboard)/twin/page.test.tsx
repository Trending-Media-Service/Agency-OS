import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TwinPage from "./page";

// Mock Tenant Context
let mockRole = "AGENCY_OWNER";
vi.mock("@/contexts/TenantContext", () => ({
  useTenant: () => ({
    tenantId: "t1",
    activeBrandId: "b1",
    role: mockRole,
  }),
}));

// Mock API client
const mockRequest = vi.fn();
vi.mock("@/lib/api-client", () => ({
  useApi: () => ({ request: mockRequest }),
}));

describe("Brand Twin Cockpit Page", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    mockRole = "AGENCY_OWNER";
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.clearAllMocks();
  });

  const renderWithProviders = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <TwinPage />
      </QueryClientProvider>
    );

  it("renders the twin cockpit with strategic goal, B-score, and recommendations", async () => {
    // Mock the backend requests
    mockRequest.mockImplementation((path: string, method?: string) => {
      if (path === "/brands/b1/objective" && method === "get") {
        return Promise.resolve({ brand_id: "b1", objective: "footprint" });
      }
      if (path === "/brands/b1/recommendations" && method === "get") {
        return Promise.resolve([
          {
            action: "presence.google.connect",
            domain: "presence",
            params: { provider: "google" },
            preview_summary: "Connect Google Search Console and Merchant Center channels to establish presence.",
            impact: 1,
            reversibility: "COMPENSATABLE",
            cost_minor: 0,
          },
        ]);
      }
      if (path === "/brands/b1/performance-score" && method === "get") {
        return Promise.resolve({
          brand_id: "b1",
          performance_score: { score: 78.0 },
        });
      }
      if (path === "/connections" && method === "get") {
        return Promise.resolve([]);
      }
      return Promise.resolve(null);
    });

    renderWithProviders();

    // 1. Verify Header and Strategic Selector
    expect(screen.getByRole("heading", { name: /Brand Twin Cockpit/i })).toBeTruthy();
    
    // Check active objective (Footprint button should be rendered and styled as active)
    const footprintBtn = await screen.findByRole("button", { name: /Footprint/i });
    expect(footprintBtn).toBeTruthy();

    // 2. Verify B-score is rendered
    expect(await screen.findByText("78")).toBeTruthy();

    // 3. Verify recommendation card is rendered
    expect(
      await screen.findByText("Connect Google Search Console and Merchant Center channels to establish presence.")
    ).toBeTruthy();
  });

  it("allows the operator to change the strategic goal", async () => {
    mockRequest.mockImplementation((path: string, method?: string) => {
      if (path === "/brands/b1/objective") {
        return method === "get" 
          ? Promise.resolve({ brand_id: "b1", objective: "footprint" })
          : Promise.resolve({ brand_id: "b1", objective: "growth" });
      }
      if (path === "/brands/b1/recommendations") return Promise.resolve([]);
      if (path === "/brands/b1/performance-score") return Promise.resolve({ performance_score: { score: 85.0 } });
      if (path === "/connections") return Promise.resolve([]);
      return Promise.resolve(null);
    });

    renderWithProviders();

    // Click on the Growth objective button
    const growthBtn = await screen.findByRole("button", { name: /Growth/i });
    fireEvent.click(growthBtn);

    // Verify it posts the objective change to the backend
    await waitFor(() => {
      expect(mockRequest).toHaveBeenCalledWith("/brands/b1/objective", "post", {
        objective: "growth",
      });
    });
  });

  it("submits a structured proposal when clicking Propose Action on a recommendation", async () => {
    const testRec = {
      action: "presence.google.connect",
      domain: "presence",
      params: { provider: "google" },
      preview_summary: "Connect Google Search Console",
      impact: 1,
      reversibility: "COMPENSATABLE",
      cost_minor: 0,
    };

    mockRequest.mockImplementation((path: string, method?: string) => {
      if (path === "/brands/b1/objective") return Promise.resolve({ objective: "footprint" });
      if (path === "/brands/b1/recommendations") return Promise.resolve([testRec]);
      if (path === "/brands/b1/performance-score") return Promise.resolve({ performance_score: { score: 85.0 } });
      if (path === "/connections") return Promise.resolve([]);
      if (path === "/actions" && method === "post") return Promise.resolve({ ok: true });
      return Promise.resolve(null);
    });

    renderWithProviders();

    // Click "Propose Action" on the recommendation card
    const proposeBtn = await screen.findByRole("button", { name: /Propose Action/i });
    fireEvent.click(proposeBtn);

    // Verify it proposes the action on /actions with snake_case tool mapping
    await waitFor(() => {
      expect(mockRequest).toHaveBeenCalledWith("/actions", "post", {
        tool: "presence_google_connect",
        brand_id: "b1",
        params: { provider: "google" },
      });
    });
  });
});
