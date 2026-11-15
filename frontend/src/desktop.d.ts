import type { SoftwareUpdate } from "@/lib/api";
export {};

export interface DesktopCredentialStatus {
  available: boolean;
  configured: string[];
  migrated: string[];
}

declare global {
  interface Window {
    vibeDesktop?: {
      isDesktop: boolean;
      checkForUpdates: () => Promise<SoftwareUpdate>;
      installUpdate: () => Promise<void>;
      restartBackend: () => Promise<boolean>;
      getCredentialStatus: () => Promise<DesktopCredentialStatus>;
      setCredential: (
        name: string,
        value: string | null,
      ) => Promise<DesktopCredentialStatus>;
    };
  }
}
