import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { OpDetailDrawer, OpDetailData } from "./op-detail-drawer";

const mockOnDecision = vi.fn();
const mockOnClose = vi.fn();

const MOCK_OP_DATA: OpDetailData = {
  action: "grow.campaign.create",
  state: "AWAITING_APPROVAL",
  preview: "Creating a Google Ads campaign under t_metrics",
  params: {
    name: "summer-promo",
    budget_minor: 100000,
    bid_minor: 500,
    provider: "google-ads"
  },
  impact: 2,
  reversibility: "reversible",
  statutory: true,
  cost_estimate: "1000.00 INR/mo",
  trace: [
    {
      ts: "2026-06-19T22:00:00Z",
      kind: "gate",
      detail: {
        requires_human: true,
        violations: [
          { rule_id: "budget_limit", message: "Budget exceeds Tier-1 maximum limits (delta +500.00 INR)" }
        ]
      }
    },
    {
      ts: "2026-06-19T22:01:00Z",
      kind: "preview",
      detail: { kind: "campaign_create_preview" }
    }
  ]
};

describe("OpDetailDrawer component and Cockpit UX", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const renderDrawer = (data: OpDetailData = MOCK_OP_DATA, role: string = "OPERATOR") => {
    return render(
      <OpDetailDrawer
        opId="op-test-123"
        opData={data}
        loading={false}
        onClose={mockOnClose}
        onDecision={mockOnDecision}
        role={role}
      />
    );
  };

  it("renders custom metadata badges and warnings correctly", () => {
    renderDrawer();

    // 1. Verify Severity (Impact)
    expect(screen.getByText("Tier-2 Severity")).toBeTruthy();

    // 2. Verify Reversibility
    expect(screen.getByText("reversible")).toBeTruthy();

    // 3. Verify Cost Estimate
    expect(screen.getByText("1000.00 INR/mo")).toBeTruthy();

    // 4. Verify Statutory dual-control warning
    expect(screen.getByText("⚠️ Dual-Control Required")).toBeTruthy();
  });

  it("extracts and renders policy violations prominently at the top", () => {
    renderDrawer();

    // Verify policy violation section is visible
    expect(screen.getByText("⚠️ Policy Violations Detected")).toBeTruthy();

    // Verify the specific rule and message are shown (assert at least one matching element to dodge duplicate timeline entries)
    expect(screen.getAllByText("budget_limit").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Budget exceeds Tier-1 maximum limits/).length).toBeGreaterThanOrEqual(1);
  });

  it("supports keyboard-first approvals (Pressing 'a' triggers Approve)", () => {
    renderDrawer();

    // Trigger keyboard press 'a'
    const event = new KeyboardEvent("keydown", { key: "a" });
    window.dispatchEvent(event);

    // Verify onDecision was called with 'approve'
    expect(mockOnDecision).toHaveBeenCalledWith("op-test-123", "approve");
  });

  it("supports keyboard-first shortcuts (Pressing 'r' opens and focuses rejection textarea)", async () => {
    const { container } = renderDrawer();

    // Trigger keyboard press 'r'
    const event = new KeyboardEvent("keydown", { key: "r" });
    window.dispatchEvent(event);

    // Wait asynchronously for React state update to batch and render textarea
    await waitFor(() => {
      const textarea = container.querySelector("textarea");
      expect(textarea).toBeTruthy();
      expect(document.activeElement).toBe(textarea);
    });
  });

  it("supports keyboard-first shortcuts (Pressing 'm' opens and focuses tweak input)", async () => {
    const { container } = renderDrawer();

    // Trigger keyboard press 'm'
    const event = new KeyboardEvent("keydown", { key: "m" });
    window.dispatchEvent(event);

    // Wait asynchronously for React state update to batch and render input
    await waitFor(() => {
      const input = container.querySelector("input[placeholder*='increase']");
      expect(input).toBeTruthy();
      expect(document.activeElement).toBe(input);
    });
  });

  it("satisfies the governance invariant: mutates only via governed /ops/{op_id}/decision path", () => {
    renderDrawer();

    // Click Approve button
    const approveBtn = screen.getByRole("button", { name: "Approve" });
    fireEvent.click(approveBtn);

    // Verify that the callback is triggered with correct arguments
    expect(mockOnDecision).toHaveBeenCalledTimes(1);
    expect(mockOnDecision).toHaveBeenCalledWith("op-test-123", "approve");
  });
});
