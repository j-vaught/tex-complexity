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
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any

from pylatexenc.latex2text import LatexNodes2Text
from wordfreq import zipf_frequency

from . import __version__
from .metrics import METRICS, SentenceStats
from .readability import (
    flesch_kincaid_grade,
    flesch_reading_ease,
    gunning_fog,
    syllable_count,
)

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
THIRD_PERSON_PRONOUNS = {
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "herself",
    "himself",
    "it",
    "its",
    "itself",
    "they",
    "them",
    "their",
    "theirs",
    "themselves",
}

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

RARE_ZIPF_THRESHOLD = 3.5  # zipf < 3.5 ~ rarer than ~1 per 316,000 words
MAX_INCLUDE_DEPTH = 20
MAX_DOCUMENT_CHARS = 2_000_000
NON_PROSE_ENVIRONMENTS = (
    "verbatim",
    "lstlisting",
    "minted",
    "comment",
    "equation",
    "align",
    "alignat",
    "gather",
    "multline",
    "displaymath",
    "math",
    "figure",
    "table",
    "tabular",
    "tabularx",
    "algorithm",
    "algorithmic",
    "tikzpicture",
    "thebibliography",
)
LITERAL_ENVIRONMENTS = ("lstlisting", "verbatim", "minted")
INLINE_VERBATIM_RE = re.compile(
    r"\\verb\*?(?![A-Za-z@])(?P<delimiter>[^\s])"
    r"(?:(?!(?P=delimiter))[^\r\n])*(?P=delimiter)"
)
_ANAPHORIC_PATTERNS = [
    (phrase, re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE))
    for phrase in ANAPHORIC_PHRASES
]


class NoProseError(ValueError):
    """Raised when a source file contains no analyzable prose."""


class UnsafeIncludeError(ValueError):
    """Raised when a TeX include escapes the document directory."""


class IncludeError(ValueError):
    """Raised when a TeX include cannot be expanded safely and completely."""


class DocumentTooLargeError(ValueError):
    """Raised when expanded prose exceeds the parser's safety limit."""


def remove_inline_verbatim(source: str) -> str:
    """Remove inline verbatim spans before interpreting TeX commands."""
    return INLINE_VERBATIM_RE.sub(" ", source)


def remove_non_prose_environments(source: str) -> str:
    """Remove environments whose contents should never enter prose analysis."""
    for environment in NON_PROSE_ENVIRONMENTS:
        source = re.sub(
            rf"\\begin\{{{environment}\*?\}}.*?\\end\{{{environment}\*?\}}",
            " ",
            source,
            flags=re.DOTALL,
        )
        source = re.sub(
            rf"\\begin\{{{environment}\*?\}}.*\Z",
            " ",
            source,
            flags=re.DOTALL,
        )
    return source


def _strip_line_comment(line: str) -> str:
    """Strip one TeX comment from a non-literal line."""
    for index, char in enumerate(line):
        if char != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index] + ("\n" if line.endswith("\n") else "")
    return line


def strip_comments(source: str) -> str:
    """Remove TeX comments while preserving escaped percent signs."""
    cleaned: list[str] = []
    literal_environment: str | None = None
    for line in source.splitlines(keepends=True):
        if literal_environment is not None:
            end = re.search(rf"\\end\{{{literal_environment}\*?\}}", line)
            if end is None:
                cleaned.append(line)
                continue
            line = line[: end.end()] + _strip_line_comment(line[end.end() :])
            literal_environment = None
        else:
            line = _strip_line_comment(line)
        cleaned.append(line)
        for environment in LITERAL_ENVIRONMENTS:
            begin = re.search(rf"\\begin\{{{environment}\*?\}}", line)
            if begin and not re.search(rf"\\end\{{{environment}\*?\}}", line[begin.end() :]):
                literal_environment = environment
                break
    return "".join(cleaned)


def preprocess_tex(source: str) -> str:
    """Remove literal code, comments, and non-prose environments safely."""
    source = remove_inline_verbatim(source)
    return remove_non_prose_environments(strip_comments(source))


def inline_inputs(
    source: str,
    base_dir: Path,
    depth: int = 0,
    active_paths: set[Path] | None = None,
    allow_outside: bool = False,
) -> str:
    """Recursively expand \\input{...} and \\include{...} relative to base_dir."""
    source = remove_inline_verbatim(source)
    if depth >= MAX_INCLUDE_DEPTH:
        raise IncludeError(f"include nesting exceeds {MAX_INCLUDE_DEPTH} levels")
    active_paths = set() if active_paths is None else active_paths

    def repl(m: re.Match[str]) -> str:
        rel = m.group(2)
        path = base_dir / rel
        if path.suffix == "":
            path = path.with_suffix(".tex")
        try:
            path = path.resolve()
        except OSError as exc:
            raise IncludeError(f"could not resolve included file: {rel}") from exc
        root = base_dir.resolve()
        if not allow_outside and not path.is_relative_to(root):
            raise UnsafeIncludeError(f"include escapes the document directory: {rel}")
        if not path.is_file():
            raise IncludeError(f"included file not found: {rel}")
        if path in active_paths:
            raise IncludeError(f"cyclic include detected: {rel}")
        active_paths.add(path)
        try:
            included = path.read_text(encoding="utf-8", errors="replace")
            included = preprocess_tex(included)
            return inline_inputs(
                included,
                base_dir,
                depth + 1,
                active_paths,
                allow_outside,
            )
        except OSError as exc:
            raise IncludeError(f"could not read included file: {rel}") from exc
        finally:
            active_paths.remove(path)

    return re.sub(r"\\(input|include)\{([^}]+)\}", repl, source)


def load_aux(
    aux_path: Path,
    root_dir: Path | None = None,
    seen: set[Path] | None = None,
) -> tuple[dict[str, int], dict[str, str]]:
    """Citation numbers and label values from a LaTeX .aux file."""
    cites: dict[str, int] = {}
    labels: dict[str, str] = {}
    root_dir = aux_path.parent.resolve() if root_dir is None else root_dir
    seen = set() if seen is None else seen
    try:
        aux_path = aux_path.resolve()
    except OSError:
        return cites, labels
    if not aux_path.is_file() or aux_path in seen or not aux_path.is_relative_to(root_dir):
        return cites, labels
    seen.add(aux_path)
    aux = aux_path.read_text(encoding="utf-8", errors="replace")
    for key, num in re.findall(r"\\bibcite\{([^}]*)\}\{(\d+)\}", aux):
        cites[key] = int(num)
    for key, val in re.findall(r"\\newlabel\{([^}]*)\}\{\{(.*?)\}\{", aux):
        labels[key] = re.sub(r"\\mbox\s*|\{|\}", "", val).strip()
    for relative_path in re.findall(r"\\@input\{([^}]*)\}", aux):
        child_cites, child_labels = load_aux(root_dir / relative_path, root_dir, seen)
        cites.update(child_cites)
        labels.update(child_labels)
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
    next_fallback = max(cites.values(), default=0) + 1

    def cite_num(key: str) -> int:
        nonlocal next_fallback
        key = key.strip()
        if key in cites:
            return cites[key]
        if key not in fallback:
            fallback[key] = next_fallback
            next_fallback += 1
        return fallback[key]

    def cite_repl(m: re.Match) -> str:
        return _fmt_citation([cite_num(k) for k in m.group(1).split(",")])

    def ref_repl(m: re.Match) -> str:
        val = labels.get(m.group(2).strip(), "?")
        return f"({val})" if m.group(1) == "eqref" else val

    source = re.sub(r"\\cite[tp]?\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}", cite_repl, source)
    source = re.sub(r"\\(ref|eqref|autoref|[cC]ref|pageref)\*?\{([^}]*)\}", ref_repl, source)
    return source


def _roman(value: int) -> str:
    """Return a positive integer as an uppercase Roman numeral."""
    numerals = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    result: list[str] = []
    for amount, numeral in numerals:
        count, value = divmod(value, amount)
        result.extend([numeral] * count)
    return "".join(result)


def _alpha(value: int) -> str:
    """Return a one-based integer as A, B, ..., Z, AA, AB, and so on."""
    result: list[str] = []
    while value:
        value, remainder = divmod(value - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def split_sections(body: str) -> list[tuple[int, str, str]]:
    """Split document body into (level, numbered title, body) segments.

    Level 1 = section, 2 = subsection, 3 = subsubsection, numbered in
    IEEE style (I / A / 1). Prose before the first section (the abstract)
    becomes a level-0 leading segment.
    """
    pat = re.compile(r"\\(section|subsection|subsubsection)\*?\{((?:[^{}]|\{[^{}]*\})*)\}")
    matches = list(pat.finditer(body))
    if not matches:
        return [(0, "", body)]
    segments: list[tuple[int, str, str]] = [(0, "", body[: matches[0].start()])]
    n_sec = n_sub = n_subsub = 0
    for m, nxt in zip(matches, [*matches[1:], None], strict=True):
        kind, title = m.group(1), m.group(2)
        end = nxt.start() if nxt else len(body)
        if kind == "section":
            n_sec, n_sub, n_subsub = n_sec + 1, 0, 0
            level, num = 1, _roman(n_sec)
            display = f"{num}. {title}"
        elif kind == "subsection":
            n_sub, n_subsub = n_sub + 1, 0
            level, display = 2, f"{_alpha(n_sub)}. {title}"
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
    source = remove_non_prose_environments(source)
    text = LatexNodes2Text(math_mode="remove").latex_to_text(source)
    # Drop heading lines (pylatexenc renders \section{...} as "§ TITLE").
    text = re.sub(r"^\s*§+.*$", " ", text, flags=re.MULTILINE)
    # Collapse whitespace and drop leftover bracket junk.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def vague_definite_hits(
    sent: Any, sent_idx: int, last_seen: dict[str, int], flag_distant: bool = True
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
    sent: Any,
    sent_idx: int = 0,
    last_seen: dict[str, int] | None = None,
    count_pronouns: bool = True,
) -> SentenceStats:
    words = [t for t in sent if t.is_alpha]
    n_words = len(words)

    syllable_counts = [syllable_count(t.text) for t in words]
    rare_flags = [
        not t.is_stop and zipf_frequency(t.lemma_.lower(), "en") < RARE_ZIPF_THRESHOLD
        for t in words
    ]
    poly_flags = [count >= 3 for count in syllable_counts]
    n_syllables = sum(syllable_counts)
    n_poly = sum(poly_flags)
    n_rare = sum(rare_flags)
    n_complex = sum(poly or rare for poly, rare in zip(poly_flags, rare_flags, strict=True))

    word_features = {
        token.i: (syllables, rare)
        for token, syllables, rare in zip(words, syllable_counts, rare_flags, strict=True)
    }
    word_scores: list[tuple[str, float]] = []
    for t in sent:
        w = 0.0
        if t.i in word_features:
            syllables, rare = word_features[t.i]
            zipf = zipf_frequency(t.lemma_.lower(), "en")
            syllable_score = min(1.0, max(0.0, (syllables - 2) / 3))
            rarity_score = max(0.3, min(1.0, 0.3 + (RARE_ZIPF_THRESHOLD - zipf) / 2.5))
            if syllables >= 3 or rare:
                w = max(syllable_score, rarity_score if rare else 0.0)
        word_scores.append((t.text_with_ws, w))

    max_sv = 0
    has_subject_verb_pair = False
    for tok in sent:
        if tok.dep_ in SUBJECT_DEPS and tok.head.pos_ in ("VERB", "AUX"):
            has_subject_verb_pair = True
            start, end = sorted((tok.i, tok.head.i))
            gap = sum(1 for item in sent if start < item.i < end and item.is_alpha)
            max_sv = max(max_sv, gap)

    n_sub = sum(1 for t in sent if t.dep_ in SUBORDINATE_DEPS)

    def depth(tok: Any, d: int = 0) -> int:
        kids = [c for c in tok.children if c.sent == sent]
        return d if not kids else max(depth(c, d + 1) for c in kids)

    tree_depth = depth(sent.root)

    hits: list[str] = []
    for phrase, pattern in _ANAPHORIC_PATTERNS:
        if pattern.search(sent.text):
            hits.append(phrase)
    # Bare demonstrative: sentence opens with this/that/these/those/it NOT
    # followed by a noun ("This shows..." forces the reader to resolve the
    # referent; "This method shows..." does not).
    first = next((t for t in sent if t.is_alpha), None)
    bare_first = False
    if first is not None and first.lower_ in BARE_DEMONSTRATIVES and first.pos_ in ("DET", "PRON"):
        anchors_noun = first.dep_ == "det" and first.head.pos_ in ("NOUN", "PROPN")
        if not anchors_noun:
            hits.append(f"bare '{first.text}'")
            bare_first = True
    # Pronoun density adds one point per third-person pronoun. A sentence-opening
    # bare "it" is already represented by the demonstrative signal above.
    pron = 0
    if count_pronouns:
        pron = sum(
            1
            for t in sent
            if t.lower_ in THIRD_PERSON_PRONOUNS
            and t.pos_ == "PRON"
            and not (bare_first and first is not None and t.i == first.i)
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
        n_syllables=n_syllables,
        n_polysyllables=n_poly,
        n_rare_words=n_rare,
        n_complex_words=n_complex,
        max_subj_verb_dist=max_sv,
        has_subject_verb_pair=has_subject_verb_pair,
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


def report(stats: list[SentenceStats], top: int, show_all: bool) -> str:
    out: list[str] = []
    sents = [s for s in stats if s.n_words >= 3]
    if not sents:
        return "No prose sentences found."
    lengths = [s.n_words for s in sents]
    total_words = sum(lengths)
    total_syllables = sum(s.n_syllables for s in sents)
    total_complex = sum(s.n_complex_words for s in sents)
    total_polysyllables = sum(s.n_polysyllables for s in sents)

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
    long_sentence_count = sum(1 for length in lengths if length > 30)
    out.append(
        fmt_row(
            "Sentences > 30 words",
            f"{long_sentence_count} ({100 * long_sentence_count / len(sents):.0f}%)",
        )
    )
    out.append(
        fmt_row(
            "Flesch reading ease",
            f"{flesch_reading_ease(total_words, len(sents), total_syllables):.1f}",
            "30-50 typical for papers",
        )
    )
    out.append(
        fmt_row(
            "Flesch-Kincaid grade",
            f"{flesch_kincaid_grade(total_words, len(sents), total_syllables):.1f}",
        )
    )
    out.append(
        fmt_row(
            "Gunning fog index",
            f"{gunning_fog(total_words, len(sents), total_polysyllables):.1f}",
        )
    )
    out.append("")
    out.append(f"  Longest {top}:")
    for s in sorted(sents, key=lambda s: -s.n_words)[:top]:
        out.append(f"    [{s.n_words} w] {clip(s.text)}")

    out.append("")
    out.append("=" * 78)
    out.append("WORD COMPLEXITY")
    out.append("=" * 78)
    poly = total_polysyllables
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
        fmt_row("Complex-word union", f"{total_complex} ({100 * total_complex / total_words:.1f}%)")
    )
    out.append(fmt_row("Avg syllables per word", f"{total_syllables / total_words:.2f}"))
    out.append("")
    out.append(f"  Most complex {top}:")
    for s in sorted(sents, key=lambda s: -s.n_complex_words / s.n_words)[:top]:
        ratio = 100 * s.n_complex_words / s.n_words
        out.append(f"    [{ratio:.0f}% complex] {clip(s.text)}")

    out.append("")
    out.append("=" * 78)
    out.append("SUBJECT-VERB SEPARATION")
    out.append("=" * 78)
    sv_sents = [s for s in sents if s.has_subject_verb_pair]
    sv = [s.max_subj_verb_dist for s in sv_sents]
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
        for s in sorted(sv_sents, key=lambda s: -s.max_subj_verb_dist)[:top]:
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
    nesting_score = METRICS["nesting"][2]
    for s in sorted(
        sents,
        key=lambda s: (-nesting_score(s), -s.n_subordinate_clauses, -s.tree_depth),
    )[:top]:
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
    n_dist = sum(
        1
        for s in ref
        for h in s.referential_hits
        if h.startswith(("distant referent", "far antecedent"))
    )
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
    path: Path, nlp: Any, allow_outside_includes: bool = False
) -> tuple[str, list[SentenceStats], list[tuple[int, str]]]:
    source = path.read_text(encoding="utf-8", errors="replace")
    seg_titles: list[tuple[int, str]] = [(0, "")]
    pieces: list[str]
    if path.suffix.lower() == ".tex":
        source = preprocess_tex(source)
        source = inline_inputs(
            source,
            path.parent,
            active_paths={path.resolve()},
            allow_outside=allow_outside_includes,
        )
        cites, labels = load_aux(path.with_suffix(".aux"))
        source = resolve_refs(source, cites, labels)
        abstract, body = document_body(source)
        segments = split_sections(body)
        if abstract:
            segments.insert(0, (1, "Abstract", abstract))
        seg_titles, pieces = [], []
        strip_title = LatexNodes2Text(math_mode="remove")
        for level, title, seg_body in segments:
            prose = strip_latex(seg_body)
            if not prose and not title:
                continue
            seg_titles.append((level, strip_title.latex_to_text(title).strip()))
            pieces.append(prose)
        text = "\n\n".join(pieces)
    else:
        text = source
        pieces = [text]
    if not text:
        raise NoProseError("no prose found after stripping LaTeX markup")
    if len(text) > MAX_DOCUMENT_CHARS:
        raise DocumentTooLargeError(
            f"expanded prose is {len(text):,} characters; limit is {MAX_DOCUMENT_CHARS:,}"
        )
    nlp.max_length = max(max((len(piece) for piece in pieces), default=0) + 1, nlp.max_length)
    segmented_sents = [
        (segment_index, sent)
        for segment_index, doc in enumerate(nlp.pipe(pieces))
        for sent in doc.sents
    ]
    if not any(sum(token.is_alpha for token in sent) >= 3 for _, sent in segmented_sents):
        raise NoProseError("no prose sentences with at least three words found")

    stats: list[SentenceStats] = []
    last_seen: dict[str, int] = {}

    for idx, (segment_index, sent) in enumerate(segmented_sents):
        st = analyze_sentence(sent, idx, last_seen)
        st.seg = segment_index
        stats.append(st)
        for tok in sent:
            if tok.pos_ in ("NOUN", "PROPN"):
                last_seen[tok.lemma_.lower()] = idx
    return text, stats, seg_titles


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _highlight_output_path(path: Path, metric: str) -> Path:
    """Return an output name that preserves the complete input filename."""
    return path.with_name(f"{path.name}_{metric}.pdf")


def _run() -> None:
    ap = argparse.ArgumentParser(
        prog="texstats",
        description="Writing-complexity statistics for LaTeX documents",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("files", type=Path, nargs="+", help=".tex (or plain text) files to analyze")
    ap.add_argument(
        "--top",
        type=_positive_int,
        default=5,
        help="how many worst offenders to list per category",
    )
    ap.add_argument("--all", action="store_true", help="also print the full per-sentence table")
    ap.add_argument(
        "--highlight",
        choices=[*METRICS, "all"],
        help="render a PDF with each sentence highlighted white->garnet by this metric "
        "('all' renders one PDF per metric)",
    )
    ap.add_argument(
        "--allow-outside-includes",
        action="store_true",
        help="allow TeX input/include commands to read outside the document directory",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing highlighted PDF files",
    )
    args = ap.parse_args()

    if args.highlight and shutil.which("typst") is None:
        print(
            "texstats: error: --highlight requires the 'typst' executable on PATH", file=sys.stderr
        )
        raise SystemExit(1)

    failed = False
    paths: list[Path] = []
    for path in args.files:
        if path.is_file():
            paths.append(path)
        else:
            print(f"texstats: error: {path}: input file not found", file=sys.stderr)
            failed = True
    if not paths:
        raise SystemExit(1)

    highlight_plan: list[tuple[Path, str, Path]] = []
    if args.highlight:
        keys = list(METRICS) if args.highlight == "all" else [args.highlight]
        requested_inputs = {path.resolve(): path for path in paths}
        claimed_outputs: dict[Path, tuple[Path, str]] = {}
        for path in paths:
            for key in keys:
                out_pdf = _highlight_output_path(path, key)
                destination = out_pdf.resolve()
                colliding_input = requested_inputs.get(destination)
                if colliding_input is not None:
                    print(
                        f"texstats: error: {out_pdf}: highlighted PDF would overwrite "
                        f"requested input {colliding_input}",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)
                previous = claimed_outputs.get(destination)
                if previous is not None:
                    previous_path, previous_key = previous
                    print(
                        f"texstats: error: {out_pdf}: multiple requested highlights target "
                        f"the same PDF ({previous_path} [{previous_key}] and {path} [{key}])",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)
                claimed_outputs[destination] = (path, key)
                highlight_plan.append((path, key, out_pdf))
        if not args.force:
            existing_outputs = [out_pdf for _, _, out_pdf in highlight_plan if out_pdf.exists()]
            if existing_outputs:
                for out_pdf in existing_outputs:
                    print(
                        f"texstats: error: {out_pdf}: output exists; pass --force to overwrite",
                        file=sys.stderr,
                    )
                raise SystemExit(1)

    import spacy

    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError as exc:
        print(
            f"texstats: error: could not load the en_core_web_sm language model: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    for path in paths:
        try:
            text, stats, seg_titles = analyze_file(
                path,
                nlp,
                allow_outside_includes=args.allow_outside_includes,
            )
        except (
            DocumentTooLargeError,
            IncludeError,
            NoProseError,
            OSError,
            UnsafeIncludeError,
        ) as exc:
            print(f"texstats: error: {path}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"\n{path}  ({len(text.split())} words after markup stripping)\n")
        print(report(stats, args.top, args.all))
        if args.highlight:
            from .highlight import RenderError, render_metric_pdf

            for planned_path, key, out_pdf in highlight_plan:
                if planned_path != path:
                    continue
                if out_pdf.exists() and not args.force:
                    print(
                        f"texstats: error: {out_pdf}: output exists; pass --force to overwrite",
                        file=sys.stderr,
                    )
                    failed = True
                    break
                try:
                    render_metric_pdf(stats, seg_titles, key, path.name, out_pdf)
                except (OSError, RenderError) as exc:
                    print(f"texstats: error: {path}: {exc}", file=sys.stderr)
                    failed = True
                    break
                print(f"  wrote {out_pdf}")
    if failed:
        raise SystemExit(1)


def main() -> None:
    try:
        _run()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        finally:
            raise SystemExit(0) from None


if __name__ == "__main__":
    main()
