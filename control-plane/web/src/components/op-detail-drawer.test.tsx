import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { OpDetailDrawer, VisualDiff, OpDetailPreview, TraceTimeline } from "./op-detail-drawer";

describe("VisualDiff Component", () => {
  it("renders side-by-side differences for payload modifications", () => {
    const before = { budget_minor: 1000, name: "old name" };
    const after = { budget_minor: 2000, name: "new name", new_field: "yay" };

    render(<VisualDiff before={before} after={after} />);

    expect(screen.getByText("Before (Baseline)")).toBeTruthy();
    expect(screen.getByText("After (Proposed)")).toBeTruthy();

    expect(screen.getByText(/- budget_minor: 1000/)).toBeTruthy();
    expect(screen.getByText(/\+ budget_minor: 2000/)).toBeTruthy();
    expect(screen.getByText(/- name: "old name"/)).toBeTruthy();
    expect(screen.getByText(/\+ name: "new name"/)).toBeTruthy();
    expect(screen.getByText(/\+ new_field: "yay"/)).toBeTruthy();
  });

  it("renders correct fallback message when no modifications", () => {
    const data = { budget_minor: 1000 };
    render(<VisualDiff before={data} after={data} />);
    expect(screen.getByText("No modifications.")).toBeTruthy();
  });
});

describe("OpDetailPreview Component", () => {
  it("renders campaign create preview accurately using parameters", () => {
    const params = {
      name: "Spring Sale Campaign",
      campaign_id: "camp-555",
      budget_minor: 150000,
      bid_minor: 5000,
    };

    render(
      <OpDetailPreview
        action="grow.campaign.create"
        previewKind="campaign_create_preview"
        previewSummary=""
        params={params}
      />
    );

    expect(screen.getByText("Create Google Ads Campaign")).toBeTruthy();
    expect(screen.getByText(/Spring Sale Campaign/)).toBeTruthy();
    expect(screen.getByText(/camp-555/)).toBeTruthy();
    expect(screen.getByText(/1500 INR/)).toBeTruthy();
    expect(screen.getByText(/50 INR/)).toBeTruthy();
  });

  it("renders campaign delete preview accurately using parameters", () => {
    const params = { campaign_id: "camp-del-999" };

    render(
      <OpDetailPreview
        action="grow.campaign.delete"
        previewKind="campaign_delete_preview"
        previewSummary=""
        params={params}
      />
    );

    expect(screen.getByText("Danger: Delete Campaign")).toBeTruthy();
    expect(screen.getByText(/camp-del-999/)).toBeTruthy();
  });

  it("falls back to rendering text summary if no matching template", () => {
    render(
      <OpDetailPreview
        action="some.random.action"
        previewSummary="Custom plain text preview description summary."
        params={{}}
      />
    );

    expect(screen.getByText("Custom plain text preview description summary.")).toBeTruthy();
  });
});

describe("TraceTimeline Component", () => {
  it("renders traces and their transition details", () => {
    const traces = [
      {
        ts: "2026-06-15T18:00:00Z",
        kind: "preview",
        detail: { kind: "campaign_create_preview" },
      },
      {
        ts: "2026-06-15T18:01:00Z",
        kind: "transition",
        detail: {
          from: "PROPOSED",
          to: "PREVIEWED",
          actor: "kernel",
          detail: { reason: "Initial previewing success" },
        },
      },
    ];

    render(<TraceTimeline traces={traces} />);

    expect(screen.getByText("Preview Generation")).toBeTruthy();
    expect(screen.getByText("State Transition")).toBeTruthy();
    expect(screen.getByText(/Changed state from/)).toBeTruthy();
    expect(screen.getByText("PROPOSED")).toBeTruthy();
    expect(screen.getByText("PREVIEWED")).toBeTruthy();
    expect(screen.getByText("kernel")).toBeTruthy();
    expect(screen.getByText(/Reason: "Initial previewing success"/)).toBeTruthy();
  });
});

describe("OpDetailDrawer Component", () => {
  const defaultOpData = {
    action: "grow.campaign.create",
    state: "AWAITING_APPROVAL",
    preview: "Will create campaign XYZ",
    params: { name: "XYZ", budget_minor: 50000 },
    trace: [
      {
        ts: "2026-06-15T18:00:00Z",
        kind: "preview",
        detail: { kind: "campaign_create_preview" },
      },
    ],
  };

  it("renders loading message when loading state is true", () => {
    render(
      <OpDetailDrawer
        opId="op-123"
        onClose={vi.fn()}
        opData={null}
        loading={true}
        onDecision={vi.fn()}
        role="OPERATOR"
      />
    );
    expect(screen.getByText("Loading operation metadata...")).toBeTruthy();
  });

  it("renders details and actions when opData is loaded", () => {
    const onDecision = vi.fn();
    render(
      <OpDetailDrawer
        opId="op-123"
        onClose={vi.fn()}
        opData={defaultOpData}
        loading={false}
        onDecision={onDecision}
        role="OPERATOR"
      />
    );

    expect(screen.getByText("grow.campaign.create")).toBeTruthy();
    expect(screen.getByText("op-123")).toBeTruthy();
    
    // Check decisions
    expect(screen.getByText("Approve")).toBeTruthy();
    expect(screen.getByText("Modify")).toBeTruthy();
    expect(screen.getByText("Reject")).toBeTruthy();
  });

  it("sends decision when clicking approve", () => {
    const onDecision = vi.fn();
    render(
      <OpDetailDrawer
        opId="op-123"
        onClose={vi.fn()}
        opData={defaultOpData}
        loading={false}
        onDecision={onDecision}
        role="OPERATOR"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onDecision).toHaveBeenCalledWith("op-123", "approve");
  });

  it("shows form for modify action, captures reason, and submits on Decision", () => {
    const onDecision = vi.fn();
    render(
      <OpDetailDrawer
        opId="op-123"
        onClose={vi.fn()}
        opData={defaultOpData}
        loading={false}
        onDecision={onDecision}
        role="OPERATOR"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Modify" }));
    
    const input = screen.getByPlaceholderText(/e.g. increase budget/i);
    expect(input).toBeTruthy();

    fireEvent.change(input, { target: { value: "reduce budget to 400 INR" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit Tweak" }));

    expect(onDecision).toHaveBeenCalledWith("op-123", "modify", "reduce budget to 400 INR");
  });
});
