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
    />
  );
}

describe("ModelPicker", () => {
  it("shows every loaded model even when the current value is different", async () => {
    render(<Harness />);

    await userEvent.setup().click(screen.getByRole("combobox", { name: "Model" }));

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
});
