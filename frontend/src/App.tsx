import { useEffect, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { DebugGallery } from "./debug/Gallery";
import { useSession } from "./state/session";
import { Panel, Toasts } from "./ui/components/kit";
import { LoginScreen, RecoverScreen, SignupScreen } from "./ui/screens/Auth";
import { PlayScreen } from "./ui/screens/Play";

function Loading({ text = "Lighting the hearth…" }: { text?: string }) {
  return (
    <div className="title-bg">
      <Panel>
        <div className="head" style={{ fontSize: 22 }}>{text}</div>
      </Panel>
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const status = useSession((s) => s.status);
  if (status === "idle" || status === "loading") return <Loading />;
  if (status === "error") return <Loading text="Can't reach the server. Retrying soon…" />;
  if (status !== "ready") return <Navigate to="/" replace />;
  return <>{children}</>;
}

function AnonOnly({ children }: { children: ReactNode }) {
  const status = useSession((s) => s.status);
  if (status === "idle" || status === "loading") return <Loading />;
  if (status === "ready") return <Navigate to="/play" replace />;
  return <>{children}</>;
}

export function App() {
  const load = useSession((s) => s.load);
  const status = useSession((s) => s.status);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (status !== "error") return;
    const t = window.setTimeout(load, 4000);
    return () => window.clearTimeout(t);
  }, [status, load]);
  return (
    <BrowserRouter>
      <Toasts />
      <Routes>
        <Route path="/" element={<AnonOnly><LoginScreen /></AnonOnly>} />
        <Route path="/signup" element={<AnonOnly><SignupScreen /></AnonOnly>} />
        <Route path="/recover" element={<RecoverScreen />} />
        <Route path="/play" element={<RequireAuth><PlayScreen /></RequireAuth>} />
        <Route path="/debug" element={<DebugGallery />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
