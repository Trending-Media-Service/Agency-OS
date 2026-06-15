import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Home from "./page";

// Mock Tenant Context
const mockSetRole = vi.fn();
vi.mock("@/contexts/TenantContext", () => ({
  useTenant: () => ({
    tenantId: "t1",
    role: "AGENCY_OWNER",
    setRole: mockSetRole,
  }),
}));

// Mock API client
const mockRequest = vi.fn();
vi.mock("@/lib/api-client", () => ({
  useApi: () => ({
    request: mockRequest,
  }),
}));

describe("Governance Dashboard Home Page", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    vi.clearAllMocks();
  });

  const renderWithProviders = () => {
    return render(
      <QueryClientProvider client={queryClient}>
        <Home />
      </QueryClientProvider>
    );
  };

  it("renders operations queue table with active items", async () => {
    mockRequest.mockImplementation((path: string) => {
      if (path === "/ops") {
        return Promise.resolve([
          {
            op_id: "op-1",
            tenant_id: "t1",
            brand_id: "brand-1",
            domain: "grow",
            action: "grow.campaign.pause",
            state: "AWAITING_APPROVAL",
            preview: "Pause Shopify active marketing campaigns",
            cost_estimate: "150.00 INR",
          },
        ]);
      }
      if (path === "/connections") return Promise.resolve([]);
      if (path === "/circuit-breakers") return Promise.resolve([]);
      if (path === "/audit/events") return Promise.resolve([]);
      if (path === "/audit/verify") return Promise.resolve({ ok: true });
      return Promise.resolve(null);
    });

    renderWithProviders();

    // Check header
    expect(screen.getByText("Governance Console")).toBeTruthy();

    // Operations list
    await waitFor(() => {
      expect(screen.getByText("grow.campaign.pause")).toBeTruthy();
      expect(screen.getByText("Pause Shopify active marketing campaigns")).toBeTruthy();
      expect(screen.getByText("AWAITING_APPROVAL")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
    });
  });

  it("displays red warning banner when a circuit breaker trips (state is OPEN)", async () => {
    mockRequest.mockImplementation((path: string) => {
      if (path === "/ops") return Promise.resolve([]);
      if (path === "/connections") return Promise.resolve([]);
      if (path === "/circuit-breakers") {
        return Promise.resolve([
          {
            brand_id: "brand-1",
            domain: "grow",
            state: "OPEN",
            consecutive_failures: 3,
            tripped_at: "2026-06-15T08:00:00Z",
            last_failure_at: "2026-06-15T08:00:00Z",
          },
        ]);
      }
      if (path === "/audit/events") return Promise.resolve([]);
      if (path === "/audit/verify") return Promise.resolve({ ok: true });
      return Promise.resolve(null);
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText(/Safety shutdown active on domain/)).toBeTruthy();
      expect(screen.getByText(/'grow'/)).toBeTruthy();
    });
  });

  it("renders active connection cards in connections tab", async () => {
    mockRequest.mockImplementation((path: string) => {
      if (path === "/ops") return Promise.resolve([]);
      if (path === "/connections") {
        return Promise.resolve([
          {
            id: "conn-1",
            provider: "shopify",
            scope: "read_products,write_orders",
            secret_ref: "gcp:secret:shopify",
            config: { shop_url: "tanmatra.myshopify.com" },
            created_at: "2026-06-15T08:00:00Z",
          },
        ]);
      }
      if (path === "/circuit-breakers") return Promise.resolve([]);
      if (path === "/audit/events") return Promise.resolve([]);
      if (path === "/audit/verify") return Promise.resolve({ ok: true });
      return Promise.resolve(null);
    });

    renderWithProviders();

    // Click on Active Connections tab
    const tabButton = screen.getByRole("button", { name: /Active Connections/ });
    fireEvent.click(tabButton);

    await waitFor(() => {
      expect(screen.getByText("shopify")).toBeTruthy();
      expect(screen.getByText("read_products,write_orders")).toBeTruthy();
      expect(screen.getByText("gcp:secret:shopify")).toBeTruthy();
    });
  });
});
