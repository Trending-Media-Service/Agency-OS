import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Home from "./page";

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
    knownTenants: [
      { tenantId: "t1", tenantName: "Bootstrap Developer", brandId: "brand-bootstrap", brandName: "Bootstrap Brand" },
      { tenantId: "tenant-acme", tenantName: "Acme", brandId: "brand-acme", brandName: "Acme Retail" },
    ],
    addKnownTenant: vi.fn(),
  }),
}));

// Mock API client
const mockRequest = vi.fn();
vi.mock("@/lib/api-client", () => ({
  useApi: () => ({
    request: mockRequest,
  }),
}));

describe("Conversational Chat UI and Dashboard", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    mockRole = "AGENCY_OWNER";
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

  it("renders partner chat panel and submits user prompts", async () => {
    mockRequest.mockImplementation((path: string, method?: string) => {
      if (path === "/ops") return Promise.resolve([]);
      if (path === "/connections") return Promise.resolve([]);
      if (path === "/circuit-breakers") return Promise.resolve([]);
      if (path === "/audit/events") return Promise.resolve([]);
      if (path === "/audit/verify") return Promise.resolve({ ok: true });
      
      if (path === "/chat" && method === "post") {
        return Promise.resolve({
          reply: "I have planned your request. Please approve the proposal.",
          cards: [
            {
              op_id: "op-grow-bid",
              action: "grow.bid.adjust",
              state: "AWAITING_APPROVAL",
              preview: "Adjust bid for campaign camp-123 to 50 INR",
              cost_estimate: "Free",
              violations: [],
            }
          ]
        });
      }
      return Promise.resolve(null);
    });

    renderWithProviders();

    expect(screen.getByText(/Partner Chat/i)).toBeTruthy();
    expect(screen.getByText(/Hello! I am your Agency OS partner agent/i)).toBeTruthy();

    const input = screen.getByPlaceholderText(/e.g. configure email dns routing/i);
    fireEvent.change(input, { target: { value: "adjust bid for campaign camp-123" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(mockRequest).toHaveBeenCalledWith("/chat", "post", {
        brand_id: "brand-bootstrap",
        text: "adjust bid for campaign camp-123"
      });
      expect(screen.getByText("I have planned your request. Please approve the proposal.")).toBeTruthy();
      expect(screen.getByText("grow.bid.adjust")).toBeTruthy();
      expect(screen.getByText("Adjust bid for campaign camp-123 to 50 INR")).toBeTruthy();
      
      const approveBtn = screen.getAllByRole("button", { name: "Approve" })[0];
      expect(approveBtn).toBeTruthy();
    });
  });

  it("triggers decision mutation when clicking approve on a proposal card", async () => {
    mockRequest.mockImplementation((path: string, method?: string) => {
      if (path === "/ops") return Promise.resolve([]);
      if (path === "/connections") return Promise.resolve([]);
      if (path === "/circuit-breakers") return Promise.resolve([]);
      if (path === "/audit/events") return Promise.resolve([]);
      if (path === "/audit/verify") return Promise.resolve({ ok: true });
      
      if (path === "/chat" && method === "post") {
        return Promise.resolve({
          reply: "Planned.",
          cards: [
            {
              op_id: "op-approve-test",
              action: "grow.bid.adjust",
              state: "AWAITING_APPROVAL",
              preview: "Test Approve",
              cost_estimate: "Free",
            }
          ]
        });
      }
      
      if (path === "/ops/op-approve-test/decision" && method === "post") {
        return Promise.resolve({ op_id: "op-approve-test", state: "APPROVED" });
      }
      
      return Promise.resolve(null);
    });

    renderWithProviders();

    const input = screen.getByPlaceholderText(/e.g. configure email dns routing/i);
    fireEvent.change(input, { target: { value: "test approve" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(async () => {
      const approveBtn = screen.getAllByRole("button", { name: "Approve" })[0];
      fireEvent.click(approveBtn);
    });

    await waitFor(() => {
      expect(mockRequest).toHaveBeenCalledWith("/ops/op-approve-test/decision", "post", {
        decision: "approve",
        actor: "chandan",
        role: "AGENCY_OWNER",
        surface: "web"
      });
    });
  });

  it("hides and disables all control mutations when role is BRAND_VIEWER", async () => {
    mockRole = "BRAND_VIEWER";
    
    mockRequest.mockImplementation((path: string) => {
      if (path === "/ops") return Promise.resolve([
        {
          op_id: "op-viewer-test",
          action: "grow.bid.adjust",
          state: "AWAITING_APPROVAL",
          domain: "search",
          brand_id: "brand-1",
          preview: "Test operations visibility under viewer",
          cost_estimate: "100 INR"
        }
      ]);
      if (path === "/connections") return Promise.resolve([]);
      if (path === "/circuit-breakers") return Promise.resolve([]);
      if (path === "/audit/events") return Promise.resolve([]);
      if (path === "/audit/verify") return Promise.resolve({ ok: true });
      return Promise.resolve(null);
    });

    renderWithProviders();

    // 1. Check operations queue table does NOT render approve/reject buttons
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    });

    // 2. Check chat input is disabled and read-only text is displayed
    const input = screen.getByPlaceholderText(/Transparency Portal/i);
    expect(input).toBeTruthy();
    expect((input as HTMLInputElement).disabled).toBe(true);
  });
});
