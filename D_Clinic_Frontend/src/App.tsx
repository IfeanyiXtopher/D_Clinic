import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ChatPage } from "./pages/Chat";
import { EvalPage } from "./pages/Eval";
import { PatientPage } from "./pages/Patient";
import { WorklistPage } from "./pages/Worklist";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<WorklistPage />} />
        <Route path="/patients/:id" element={<PatientPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/eval" element={<EvalPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
