import { api } from "@/lib/api";
import { useSessionsStore } from "../sessions";

vi.mock("@/lib/api", () => ({
  api: {
    listSessions: vi.fn(),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
  },
}));

const one = { session_id: "s1", title: "One" };
const two = { session_id: "s2", title: "Two" };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const store = () => useSessionsStore.getState();

describe("session list store", () => {
  beforeEach(() => {
    store().reset();
    vi.mocked(api.listSessions).mockReset();
    vi.mocked(api.renameSession).mockReset().mockResolvedValue({ status: "ok" } as never);
    vi.mocked(api.deleteSession).mockReset().mockResolvedValue({ status: "ok" } as never);
  });

  it("is initial until the first list arrives, then refreshes in the background", async () => {
    const first = deferred<typeof one[]>();
    vi.mocked(api.listSessions).mockReturnValueOnce(first.promise as never);
    const loading = store().refresh();
    expect(store().phase).toBe("initial");
    first.resolve([one]);
    await loading;
    expect(store().phase).toBe("settled");

    const second = deferred<typeof one[]>();
    vi.mocked(api.listSessions).mockReturnValueOnce(second.promise as never);
    const refreshing = store().refresh();
    expect(store().phase).toBe("refreshing");
    expect(store().sessions).toEqual([one]);
    second.resolve([one, two]);
    await refreshing;
    expect(store().sessions).toEqual([one, two]);
  });

  it("keeps the list and reports the error when a refresh fails", async () => {
    vi.mocked(api.listSessions).mockResolvedValueOnce([one] as never);
    await store().refresh();
    vi.mocked(api.listSessions).mockRejectedValueOnce(new Error("offline"));
    await store().refresh();
    expect(store().sessions).toEqual([one]);
    expect(store().error).toBe("offline");
    expect(store().phase).toBe("settled");

    vi.mocked(api.listSessions).mockResolvedValueOnce([one] as never);
    await store().refresh();
    expect(store().error).toBeNull();
  });

  it("shows a created session at once and survives a list fetched before it existed", async () => {
    vi.mocked(api.listSessions).mockResolvedValueOnce([one] as never);
    await store().refresh();

    const stale = deferred<typeof one[]>();
    vi.mocked(api.listSessions)
      .mockReturnValueOnce(stale.promise as never)
      .mockResolvedValueOnce([two, one] as never);
    const inFlight = store().refresh();
    store().upsert(two);
    expect(store().sessions[0]).toEqual(two);

    stale.resolve([one]);
    await inFlight;
    await vi.waitFor(() => expect(store().phase).toBe("settled"));
    expect(store().sessions).toEqual([two, one]);
  });

  it("applies rename and delete locally after the server accepts them", async () => {
    vi.mocked(api.listSessions).mockResolvedValueOnce([one, two] as never);
    await store().refresh();
    await store().rename("s1", "Renamed");
    expect(api.renameSession).toHaveBeenCalledWith("s1", "Renamed");
    expect(store().sessions[0].title).toBe("Renamed");
    await store().remove("s2");
    expect(store().has("s2")).toBe(false);

    vi.mocked(api.deleteSession).mockRejectedValueOnce(new Error("Delete failed"));
    await expect(store().remove("s1")).rejects.toThrow("Delete failed");
    expect(store().has("s1")).toBe(true);
  });
});
