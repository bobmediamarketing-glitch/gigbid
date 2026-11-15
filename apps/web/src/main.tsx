import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { SessionProvider, useSession } from "./lib/session";
import Analytics from "./pages/Analytics";
import Approvals from "./pages/Approvals";
import Inbox from "./pages/Inbox";
import JobDetail from "./pages/JobDetail";
import Login from "./pages/Login";
import Messages from "./pages/Messages";
import Onboarding from "./pages/Onboarding";
import Pipeline from "./pages/Pipeline";
import RunViewer from "./pages/RunViewer";
import Runs from "./pages/Runs";
import Settings from "./pages/Settings";
import Studio from "./pages/Studio";
import "./styles.css";

function Guard({ children }: { children: ReactNode }) {
  const { me, loading } = useSession();
  const loc = useLocation();
  if (loading) return <div className="main"><Loading /></div>;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (!me.settings.onboarded && loc.pathname !== "/onboarding") return <Navigate to="/onboarding" replace />;
  return <>{children}</>;
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/onboarding" element={<Guard><Onboarding /></Guard>} />
      <Route
        path="*"
        element={
          <Guard>
            <Layout>
              <Routes>
                <Route path="/" element={<Navigate to="/inbox" replace />} />
                <Route path="/inbox" element={<Inbox />} />
                <Route path="/jobs/:jobId" element={<JobDetail />} />
                <Route path="/studio/:threadId" element={<Studio />} />
                <Route path="/approvals" element={<Approvals />} />
                <Route path="/pipeline" element={<Pipeline />} />
                <Route path="/messages" element={<Messages />} />
                <Route path="/runs" element={<Runs />} />
                <Route path="/runs/:threadId" element={<RunViewer />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<div className="empty card"><h2>Page not found</h2></div>} />
              </Routes>
            </Layout>
          </Guard>
        }
      />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
);
