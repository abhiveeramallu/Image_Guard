const COPY_MOVE_STEPS = [
  ['Grayscale analysis copy', 'The image is converted to grayscale and, if large, downscaled. The scale is tracked so results map back to original pixels.'],
  ['ORB features', 'ORB finds up to a few thousand corner-like keypoints, each with a 256-bit binary descriptor.'],
  ['Self-matching', 'Each descriptor is compared with all others by Hamming distance. A keypoint\'s own location and nearby neighbours are excluded, so only distant look-alikes count.'],
  ['Filtering', 'A ratio test keeps matches whose best candidate is clearly better than the second best, an absolute distance cap removes weak ones, and symmetric duplicates are merged.'],
  ['Geometric consistency', 'Sequential RANSAC fits a similarity transform (shift, rotation, uniform scale). Matches that agree on one transform form a cluster; isolated matches are discarded.'],
  ['Localization', 'Each cluster\'s matched keypoints on both sides are wrapped in a padded convex hull, giving an approximate region A and region B.'],
]

const DISTINCTIONS = [
  ['Copy-move detection', 'Finds regions duplicated within the same image. This is what ImageGuard implements.'],
  ['Image splicing detection', 'Finds content pasted in from a different image. Needs other cues (noise, lighting, compression inconsistencies). Not implemented.'],
  ['Pixel-level tampering localization', 'Labels exactly which pixels were altered, usually with a trained segmentation model. Not implemented; ImageGuard’s regions are approximate hulls.'],
  ['Visible watermarking', 'Overlays text or a logo on the image. Implemented in Watermark Studio. It discourages reuse but can be cropped or edited out.'],
  ['Invisible watermarking', 'Embeds a hidden signal for later extraction. Not implemented.'],
]

export default function HowItWorksPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-ink-900">How It Works</h1>
        <p className="mt-1 text-sm text-slate-600">A transparent baseline. Every number shown in the app comes from the processing run itself.</p>
      </header>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-800">Copy-move detection pipeline</h2>
        <ol className="mt-3 space-y-3">
          {COPY_MOVE_STEPS.map(([t, d], i) => (
            <li key={t} className="flex gap-3 text-sm">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-900 text-xs font-semibold text-accent-400">{i + 1}</span>
              <div><b className="text-slate-800">{t}.</b> <span className="text-slate-600">{d}</span></div>
            </li>
          ))}
        </ol>
      </section>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-800">Reading the result</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li><b>Candidate regions detected:</b> at least one cluster of consistent matches passed the evidence thresholds. Review it visually; natural repetition can look the same.</li>
          <li><b>No candidate regions detected:</b> this method found nothing. The image may still be edited in ways it cannot see.</li>
          <li><b>Inconclusive:</b> too little texture, or so many repeated structures that duplication cannot be separated from natural patterns.</li>
          <li>Match counts are evidence volume, not a probability of forgery. The app produces no confidence score.</li>
          <li>The heatmap shows where retained match keypoints concentrate; it is not a tampering-probability map.</li>
        </ul>
      </section>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-800">Watermarking</h2>
        <p className="mt-2 text-sm text-slate-600">
          Text or a logo is rendered into a transparent RGBA layer, its opacity is applied to the alpha channel only, it is rotated,
          then alpha-composited onto the image at one position or tiled across it and clipped to the image bounds. Output keeps the original dimensions.
        </p>
      </section>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-800">Related techniques</h2>
        <dl className="mt-2 space-y-2 text-sm">
          {DISTINCTIONS.map(([t, d]) => <div key={t}><dt className="font-semibold text-slate-800">{t}</dt><dd className="text-slate-600">{d}</dd></div>)}
        </dl>
      </section>
    </div>
  )
}
