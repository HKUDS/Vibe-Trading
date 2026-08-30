import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CustomProviderManager } from "../CustomProviderManager";

const apiMock = vi.hoisted(() => ({
  listCustomProviders: vi.fn(),
  testCustomProvider: vi.fn(),
  saveCustomProvider: vi.fn(),
  activateCustomProvider: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));

describe("CustomProviderManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    apiMock.listCustomProviders.mockResolvedValue({ status: "ok", providers: [] });
    apiMock.testCustomProvider.mockResolvedValue({
      status: "ok",
      test_id: "test-123",
      response_preview: "PROVIDER_TEST_OK",
      latency_ms: 42,
    });
    apiMock.saveCustomProvider.mockResolvedValue({
      status: "ok",
      provider: {
        id: "demo",
        label: "Demo",
        base_url: "https://example.com/v1",
        model: "demo-model",
        api_key_configured: true,
        active: false,
      },
    });
  });

  it("requires a successful test before saving", async () => {
    render(<CustomProviderManager />);

    expect(await screen.findByText("No custom providers yet. Add one below and test it before saving.")).toBeInTheDocument();
    const saveButton = screen.getByRole("button", { name: "Save tested provider" });
    expect(saveButton).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: "API Base URL" }), { target: { value: "https://example.com/v1" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Model" }), { target: { value: "demo-model" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "secret-value" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Provider ID" }), { target: { value: "demo" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Display name" }), { target: { value: "Demo" } });

    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(apiMock.testCustomProvider).toHaveBeenCalledWith({
      base_url: "https://example.com/v1",
      model: "demo-model",
      api_key: "secret-value",
    }));

    expect(await screen.findByText(/Test passed: PROVIDER_TEST_OK/)).toBeInTheDocument();
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);
    await waitFor(() => expect(apiMock.saveCustomProvider).toHaveBeenCalledWith({
      id: "demo",
      label: "Demo",
      base_url: "https://example.com/v1",
      model: "demo-model",
      api_key: "secret-value",
      test_id: "test-123",
    }));
  });

  it("requires confirmation before activating a saved provider", async () => {
    apiMock.listCustomProviders.mockResolvedValue({
      status: "ok",
      providers: [{
        id: "demo",
        label: "Demo",
        base_url: "https://example.com/v1",
        model: "demo-model",
        api_key_configured: true,
        active: false,
      }],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<CustomProviderManager />);

    fireEvent.click(await screen.findByRole("button", { name: "Activate" }));
    expect(confirm).toHaveBeenCalledWith("Activate Demo for new agent requests?");
    expect(apiMock.activateCustomProvider).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(apiMock.activateCustomProvider).toHaveBeenCalledWith("demo"));
  });

  it("shows a provider test failure inside the manager", async () => {
    apiMock.testCustomProvider.mockRejectedValue(new Error("Provider returned HTTP 404"));
    render(<CustomProviderManager />);

    fireEvent.change(screen.getByRole("textbox", { name: "API Base URL" }), { target: { value: "https://example.com/v1" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Model" }), { target: { value: "demo-model" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "synthetic-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Provider returned HTTP 404");
    expect(screen.getByRole("button", { name: "Test connection" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Save tested provider" })).toBeDisabled();
  });
});
