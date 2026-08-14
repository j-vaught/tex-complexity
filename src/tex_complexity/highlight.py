"""Render per-sentence complexity as a highlighted PDF via Typst.

Each sentence of the document prose is typeset with a background color on a
light-green -> light-red scale according to its score on one metric, with the
raw value shown as a small superscript. One PDF per requested metric.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .metrics import METRICS, SentenceStats

# Light green -> light yellow -> light red.
_GREEN = (226, 240, 217)
_YELLOW = (255, 242, 204)
_RED = (244, 199, 195)

_TYPST_ESCAPES = str.maketrans({c: f"\\{c}" for c in "\\#$*_`[]<>@"})


def _color(t: float) -> str:
    t = min(max(t, 0.0), 1.0)
    if t < 0.5:
        a, b, u = _GREEN, _YELLOW, t * 2
    else:
        a, b, u = _YELLOW, _RED, (t - 0.5) * 2
    rgb = tuple(round(x + (y - x) * u) for x, y in zip(a, b))
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _esc(s: str) -> str:
    return s.translate(_TYPST_ESCAPES)


def _legend(lo: float, hi: float, fmt: str) -> str:
    stops = []
    for i in range(5):
        t = i / 4
        val = lo + (hi - lo) * t
        stops.append(f'#highlight(fill: rgb("{_color(t)}"))[ {format(val, fmt)} ]')
    return "  ".join(stops)


_WORD_THRESHOLD = 0.25


def _word_color(w: float) -> str:
    # Yellow -> red; plain words get no highlight at all.
    return _color(0.5 + min(w, 1.0) / 2)


def _word_run(group: list[SentenceStats]) -> str:
    body = []
    for s in group:
        for token, w in s.word_scores:
            text, ws = token.rstrip(), token[len(token.rstrip()) :]
            if w >= _WORD_THRESHOLD and text:
                body.append(
                    f'#highlight(fill: rgb("{_word_color(w)}"), top-edge: 0.9em, '
                    f"bottom-edge: -0.25em)[{_esc(text)}]{_esc(ws)}"
                )
            else:
                body.append(_esc(token))
        body.append(" ")
    return "".join(body)


def _sentence_run(group: list[SentenceStats], score_fn, lo: float, hi: float, fmt: str) -> str:
    body = []
    for s in group:
        val = score_fn(s)
        t = (val - lo) / (hi - lo) if hi > lo else 0.0
        body.append(
            f'#highlight(fill: rgb("{_color(t)}"), top-edge: 0.9em, bottom-edge: -0.25em)'
            f"[{_esc(s.text)}#text(size: 6pt, fill: luma(90))[ ({format(val, fmt)})]] "
        )
    return "".join(body)


def render_metric_pdf(
    stats: list[SentenceStats],
    seg_titles: list[tuple[int, str]],
    metric_key: str,
    source_name: str,
    out_pdf: Path,
) -> None:
    title, describe, score_fn, lo, hi, fmt = METRICS[metric_key]
    per_word = metric_key == "word"
    if per_word:
        describe = (
            "Each word is highlighted by how rare it is in general English "
            "(Zipf corpus frequency). Common words are left plain; unknown "
            "words, acronyms, and coined terms score highest."
        )
        legend = (
            "plain = common  "
            + f'#highlight(fill: rgb("{_word_color(0.3)}"))[ uncommon ]  '
            + f'#highlight(fill: rgb("{_word_color(0.6)}"))[ rare ]  '
            + f'#highlight(fill: rgb("{_word_color(1.0)}"))[ very rare / unknown ]'
        )
    else:
        legend = _legend(lo, hi, fmt)
    lines = [
        "#set page(margin: 2cm)",
        '#set text(size: 10pt, font: "New Computer Modern")',
        "#set par(justify: true, leading: 0.75em)",
        f"= {_esc(source_name)} — {title}",
        f"#text(size: 9pt, fill: luma(80))[{_esc(describe)}]",
        "",
        f"Scale ({title.lower()}): {legend}",
        "#v(0.8em)",
        "#line(length: 100%, stroke: 0.5pt + luma(160))",
        "#v(0.8em)",
    ]
    any_content = False
    for si, (level, seg_title) in enumerate(seg_titles):
        group = [s for s in stats if s.seg == si]
        if not group and not seg_title:
            continue
        if seg_title:
            if level <= 1:
                if any_content:
                    lines.append("#pagebreak()")
                lines.append(f"#heading(level: 2, outlined: false)[{_esc(seg_title)}]")
            else:
                size = "11pt" if level == 2 else "10pt"
                lines.append("")
                lines.append(f'#text(size: {size}, weight: "bold")[{_esc(seg_title)}]')
        lines.append("")
        if group:
            if per_word:
                lines.append(_word_run(group))
            else:
                lines.append(_sentence_run(group, score_fn, lo, hi, fmt))
            any_content = True
    with tempfile.NamedTemporaryFile("w", suffix=".typ", delete=False) as f:
        f.write("\n".join(lines))
        typ_path = Path(f.name)
    try:
        subprocess.run(
            ["typst", "compile", str(typ_path), str(out_pdf)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"typst compile failed for {out_pdf.name}:\n{e.stderr}") from e
    finally:
        typ_path.unlink(missing_ok=True)
