import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { ModelPicker } from "../ModelPicker";

function Harness() {
  const [value, setValue] = useState("deepseek-v4-pro");
  return (
    <ModelPicker
      value={value}
      options={["deepseek-v4-pro", "deepseek-v4-flash"]}
      onChange={setValue}
      ariaLabel="Model"
      optionsAriaLabel="Available models"
    />
  );
}

describe("ModelPicker", () => {
  it("shows every loaded model even when the current value is different", async () => {
    render(<Harness />);
    const user = userEvent.setup();
    const input = screen.getByRole("combobox", { name: "Model" });

    await user.clear(input);
    await user.type(input, "vendor/custom-model");

    expect(screen.getByRole("option", { name: "deepseek-v4-pro" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "deepseek-v4-flash" })).toBeInTheDocument();
  });

  it("keeps an exact custom model id editable", async () => {
    render(<Harness />);
    const input = screen.getByRole("combobox", { name: "Model" });

    await userEvent.setup().clear(input);
    await userEvent.setup().type(input, "vendor/custom-model");

    expect(input).toHaveValue("vendor/custom-model");
  });

  it("selects the first loaded model with ArrowDown after custom input", async () => {
    render(<Harness />);
    const user = userEvent.setup();
    const input = screen.getByRole("combobox", { name: "Model" });

    await user.clear(input);
    await user.type(input, "vendor/custom-model");
    await user.keyboard("{ArrowDown}{Enter}");

    expect(input).toHaveValue("deepseek-v4-pro");
  });

  it("uses the translated options label without appending English prose", async () => {
    render(<Harness />);
    await userEvent.setup().click(screen.getByRole("combobox", { name: "Model" }));

    expect(screen.getByRole("listbox", { name: "Available models" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Available models" })).toBeInTheDocument();
  });
});
