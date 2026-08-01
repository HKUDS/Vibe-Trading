import './i18n';
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { Toaster } from "sonner";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { router } from "./router";
import "highlight.js/styles/github-dark-dimmed.min.css";
import "./index.css";

const prefetchMiniEquityChart = () => {
  void import("@/components/charts/MiniEquityChart");
};

const idleWindow = window as Window & {
  requestIdleCallback?: (
    callback: IdleRequestCallback,
    options?: IdleRequestOptions,
  ) => number;
};

if (typeof idleWindow.requestIdleCallback === "function") {
  idleWindow.requestIdleCallback(prefetchMiniEquityChart, { timeout: 2000 });
} else {
  window.setTimeout(prefetchMiniEquityChart, 0);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <RouterProvider router={router} />
      <Toaster position="bottom-right" richColors closeButton duration={3500} />
    </ErrorBoundary>
  </StrictMode>
);
