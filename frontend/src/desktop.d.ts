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
      restartBackend: () => Promise<boolean>;
      getCredentialStatus: () => Promise<DesktopCredentialStatus>;
      setCredential: (
        name: string,
        value: string | null,
      ) => Promise<DesktopCredentialStatus>;
    };
  }
}
