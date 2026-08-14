# tex-complexity

Writing-complexity statistics for LaTeX documents, by J.C. Vaught.

`texstats` strips LaTeX markup from a `.tex` file (math, floats, and preamble removed) and reports five families of metrics over the remaining prose, each with the worst offending sentences quoted so they can be found and revised.

## Metrics

**Sentence complexity.** Length distribution (mean, median, max, standard deviation), the share of sentences over 30 words, and standard readability indices (Flesch reading ease, Flesch-Kincaid grade, Gunning fog).

**Word complexity.** Share of polysyllabic words (three or more syllables), share of rare words (Zipf frequency below 3.5, roughly rarer than one occurrence per three million words), and average syllables per word.

**Subject-verb separation.** For each sentence, the widest gap in words between a grammatical subject and its governing verb, found by dependency parsing. Wide gaps force the reader to hold the subject in memory across an interruption.

**Nesting.** Subordinate-clause count per sentence (relative, adverbial, complement, and clausal-subject clauses) and maximum dependency-tree depth.

**Referential load.** Sentences whose meaning depends on recalling something stated earlier. Four signals are combined. First, bare demonstrative openers ("This shows..." with no noun after the demonstrative). Second, anaphoric phrases ("the former", "the latter", "as mentioned above", "aforementioned", "respectively"). Third, third-person pronoun density. Fourth, vague definite noun phrases, found by dependency parsing. A definite NP headed by an abstract shell noun (metric, object, approach, criterion, and similar) is searched for a concrete anchor anywhere in its subtree, including attached of-phrases. A proper noun, a number, or a specific noun mentioned within the last three sentences counts as an anchor. "The accuracy of BERT" is anchored and passes; "the main target metric of this paper" is not and is flagged, since nothing inside the phrase names the referent. Phrases whose antecedent exists but was last mentioned more than three sentences back are flagged separately as distant referents, with the distance reported. Noun phrases governed by verbs of naming ("we define tracking error as our primary evaluation criterion") are treated as introductions rather than back-references and are not flagged.

Referential distance is scored with neural coreference resolution (fastcoref). Each anaphoric mention, meaning a pronoun or demonstrative phrase rather than a repeated full noun, is resolved to its antecedent and charged by how many sentences back that antecedent sits. Mentions resolved within three sentences cost nothing; beyond five the penalty doubles. The first run downloads the coreference model; pass `--no-coref` to skip resolution and fall back to surface heuristics.

## Usage

```
uv run texstats paper.tex
uv run texstats paper.tex --top 10      # list ten worst offenders per category
uv run texstats paper.tex --all         # append a per-sentence table
uv run texstats paper.tex --no-coref    # faster, surface heuristics only
```

## Highlighted PDF output

`--highlight <metric>` renders the document prose as a PDF in which every sentence carries a background color from light green (simple) to light red (complex) for that metric, with the raw value shown as a small superscript after each sentence. `--highlight all` writes one PDF per metric next to the input file, named `<stem>_<metric>.pdf`.

```
uv run texstats paper.tex --highlight referential
uv run texstats paper.tex --highlight all
```

Metric keys are `sentence` (words per sentence), `word` (polysyllabic plus rare-word share), `svgap` (subject-verb separation), `nesting` (clauses and parse depth), and `referential` (backward-reference load). Rendering requires `typst` on the PATH. Multiple `.tex` files can be passed in one invocation and are processed independently.

From any directory, pass the project explicitly.

```
uv run --project /path/to/tex-complexity texstats paper.tex
```

In VS Code, run the task "Writing complexity stats (texstats)" (Cmd+Shift+P, "Tasks: Run Task") to analyze the currently open file.

## Setup

```
uv sync
```

This installs spaCy with the small English model, pylatexenc for markup stripping, textstat for readability indices, and wordfreq for rarity scoring.
