import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import CharityClaimPage from "./pages/CharityClaimPage";
import PublicMarketplacePage from "./pages/PublicMarketplacePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/charity" replace />} />
        <Route path="/charity" element={<CharityClaimPage />} />
        <Route path="/marketplace" element={<PublicMarketplacePage />} />
      </Routes>
    </BrowserRouter>
  );
}