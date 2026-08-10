import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { QueryPage } from "./pages/QueryPage";
import { SearchPage } from "./pages/SearchPage";
import { UploadPage } from "./pages/UploadPage";
import { WorkflowPage } from "./pages/WorkflowPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<UploadPage />} />
        <Route path="workflow" element={<WorkflowPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="query" element={<QueryPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="settings/integrations" element={<IntegrationsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
