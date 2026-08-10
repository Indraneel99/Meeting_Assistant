import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ConfigProvider } from "./context/ConfigContext";
import { SessionProvider } from "./context/SessionContext";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ConfigProvider>
        <SessionProvider>
          <App />
        </SessionProvider>
      </ConfigProvider>
    </BrowserRouter>
  </StrictMode>,
);
