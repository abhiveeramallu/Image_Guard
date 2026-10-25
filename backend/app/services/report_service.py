"""Downloadable JSON and HTML reports built from a real detection response."""
import base64
import html
import json
from datetime import datetime, timezone

DISCLAIMER = (
    "This report describes the output of a single copy-move heuristic (ORB + Hamming matching + RANSAC). "
    "Candidate regions are not proof of manipulation, and the absence of candidates is not proof of authenticity."
)


def build_report(result: dict, filename: str | None) -> dict:
    return {
        "report_generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uploaded_filename": filename,
        "disclaimer": DISCLAIMER,
        **result,
    }


def report_json_bytes(report: dict) -> bytes:
    return json.dumps(report, indent=2).encode()


def report_html_bytes(report: dict, images: dict[str, bytes]) -> bytes:
    e = html.escape

    def img(name: str, caption: str) -> str:
        if name not in images:
            return ""
        b64 = base64.b64encode(images[name]).decode()
        return f'<figure><img alt="{e(caption)}" src="data:image/png;base64,{b64}"><figcaption>{e(caption)}</figcaption></figure>'

    rows = "".join(
        f"<tr><td>{r['id']}</td><td>{r['matches']}</td><td>{r['mean_hamming_distance']}</td>"
        f"<td>{_box(r['region_a']['bbox'])}</td><td>{_box(r['region_b']['bbox'])}</td>"
        f"<td>dx {r['transform']['translation_x']:.1f}, dy {r['transform']['translation_y']:.1f}, "
        f"rot {r['transform']['rotation_degrees']:.1f}&deg;, scale {r['transform']['scale']:.2f}</td></tr>"
        for r in report["regions"]
    ) or '<tr><td colspan="6">None</td></tr>'
    settings = "".join(f"<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>" for k, v in report["settings"].items())
    limits = "".join(f"<li>{e(x)}</li>" for x in report["limitations"])
    warns = "".join(f"<li>{e(x)}</li>" for x in report["warnings"])
    dims = report["image"]
    doc = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>ImageGuard report</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#16202e}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}td,th{{border:1px solid #cfd8e3;padding:.35rem .6rem;text-align:left}}
img{{max-width:100%}}figure{{margin:1rem 0}}.note{{background:#fff7e0;border:1px solid #e8c766;padding:.75rem 1rem;border-radius:6px}}</style>
<h1>ImageGuard copy-move report</h1>
<p class="note">{e(report['disclaimer'])}</p>
<p><b>Analysis ID:</b> {e(report['analysis_id'])}<br><b>Generated:</b> {e(report['report_generated_at'])}<br>
<b>File:</b> {e(report['uploaded_filename'] or 'n/a')}<br><b>Dimensions:</b> {dims['width']}&times;{dims['height']} px<br>
<b>Method:</b> {e(report['method']['name'])} v{e(report['method']['version'])}<br><b>Processing time:</b> {report['processing_ms']} ms</p>
<h2>Result</h2><p><b>{e(report['status'])}</b> &mdash; {e(report['status_reason'])}</p>
<h2>Statistics</h2><table><tr><td>ORB keypoints</td><td>{report['keypoints']}</td></tr>
<tr><td>Matches before filtering</td><td>{report['matches_before_filtering']}</td></tr>
<tr><td>After descriptor filtering</td><td>{report['matches_after_descriptor_filtering']}</td></tr>
<tr><td>Retained after geometric clustering</td><td>{report['matches_retained']}</td></tr></table>
<h2>Candidate regions</h2><table><tr><th>#</th><th>Matches</th><th>Mean Hamming</th><th>Region A (x,y,w,h)</th><th>Region B (x,y,w,h)</th><th>Transform A&rarr;B</th></tr>{rows}</table>
<h2>Artifacts</h2>{img('annotated','Annotated image')}{img('mask','Candidate mask')}{img('heatmap','Match-density overlay (not a probability map)')}
<h2>Settings</h2><table>{settings}</table>
<h2>Warnings</h2><ul>{warns or '<li>None</li>'}</ul>
<h2>Limitations</h2><ul>{limits}</ul></html>"""
    return doc.encode()


def _box(b: dict) -> str:
    return f"{b['x']}, {b['y']}, {b['width']}, {b['height']}"


def build_analysis_report(result: dict, filename: str | None) -> dict:
    return {"report_generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "uploaded_filename": filename,
            "disclaimer": ("Each method below is independent. Detector output is evidence for human review, not proof of manipulation, "
                           "and the absence of findings is not proof of authenticity. Heuristic and model scores are not combined."),
            **result}
