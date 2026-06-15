import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { TenantProvider } from "@/contexts/TenantContext";
import { DevGate } from "./DevGate";

describe("DevGate Component", () => {
  it("renders the gateway login form when entered is false", () => {
    render(
      <TenantProvider>
        <DevGate>
          <div data-testid="child">Dashboard Content</div>
        </DevGate>
      </TenantProvider>
    );

    // Verify gateway form elements render
    expect(screen.getByText("Agency OS Gateway")).toBeTruthy();
    expect(screen.getByText("Tenant ID")).toBeTruthy();
    expect(screen.getByText("Role Authority")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Enter Dashboard" })).toBeTruthy();
    
    // Verify children do not render
    expect(screen.queryByTestId("child")).toBeNull();
  });
});
