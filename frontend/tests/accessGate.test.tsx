// @vitest-environment jsdom
import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import AccessGate, { useBuyerAccess } from "../src/components/AccessGate";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); history.replaceState(null, "", "/"); });

function Buyer() {
  const access = useBuyerAccess();
  return <p data-testid="buyer">{access?.buyerId ?? "demo"}</p>;
}
function response(body: object, status = 200) {
  return Promise.resolve({ ok: status === 200, status, json: async () => body });
}

it("keeps the shopping app unmounted when service discovery fails", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({}, 502)));
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<AccessGate><Buyer /></AccessGate>));
    expect(host.querySelector('[data-testid="buyer"]')).toBeNull();
    expect(host.textContent).toContain("暂时无法连接服务");
  } finally { await act(async () => root.unmount()); }
});

it("verifies a pasted credential before mounting the buyer workspace", async () => {
  const fetch = vi.fn((..._args: unknown[]) => response({ mode: "hmac", authenticated: false }))
    .mockImplementationOnce(() => response({ mode: "hmac", authenticated: false }))
    .mockImplementationOnce(() => response({ mode: "hmac", authenticated: true, buyer_id: "tester-01" }));
  vi.stubGlobal("fetch", fetch);
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<AccessGate><Buyer /></AccessGate>));
    const input = host.querySelector("input")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "personal-token");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({ headers: { Authorization: "Bearer personal-token" } });
    expect(host.querySelector('[data-testid="buyer"]')?.textContent).toBe("tester-01");
    expect(sessionStorage.getItem("globex.access-token")).toBe("personal-token");
  } finally { await act(async () => root.unmount()); }
});

it("restores only a server-verified buyer and clears tab credentials on logout", async () => {
  sessionStorage.setItem("globex.access-token", "saved-test-token");
  sessionStorage.setItem("globex.test-private-cache", "buyer-private-data");
  const fetch = vi.fn((..._args: unknown[]) => response({ mode: "hmac", authenticated: true, buyer_id: "tester-02" }));
  vi.stubGlobal("fetch", fetch);
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<AccessGate><Buyer /></AccessGate>));
    expect(host.querySelector('[data-testid="buyer"]')?.textContent).toBe("tester-02");
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ headers: { Authorization: "Bearer saved-test-token" } });
    await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "退出登录")!.click());
    expect(host.querySelector('[data-testid="buyer"]')).toBeNull();
    expect(sessionStorage.getItem("globex.access-token")).toBeNull();
    expect(sessionStorage.getItem("globex.test-private-cache")).toBeNull();
  } finally { await act(async () => root.unmount()); }
});

it("rejects invalid saved credentials without mounting buyer content", async () => {
  sessionStorage.setItem("globex.access-token", "expired");
  vi.stubGlobal("fetch", vi.fn(() => response({}, 401)));
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<AccessGate><Buyer /></AccessGate>));
    expect(host.querySelector('[data-testid="buyer"]')).toBeNull();
    expect(host.textContent).toContain("凭证无效或已过期");
  } finally { await act(async () => root.unmount()); }
});

it("allows the existing demo workspace only when the server explicitly reports demo", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({ mode: "demo", authenticated: false })));
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<AccessGate><Buyer /></AccessGate>));
    expect(host.querySelector('[data-testid="buyer"]')?.textContent).toBe("demo");
  } finally { await act(async () => root.unmount()); }
});

it("exchanges a shared fragment once under StrictMode and never stores the invite or a bearer token", async () => {
  const invite = "x".repeat(43);
  history.replaceState(null, "", `/demo#invite=${invite}`);
  sessionStorage.setItem("globex.access-token", "old-personal-token");
  const fetch = vi.fn(() => response({ mode: "hmac", authenticated: true, buyer_id: "guest-browser-a", credential: "invite" }));
  vi.stubGlobal("fetch", fetch);
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<StrictMode><AccessGate><Buyer /></AccessGate></StrictMode>));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]?.[0]).toBe("/commerce/auth/invite");
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: "POST", credentials: "include", body: JSON.stringify({ invite }) });
    expect(location.hash).toBe("");
    expect(host.querySelector('[data-testid="buyer"]')?.textContent).toBe("guest-browser-a");
    expect(host.textContent).toContain("演示体验");
    expect(sessionStorage.getItem("globex.access-token")).toBeNull();
    expect(JSON.stringify(sessionStorage)).not.toContain(invite);
  } finally { await act(async () => root.unmount()); }
});

it("restores a server-verified cookie login without any code and logs out on the server", async () => {
  const fetch = vi.fn((..._args: unknown[]) => response({ authenticated: false }))
    .mockImplementationOnce(() => response({ mode: "hmac", authenticated: true, buyer_id: "guest-browser-b", credential: "invite" }));
  vi.stubGlobal("fetch", fetch);
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<AccessGate><Buyer /></AccessGate>));
    expect(host.querySelector('[data-testid="buyer"]')?.textContent).toBe("guest-browser-b");
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ credentials: "include", headers: {} });
    await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "退出登录")!.click());
    expect(fetch.mock.calls[1]?.[0]).toBe("/commerce/auth/logout");
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({ method: "POST", credentials: "include" });
    expect(host.querySelector('[data-testid="buyer"]')).toBeNull();
  } finally { await act(async () => root.unmount()); }
});

it("keeps buyer content unmounted for a revoked invite and removes it from the address bar", async () => {
  history.replaceState(null, "", `/demo#invite=${"x".repeat(43)}`);
  vi.stubGlobal("fetch", vi.fn(() => response({}, 401)));
  const host = document.createElement("div"), root = createRoot(host);
  try {
    await act(async () => root.render(<AccessGate><Buyer /></AccessGate>));
    expect(host.querySelector('[data-testid="buyer"]')).toBeNull();
    expect(host.textContent).toContain("邀请链接无效、已过期或已撤销");
    expect(location.hash).toBe("");
  } finally { await act(async () => root.unmount()); }
});
