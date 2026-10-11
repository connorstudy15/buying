import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

export type BuyerAccess = { buyerId: string; accessToken: string; credential?: "invite" };
const AccessContext = createContext<BuyerAccess | undefined>(undefined);
export const useBuyerAccess = () => useContext(AccessContext);
const TOKEN_KEY = "globex.access-token";
const base = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

function savedToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}

async function verify(token = "", invite = "") {
  const response = await fetch(`${base}/commerce/auth${invite ? "/invite" : ""}`, {
    method: invite ? "POST" : "GET",
    headers: invite ? { "Content-Type": "application/json" } : token ? { Authorization: `Bearer ${token}` } : {},
    body: invite ? JSON.stringify({ invite }) : undefined,
    credentials: "include",
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
  });
  if (response.status === 401) throw new Error(invite ? "邀请链接无效、已过期或已撤销，请联系管理员。" : "凭证无效或已过期，请重新打开有效的邀请链接或领取新的内测凭证。");
  if (response.status === 403) throw new Error("邀请链接与当前访问地址不匹配，请使用管理员提供的完整链接。");
  if (!response.ok) throw new Error("暂时无法连接服务，请稍后重试。");
  const data = await response.json();
  if (data.mode === "demo") return undefined;
  if (data.mode !== "hmac") throw new Error("服务身份配置异常，请联系管理员。");
  if (!data.authenticated) return null;
  if (typeof data.buyer_id !== "string" || !data.buyer_id || (!token && data.credential !== "invite")) throw new Error("身份验证失败。");
  return { buyerId: data.buyer_id, accessToken: invite || data.credential === "invite" ? "" : token,
    ...(data.credential === "invite" ? { credential: "invite" as const } : {}) };
}

export default function AccessGate({ children }: { children: ReactNode }) {
  const [checking, setChecking] = useState(true);
  const [demo, setDemo] = useState(false);
  const [access, setAccess] = useState<BuyerAccess>();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const invite = useRef(new URLSearchParams(window.location.hash.slice(1)).get("invite") ?? "");
  const boot = useRef<ReturnType<typeof verify> | undefined>(undefined);
  useEffect(() => {
    let disposed = false;
    setChecking(true);
    setError("");
    // Fragment 不会发送给静态服务器；尽早移除地址栏中的邀请码。
    if (invite.current) {
      const fragment = new URLSearchParams(window.location.hash.slice(1));
      fragment.delete("invite");
      history.replaceState(history.state, "", window.location.pathname + window.location.search + (fragment.size ? `#${fragment}` : ""));
    }
    // StrictMode 重放 effect 时共用首次请求，避免重复签发浏览器身份。
    boot.current ??= verify(invite.current ? "" : savedToken(), invite.current);
    void boot.current.then(result => {
      if (disposed) return;
      if (result?.credential === "invite") {
        try { sessionStorage.removeItem(TOKEN_KEY); } catch {}
      }
      setDemo(result === undefined);
      setAccess(result ?? undefined);
    }).catch(err => {
      if (!disposed) setError(err instanceof Error ? err.message : "无法验证身份，请重试。");
    }).finally(() => { if (!disposed) setChecking(false); });
    return () => { disposed = true; };
  }, [retry]);

  useEffect(() => {
    if (!access) return;
    const timer = window.setInterval(() => {
      void verify(access.accessToken).then(result => {
        if (!result) { setAccess(undefined); setDemo(false); }
        else if (result.buyerId !== access.buyerId) setAccess(result);
      }).catch(err => {
        if (err instanceof Error && err.message.startsWith("凭证")) {
          setAccess(undefined);
          setError(err.message);
          try { sessionStorage.removeItem(TOKEN_KEY); } catch {}
        }
      });
    }, 60000);
    return () => window.clearInterval(timer);
  }, [access]);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await verify(token.trim());
      if (!result) throw new Error("请输入有效的内测凭证。");
      try { sessionStorage.setItem(TOKEN_KEY, result.accessToken); } catch {}
      setAccess(result);
      setToken("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请重试。");
    } finally { setBusy(false); }
  }

  async function logout() {
    setBusy(true);
    try {
      const response = await fetch(`${base}/commerce/auth/logout`, { method: "POST", credentials: "include", cache: "no-store" });
      if (!response.ok) throw new Error("退出登录失败，请稍后重试。");
    } catch {
      setError("退出登录失败，请稍后重试。");
      setBusy(false);
      return;
    }
    try {
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith("globex.")) sessionStorage.removeItem(key);
      }
    } catch {}
    setAccess(undefined);
    setToken("");
    setError("");
    invite.current = "";
    boot.current = undefined;
    setBusy(false);
  }

  if (checking) return <main className="access-screen" aria-busy="true"><p>正在连接 Globex…</p></main>;
  if (demo) return <>{children}</>;
  if (access) return <AccessContext.Provider value={access} key={access.buyerId}>
    <div className="access-bar"><span>{access.credential === "invite" ? "演示体验" : `内测账号：${access.buyerId}`}</span><button onClick={() => void logout()} disabled={busy}>退出登录</button>
      {error && <span role="alert">{error}</span>}</div>
    {children}
  </AccessContext.Provider>;
  return <main className="access-screen"><section className="access-card">
    <p className="access-eyebrow">GLOBEX · 受邀内测</p>
    <h1>开始你的选购</h1>
    <p>请通过邀请链接进入体验，也可以输入管理员发给你的个人内测凭证。</p>
    <form onSubmit={login}>
      <label htmlFor="beta-token">内测凭证</label>
      <input id="beta-token" type="password" value={token} onChange={event => setToken(event.target.value)}
        autoComplete="off" spellCheck={false} maxLength={8192} required disabled={busy} />
      {error && <p role="alert" className="access-error">{error}</p>}
      <button className="access-submit" type="submit" disabled={busy}>{busy ? "正在验证…" : "进入 Globex"}</button>
    </form>
    <button className="access-retry" onClick={() => { boot.current = undefined; setRetry(value => value + 1); }} disabled={busy}>重新连接服务</button>
    <p className="access-note">本次内测仅使用演示商品和测试订单，不进行真实支付或发货。</p>
  </section></main>;
}
