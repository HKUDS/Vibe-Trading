import { create } from "zustand";
import { api, type SessionItem } from "@/lib/api";
import i18n from "@/i18n";

/** Session list shared by the sidebar and the pages that create or retitle sessions. */
export type SessionListPhase = "initial" | "refreshing" | "settled";

interface SessionListState {
  sessions: SessionItem[];
  phase: SessionListPhase;
  error: string | null;
  refresh: () => Promise<void>;
  upsert: (session: SessionItem) => void;
  rename: (sid: string, title: string) => Promise<void>;
  remove: (sid: string) => Promise<void>;
  has: (sid: string) => boolean;
  reset: () => void;
}

let generation = 0;
let hasLoaded = false;
let inFlight = false;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : i18n.t("settings.unknownError");
}

export const useSessionsStore = create<SessionListState>((set, get) => {
  // A response that left the server before a local change would overwrite it,
  // so a local change discards that response and asks again.
  const supersedeInFlight = () => {
    if (inFlight) void get().refresh();
  };

  return {
    sessions: [],
    phase: "initial",
    error: null,

    refresh: async () => {
      const current = ++generation;
      inFlight = true;
      set({ phase: hasLoaded ? "refreshing" : "initial" });
      try {
        const list = await api.listSessions();
        if (current !== generation) return;
        hasLoaded = true;
        set({ sessions: Array.isArray(list) ? list : [], error: null });
      } catch (error) {
        if (current !== generation) return;
        set({ error: errorMessage(error) });
      } finally {
        if (current === generation) {
          inFlight = false;
          set({ phase: "settled" });
        }
      }
    },

    upsert: (session) => {
      set((s) => {
        const exists = s.sessions.some((item) => item.session_id === session.session_id);
        return {
          sessions: exists
            ? s.sessions.map((item) => item.session_id === session.session_id ? { ...item, ...session } : item)
            : [session, ...s.sessions],
        };
      });
      supersedeInFlight();
    },

    rename: async (sid, title) => {
      await api.renameSession(sid, title);
      set((s) => ({
        sessions: s.sessions.map((item) => item.session_id === sid ? { ...item, title } : item),
      }));
      supersedeInFlight();
    },

    remove: async (sid) => {
      await api.deleteSession(sid);
      set((s) => ({ sessions: s.sessions.filter((item) => item.session_id !== sid) }));
      supersedeInFlight();
    },

    has: (sid) => get().sessions.some((item) => item.session_id === sid),

    reset: () => {
      generation += 1;
      hasLoaded = false;
      inFlight = false;
      set({ sessions: [], phase: "initial", error: null });
    },
  };
});
