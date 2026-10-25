import { Link } from 'react-router-dom'
import { ArrowRight, FileImage, ScanSearch, Stamp, TriangleAlert } from 'lucide-react'

export default function Dashboard() {
  return (
    <div className="space-y-8">
      <header className="rounded-2xl bg-ink-900 px-6 py-8 text-white sm:px-10 sm:py-10">
        <h1 className="text-3xl font-bold">ImageGuard</h1>
        <p className="mt-2 max-w-2xl text-slate-300">
          Image forgery detection and watermarking. Flag possible copy-move duplication with explainable feature matching,
          or add a visible text or logo watermark to an image.
        </p>
      </header>

      <div className="grid gap-5 md:grid-cols-2">
        <Card to="/detect" Icon={ScanSearch} title="Detect Forgery" cta="Analyse an image"
          text="Upload an image and search it for duplicated regions (copy-move). Get an annotated image, candidate mask, match-density overlay, region coordinates, match statistics and a downloadable report." />
        <Card to="/watermark" Icon={Stamp} title="Watermark Image" cta="Open Watermark Studio"
          text="Place a text or logo watermark with control over position, opacity, size, colour, rotation, margins and tiling. Compare with the original and download as PNG or JPEG." />
      </div>

      <section className="card p-5">
        <h2 className="flex items-center gap-2 font-semibold text-slate-800"><FileImage size={18} className="text-accent-600" aria-hidden /> Supported files</h2>
        <p className="mt-1 text-sm text-slate-600">JPEG and PNG (including transparent PNG). Up to 10 MB and 16 megapixels per image. Uploads are processed in memory and are not stored permanently.</p>
      </section>

      <section className="card border-amber-200 p-5">
        <h2 className="flex items-center gap-2 font-semibold text-slate-800"><TriangleAlert size={18} className="text-amber-600" aria-hidden /> Methodology &amp; limitations</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>Detection uses ORB keypoints, Hamming-distance matching with a ratio test, and RANSAC to group consistent matches. It reports <em>candidates</em> for human review.</li>
          <li>It covers copy-move only. It does not detect splicing from other images, retouching, or AI-generated edits.</li>
          <li>Smooth areas, heavy resizing or compression, and repeated natural patterns can cause misses or false alarms.</li>
          <li>“No candidate regions” is not evidence that an image is authentic. A visible watermark does not prove authenticity either.</li>
        </ul>
        <Link to="/how-it-works" className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-accent-700 hover:underline">
          Read how it works <ArrowRight size={14} aria-hidden />
        </Link>
      </section>
    </div>
  )
}

function Card({ to, Icon, title, text, cta }: { to: string; Icon: typeof ScanSearch; title: string; text: string; cta: string }) {
  return (
    <Link to={to} className="card group flex flex-col gap-3 p-6 transition hover:border-accent-500 hover:shadow-md">
      <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-ink-900 text-accent-400"><Icon size={22} aria-hidden /></span>
      <h2 className="text-lg font-semibold text-ink-900">{title}</h2>
      <p className="flex-1 text-sm text-slate-600">{text}</p>
      <span className="inline-flex items-center gap-1 text-sm font-semibold text-accent-700">{cta} <ArrowRight size={16} className="transition group-hover:translate-x-0.5" aria-hidden /></span>
    </Link>
  )
}
