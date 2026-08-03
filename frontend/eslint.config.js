// @ts-check

import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist", "coverage"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The React-Compiler-era checks (set-state-in-effect / refs) landed in
      // eslint-plugin-react-hooks 6.x after this codebase matured; they flag
      // real anti-patterns but each fix needs a behavioral review. Land them as
      // warnings first (CI still fails on errors), flip to errors as the batch
      // of fixes lands. The classic rules (rules-of-hooks, exhaustive-deps)
      // stay errors.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      // useSSE's attach/scheduleReconnect/doConnect callbacks form a mutually
      // recursive triple; untangling it to the compiler's mutable-ref model is
      // a behavioral refactor that deserves its own reviewed change.
      "react-hooks/immutability": "warn",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // Explicit `any` is a code smell the tsconfig's strict mode should
      // eliminate; report it loudly so new ones are reviewed (fixes welcome).
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
