"""Writing-complexity statistics for LaTeX documents.

Usage: texstats paper.tex [--top N] [--all]

Reports five families of metrics over the document prose (LaTeX markup stripped):

  1. Sentence complexity   - length distribution, readability grades
  2. Word complexity       - syllable load, polysyllabic and rare-word ratios
  3. Subject-verb distance - tokens separating a subject from its governing verb
  4. Nesting               - subordinate-clause counts and parse-tree depth
  5. Referential load      - sentences that lean on prior context: bare
                             demonstratives, anaphoric phrases, vague definite
                             NPs ("the main target metric of this paper"), and
                             referents whose antecedent is many sentences back
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

from pylatexenc.latex2text import LatexNodes2Text
from textstat import textstat
from wordfreq import zipf_frequency

from .coref import coref_distance_hits
from .metrics import METRICS, SentenceStats

SUBORDINATE_DEPS = {"advcl", "ccomp", "xcomp", "acl", "relcl", "csubj", "csubjpass"}
SUBJECT_DEPS = {"nsubj", "nsubjpass", "csubj", "csubjpass"}

# Words/phrases whose meaning depends on remembering something stated earlier.
ANAPHORIC_PHRASES = [
    "the former",
    "the latter",
    "aforementioned",
    "as mentioned above",
    "as noted above",
    "as described above",
    "as discussed above",
    "as shown above",
    "the above",
    "the preceding",
    "the previous",
    "said method",
    "respectively",
    "in this way",
    "this approach",
    "this method",
    "this result",
    "these results",
    "such a",
    "such an",
]
BARE_DEMONSTRATIVES = {"this", "that", "these", "those", "it"}

# Abstract "shell" nouns: they name a category, not a thing. A definite NP
# headed by one of these ("the main target metric", "this paper's object of
# interest") points AT a referent without naming it, so the reader must go
# recover what it actually is.
SHELL_NOUNS = {
    "approach",
    "method",
    "methodology",
    "technique",
    "procedure",
    "framework",
    "model",
    "system",
    "algorithm",
    "scheme",
    "strategy",
    "mechanism",
    "process",
    "formulation",
    "implementation",
    "pipeline",
    "metric",
    "measure",
    "criterion",
    "quantity",
    "value",
    "score",
    "statistic",
    "accuracy",
    "performance",
    "quality",
    "efficiency",
    "effectiveness",
    "robustness",
    "objective",
    "goal",
    "target",
    "aim",
    "purpose",
    "object",
    "subject",
    "focus",
    "interest",
    "topic",
    "matter",
    "question",
    "issue",
    "problem",
    "challenge",
    "aspect",
    "factor",
    "feature",
    "property",
    "characteristic",
    "attribute",
    "notion",
    "concept",
    "idea",
    "term",
    "definition",
    "assumption",
    "hypothesis",
    "claim",
    "argument",
    "point",
    "observation",
    "finding",
    "result",
    "outcome",
    "consequence",
    "implication",
    "phenomenon",
    "effect",
    "behavior",
    "task",
    "setting",
    "scenario",
    "case",
    "situation",
    "condition",
    "context",
    "contribution",
    "limitation",
    "advantage",
    "drawback",
    "tradeoff",
    "component",
    "element",
    "entity",
    "item",
    "part",
    "portion",
    "aspect",
    "way",
    "manner",
    "fashion",
    "respect",
    "regard",
    "sense",
}

# Deictic self-references ("this paper", "our work") never identify a concrete
# referent, so they cannot anchor a vague NP.
PAPER_NOUNS = {
    "paper",
    "work",
    "study",
    "article",
    "manuscript",
    "thesis",
    "dissertation",
    "section",
    "chapter",
}

DEFINITE_DETS = {"the", "this", "that", "these", "those"}

# Verbs of naming: an NP governed by one of these is being INTRODUCED, not
# referred back to ("we define tracking error as our evaluation criterion").
NAMING_VERBS = {"define", "call", "denote", "term", "name", "refer", "introduce", "designate"}
RECENT_SENTS = 3  # referent mentioned within this many sentences = still in working memory
DISTANT_SENTS = 5  # referent last mentioned further back than this = reader must flip back

RARE_ZIPF_THRESHOLD = 3.5  # zipf < 3.5 ~ rarer than ~1 per 3M words


def inline_inputs(source: str, base_dir: Path, depth: int = 0) -> str:
    """Recursively expand \\input{...} and \\include{...} relative to base_dir."""
    if depth > 5:
        return source

    def repl(m: re.Match) -> str:
        rel = m.group(2)
        path = base_dir / rel
        if path.suffix == "":
            path = path.with_suffix(".tex")
        if not path.is_file():
            return " "
        return inline_inputs(
            path.read_text(encoding="utf-8", errors="replace"), base_dir, depth + 1
        )

    return re.sub(r"\\(input|include)\{([^}]+)\}", repl, source)


def load_aux(aux_path: Path) -> tuple[dict[str, int], dict[str, str]]:
    """Citation numbers and label values from a LaTeX .aux file."""
    cites: dict[str, int] = {}
    labels: dict[str, str] = {}
    if not aux_path.is_file():
        return cites, labels
    aux = aux_path.read_text(encoding="utf-8", errors="replace")
    for key, num in re.findall(r"\\bibcite\{([^}]*)\}\{(\d+)\}", aux):
        cites[key] = int(num)
    for key, val in re.findall(r"\\newlabel\{([^}]*)\}\{\{(.*?)\}\{", aux):
        labels[key] = re.sub(r"\\mbox\s*|\{|\}", "", val).strip()
    return cites, labels


def _fmt_citation(nums: list[int]) -> str:
    nums = sorted(set(nums))
    parts: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{nums[i]}-{nums[j]}")
        else:
            parts.extend(str(n) for n in nums[i : j + 1])
        i = j + 1
    return "[" + ", ".join(parts) + "]"


def resolve_refs(source: str, cites: dict[str, int], labels: dict[str, str]) -> str:
    """Replace \\cite and \\ref-family commands with their rendered text.

    Citations become IEEE-style bracketed numbers ([3], [1-3]); cross
    references become the label's number from the .aux ("II-C", "4").
    Unresolvable keys fall back to sequential numbering (cites) or "?".
    """
    fallback: dict[str, int] = {}

    def cite_num(key: str) -> int:
        key = key.strip()
        if key in cites:
            return cites[key]
        if key not in fallback:
            fallback[key] = len(cites) + len(fallback) + 1
        return fallback[key]

    def cite_repl(m: re.Match) -> str:
        return _fmt_citation([cite_num(k) for k in m.group(1).split(",")])

    def ref_repl(m: re.Match) -> str:
        val = labels.get(m.group(2).strip(), "?")
        return f"({val})" if m.group(1) == "eqref" else val

    source = re.sub(r"\\cite[tp]?\*?(?:\[[^\]]*\])?\{([^}]*)\}", cite_repl, source)
    source = re.sub(r"\\(ref|eqref|autoref|[cC]ref|pageref)\*?\{([^}]*)\}", ref_repl, source)
    return source


_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def split_sections(body: str) -> list[tuple[int, str, str]]:
    """Split document body into (level, numbered title, body) segments.

    Level 1 = section, 2 = subsection, 3 = subsubsection, numbered in
    IEEE style (I / A / 1). Prose before the first section (the abstract)
    becomes a level-0 leading segment.
    """
    pat = re.compile(r"\\(section|subsection|subsubsection)\*?\{((?:[^{}]|\{[^{}]*\})*)\}")
    matches = list(pat.finditer(body))
    segments: list[tuple[int, str, str]] = [
        (0, "", body[: matches[0].start() if matches else None])
    ]
    n_sec = n_sub = n_subsub = 0
    for m, nxt in zip(matches, matches[1:] + [None]):
        kind, title = m.group(1), m.group(2)
        end = nxt.start() if nxt else len(body)
        if kind == "section":
            n_sec, n_sub, n_subsub = n_sec + 1, 0, 0
            level, num = 1, _ROMAN[min(n_sec - 1, len(_ROMAN) - 1)]
            display = f"{num}. {title}"
        elif kind == "subsection":
            n_sub, n_subsub = n_sub + 1, 0
            level, display = 2, f"{chr(64 + n_sub)}. {title}"
        else:
            n_subsub += 1
            level, display = 3, f"{n_subsub}) {title}"
        segments.append((level, display, body[m.end() : end]))
    return segments


def document_body(source: str) -> tuple[str, str]:
    """Return (abstract, body) with preamble, title block, and keywords removed."""
    m = re.search(r"\\begin\{document\}(.*?)(?:\\end\{document\}|$)", source, flags=re.DOTALL)
    body = m.group(1) if m else source
    abstract = ""
    am = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", body, flags=re.DOTALL)
    if am:
        abstract = am.group(1)
        # Everything before the abstract is title-block material (title,
        # authors, teaser figures) — not document prose.
        body = body[am.end() :]
    body = re.sub(r"\\begin\{IEEEkeywords\}.*?\\end\{IEEEkeywords\}", " ", body, flags=re.DOTALL)
    body = re.sub(r"\\IEEEPARstart\{([^}]*)\}\{([^}]*)\}", r"\1\2", body)
    body = re.sub(r"\\maketitle|\\IEEEpeerreviewmaketitle", " ", body)
    return abstract, body


def strip_latex(source: str) -> str:
    """Convert LaTeX source to plain prose, dropping math and float bodies."""
    # Remove environments whose content is not prose.
    for env in (
        "equation",
        "align",
        "gather",
        "figure",
        "table",
        "tabular",
        "algorithm",
        "algorithmic",
        "lstlisting",
        "verbatim",
        "tikzpicture",
    ):
        source = re.sub(
            rf"\\begin\{{{env}\*?\}}.*?\\end\{{{env}\*?\}}", " ", source, flags=re.DOTALL
        )
    text = LatexNodes2Text(math_mode="remove").latex_to_text(source)
    # Drop heading lines (pylatexenc renders \section{...} as "§ TITLE").
    text = re.sub(r"^\s*§+.*$", " ", text, flags=re.MULTILINE)
    # Collapse whitespace and drop leftover bracket junk.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def vague_definite_hits(
    sent, sent_idx: int, last_seen: dict[str, int], flag_distant: bool = True
) -> tuple[list[str], int]:
    """Flag definite NPs the reader cannot resolve from the sentence itself.

    A definite noun phrase headed by a shell noun is checked for a concrete
    anchor anywhere in its subtree (including attached of-phrases): a proper
    noun, a number, or a specific noun the document introduced recently.
    "the accuracy of BERT" is anchored; "the main target metric of this paper"
    is not — nothing inside it names the referent.
    """
    hits: list[str] = []
    score = 0
    seen_roots: set[int] = set()
    for chunk in sent.noun_chunks:
        head = chunk.root
        if head.i in seen_roots or head.pos_ != "NOUN":
            continue
        definite = any(
            (t.dep_ == "det" and t.lower_ in DEFINITE_DETS) or t.dep_ == "poss"
            for t in head.children
        )
        if not definite or head.lemma_.lower() not in SHELL_NOUNS:
            continue
        # Skip superlative NPs ("the best tracking performance"): evaluative,
        # not a reference back to an earlier entity.
        if any(c.tag_ in ("JJS", "RBS") for c in head.children):
            continue
        # Skip NPs governed by a naming verb: they introduce the term.
        gov = head
        while gov.dep_ in ("pobj", "prep", "attr", "oprd", "dobj") and gov.head is not gov:
            gov = gov.head
        if gov.lemma_.lower() in NAMING_VERBS:
            continue
        seen_roots.add(head.i)
        subtree = [t for t in head.subtree if t.sent == sent]
        seen_roots.update(t.i for t in subtree)

        anchored_now = any(t.pos_ == "PROPN" or t.like_num for t in subtree)
        phrase = " ".join(t.text for t in subtree)
        if anchored_now:
            continue
        # Concrete nouns inside the NP, or the head noun itself, mentioned
        # recently enough to still be in the reader's working memory?
        candidates = [
            t.lemma_.lower()
            for t in subtree
            if t.pos_ == "NOUN" and t.lemma_.lower() not in PAPER_NOUNS
        ]
        ages = [sent_idx - last_seen[c] for c in candidates if c in last_seen]
        if not ages:
            hits.append(f"vague reference '{clip(phrase, 40)}'")
            score += 2
        elif min(ages) <= RECENT_SENTS or not flag_distant:
            # When coreference resolution is active it scores antecedent
            # distance itself; only unresolvable vagueness is flagged here.
            continue
        else:
            age = min(ages)
            hits.append(f"distant referent '{clip(phrase, 40)}' ({age} sents back)")
            score += 1 if age <= DISTANT_SENTS else 2
    return hits, score


def analyze_sentence(
    sent,
    sent_idx: int = 0,
    last_seen: dict[str, int] | None = None,
    count_pronouns: bool = True,
) -> SentenceStats:
    words = [t for t in sent if t.is_alpha]
    n_words = len(words)

    n_poly = sum(1 for t in words if textstat.syllable_count(t.text) >= 3)
    n_rare = sum(
        1
        for t in words
        if not t.is_stop
        and len(t.text) > 3
        and zipf_frequency(t.lemma_.lower(), "en") < RARE_ZIPF_THRESHOLD
    )

    word_scores: list[tuple[str, float]] = []
    for t in sent:
        w = 0.0
        if t.is_alpha and not t.is_stop and len(t.text) > 2:
            zipf = zipf_frequency(t.lemma_.lower(), "en")
            # zipf 4 (common) -> 0; zipf 1.5 or unknown-to-the-corpus -> 1.
            w = min(1.0, max(0.0, (4.0 - zipf) / 2.5))
        word_scores.append((t.text_with_ws, w))

    max_sv = 0
    for tok in sent:
        if tok.dep_ in SUBJECT_DEPS and tok.head.pos_ in ("VERB", "AUX"):
            max_sv = max(max_sv, abs(tok.head.i - tok.i) - 1)

    n_sub = sum(1 for t in sent if t.dep_ in SUBORDINATE_DEPS)

    def depth(tok, d=0):
        kids = [c for c in tok.children if c.sent == sent]
        return d if not kids else max(depth(c, d + 1) for c in kids)

    tree_depth = depth(sent.root)

    hits: list[str] = []
    lowered = sent.text.lower()
    for phrase in ANAPHORIC_PHRASES:
        if phrase in lowered:
            hits.append(phrase)
    # Bare demonstrative: sentence opens with this/that/these/those/it NOT
    # followed by a noun ("This shows..." forces the reader to resolve the
    # referent; "This method shows..." does not).
    first = next((t for t in sent if t.is_alpha), None)
    if first is not None and first.lower_ in BARE_DEMONSTRATIVES:
        nxt = next((t for t in sent if t.i > first.i and t.is_alpha), None)
        if nxt is None or nxt.pos_ not in ("NOUN", "PROPN"):
            hits.append(f"bare '{first.text}'")
    # Mid-sentence pronoun density adds one point per third-person pronoun.
    # Skipped when coreference resolution runs: it charges pronouns by actual
    # antecedent distance instead of a blanket count.
    pron = 0
    if count_pronouns:
        pron = sum(
            1
            for t in sent
            if t.lower_ in ("it", "its", "they", "them", "their")
            and t.i != (first.i if first else -1)
        )
    score = len(hits) + pron
    if pron:
        hits.append(f"{pron} pronoun(s)")
    vague_hits, vague_score = vague_definite_hits(
        sent, sent_idx, last_seen or {}, flag_distant=count_pronouns
    )
    hits.extend(vague_hits)
    score += vague_score

    return SentenceStats(
        text=sent.text.strip(),
        n_words=n_words,
        n_polysyllables=n_poly,
        n_rare_words=n_rare,
        max_subj_verb_dist=max_sv,
        n_subordinate_clauses=n_sub,
        tree_depth=tree_depth,
        referential_score=score,
        referential_hits=hits,
        word_scores=word_scores,
    )


def fmt_row(label: str, value: str, note: str = "") -> str:
    return f"  {label:<38}{value:>10}   {note}"


def clip(s: str, n: int = 90) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."


def report(stats: list[SentenceStats], full_text: str, top: int, show_all: bool) -> str:
    out: list[str] = []
    sents = [s for s in stats if s.n_words >= 3]
    if not sents:
        return "No prose sentences found."
    lengths = [s.n_words for s in sents]

    out.append("=" * 78)
    out.append("SENTENCE COMPLEXITY")
    out.append("=" * 78)
    out.append(fmt_row("Sentences", str(len(sents))))
    out.append(
        fmt_row(
            "Mean length (words)",
            f"{statistics.mean(lengths):.1f}",
            "aim 15-22 for technical prose",
        )
    )
    out.append(fmt_row("Median / max length", f"{statistics.median(lengths):.0f} / {max(lengths)}"))
    out.append(
        fmt_row(
            "Std dev of length",
            f"{statistics.stdev(lengths):.1f}" if len(lengths) > 1 else "n/a",
            "low = monotone rhythm",
        )
    )
    out.append(
        fmt_row(
            "Sentences > 30 words",
            f"{sum(1 for n in lengths if n > 30)} ({100 * sum(1 for n in lengths if n > 30) / len(sents):.0f}%)",
        )
    )
    out.append(
        fmt_row(
            "Flesch reading ease",
            f"{textstat.flesch_reading_ease(full_text):.1f}",
            "30-50 typical for papers",
        )
    )
    out.append(fmt_row("Flesch-Kincaid grade", f"{textstat.flesch_kincaid_grade(full_text):.1f}"))
    out.append(fmt_row("Gunning fog index", f"{textstat.gunning_fog(full_text):.1f}"))
    out.append("")
    out.append(f"  Longest {top}:")
    for s in sorted(sents, key=lambda s: -s.n_words)[:top]:
        out.append(f"    [{s.n_words} w] {clip(s.text)}")

    out.append("")
    out.append("=" * 78)
    out.append("WORD COMPLEXITY")
    out.append("=" * 78)
    total_words = sum(lengths)
    poly = sum(s.n_polysyllables for s in sents)
    rare = sum(s.n_rare_words for s in sents)
    out.append(fmt_row("Words analyzed", str(total_words)))
    out.append(
        fmt_row(
            "Polysyllabic (3+ syl)",
            f"{poly} ({100 * poly / total_words:.1f}%)",
            "> 20% reads as dense",
        )
    )
    out.append(
        fmt_row(
            "Rare words (zipf < 3.5)",
            f"{rare} ({100 * rare / total_words:.1f}%)",
            "jargon / uncommon vocabulary",
        )
    )
    out.append(
        fmt_row("Avg syllables per word", f"{textstat.avg_syllables_per_word(full_text):.2f}")
    )

    out.append("")
    out.append("=" * 78)
    out.append("SUBJECT-VERB SEPARATION")
    out.append("=" * 78)
    sv = [s.max_subj_verb_dist for s in sents if s.max_subj_verb_dist > 0]
    if sv:
        out.append(
            fmt_row(
                "Mean separation (words)",
                f"{statistics.mean(sv):.1f}",
                "interruptions between subject and verb",
            )
        )
        out.append(
            fmt_row(
                "Sentences with gap >= 8",
                f"{sum(1 for d in sv if d >= 8)}",
                "reader holds subject in memory",
            )
        )
        out.append("")
        out.append(f"  Widest {top}:")
        for s in sorted(sents, key=lambda s: -s.max_subj_verb_dist)[:top]:
            out.append(f"    [{s.max_subj_verb_dist} w gap] {clip(s.text)}")

    out.append("")
    out.append("=" * 78)
    out.append("NESTING (SUBORDINATE CLAUSES / PARSE DEPTH)")
    out.append("=" * 78)
    out.append(
        fmt_row(
            "Mean clauses per sentence",
            f"{statistics.mean([s.n_subordinate_clauses for s in sents]):.2f}",
            "> 1.5 = heavily nested style",
        )
    )
    out.append(
        fmt_row(
            "Sentences with 3+ clauses", f"{sum(1 for s in sents if s.n_subordinate_clauses >= 3)}"
        )
    )
    out.append(
        fmt_row(
            "Mean parse-tree depth",
            f"{statistics.mean([s.tree_depth for s in sents]):.1f}",
            "> 6 = deeply embedded",
        )
    )
    out.append("")
    out.append(f"  Most nested {top}:")
    for s in sorted(sents, key=lambda s: (-s.n_subordinate_clauses, -s.tree_depth))[:top]:
        out.append(f"    [{s.n_subordinate_clauses} cl, depth {s.tree_depth}] {clip(s.text)}")

    out.append("")
    out.append("=" * 78)
    out.append("REFERENTIAL LOAD (BACKWARD REFERENCES)")
    out.append("=" * 78)
    ref = [s for s in sents if s.referential_score > 0]
    out.append(
        fmt_row(
            "Sentences needing prior context",
            f"{len(ref)} ({100 * len(ref) / len(sents):.0f}%)",
            "reader must recall an earlier referent",
        )
    )
    heavy = [s for s in ref if s.referential_score >= 2]
    out.append(fmt_row("Heavy (score >= 2)", str(len(heavy))))
    n_vague = sum(1 for s in ref for h in s.referential_hits if h.startswith("vague reference"))
    n_dist = sum(1 for s in ref for h in s.referential_hits if h.startswith("distant referent"))
    out.append(
        fmt_row("Vague definite NPs", str(n_vague), "unanchored, e.g. 'the main target metric'")
    )
    out.append(fmt_row("Distant referents", str(n_dist), "antecedent > 3 sentences back"))
    out.append("")
    out.append(f"  Worst {top}:")
    for s in sorted(ref, key=lambda s: -s.referential_score)[:top]:
        out.append(f"    [{', '.join(s.referential_hits)}]")
        out.append(f"      {clip(s.text)}")

    if show_all:
        out.append("")
        out.append("=" * 78)
        out.append("PER-SENTENCE TABLE  (words | polysyl | rare | s-v gap | clauses | depth | ref)")
        out.append("=" * 78)
        for i, s in enumerate(sents, 1):
            out.append(
                f"  {i:>4}. {s.n_words:>3}w {s.n_polysyllables:>3}p {s.n_rare_words:>3}r "
                f"{s.max_subj_verb_dist:>3}g {s.n_subordinate_clauses:>2}c {s.tree_depth:>2}d "
                f"{s.referential_score:>2}f  {clip(s.text, 60)}"
            )
    return "\n".join(out)


def analyze_file(
    path: Path, nlp, use_coref: bool
) -> tuple[str, list[SentenceStats], list[tuple[int, str]]]:
    source = path.read_text(encoding="utf-8", errors="replace")
    seg_titles: list[tuple[int, str]] = [(0, "")]
    seg_starts: list[int] = [0]
    if path.suffix == ".tex":
        source = inline_inputs(source, path.parent)
        cites, labels = load_aux(path.with_suffix(".aux"))
        source = resolve_refs(source, cites, labels)
        abstract, body = document_body(source)
        segments = split_sections(body)
        if abstract:
            segments.insert(0, (1, "Abstract", abstract))
        seg_titles, seg_starts, pieces = [], [], []
        pos = 0
        strip_title = LatexNodes2Text(math_mode="remove")
        for level, title, seg_body in segments:
            prose = strip_latex(seg_body)
            if not prose and not title:
                continue
            seg_titles.append((level, strip_title.latex_to_text(title).strip()))
            seg_starts.append(pos)
            pieces.append(prose)
            pos += len(prose) + 2  # the "\n\n" joiner
        text = "\n\n".join(pieces)
    else:
        text = source
    if not text:
        sys.exit(f"{path}: no prose found after stripping LaTeX markup.")
    nlp.max_length = max(len(text) + 1, nlp.max_length)
    doc = nlp(text)
    sents = list(doc.sents)

    coref_hits = None
    if use_coref:
        coref_hits = coref_distance_hits(text, [(s.start_char, s.end_char) for s in sents])

    stats: list[SentenceStats] = []
    last_seen: dict[str, int] = {}
    from bisect import bisect_right

    for idx, sent in enumerate(sents):
        st = analyze_sentence(sent, idx, last_seen, count_pronouns=coref_hits is None)
        if coref_hits is not None:
            for msg, weight in coref_hits[idx]:
                st.referential_hits.append(msg)
                st.referential_score += weight
        st.seg = max(0, bisect_right(seg_starts, sent.start_char) - 1)
        stats.append(st)
        for tok in sent:
            if tok.pos_ in ("NOUN", "PROPN"):
                last_seen[tok.lemma_.lower()] = idx
    return text, stats, seg_titles


def main() -> None:
    ap = argparse.ArgumentParser(description="Writing-complexity statistics for LaTeX documents")
    ap.add_argument("files", type=Path, nargs="+", help=".tex (or plain text) files to analyze")
    ap.add_argument(
        "--top", type=int, default=5, help="how many worst offenders to list per category"
    )
    ap.add_argument("--all", action="store_true", help="also print the full per-sentence table")
    ap.add_argument(
        "--highlight",
        choices=[*METRICS, "all"],
        help="render a PDF with each sentence highlighted green->red by this metric "
        "('all' renders one PDF per metric)",
    )
    ap.add_argument(
        "--no-coref",
        action="store_true",
        help="skip neural coreference resolution (faster; surface heuristics only)",
    )
    args = ap.parse_args()

    import spacy

    nlp = spacy.load("en_core_web_sm")
    for path in args.files:
        text, stats, seg_titles = analyze_file(path, nlp, use_coref=not args.no_coref)
        print(f"\n{path}  ({len(text.split())} words after markup stripping)\n")
        print(report(stats, text, args.top, args.all))
        if args.highlight:
            from .highlight import render_metric_pdf

            keys = list(METRICS) if args.highlight == "all" else [args.highlight]
            prose = [s for s in stats if s.n_words >= 3]
            for key in keys:
                out_pdf = path.with_name(f"{path.stem}_{key}.pdf")
                render_metric_pdf(prose, seg_titles, key, path.name, out_pdf)
                print(f"  wrote {out_pdf}")


if __name__ == "__main__":
    main()
