import { render, screen } from "@testing-library/react";
import { ModelRuntimeBar } from "../ModelRuntimeBar";
import type { LLMSettings } from "@/lib/api";

const settings: LLMSettings = {
  provider: "deepseek",
  model_name: "deepseek-v4-flash",
  base_url: "https://api.deepseek.com",
  api_key_configured: true,
  api_key_required: true,
  temperature: 0,
  timeout_seconds: 120,
  max_retries: 2,
  reasoning_effort: "high",
  sse_timeout_seconds: 90,
  env_path: "agent/.env",
  providers: [{
    name: "deepseek",
    label: "DeepSeek",
    base_url_env: "LANGCHAIN_BASE_URL",
    default_model: "deepseek-chat",
    default_base_url: "https://api.deepseek.com",
    api_key_required: true,
  }],
};

describe("ModelRuntimeBar", () => {
  it("shows provider, provider-reported model and configured reasoning effort", () => {
    render(
      <ModelRuntimeBar
        settings={settings}
        runtimeProvider="deepseek"
        runtimeModel="deepseek-v4-flash-202607"
      />,
    );

    expect(screen.getByText("DeepSeek")).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash-202607")).toBeInTheDocument();
    expect(screen.getByText(/Reasoning Effort: High/)).toBeInTheDocument();
  });
});
