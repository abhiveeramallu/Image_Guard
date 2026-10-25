import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Download,
  Eraser,
  FileCode,
  FileDown,
  Info,
  Loader2,
  Paintbrush,
  Play,
  Redo2,
  RotateCcw,
  ScanSearch,
  SlidersHorizontal,
  Undo2,
  UploadCloud,
} from 'lucide-react'
import Alert from '../components/Alert'
import ImageDropzone from '../components/ImageDropzone'
import {
  API_URL,
  analyzeManualForgery,
  fetchArtifact,
  getCapabilities,
} from '../services/api'
import type {
  Capabilities,
  ExperimentAnalysisResult,
} from '../types/api'
import { downloadBlob, formatBytes, readImageDimensions } from '../utils/files'

type ToolMode = 'brush' | 'copy_move' | 'eraser'
type ResultViewTab =
  | 'edited'
  | 'original'
  | 'side_by_side'
  | 'copy_move_overlay'
  | 'splicing_overlay'
  | 'ground_truth'

interface HistorySnapshot {
  mainData: ImageData
  gtData: ImageData
}

interface Rect {
  x: number
  y: number
  width: number
  height: number
}

const BRUSH_PALETTE = [
  '#ef4444', // Red
  '#000000', // Black
  '#ffffff', // White
  '#3b82f6', // Blue
  '#eab308', // Yellow
  '#10b981', // Green
  '#8b5cf6', // Purple
]

export default function ManualForgeryLabPage() {
  // Capabilities
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)

  // Panel A: Original Image
  const [originalFile, setOriginalFile] = useState<File | null>(null)
  const [originalUrl, setOriginalUrl] = useState<string | null>(null)
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null)

  // Panel B: Canvas & Editing
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const overlayRef = useRef<HTMLCanvasElement | null>(null)
  const origImageRef = useRef<HTMLImageElement | null>(null)
  const gtCanvasRef = useRef<HTMLCanvasElement | null>(null)

  const [activeTool, setActiveTool] = useState<ToolMode>('brush')
  const [brushColor, setBrushColor] = useState<string>('#ef4444')
  const [brushSize, setBrushSize] = useState<number>(14)
  const [eraserSize, setEraserSize] = useState<number>(24)

  // Drawing state
  const isDrawingRef = useRef(false)
  const lastPointRef = useRef<{ x: number; y: number } | null>(null)

  // History for Undo / Redo
  const [history, setHistory] = useState<HistorySnapshot[]>([])
  const [redoStack, setRedoStack] = useState<HistorySnapshot[]>([])

  // Copy-Move state
  const [cmStep, setCmStep] = useState<'select_source' | 'place_destination'>('select_source')
  const [cmSourceRect, setCmSourceRect] = useState<Rect | null>(null)
  const [cmSourceData, setCmSourceData] = useState<ImageData | null>(null)
  const [cmDestPos, setCmDestPos] = useState<{ x: number; y: number } | null>(null)
  const isDraggingSelectionRef = useRef(false)
  const selectionStartRef = useRef<{ x: number; y: number } | null>(null)

  // Edited Pixel Stats
  const [editedPixelCount, setEditedPixelCount] = useState<number>(0)
  const [editedPercentage, setEditedPercentage] = useState<number>(0)

  // Panel C: Analysis & Forensic Detectors
  const [runCopyMove, setRunCopyMove] = useState(true)
  const [runSplicing, setRunSplicing] = useState(true)
  const [runLocalization, setRunLocalization] = useState(false)
  const [runWatermarkVerify, setRunWatermarkVerify] = useState(true)

  // Detector advanced settings
  const [showSettings, setShowSettings] = useState(false)
  const [ratio, setRatio] = useState<number>(0.75)
  const [minMatches, setMinMatches] = useState<number>(6)
  const [minDisplacement, setMinDisplacement] = useState<number>(20)
  const [splicingThreshold, setSplicingThreshold] = useState<number>(0.5)

  // Analysis result state
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [analysisResult, setAnalysisResult] = useState<ExperimentAnalysisResult | null>(null)
  const [activeViewTab, setActiveViewTab] = useState<ResultViewTab>('edited')
  const [artifactBlobUrls, setArtifactBlobUrls] = useState<Record<string, string>>({})

  // Load capabilities on mount
  useEffect(() => {
    getCapabilities()
      .then((c) => setCapabilities(c))
      .catch(() => {
        // Fallback gracefully
      })
  }, [])

  // Initialize ground truth canvas
  const getGtCanvas = useCallback((w: number, h: number): HTMLCanvasElement => {
    if (!gtCanvasRef.current) {
      const c = document.createElement('canvas')
      c.width = w
      c.height = h
      const ctx = c.getContext('2d')
      if (ctx) {
        ctx.fillStyle = '#000000'
        ctx.fillRect(0, 0, w, h)
      }
      gtCanvasRef.current = c
    } else {
      gtCanvasRef.current.width = w
      gtCanvasRef.current.height = h
    }
    return gtCanvasRef.current
  }, [])

  // Calculate edited pixel statistics from GT canvas
  const updateEditedPixelStats = useCallback(() => {
    const gt = gtCanvasRef.current
    if (!gt) {
      setEditedPixelCount(0)
      setEditedPercentage(0)
      return
    }
    const ctx = gt.getContext('2d')
    if (!ctx) return
    const imgData = ctx.getImageData(0, 0, gt.width, gt.height)
    const data = imgData.data
    let edited = 0
    const total = gt.width * gt.height
    for (let i = 0; i < data.length; i += 4) {
      // If red channel > 10, pixel is modified
      if (data[i] > 10) {
        edited++
      }
    }
    setEditedPixelCount(edited)
    setEditedPercentage(total > 0 ? (edited / total) * 100 : 0)
  }, [])

  // Capture history snapshot before any mutation
  const pushHistory = useCallback(() => {
    const canvas = canvasRef.current
    const gt = gtCanvasRef.current
    if (!canvas || !gt) return
    const ctx = canvas.getContext('2d')
    const gtCtx = gt.getContext('2d')
    if (!ctx || !gtCtx) return

    const mainSnap = ctx.getImageData(0, 0, canvas.width, canvas.height)
    const gtSnap = gtCtx.getImageData(0, 0, gt.width, gt.height)

    setHistory((prev) => [...prev.slice(-20), { mainData: mainSnap, gtData: gtSnap }])
    setRedoStack([])
    // Clear previous stale detector results whenever working image is mutated
    setAnalysisResult(null)
    setAnalysisError(null)
  }, [])

  // Handle image upload
  const handleFile = useCallback(
    async (file: File) => {
      try {
        const url = URL.createObjectURL(file)
        const dims = await readImageDimensions(url)
        setOriginalFile(file)
        setOriginalUrl(url)
        setDimensions(dims)
        setHistory([])
        setRedoStack([])
        setAnalysisResult(null)
        setAnalysisError(null)
        setCmSourceRect(null)
        setCmSourceData(null)
        setCmDestPos(null)
        setCmStep('select_source')

        // Initialize ground truth immediately
        getGtCanvas(dims.width, dims.height)

        const img = new Image()
        img.onload = () => {
          origImageRef.current = img
          const canvas = canvasRef.current
          const overlay = overlayRef.current
          if (canvas) {
            canvas.width = dims.width
            canvas.height = dims.height
            const ctx = canvas.getContext('2d')
            if (ctx) {
              ctx.drawImage(img, 0, 0)
            }
          }
          if (overlay) {
            overlay.width = dims.width
            overlay.height = dims.height
            const oCtx = overlay.getContext('2d')
            oCtx?.clearRect(0, 0, dims.width, dims.height)
          }
          const gt = getGtCanvas(dims.width, dims.height)
          const gtCtx = gt.getContext('2d')
          if (gtCtx) {
            gtCtx.fillStyle = '#000000'
            gtCtx.fillRect(0, 0, dims.width, dims.height)
          }
          updateEditedPixelStats()
        }
        img.src = url
      } catch (err) {
        setAnalysisError('Failed to load image: ' + (err instanceof Error ? err.message : String(err)))
      }
    },
    [getGtCanvas, updateEditedPixelStats],
  )

  // Reset working canvas to original image
  const handleResetToOriginal = useCallback(() => {
    if (!origImageRef.current || !dimensions) return
    const canvas = canvasRef.current
    const overlay = overlayRef.current
    if (canvas) {
      const ctx = canvas.getContext('2d')
      if (ctx) {
        ctx.drawImage(origImageRef.current, 0, 0)
      }
    }
    if (overlay) {
      const oCtx = overlay.getContext('2d')
      oCtx?.clearRect(0, 0, dimensions.width, dimensions.height)
    }
    const gt = getGtCanvas(dimensions.width, dimensions.height)
    const gtCtx = gt.getContext('2d')
    if (gtCtx) {
      gtCtx.fillStyle = '#000000'
      gtCtx.fillRect(0, 0, dimensions.width, dimensions.height)
    }
    setHistory([])
    setRedoStack([])
    setCmSourceRect(null)
    setCmSourceData(null)
    setCmDestPos(null)
    setCmStep('select_source')
    setAnalysisResult(null)
    setAnalysisError(null)
    updateEditedPixelStats()
  }, [dimensions, getGtCanvas, updateEditedPixelStats])

  // Undo
  const handleUndo = useCallback(() => {
    if (history.length === 0 || !canvasRef.current || !gtCanvasRef.current) return
    const canvas = canvasRef.current
    const gt = gtCanvasRef.current
    const ctx = canvas.getContext('2d')
    const gtCtx = gt.getContext('2d')
    if (!ctx || !gtCtx) return

    // Save current into redo stack
    const currentMain = ctx.getImageData(0, 0, canvas.width, canvas.height)
    const currentGt = gtCtx.getImageData(0, 0, gt.width, gt.height)
    setRedoStack((prev) => [...prev, { mainData: currentMain, gtData: currentGt }])

    const last = history[history.length - 1]
    ctx.putImageData(last.mainData, 0, 0)
    gtCtx.putImageData(last.gtData, 0, 0)
    setHistory((prev) => prev.slice(0, prev.length - 1))
    setAnalysisResult(null)
    updateEditedPixelStats()
  }, [history, updateEditedPixelStats])

  // Redo
  const handleRedo = useCallback(() => {
    if (redoStack.length === 0 || !canvasRef.current || !gtCanvasRef.current) return
    const canvas = canvasRef.current
    const gt = gtCanvasRef.current
    const ctx = canvas.getContext('2d')
    const gtCtx = gt.getContext('2d')
    if (!ctx || !gtCtx) return

    const next = redoStack[redoStack.length - 1]
    // Save current to history
    const currentMain = ctx.getImageData(0, 0, canvas.width, canvas.height)
    const currentGt = gtCtx.getImageData(0, 0, gt.width, gt.height)
    setHistory((prev) => [...prev, { mainData: currentMain, gtData: currentGt }])

    ctx.putImageData(next.mainData, 0, 0)
    gtCtx.putImageData(next.gtData, 0, 0)
    setRedoStack((prev) => prev.slice(0, prev.length - 1))
    setAnalysisResult(null)
    updateEditedPixelStats()
  }, [redoStack, updateEditedPixelStats])

  // Coordinate mapping from client mouse event to canvas pixel coordinate
  const getCanvasCoords = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>): { x: number; y: number } => {
      const canvas = canvasRef.current
      if (!canvas) return { x: 0, y: 0 }
      const rect = canvas.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) return { x: 0, y: 0 }
      const scaleX = canvas.width / rect.width
      const scaleY = canvas.height / rect.height
      const x = Math.max(0, Math.min(canvas.width, Math.round((e.clientX - rect.left) * scaleX)))
      const y = Math.max(0, Math.min(canvas.height, Math.round((e.clientY - rect.top) * scaleY)))
      return { x, y }
    },
    [],
  )

  // Brush / Eraser drawing
  const drawStroke = useCallback(
    (x: number, y: number, isStarting: boolean) => {
      const canvas = canvasRef.current
      const gt = gtCanvasRef.current
      if (!canvas || !gt) return
      const ctx = canvas.getContext('2d')
      const gtCtx = gt.getContext('2d')
      if (!ctx || !gtCtx) return

      const last = lastPointRef.current ?? { x, y }

      if (activeTool === 'brush') {
        // Main canvas stroke
        ctx.save()
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'
        ctx.strokeStyle = brushColor
        ctx.lineWidth = brushSize
        ctx.beginPath()
        if (isStarting) {
          ctx.arc(x, y, brushSize / 2, 0, Math.PI * 2)
          ctx.fillStyle = brushColor
          ctx.fill()
        } else {
          ctx.moveTo(last.x, last.y)
          ctx.lineTo(x, y)
          ctx.stroke()
        }
        ctx.restore()

        // Ground-truth canvas stroke (white on black)
        gtCtx.save()
        gtCtx.lineCap = 'round'
        gtCtx.lineJoin = 'round'
        gtCtx.strokeStyle = '#ffffff'
        gtCtx.fillStyle = '#ffffff'
        gtCtx.lineWidth = brushSize
        gtCtx.beginPath()
        if (isStarting) {
          gtCtx.arc(x, y, brushSize / 2, 0, Math.PI * 2)
          gtCtx.fill()
        } else {
          gtCtx.moveTo(last.x, last.y)
          gtCtx.lineTo(x, y)
          gtCtx.stroke()
        }
        gtCtx.restore()
      } else if (activeTool === 'eraser') {
        const rad = eraserSize / 2
        // Main canvas: restore original image pixels inside brush circle
        if (origImageRef.current) {
          ctx.save()
          ctx.beginPath()
          ctx.arc(x, y, rad, 0, Math.PI * 2)
          ctx.clip()
          ctx.drawImage(origImageRef.current, 0, 0, canvas.width, canvas.height)
          ctx.restore()
        }

        // GT canvas: clear mask (black out)
        gtCtx.save()
        gtCtx.beginPath()
        gtCtx.arc(x, y, rad, 0, Math.PI * 2)
        gtCtx.fillStyle = '#000000'
        gtCtx.fill()
        gtCtx.restore()
      }

      lastPointRef.current = { x, y }
    },
    [activeTool, brushColor, brushSize, eraserSize],
  )

  // Copy-Move: Stamp clone to canvas
  const stampCopyMove = useCallback(() => {
    if (!cmSourceRect || !cmSourceData || !cmDestPos || !canvasRef.current || !gtCanvasRef.current) {
      return
    }
    pushHistory()

    const canvas = canvasRef.current
    const gt = gtCanvasRef.current
    const ctx = canvas.getContext('2d')
    const gtCtx = gt.getContext('2d')
    if (!ctx || !gtCtx) return

    // Paint source pixels at destination
    ctx.putImageData(cmSourceData, cmDestPos.x, cmDestPos.y)

    // Mark destination region as modified in ground-truth mask
    gtCtx.fillStyle = '#ffffff'
    gtCtx.fillRect(cmDestPos.x, cmDestPos.y, cmSourceRect.width, cmSourceRect.height)

    // Clear overlay
    const overlay = overlayRef.current
    if (overlay) {
      const oCtx = overlay.getContext('2d')
      oCtx?.clearRect(0, 0, overlay.width, overlay.height)
    }

    updateEditedPixelStats()
    setCmStep('select_source')
    setCmSourceRect(null)
    setCmSourceData(null)
    setCmDestPos(null)
  }, [cmDestPos, cmSourceData, cmSourceRect, pushHistory, updateEditedPixelStats])

  // Mouse event handlers for interactive canvas
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!dimensions) return
      const coords = getCanvasCoords(e)

      if (activeTool === 'brush' || activeTool === 'eraser') {
        pushHistory()
        isDrawingRef.current = true
        lastPointRef.current = coords
        drawStroke(coords.x, coords.y, true)
      } else if (activeTool === 'copy_move') {
        if (cmStep === 'select_source') {
          isDraggingSelectionRef.current = true
          selectionStartRef.current = coords
        } else if (cmStep === 'place_destination') {
          // Set destination position
          if (cmSourceRect) {
            const dstX = Math.max(0, Math.min(dimensions.width - cmSourceRect.width, coords.x))
            const dstY = Math.max(0, Math.min(dimensions.height - cmSourceRect.height, coords.y))
            setCmDestPos({ x: dstX, y: dstY })
          }
        }
      }
    },
    [activeTool, cmStep, cmSourceRect, dimensions, drawStroke, getCanvasCoords, pushHistory],
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const coords = getCanvasCoords(e)

      if (isDrawingRef.current && (activeTool === 'brush' || activeTool === 'eraser')) {
        drawStroke(coords.x, coords.y, false)
      } else if (activeTool === 'copy_move') {
        const overlay = overlayRef.current
        if (!overlay || !dimensions) return
        const oCtx = overlay.getContext('2d')
        if (!oCtx) return

        if (isDraggingSelectionRef.current && selectionStartRef.current) {
          // Draw live selection box
          oCtx.clearRect(0, 0, overlay.width, overlay.height)
          const start = selectionStartRef.current
          const x = Math.min(start.x, coords.x)
          const y = Math.min(start.y, coords.y)
          const w = Math.abs(coords.x - start.x)
          const h = Math.abs(coords.y - start.y)

          oCtx.strokeStyle = '#38bdf8'
          oCtx.lineWidth = 2
          oCtx.setLineDash([6, 4])
          oCtx.strokeRect(x, y, w, h)
          oCtx.fillStyle = 'rgba(56, 189, 248, 0.2)'
          oCtx.fillRect(x, y, w, h)
          oCtx.setLineDash([])

          // HUD dimension label
          oCtx.fillStyle = '#0f172a'
          oCtx.fillRect(x, Math.max(0, y - 22), 110, 20)
          oCtx.fillStyle = '#ffffff'
          oCtx.font = '11px sans-serif'
          oCtx.fillText(`${w} × ${h} px`, x + 6, Math.max(0, y - 22) + 14)
        } else if (cmStep === 'place_destination' && cmSourceRect) {
          // Preview destination placement
          oCtx.clearRect(0, 0, overlay.width, overlay.height)

          // Draw fixed source rect outline
          oCtx.strokeStyle = '#38bdf8'
          oCtx.lineWidth = 2
          oCtx.setLineDash([4, 4])
          oCtx.strokeRect(cmSourceRect.x, cmSourceRect.y, cmSourceRect.width, cmSourceRect.height)
          oCtx.fillStyle = 'rgba(56, 189, 248, 0.15)'
          oCtx.fillRect(cmSourceRect.x, cmSourceRect.y, cmSourceRect.width, cmSourceRect.height)

          // Destination box tracking cursor
          const dstX = Math.max(0, Math.min(dimensions.width - cmSourceRect.width, coords.x))
          const dstY = Math.max(0, Math.min(dimensions.height - cmSourceRect.height, coords.y))

          oCtx.strokeStyle = '#10b981'
          oCtx.lineWidth = 2
          oCtx.setLineDash([])
          oCtx.strokeRect(dstX, dstY, cmSourceRect.width, cmSourceRect.height)
          oCtx.fillStyle = 'rgba(16, 185, 129, 0.25)'
          oCtx.fillRect(dstX, dstY, cmSourceRect.width, cmSourceRect.height)

          // Arrow from source to dest
          oCtx.strokeStyle = '#10b981'
          oCtx.beginPath()
          oCtx.moveTo(cmSourceRect.x + cmSourceRect.width / 2, cmSourceRect.y + cmSourceRect.height / 2)
          oCtx.lineTo(dstX + cmSourceRect.width / 2, dstY + cmSourceRect.height / 2)
          oCtx.stroke()

          // HUD
          oCtx.fillStyle = '#0f172a'
          oCtx.fillRect(dstX, Math.max(0, dstY - 22), 140, 20)
          oCtx.fillStyle = '#ffffff'
          oCtx.font = '11px sans-serif'
          oCtx.fillText(`Paste at: (${dstX}, ${dstY})`, dstX + 6, Math.max(0, dstY - 22) + 14)
        }
      }
    },
    [activeTool, cmStep, cmSourceRect, dimensions, drawStroke, getCanvasCoords],
  )

  const handleMouseUp = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (isDrawingRef.current) {
        isDrawingRef.current = false
        lastPointRef.current = null
        updateEditedPixelStats()
      } else if (activeTool === 'copy_move' && isDraggingSelectionRef.current && selectionStartRef.current) {
        isDraggingSelectionRef.current = false
        const coords = getCanvasCoords(e)
        const start = selectionStartRef.current
        const x = Math.min(start.x, coords.x)
        const y = Math.min(start.y, coords.y)
        const w = Math.abs(coords.x - start.x)
        const h = Math.abs(coords.y - start.y)

        if (w >= 10 && h >= 10 && canvasRef.current) {
          const rect: Rect = { x, y, width: w, height: h }
          setCmSourceRect(rect)
          const ctx = canvasRef.current.getContext('2d')
          if (ctx) {
            const imgData = ctx.getImageData(x, y, w, h)
            setCmSourceData(imgData)
          }
          setCmStep('place_destination')
        } else {
          // Too small, clear overlay
          const overlay = overlayRef.current
          if (overlay) {
            const oCtx = overlay.getContext('2d')
            oCtx?.clearRect(0, 0, overlay.width, overlay.height)
          }
        }
        selectionStartRef.current = null
      }
    },
    [activeTool, getCanvasCoords, updateEditedPixelStats],
  )

  const handleMouseLeave = useCallback(() => {
    if (isDrawingRef.current) {
      isDrawingRef.current = false
      lastPointRef.current = null
      updateEditedPixelStats()
    }
  }, [updateEditedPixelStats])

  // Run Forgery Detection
  const handleRunDetection = useCallback(async () => {
    if (!canvasRef.current || !gtCanvasRef.current || !originalFile) {
      setAnalysisError('Please upload an image before running forgery detection.')
      return
    }

    setIsAnalyzing(true)
    setAnalysisError(null)

    try {
      // 1. Export modified image from canvas
      const modifiedBlob: Blob = await new Promise((resolve) =>
        canvasRef.current!.toBlob((b) => resolve(b!), 'image/png'),
      )

      // 2. Export ground-truth mask from gtCanvas
      const gtBlob: Blob = await new Promise((resolve) =>
        gtCanvasRef.current!.toBlob((b) => resolve(b!), 'image/png'),
      )

      // 3. Collect active detection methods
      const methods: string[] = []
      if (runCopyMove) methods.push('copy_move')
      if (runSplicing) methods.push('splicing')
      if (runLocalization && capabilities?.methods?.localization?.available) methods.push('localization')
      if (runWatermarkVerify) methods.push('watermark_verify')

      if (methods.length === 0) {
        setAnalysisError('Please enable at least one detection method.')
        setIsAnalyzing(false)
        return
      }

      // 4. Send directly to direct analysis route
      const res = await analyzeManualForgery(modifiedBlob, originalFile, gtBlob, methods, {
        ratio,
        min_matches: minMatches,
        min_displacement: minDisplacement,
        splicing_threshold: splicingThreshold,
      })

      setAnalysisResult(res)

      // 5. Pre-fetch artifact blobs for smooth tab switching
      const urls: Record<string, string> = {}
      if (res.artifacts) {
        for (const [key, artifactPath] of Object.entries(res.artifacts)) {
          if (typeof artifactPath === 'string') {
            try {
              const b = await fetchArtifact(artifactPath)
              urls[key] = URL.createObjectURL(b)
            } catch {
              urls[key] = `${API_URL}${artifactPath}`
            }
          }
        }
      }
      setArtifactBlobUrls(urls)

      // Default active tab to copy-move overlay if detected, or edited
      if (res.artifacts['copy_move.overlay']) {
        setActiveViewTab('copy_move_overlay')
      } else if (res.artifacts['splicing.overlay']) {
        setActiveViewTab('splicing_overlay')
      } else {
        setActiveViewTab('edited')
      }
    } catch (err) {
      setAnalysisError(err instanceof Error ? err.message : 'Analysis failed. Please check backend connection.')
    } finally {
      setIsAnalyzing(false)
    }
  }, [
    capabilities?.methods?.localization?.available,
    minDisplacement,
    minMatches,
    originalFile,
    ratio,
    runCopyMove,
    runLocalization,
    runSplicing,
    runWatermarkVerify,
    splicingThreshold,
  ])

  // Download Modified Image
  const handleDownloadModified = useCallback(async () => {
    if (!canvasRef.current) return
    canvasRef.current.toBlob((blob) => {
      if (blob) {
        downloadBlob(blob, 'imageguard_tampered.png')
      }
    }, 'image/png')
  }, [])

  // Download Reports
  const handleDownloadReport = useCallback(
    async (format: 'json' | 'html') => {
      if (!analysisResult) return
      const url = format === 'json' ? analysisResult.report_json : analysisResult.report_html
      try {
        const b = await fetchArtifact(url)
        downloadBlob(b, `imageguard_analysis_report.${format}`)
      } catch (err) {
        setAnalysisError('Failed to download report: ' + (err instanceof Error ? err.message : String(err)))
      }
    },
    [analysisResult],
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="rounded-2xl bg-ink-900 px-6 py-8 text-white sm:px-10 sm:py-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-accent-500/20 px-3 py-1 text-xs font-semibold text-accent-300">
              <ScanSearch size={14} aria-hidden /> Manual Forgery Lab
            </div>
            <h1 className="mt-2 text-2xl font-bold sm:text-3xl">Manual Image Editing &amp; Forgery Detection</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-300">
              Manually paint scratches, cover regions, or stamp copy-move clone forgeries on an image. Then run explainable
              forensic detectors to inspect candidate regions and benchmark detection performance against ground truth.
            </p>
          </div>
          {dimensions && (
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleResetToOriginal}
                className="btn-secondary flex items-center gap-2 text-xs"
                title="Reset all modifications back to pristine original"
              >
                <RotateCcw size={14} aria-hidden /> Reset to Original
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Main 3-Panel Layout */}
      <div className="grid grid-cols-12 gap-6">
        {/* PANEL A: Original Image */}
        <section className="col-span-12 flex flex-col gap-4 lg:col-span-3">
          <div className="card flex-1 p-5">
            <h2 className="flex items-center gap-2 text-base font-semibold text-slate-800">
              <UploadCloud size={18} className="text-accent-600" aria-hidden /> Panel A: Original Image
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Source baseline image. Unmodified pixels are preserved in an isolated buffer.
            </p>

            <div className="mt-4">
              {!originalFile ? (
                <ImageDropzone onFile={handleFile} label="Upload source image (JPG / PNG)" />
              ) : (
                <div className="space-y-4">
                  {originalUrl && (
                    <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-900">
                      <img
                        src={originalUrl}
                        alt="Original source"
                        className="max-h-52 w-full object-contain"
                      />
                    </div>
                  )}

                  <div className="rounded-lg bg-slate-50 p-3 text-xs space-y-1.5 border border-slate-200">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Filename:</span>
                      <span className="font-medium text-slate-800 truncate max-w-[140px]" title={originalFile.name}>
                        {originalFile.name}
                      </span>
                    </div>
                    {dimensions && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">Dimensions:</span>
                        <span className="font-semibold text-slate-800">
                          {dimensions.width} × {dimensions.height} px
                        </span>
                      </div>
                    )}
                    <div className="flex justify-between">
                      <span className="text-slate-500">File Size:</span>
                      <span className="font-medium text-slate-800">{formatBytes(originalFile.size)}</span>
                    </div>
                  </div>

                  <div className="flex flex-col gap-2">
                    <label className="btn-secondary cursor-pointer text-center text-xs">
                      Choose Another Image
                      <input
                        type="file"
                        accept="image/jpeg,image/png"
                        className="sr-only"
                        onChange={(e) => {
                          const f = e.target.files?.[0]
                          if (f) handleFile(f)
                        }}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={handleResetToOriginal}
                      className="btn-secondary text-xs text-rose-700 hover:bg-rose-50"
                    >
                      <RotateCcw size={14} className="inline mr-1" aria-hidden /> Clear Canvas &amp; Reset
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* PANEL B: Interactive Editing Canvas */}
        <section className="col-span-12 flex flex-col gap-4 lg:col-span-5">
          <div className="card flex-1 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
              <div>
                <h2 className="flex items-center gap-2 text-base font-semibold text-slate-800">
                  <Paintbrush size={18} className="text-accent-600" aria-hidden /> Panel B: Editing Canvas
                </h2>
                <p className="text-xs text-slate-500">
                  Interactive workspace. Coordinates map accurately to full image resolution.
                </p>
              </div>

              {/* Undo / Redo controls */}
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={handleUndo}
                  disabled={history.length === 0}
                  className="rounded-md border border-slate-200 p-1.5 text-slate-600 transition hover:bg-slate-100 disabled:opacity-40"
                  title="Undo last stroke / action (Ctrl+Z)"
                  aria-label="Undo"
                >
                  <Undo2 size={16} />
                </button>
                <button
                  type="button"
                  onClick={handleRedo}
                  disabled={redoStack.length === 0}
                  className="rounded-md border border-slate-200 p-1.5 text-slate-600 transition hover:bg-slate-100 disabled:opacity-40"
                  title="Redo action"
                  aria-label="Redo"
                >
                  <Redo2 size={16} />
                </button>
              </div>
            </div>

            {/* Tool Selection Tabs */}
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setActiveTool('brush')
                  setCmSourceRect(null)
                  setCmDestPos(null)
                  setCmStep('select_source')
                }}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  activeTool === 'brush'
                    ? 'bg-ink-900 text-white'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                <Paintbrush size={14} aria-hidden /> Brush / Scratch
              </button>
              <button
                type="button"
                onClick={() => {
                  setActiveTool('copy_move')
                  setCmStep('select_source')
                  setCmSourceRect(null)
                  setCmDestPos(null)
                }}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  activeTool === 'copy_move'
                    ? 'bg-ink-900 text-white'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                <Copy size={14} aria-hidden /> Copy-Move Tool
              </button>
              <button
                type="button"
                onClick={() => {
                  setActiveTool('eraser')
                  setCmSourceRect(null)
                  setCmDestPos(null)
                }}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  activeTool === 'eraser'
                    ? 'bg-ink-900 text-white'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                <Eraser size={14} aria-hidden /> Eraser
              </button>
            </div>

            {/* Tool Settings Bar */}
            <div className="mt-3 rounded-xl bg-slate-50 p-3 border border-slate-200 text-xs">
              {activeTool === 'brush' && (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-medium text-slate-700">Color:</span>
                    <div className="flex items-center gap-1.5">
                      {BRUSH_PALETTE.map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => setBrushColor(c)}
                          className={`h-5 w-5 rounded-full border ${
                            brushColor === c ? 'ring-2 ring-accent-500 scale-110' : 'border-slate-300'
                          }`}
                          style={{ backgroundColor: c }}
                          title={c}
                          aria-label={`Color ${c}`}
                        />
                      ))}
                      <input
                        type="color"
                        value={brushColor}
                        onChange={(e) => setBrushColor(e.target.value)}
                        className="h-6 w-6 cursor-pointer rounded border border-slate-300 bg-transparent p-0"
                        title="Custom Color"
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-slate-700">Size:</span>
                    <input
                      type="range"
                      min={1}
                      max={60}
                      value={brushSize}
                      onChange={(e) => setBrushSize(Number(e.target.value))}
                      className="h-1.5 flex-1 cursor-pointer accent-accent-600"
                    />
                    <span className="w-8 text-right font-mono text-slate-600">{brushSize}px</span>
                  </div>
                </div>
              )}

              {activeTool === 'copy_move' && (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-slate-700">
                      {cmStep === 'select_source'
                        ? '1. Drag a rectangle on the canvas to select source region'
                        : '2. Click destination on the canvas, then press Stamp Clone'}
                    </span>
                    {cmStep === 'place_destination' && (
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={stampCopyMove}
                          disabled={!cmDestPos}
                          className="btn-primary py-1 px-3 text-xs bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50"
                        >
                          Stamp Clone
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setCmStep('select_source')
                            setCmSourceRect(null)
                            setCmDestPos(null)
                            const overlay = overlayRef.current
                            if (overlay) {
                              const oCtx = overlay.getContext('2d')
                              oCtx?.clearRect(0, 0, overlay.width, overlay.height)
                            }
                          }}
                          className="btn-secondary py-1 px-2 text-xs"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                  {cmSourceRect && (
                    <div className="font-mono text-[11px] text-slate-600">
                      Source: [{cmSourceRect.x}, {cmSourceRect.y}, {cmSourceRect.width} × {cmSourceRect.height} px]
                      {cmDestPos ? ` → Dest: [${cmDestPos.x}, ${cmDestPos.y}]` : ' → (Click canvas to place)'}
                    </div>
                  )}
                </div>
              )}

              {activeTool === 'eraser' && (
                <div className="flex items-center gap-3">
                  <span className="font-medium text-slate-700">Eraser Size:</span>
                  <input
                    type="range"
                    min={4}
                    max={80}
                    value={eraserSize}
                    onChange={(e) => setEraserSize(Number(e.target.value))}
                    className="h-1.5 flex-1 cursor-pointer accent-accent-600"
                  />
                  <span className="w-8 text-right font-mono text-slate-600">{eraserSize}px</span>
                </div>
              )}
            </div>

            {/* Interactive Canvas Viewport */}
            <div className="mt-4">
              {!originalFile ? (
                <div className="flex h-72 flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 text-slate-400">
                  <Paintbrush size={32} className="opacity-40" />
                  <p className="mt-2 text-xs">Upload an image in Panel A to begin manual editing.</p>
                </div>
              ) : (
                <div className="relative overflow-hidden rounded-xl border border-slate-300 bg-slate-900 shadow-inner">
                  {/* Checkerboard backdrop for alpha transparency */}
                  <div className="absolute inset-0 bg-[radial-gradient(#334155_1px,transparent_1px)] [background-size:16px_16px] opacity-40 pointer-events-none" />

                  {/* Main Working Canvas */}
                  <canvas
                    ref={canvasRef}
                    onMouseDown={handleMouseDown}
                    onMouseMove={handleMouseMove}
                    onMouseUp={handleMouseUp}
                    onMouseLeave={handleMouseLeave}
                    className="relative z-10 block w-full h-auto cursor-crosshair select-none"
                    style={{ touchAction: 'none' }}
                  />

                  {/* Overlay Canvas for Selection Outlines / Preview */}
                  <canvas
                    ref={overlayRef}
                    className="pointer-events-none absolute inset-0 z-20 block w-full h-auto select-none"
                  />
                </div>
              )}
            </div>

            {/* Altered Pixel Stats & Quick Actions */}
            {dimensions && (
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 font-medium ${
                      editedPixelCount > 0
                        ? 'bg-amber-100 text-amber-800 border border-amber-300'
                        : 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                    }`}
                  >
                    {editedPixelCount > 0 ? (
                      <>
                        <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                        Edited: {editedPixelCount.toLocaleString()} px ({editedPercentage.toFixed(2)}%)
                      </>
                    ) : (
                      <>
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                        Clean Baseline (0 modified px)
                      </>
                    )}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleDownloadModified}
                    className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900 font-medium"
                  >
                    <Download size={13} aria-hidden /> Save PNG
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* PANEL C: Forensic Analysis & Results */}
        <section className="col-span-12 flex flex-col gap-4 lg:col-span-4">
          <div className="card flex-1 p-5 space-y-4">
            <div>
              <h2 className="flex items-center gap-2 text-base font-semibold text-slate-800">
                <ScanSearch size={18} className="text-accent-600" aria-hidden /> Panel C: Forensic Detection
              </h2>
              <p className="text-xs text-slate-500">
                Run explainable forensic detectors directly on the working canvas.
              </p>
            </div>

            {/* Method selection */}
            <div className="rounded-xl bg-slate-50 p-3 border border-slate-200 space-y-2 text-xs">
              <span className="font-semibold text-slate-700">Active Detectors:</span>
              <div className="space-y-1.5 pt-1">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={runCopyMove}
                    onChange={(e) => setRunCopyMove(e.target.checked)}
                    className="rounded border-slate-300 text-accent-600"
                  />
                  <span className="font-medium text-slate-800">ORB Copy-Move Detection</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={runSplicing}
                    onChange={(e) => setRunSplicing(e.target.checked)}
                    className="rounded border-slate-300 text-accent-600"
                  />
                  <span className="font-medium text-slate-800">Splicing Analysis (ELA &amp; Noise)</span>
                </label>
                <label
                  className={`flex items-center gap-2 ${
                    capabilities?.methods?.localization?.available ? 'cursor-pointer' : 'opacity-50 cursor-not-allowed'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={runLocalization}
                    disabled={!capabilities?.methods?.localization?.available}
                    onChange={(e) => setRunLocalization(e.target.checked)}
                    className="rounded border-slate-300 text-accent-600"
                  />
                  <span className="font-medium text-slate-800">ONNX Model Localization</span>
                  {!capabilities?.methods?.localization?.available && (
                    <span className="text-[10px] text-slate-400">(Weights unavailable)</span>
                  )}
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={runWatermarkVerify}
                    onChange={(e) => setRunWatermarkVerify(e.target.checked)}
                    className="rounded border-slate-300 text-accent-600"
                  />
                  <span className="font-medium text-slate-800">Invisible Watermark Verification</span>
                </label>
              </div>

              {/* Advanced Thresholds Accordion */}
              <div className="pt-2 border-t border-slate-200">
                <button
                  type="button"
                  onClick={() => setShowSettings((s) => !s)}
                  className="flex w-full items-center justify-between text-slate-600 hover:text-slate-900 font-medium"
                >
                  <span className="inline-flex items-center gap-1">
                    <SlidersHorizontal size={12} /> Detector Thresholds
                  </span>
                  <span>{showSettings ? '▲' : '▼'}</span>
                </button>
                {showSettings && (
                  <div className="mt-2.5 space-y-2 border-t border-slate-200 pt-2 text-[11px]">
                    <div>
                      <div className="flex justify-between">
                        <span>ORB Lowe's Ratio:</span>
                        <span className="font-mono">{ratio}</span>
                      </div>
                      <input
                        type="range"
                        min={0.5}
                        max={0.95}
                        step={0.05}
                        value={ratio}
                        onChange={(e) => setRatio(Number(e.target.value))}
                        className="h-1 w-full accent-accent-600"
                      />
                    </div>
                    <div>
                      <div className="flex justify-between">
                        <span>Min Matches per Cluster:</span>
                        <span className="font-mono">{minMatches}</span>
                      </div>
                      <input
                        type="range"
                        min={3}
                        max={15}
                        step={1}
                        value={minMatches}
                        onChange={(e) => setMinMatches(Number(e.target.value))}
                        className="h-1 w-full accent-accent-600"
                      />
                    </div>
                    <div>
                      <div className="flex justify-between">
                        <span>Min Displacement:</span>
                        <span className="font-mono">{minDisplacement} px</span>
                      </div>
                      <input
                        type="range"
                        min={5}
                        max={80}
                        step={5}
                        value={minDisplacement}
                        onChange={(e) => setMinDisplacement(Number(e.target.value))}
                        className="h-1 w-full accent-accent-600"
                      />
                    </div>
                    <div>
                      <div className="flex justify-between">
                        <span>Splicing ELA Threshold:</span>
                        <span className="font-mono">{splicingThreshold}</span>
                      </div>
                      <input
                        type="range"
                        min={0.1}
                        max={0.9}
                        step={0.05}
                        value={splicingThreshold}
                        onChange={(e) => setSplicingThreshold(Number(e.target.value))}
                        className="h-1 w-full accent-accent-600"
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Run Button */}
            <button
              type="button"
              onClick={handleRunDetection}
              disabled={isAnalyzing || !originalFile}
              className="btn-primary w-full py-3 flex items-center justify-center gap-2 text-sm font-semibold shadow-md disabled:opacity-50"
            >
              {isAnalyzing ? (
                <>
                  <Loader2 size={16} className="animate-spin" aria-hidden /> Analyzing Image Forensics...
                </>
              ) : (
                <>
                  <Play size={16} aria-hidden /> Run Forgery Detection
                </>
              )}
            </button>

            {analysisError && <Alert kind="error">{analysisError}</Alert>}

            {/* Clean baseline notice */}
            {editedPixelCount === 0 && dimensions && !analysisResult && (
              <div className="rounded-lg bg-blue-50 p-2.5 text-xs text-blue-700 border border-blue-200 flex gap-2">
                <Info size={16} className="shrink-0 mt-0.5" />
                <p>
                  Canvas is unedited. Running detection will evaluate baseline behavior on pristine pixels, checking for
                  natural false alarms.
                </p>
              </div>
            )}

            {/* Detection Results Output */}
            {analysisResult && (
              <div className="space-y-4 pt-2 border-t border-slate-100">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Analysis Results</h3>
                  <span className="text-[11px] text-slate-400 font-mono">
                    {analysisResult.processing_ms} ms
                  </span>
                </div>

                {/* Status Badges */}
                <div className="space-y-2">
                  {analysisResult.detection_results?.map((r, i) => (
                    <div
                      key={i}
                      className="rounded-lg border border-slate-200 bg-white p-2.5 text-xs shadow-sm"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-800">{r.method_name ?? r.method}</span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                            r.status === 'candidate_regions_found'
                              ? 'bg-amber-100 text-amber-800'
                              : r.status === 'no_candidate_regions_found'
                              ? 'bg-slate-100 text-slate-700'
                              : 'bg-indigo-100 text-indigo-700'
                          }`}
                        >
                          {r.status?.replace(/_/g, ' ')}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                        <span>Regions found: <strong>{r.region_count ?? 0}</strong></span>
                        {r.metrics?.keypoints && (
                          <span>Keypoints: {r.metrics.keypoints}</span>
                        )}
                      </div>
                      {r.status_reason && (
                        <p className="mt-1 text-[11px] text-slate-600 italic">
                          {r.status_reason}
                        </p>
                      )}
                    </div>
                  ))}

                  {/* Watermark Verification Result */}
                  {analysisResult.watermark_verification && (
                    <div className="rounded-lg border border-slate-200 bg-white p-2.5 text-xs shadow-sm">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-800">Invisible Watermark</span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                            analysisResult.watermark_verification.status === 'verified'
                              ? 'bg-emerald-100 text-emerald-800'
                              : 'bg-rose-100 text-rose-800'
                          }`}
                        >
                          {analysisResult.watermark_verification.status}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-slate-600">
                        {analysisResult.watermark_verification.status_reason}
                      </p>
                    </div>
                  )}
                </div>

                {/* Ground-Truth Evaluation Metrics */}
                {analysisResult.evaluation && analysisResult.evaluation.length > 0 && (
                  <div className="rounded-xl bg-slate-50 p-3 border border-slate-200 space-y-2 text-xs">
                    <h4 className="font-semibold text-slate-800 flex items-center gap-1.5">
                      <CheckCircle2 size={14} className="text-emerald-600" /> Ground-Truth Evaluation
                    </h4>
                    <p className="text-[11px] text-slate-500">
                      Evaluated against user-drawn edit mask (kept strictly isolated during detection).
                    </p>

                    <div className="space-y-2 pt-1">
                      {analysisResult.evaluation.map((ev, idx) => (
                        <div key={idx} className="rounded bg-white p-2 border border-slate-200 text-[11px]">
                          <div className="font-semibold text-slate-700 capitalize">{ev.method.replace(/_/g, ' ')}:</div>
                          {ev.metrics ? (
                            <div className="mt-1 grid grid-cols-4 gap-1 text-center font-mono">
                              <div className="rounded bg-slate-50 p-1">
                                <div className="text-[10px] text-slate-400">Precision</div>
                                <div className="font-bold text-slate-800">
                                  {ev.metrics.precision !== null ? (ev.metrics.precision * 100).toFixed(1) + '%' : '—'}
                                </div>
                              </div>
                              <div className="rounded bg-slate-50 p-1">
                                <div className="text-[10px] text-slate-400">Recall</div>
                                <div className="font-bold text-slate-800">
                                  {ev.metrics.recall !== null ? (ev.metrics.recall * 100).toFixed(1) + '%' : '—'}
                                </div>
                              </div>
                              <div className="rounded bg-slate-50 p-1">
                                <div className="text-[10px] text-slate-400">F1</div>
                                <div className="font-bold text-slate-800">
                                  {ev.metrics.f1 !== null ? ev.metrics.f1.toFixed(3) : '—'}
                                </div>
                              </div>
                              <div className="rounded bg-slate-50 p-1">
                                <div className="text-[10px] text-slate-400">IoU</div>
                                <div className="font-bold text-slate-800">
                                  {ev.metrics.iou !== null ? ev.metrics.iou.toFixed(3) : '—'}
                                </div>
                              </div>
                            </div>
                          ) : (
                            <div className="text-slate-500 italic mt-0.5">{ev.notes}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Report Downloads */}
                <div className="flex items-center gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => handleDownloadReport('json')}
                    className="btn-secondary flex-1 py-1.5 text-xs flex items-center justify-center gap-1"
                  >
                    <FileCode size={13} aria-hidden /> JSON Report
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDownloadReport('html')}
                    className="btn-secondary flex-1 py-1.5 text-xs flex items-center justify-center gap-1"
                  >
                    <FileDown size={13} aria-hidden /> HTML Report
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Visual Overlay & Comparison Section (When Analysis is Available) */}
      {analysisResult && (
        <section className="card p-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-3">
            <div>
              <h3 className="text-lg font-bold text-slate-900">Forensic Visualizer &amp; Evidence Inspector</h3>
              <p className="text-xs text-slate-500">
                Compare original, modified canvas, ground-truth edits, and detector candidate overlays.
              </p>
            </div>

            {/* View tabs */}
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => setActiveViewTab('edited')}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  activeViewTab === 'edited' ? 'bg-ink-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                Modified Canvas
              </button>
              <button
                type="button"
                onClick={() => setActiveViewTab('original')}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  activeViewTab === 'original' ? 'bg-ink-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                Original Image
              </button>
              <button
                type="button"
                onClick={() => setActiveViewTab('side_by_side')}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  activeViewTab === 'side_by_side'
                    ? 'bg-ink-900 text-white'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                Side-by-Side
              </button>
              {analysisResult.artifacts['copy_move.overlay'] && (
                <button
                  type="button"
                  onClick={() => setActiveViewTab('copy_move_overlay')}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                    activeViewTab === 'copy_move_overlay'
                      ? 'bg-accent-600 text-white'
                      : 'bg-accent-50 text-accent-700 hover:bg-accent-100'
                  }`}
                >
                  Copy-Move Matches
                </button>
              )}
              {analysisResult.artifacts['splicing.overlay'] && (
                <button
                  type="button"
                  onClick={() => setActiveViewTab('splicing_overlay')}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                    activeViewTab === 'splicing_overlay'
                      ? 'bg-purple-600 text-white'
                      : 'bg-purple-50 text-purple-700 hover:bg-purple-100'
                  }`}
                >
                  Splicing Heatmap
                </button>
              )}
              {analysisResult.artifacts['ground_truth_mask'] && (
                <button
                  type="button"
                  onClick={() => setActiveViewTab('ground_truth')}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                    activeViewTab === 'ground_truth'
                      ? 'bg-slate-800 text-white'
                      : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                  }`}
                >
                  Ground Truth Mask
                </button>
              )}
            </div>
          </div>

          {/* Viewer Area */}
          <div className="rounded-xl border border-slate-200 bg-slate-900 p-4 min-h-[360px] flex items-center justify-center">
            {activeViewTab === 'edited' && (
              <img
                src={artifactBlobUrls['modified_image'] ?? `${API_URL}${analysisResult.artifacts['modified_image']}`}
                alt="Modified Canvas"
                className="max-h-[500px] w-auto max-w-full rounded object-contain shadow-lg"
              />
            )}

            {activeViewTab === 'original' && originalUrl && (
              <img
                src={originalUrl}
                alt="Original"
                className="max-h-[500px] w-auto max-w-full rounded object-contain shadow-lg"
              />
            )}

            {activeViewTab === 'side_by_side' && (
              <div className="grid grid-cols-2 gap-4 w-full">
                <div className="text-center">
                  <span className="text-xs font-bold text-slate-300 uppercase mb-2 block">Original Image</span>
                  {originalUrl && (
                    <img
                      src={originalUrl}
                      alt="Original"
                      className="max-h-[440px] w-full rounded object-contain bg-slate-950"
                    />
                  )}
                </div>
                <div className="text-center">
                  <span className="text-xs font-bold text-slate-300 uppercase mb-2 block">Modified Canvas</span>
                  <img
                    src={artifactBlobUrls['modified_image'] ?? `${API_URL}${analysisResult.artifacts['modified_image']}`}
                    alt="Modified Canvas"
                    className="max-h-[440px] w-full rounded object-contain bg-slate-950"
                  />
                </div>
              </div>
            )}

            {activeViewTab === 'copy_move_overlay' && analysisResult.artifacts['copy_move.overlay'] && (
              <div className="text-center">
                <img
                  src={
                    artifactBlobUrls['copy_move.overlay'] ??
                    `${API_URL}${analysisResult.artifacts['copy_move.overlay']}`
                  }
                  alt="Copy-Move Keypoint Matches"
                  className="max-h-[500px] w-auto max-w-full rounded object-contain shadow-lg"
                />
                <p className="mt-2 text-xs text-slate-400">
                  Yellow circles: ORB keypoints. Cyan lines: Geometrically verified match pairs. Red boxes: Candidate clusters.
                </p>
              </div>
            )}

            {activeViewTab === 'splicing_overlay' && analysisResult.artifacts['splicing.overlay'] && (
              <div className="text-center">
                <img
                  src={
                    artifactBlobUrls['splicing.overlay'] ??
                    `${API_URL}${analysisResult.artifacts['splicing.overlay']}`
                  }
                  alt="Splicing Error Heatmap"
                  className="max-h-[500px] w-auto max-w-full rounded object-contain shadow-lg"
                />
                <p className="mt-2 text-xs text-slate-400">
                  Color gradient represents JPEG Error Level Analysis (ELA) and high-frequency noise residual discrepancies.
                </p>
              </div>
            )}

            {activeViewTab === 'ground_truth' && analysisResult.artifacts['ground_truth_mask'] && (
              <div className="text-center">
                <img
                  src={
                    artifactBlobUrls['ground_truth_mask'] ??
                    `${API_URL}${analysisResult.artifacts['ground_truth_mask']}`
                  }
                  alt="Ground-Truth Mask"
                  className="max-h-[500px] w-auto max-w-full rounded object-contain shadow-lg border border-slate-700"
                />
                <p className="mt-2 text-xs text-slate-400">
                  White pixels: Manually drawn scratches or pasted copy-move destination clone regions.
                </p>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Forensic Notice & Scientific Honesty */}
      <footer className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900 space-y-1.5">
        <div className="flex items-center gap-2 font-bold text-amber-950">
          <AlertTriangle size={15} className="text-amber-700" /> Forensic &amp; Scientific Methodology Notice
        </div>
        <ul className="list-disc space-y-1 pl-5 text-amber-800">
          <li>
            <strong>Candidate regions vs. proof:</strong> Detected clusters are candidate regions for expert review, not conclusive proof of forgery.
          </li>
          <li>
            <strong>Natural false alarms:</strong> Highly repetitive textures (e.g. brick patterns, foliage, windows) can produce keypoint matches even on unedited images.
          </li>
          <li>
            <strong>Watermark resilience:</strong> Invisible watermarking failure does not prove forgery; it may indicate lossy compression, geometric warping, or heavy drawing occlusion.
          </li>
          <li>
            <strong>Ground-truth isolation:</strong> The user's editing mask is only used after detection has finished to compute objective verification metrics (TP, FP, FN, IoU).
          </li>
        </ul>
      </footer>
    </div>
  )
}
