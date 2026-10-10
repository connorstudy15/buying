import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";

export type BuyerAccess = { buyerId: string; accessToken: string };
const AccessContext = createContext<BuyerAccess | undefined>(undefined);
export const useBuyerAccess = () => useContext(AccessContext);
const TOKEN_KEY = "globex.access-token";
const base = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

function savedToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}

async function verify(token = "") {
  const response = await fetch(`${base}/commerce/auth`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
  });
  if (response.status === 401) throw new Error("凭证无效或已过期，请向管理员领取新的内测凭证。");
  if (!response.ok) throw new Error("暂时无法连接服务，请稍后重试。");
  const data = await response.json();
  if (data.mode === "demo") return undefined;
  if (data.mode !== "hmac") throw new Error("服务身份配置异常，请联系管理员。");
  if (!data.authenticated) return null;
  if (typeof data.buyer_id !== "string" || !data.buyer_id || !token) throw new Error("身份验证失败。");
  return { buyerId: data.buyer_id, accessToken: token };
}

export default function AccessGate({ children }: { children: ReactNode }) {
  const [checking, setChecking] = useState(true);
  const [demo, setDemo] = useState(false);
  const [access, setAccess] = useState<BuyerAccess>();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let disposed = false;
    setChecking(true);
    setError("");
    void verify(savedToken()).then(result => {
      if (disposed) return;
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

  function logout() {
    try {
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith("globex.")) sessionStorage.removeItem(key);
      }
    } catch {}
    setAccess(undefined);
    setToken("");
    setError("");
  }

  if (checking) return <main className="access-screen" aria-busy="true"><p>正在连接 Globex…</p></main>;
  if (demo) return <>{children}</>;
  if (access) return <AccessContext.Provider value={access} key={access.buyerId}>
    <div className="access-bar"><span>内测账号：{access.buyerId}</span><button onClick={logout}>退出登录</button></div>
    {children}
  </AccessContext.Provider>;
  return <main className="access-screen"><section className="access-card">
    <p className="access-eyebrow">GLOBEX · 受邀内测</p>
    <h1>开始你的选购</h1>
    <p>请输入管理员发给你的个人内测凭证。凭证仅供本人使用，最长有效期为 24 小时。</p>
    <form onSubmit={login}>
      <label htmlFor="beta-token">内测凭证</label>
      <input id="beta-token" type="password" value={token} onChange={event => setToken(event.target.value)}
        autoComplete="off" spellCheck={false} maxLength={8192} required disabled={busy} />
      {error && <p role="alert" className="access-error">{error}</p>}
      <button className="access-submit" type="submit" disabled={busy}>{busy ? "正在验证…" : "进入 Globex"}</button>
    </form>
    <button className="access-retry" onClick={() => setRetry(value => value + 1)} disabled={busy}>重新连接服务</button>
    <p className="access-note">本次内测仅使用演示商品和测试订单，不进行真实支付或发货。</p>
  </section></main>;
}
