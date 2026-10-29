import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Settings } from "../Settings";

const apiMock = vi.hoisted(() => ({
  getLLMSettings: vi.fn(),
  getDataSourceSettings: vi.fn(),
  listLLMModels: vi.fn(),
  updateLLMSettings: vi.fn(),
  updateDataSourceSettings: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: apiMock,
    isAuthRequiredError: vi.fn(() => false),
  };
});

vi.mock("@/lib/apiAuth", () => ({
  getApiAuthKey: vi.fn(() => ""),
  setApiAuthKey: vi.fn(),
}));

vi.mock("@/components/settings/ChannelSettings", () => ({ ChannelSettings: () => null }));
vi.mock("@/components/settings/QVerisSettings", () => ({ QVerisSettings: () => null }));
vi.mock("@/components/settings/SourcePrioritySettings", () => ({
  SourcePrioritySettings: () => null,
}));

const providers = [
  { name: "openai-codex", label: "OpenAI Codex", api_key_env: null, base_url_env: null,
    default_model: "openai-codex/gpt-6-sol", default_base_url: "https://chatgpt.com/backend-api/codex/responses",
    api_key_required: false, auth_type: "oauth", reasoning_efforts: ["low", "medium", "high", "ultra"] },
  {
    name: "claude-cli",
    label: "Claude Code CLI (local login)",
    api_key_env: null,
    base_url_env: "CLAUDE_CLI_BASE_URL",
    default_model: "claude-opus-5-5",
    default_base_url: "",
    api_key_required: false,
    auth_type: "claude_cli",
    reasoning_efforts: ["low", "medium", "high", "xhigh", "max"],
  },
  {
    name: "openrouter",
    label: "OpenRouter",
    api_key_env: "OPENROUTER_API_KEY",
    base_url_env: "OPENROUTER_BASE_URL",
    default_model: "deepseek/deepseek-v3.2",
    default_base_url: "https://openrouter.ai/api/v1",
    api_key_required: true,
    auth_type: "api_key",
    reasoning_efforts: ["none", "low", "medium", "high", "max"],
  },
];

function llmSettings(overrides = {}) {
  return {
    provider: "claude-cli",
    model_name: "claude-opus-5-5",
    base_url: "",
    api_key_env: null,
    api_key_configured: true,
    api_key_required: false,
    temperature: 0,
    timeout_seconds: 120,
    max_retries: 2,
    reasoning_effort: "",
    sse_timeout_seconds: 300,
    env_path: "agent/.env",
    providers,
    ...overrides,
  };
}

const modelList = {
  provider: "claude-cli",
  models: ["claude-opus-5-5", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
  source: "provider",
  warning_code: null,
  effort_levels: {
    "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"],
    "claude-sonnet-4-6": ["low", "medium", "high", "max"],
    "claude-haiku-4-5-20251001": [],
  },
};

function effortSelect(): HTMLSelectElement {
  return screen.getByText("Reasoning Effort").closest("label")!.querySelector("select")!;
}

function effortOptions(): string[] {
  return Array.from(effortSelect().options).map((option) => option.value);
}

describe("Settings with the claude-cli provider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getDataSourceSettings.mockResolvedValue({
      tushare_token_configured: false,
      baostock_supported: true,
      baostock_installed: true,
      baostock_message: "BaoStock available",
      env_path: "agent/.env",
    });
    apiMock.listLLMModels.mockResolvedValue(modelList);
  });

  it("loads the CLI model list on open and offers the selected model's levels", async () => {
    apiMock.getLLMSettings.mockResolvedValue(llmSettings());
    render(<Settings />);

    await waitFor(() =>
      expect(apiMock.listLLMModels).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "claude-cli", refresh: false }),
      ),
    );
    await waitFor(() => expect(effortOptions()).toContain("xhigh"));
    expect(effortOptions()).toEqual(["", "low", "medium", "high", "xhigh", "max"]);
  });

  it("narrows the levels when a model without them is picked", async () => {
    apiMock.getLLMSettings.mockResolvedValue(llmSettings());
    render(<Settings />);
    // xhigh is also offered by the provider fallback while the per-model
    // levels are still loading, so wait for the fetch to actually land.
    expect(await screen.findByText("Loaded 3 available models.")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Model" }), {
      target: { value: "claude-haiku-4-5-20251001" },
    });

    expect(effortOptions()).toEqual([""]);
  });

  it("resets a level the selected model does not accept and says why", async () => {
    apiMock.getLLMSettings.mockResolvedValue(
      llmSettings({ model_name: "claude-sonnet-4-6", reasoning_effort: "xhigh" }),
    );
    render(<Settings />);

    // The hint appears once the model list says sonnet-4-6 has no xhigh.
    // The hint names the level by its label, as the menu does, not by its id.
    expect(await screen.findByText(/does not support Extra high/)).toBeInTheDocument();
    expect(effortSelect().value).toBe("");
    expect(effortOptions()).not.toContain("xhigh");

    apiMock.updateLLMSettings.mockResolvedValue(llmSettings({ model_name: "claude-sonnet-4-6" }));
    fireEvent.click(effortSelect().closest("form")!.querySelector('button[type="submit"]')!);
    await waitFor(() =>
      expect(apiMock.updateLLMSettings).toHaveBeenCalledWith(
        expect.objectContaining({ reasoning_effort: "" }),
      ),
    );
  });

  it("drops a model list that arrives after the provider was switched", async () => {
    let answer: (value: typeof modelList) => void = () => {};
    apiMock.listLLMModels.mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    apiMock.getLLMSettings.mockResolvedValue(llmSettings());
    render(<Settings />);
    await waitFor(() => expect(apiMock.listLLMModels).toHaveBeenCalled());

    fireEvent.change(screen.getByDisplayValue("Claude Code CLI (local login)"), {
      target: { value: "openrouter" },
    });
    answer(modelList);
    await new Promise((resolve) => setTimeout(resolve, 0));

    fireEvent.click(screen.getByRole("combobox", { name: "Model" }));
    expect(screen.queryByText("claude-sonnet-4-6")).not.toBeInTheDocument();
  });

  it("keeps the existing levels and makes no request for other providers", async () => {
    apiMock.getLLMSettings.mockResolvedValue(
      llmSettings({
        provider: "openrouter",
        model_name: "deepseek/deepseek-v3.2",
        base_url: "https://openrouter.ai/api/v1",
      }),
    );
    render(<Settings />);

    await waitFor(() => expect(effortOptions()).toEqual(["", "none", "low", "medium", "high", "max"]));
    expect(apiMock.listLLMModels).not.toHaveBeenCalled();
  });
});


describe("Settings with Codex OAuth discovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getDataSourceSettings.mockResolvedValue({});
    apiMock.getLLMSettings.mockResolvedValue(llmSettings({
      provider: "openai-codex", model_name: "openai-codex/saved-model",
    }));
  });

  it("automatically discovers account models, labels and model-specific efforts", async () => {
    apiMock.listLLMModels.mockResolvedValue({
      provider: "openai-codex", models: ["openai-codex/available"], source: "provider",
      model_labels: {"openai-codex/available": "Available model"},
      effort_levels: {"openai-codex/available": ["medium", "ultra"]},
      default_effort_levels: {"openai-codex/available": "medium"},
    });
    render(<Settings />);
    await waitFor(() => expect(apiMock.listLLMModels).toHaveBeenCalledWith(
      expect.objectContaining({provider: "openai-codex", refresh: false}),
    ));
    expect(await screen.findByText("Loaded 1 available models.")).toBeInTheDocument();
    const input = screen.getByRole("combobox", {name: "Model"});
    expect(input).toHaveValue("openai-codex/saved-model");
    fireEvent.click(input);
    fireEvent.click(screen.getByRole("option", {name: /Available model/}));
    expect(input).toHaveValue("openai-codex/available");
    expect(effortOptions()).toEqual(["", "medium", "ultra"]);
    expect(screen.getByText(/Provider default: Medium/)).toBeInTheDocument();
  });

  it("retains the saved model and manual entry after unavailable discovery", async () => {
    apiMock.listLLMModels.mockResolvedValue({
      provider: "openai-codex", models: ["openai-codex/gpt-6-sol"],
      source: "default", warning_code: "model_list_unavailable",
    });
    render(<Settings />);
    await waitFor(() => expect(apiMock.listLLMModels).toHaveBeenCalled());
    const input = screen.getByRole("combobox", {name: "Model"});
    expect(input).toHaveValue("openai-codex/saved-model");
    fireEvent.change(input, {target: {value: "openai-codex/manual-model"}});
    expect(input).toHaveValue("openai-codex/manual-model");
  });
});
