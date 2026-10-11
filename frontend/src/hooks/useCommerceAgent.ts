import { useEffect, useState, useSyncExternalStore } from "react";
import { CommerceClient } from "../lib/commerceClient";
import { useBuyerAccess } from "../components/AccessGate";

export function useCommerceAgent() {
  const access = useBuyerAccess();
  const [client] = useState(() => {
    let storage: Storage | undefined;
    try {
      storage = access ? window.sessionStorage : window.localStorage;
    } catch {
      /* 存储受限时使用内存。 */
    }
    const base = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
    const accessToken = access?.accessToken;
    return new CommerceClient({ url: `${base}/commerce/ag-ui/run`, storage,
      buyerId: access?.buyerId ?? import.meta.env.VITE_BUYER_ID ?? "pao-coder", accessToken });
  });
  const snapshot = useSyncExternalStore(client.subscribe, client.getSnapshot);
  useEffect(() => { void client.initialize(); return () => client.detach(); }, [client]);
  useEffect(() => {
    void client.refreshConfirmations();
    void client.refreshSkills();
  }, [client, snapshot.sessionId]);
  return {
    ...snapshot,
    submit: client.submit,
    submitForm: client.submitForm,
    resolveToolApproval: client.resolveToolApproval,
    stop: client.stop,
    reset: client.reset,
    setSession: client.setSession,
    prepareOrder: client.prepareOrder,
    prepareCancel: client.prepareCancel,
    resolveConfirmation: client.resolveConfirmation,
    refreshConfirmations: client.refreshConfirmations,
    refreshSkills: client.refreshSkills,
    refreshHistory: client.refreshHistory,
    workspaceRequest: client.workspaceRequest,
    resume: client.resume,
  };
}
