import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Loading } from "./components/Feedback";
import { Layout } from "./components/Layout";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import { ActivityPage } from "./pages/ActivityPage";
import { ChatPage } from "./pages/ChatPage";
import { GraphPage } from "./pages/GraphPage";
import { LoginPage } from "./pages/LoginPage";
import { MemoryExplorerPage } from "./pages/MemoryExplorerPage";

function Gate() {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-8"><Loading /></div>;
  if (!user) return <LoginPage />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ChatPage />} />
        <Route path="memories" element={<MemoryExplorerPage />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Gate />
      </BrowserRouter>
    </AuthProvider>
  );
}
