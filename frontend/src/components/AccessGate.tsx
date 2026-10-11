import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

export type BuyerAccess = { buyerId: string; accessToken: string; credential?: "invite" | "account"; displayName?: string; username?: string };
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
  if (typeof data.buyer_id !== "string" || !data.buyer_id || (!token && !["invite", "account"].includes(data.credential))) throw new Error("身份验证失败。");
  return { buyerId: data.buyer_id, accessToken: ["invite", "account"].includes(data.credential) ? "" : token,
    ...(["invite", "account"].includes(data.credential) ? { credential: data.credential as "invite" | "account" } : {}),
    displayName: typeof data.display_name === "string" ? data.display_name : data.buyer_id,
    username: typeof data.username === "string" ? data.username : undefined };
}

export default function AccessGate({ children }: { children: ReactNode }) {
  const [checking, setChecking] = useState(true);
  const [demo, setDemo] = useState(false);
  const [access, setAccess] = useState<BuyerAccess>();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [mode, setMode] = useState<"login" | "register" | "token">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [accountForm, setAccountForm] = useState(false);
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
      if (result?.credential) {
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
        else if (result.buyerId !== access.buyerId || result.displayName !== access.displayName) setAccess(result);
      }).catch(err => {
        if (err instanceof Error && (err.message.startsWith("凭证") || err.message.includes("已过期"))) {
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

  async function accountLogin(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      if (mode === "register" && password !== confirmation) throw new Error("两次输入的密码不一致。");
      const response = await fetch(`${base}/commerce/auth/${mode}`, {
        method: "POST", credentials: "include", cache: "no-store",
        headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(15000),
        body: JSON.stringify({ username, password, ...(mode === "register" ? { display_name: displayName } : {}) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "登录失败，请稍后重试。");
      try { sessionStorage.removeItem(TOKEN_KEY); } catch {}
      const result = await verify();
      if (!result || result.credential !== "account") throw new Error("无法保存登录状态，请允许此网站使用 Cookie。");
      setAccess(result); setAccountForm(false); setPassword(""); setConfirmation(""); setToken("");
      invite.current = ""; boot.current = undefined;
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请稍后重试。");
    } finally { setBusy(false); }
  }

  function changeMode(next: "login" | "register" | "token") {
    setMode(next); setError(""); setPassword(""); setConfirmation(""); setToken("");
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
    setAccountForm(false);
    setPassword(""); setConfirmation("");
    setToken("");
    setError("");
    invite.current = "";
    boot.current = undefined;
    setBusy(false);
  }

  if (checking) return <main className="access-screen" aria-busy="true"><p>正在连接 Ezbuying…</p></main>;
  if (demo) return <>{children}</>;
  if (access && !accountForm) return <AccessContext.Provider value={access} key={access.buyerId}>
    <div className="access-bar"><span>{access.credential === "invite" ? "演示体验" : `账号：${access.displayName || access.buyerId}`}</span>
      {access.credential === "invite" && <button onClick={() => { changeMode("register"); setAccountForm(true); }}>注册 / 登录账号</button>}
      <button onClick={() => void logout()} disabled={busy}>退出登录</button>
      {error && <span role="alert">{error}</span>}</div>
    {children}
  </AccessContext.Provider>;
  return <main className="access-screen"><section className="access-card">
    <p className="access-eyebrow">Ezbuying · 你的选购空间</p>
    <h1>开始你的选购</h1>
    <p>登录账号保存你的选购记录，也可以通过邀请链接直接体验。</p>
    <div className="access-tabs" aria-label="选择登录方式">
      <button type="button" aria-pressed={mode === "login"} disabled={busy} onClick={() => changeMode("login")}>账号登录</button>
      <button type="button" aria-pressed={mode === "register"} disabled={busy} onClick={() => changeMode("register")}>注册账号</button>
      <button type="button" aria-pressed={mode === "token"} disabled={busy} onClick={() => changeMode("token")}>内测凭证</button>
    </div>
    {mode === "token" ? <form onSubmit={login}>
      <label htmlFor="beta-token">内测凭证</label>
      <input id="beta-token" type="password" value={token} onChange={event => setToken(event.target.value)}
        autoComplete="off" spellCheck={false} maxLength={8192} required disabled={busy} />
      {error && <p role="alert" className="access-error">{error}</p>}
      <button className="access-submit" type="submit" disabled={busy}>{busy ? "正在验证…" : "进入 Ezbuying"}</button>
    </form> : <form onSubmit={accountLogin}>
      <label htmlFor="account-username">账号</label>
      <input id="account-username" value={username} onChange={event => setUsername(event.target.value)}
        autoComplete="username" autoCapitalize="none" spellCheck={false} minLength={3} maxLength={32} required disabled={busy}
        aria-describedby={mode === "register" ? "account-username-help" : undefined} />
      {mode === "register" && <>
        <small id="account-username-help">3–32 位英文字母、数字、下划线、点或短横线。</small>
        <label htmlFor="account-name">昵称</label>
        <input id="account-name" value={displayName} onChange={event => setDisplayName(event.target.value)}
          autoComplete="nickname" maxLength={32} required disabled={busy} />
      </>}
      <label htmlFor="account-password">密码{mode === "register" ? "（12–128 个字符）" : ""}</label>
      <input id="account-password" type="password" value={password} onChange={event => setPassword(event.target.value)}
        autoComplete={mode === "register" ? "new-password" : "current-password"} minLength={12} maxLength={128} required disabled={busy} />
      {mode === "register" && <>
        <label htmlFor="account-confirmation">确认密码</label>
        <input id="account-confirmation" type="password" value={confirmation} onChange={event => setConfirmation(event.target.value)}
          autoComplete="new-password" minLength={12} maxLength={128} required disabled={busy} />
        <p className="access-note">注册后开始独立的账号空间；当前访客的体验记录不会自动转入账号。暂不支持自助找回密码，请妥善保存。</p>
      </>}
      {error && <p role="alert" className="access-error">{error}</p>}
      <button className="access-submit" type="submit" disabled={busy}>{busy ? "正在验证…" : mode === "register" ? "注册并进入 Ezbuying" : "登录 Ezbuying"}</button>
    </form>}
    {accountForm && <button className="access-retry" disabled={busy} onClick={() => { setAccountForm(false); setError(""); setPassword(""); setConfirmation(""); }}>返回访客体验</button>}
    <button className="access-retry" onClick={() => { boot.current = undefined; setRetry(value => value + 1); }} disabled={busy}>重新连接服务</button>
    <p className="access-note">本次内测仅使用演示商品和测试订单，不进行真实支付或发货。</p>
  </section></main>;
}
