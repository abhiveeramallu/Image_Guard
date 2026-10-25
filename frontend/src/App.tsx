import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import DetectionPage from './pages/DetectionPage'
import HowItWorksPage from './pages/HowItWorksPage'
import WatermarkPage from './pages/WatermarkPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="detect" element={<DetectionPage />} />
        <Route path="watermark" element={<WatermarkPage />} />
        <Route path="how-it-works" element={<HowItWorksPage />} />
        <Route path="*" element={<Dashboard />} />
      </Route>
    </Routes>
  )
}
