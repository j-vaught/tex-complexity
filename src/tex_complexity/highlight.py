"""Render per-sentence complexity as a highlighted PDF via Typst.

Each sentence of the document prose is typeset with a background color on a
white-to-garnet scale according to its score on one metric, with the raw value
shown as a small superscript. One PDF per requested metric.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .metrics import METRICS, SentenceStats

# High-contrast institutional palette, from least to most complex.
_SCALE = (
    (255, 255, 255),  # White.
    (236, 236, 236),  # 10% Black.
    (255, 242, 227),  # Sandstorm.
    (204, 46, 64),  # Rose.
    (115, 0, 10),  # Garnet.
)
_BLACK = "#000000"
_WHITE = "#ffffff"

_TYPST_ESCAPES = str.maketrans({c: f"\\{c}" for c in "\\#$*_`[]<>@-+=/"})


class RenderError(RuntimeError):
    """Raised when Typst cannot render a highlighted document."""


def _color(t: float) -> str:
    t = min(max(t, 0.0), 1.0)
    rgb = _SCALE[min(int(t * len(_SCALE)), len(_SCALE) - 1)]
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _ink(t: float) -> str:
    """Choose readable text for the quantized background color."""
    index = min(int(min(max(t, 0.0), 1.0) * len(_SCALE)), len(_SCALE) - 1)
    return _WHITE if index >= 3 else _BLACK


def _esc(s: str) -> str:
    return s.translate(_TYPST_ESCAPES)


def _legend(lo: float, hi: float, fmt: str) -> str:
    stops = []
    for i in range(5):
        t = i / 4
        val = lo + (hi - lo) * t
        stops.append(
            f'#highlight(fill: rgb("{_color(t)}"))'
            f'[#text(fill: rgb("{_ink(t)}"))[ {format(val, fmt)} ]]'
        )
    return "  ".join(stops)


_WORD_THRESHOLD = 0.25


def _word_color(w: float) -> str:
    if w < 0.5:
        return _color(0.5)
    if w < 0.8:
        return _color(0.75)
    return _color(1.0)


def _word_ink(w: float) -> str:
    if w < 0.5:
        return _ink(0.5)
    if w < 0.8:
        return _ink(0.75)
    return _ink(1.0)


def _word_run(group: list[SentenceStats]) -> str:
    body = []
    for s in group:
        if not s.word_scores:
            body.append(f"{_esc(s.text)} ")
            continue
        for token, w in s.word_scores:
            text, ws = token.rstrip(), token[len(token.rstrip()) :]
            if w >= _WORD_THRESHOLD and text:
                body.append(
                    f'#highlight(fill: rgb("{_word_color(w)}"), top-edge: 0.9em, '
                    f'bottom-edge: -0.25em)[#text(fill: rgb("{_word_ink(w)}"))'
                    f"[{_esc(text)}]]{_esc(ws)}"
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
        ink = _ink(t)
        body.append(
            f'#highlight(fill: rgb("{_color(t)}"), top-edge: 0.9em, bottom-edge: -0.25em)'
            f'[#text(fill: rgb("{ink}"))'
            f"[{_esc(s.text)}#text(size: 6pt)[ ({format(val, fmt)})]]] "
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
            "Words are highlighted when they are polysyllabic (3+ syllables) "
            "or rare in general English (Zipf frequency below 3.5). Intensity "
            "increases with syllable count and rarity."
        )
        legend = (
            "plain = simple  "
            + f'#highlight(fill: rgb("{_word_color(0.3)}"))'
            + f'[#text(fill: rgb("{_word_ink(0.3)}"))[ moderately complex ]]  '
            + f'#highlight(fill: rgb("{_word_color(0.6)}"))'
            + f'[#text(fill: rgb("{_word_ink(0.6)}"))[ complex ]]  '
            + f'#highlight(fill: rgb("{_word_color(1.0)}"))'
            + f'[#text(fill: rgb("{_word_ink(1.0)}"))[ very complex ]]'
        )
    else:
        legend = _legend(lo, hi, fmt)
    if not seg_titles:
        seg_titles = [(0, "")]
    if any(stat.seg < 0 or stat.seg >= len(seg_titles) for stat in stats):
        raise RenderError("sentence section index is outside the supplied section list")
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
    with tempfile.NamedTemporaryFile("w", suffix=".typ", delete=False, encoding="utf-8") as f:
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
        raise RenderError(f"typst compile failed for {out_pdf.name}:\n{e.stderr}") from e
    except FileNotFoundError as exc:
        raise RenderError("the 'typst' executable was not found") from exc
    finally:
        typ_path.unlink(missing_ok=True)
