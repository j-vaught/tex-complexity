"""Coreference-based referential distance scoring.

Uses fastcoref (Otmazgin, Cattan & Goldberg, 2022) to resolve which mentions
in the document refer to the same entity, then charges each anaphoric mention
(a pronoun or demonstrative noun phrase — NOT a repeated full noun, which the
reader can resolve by name) according to how many sentences back its nearest
antecedent sits.
"""

from __future__ import annotations

import sys

ANAPHOR_STARTERS = {
    "it",
    "its",
    "they",
    "them",
    "their",
    "this",
    "that",
    "these",
    "those",
    "he",
    "she",
    "former",
    "latter",
}
RECENT_SENTS = 3
DISTANT_SENTS = 5


def coref_distance_hits(
    text: str, sent_spans: list[tuple[int, int]]
) -> list[list[tuple[str, int]]] | None:
    """Per-sentence (hit description, weight) pairs from coreference resolution.

    Returns one list per sentence span, or None if fastcoref is unavailable
    (caller falls back to surface heuristics).
    """
    try:
        import logging

        logging.getLogger("fastcoref").setLevel(logging.ERROR)
        from fastcoref import FCoref
    except ImportError:
        print("note: fastcoref not installed; using surface heuristics only", file=sys.stderr)
        return None
    try:
        model = FCoref(device="cpu")
        pred = model.predict(texts=[text])[0]
        clusters = pred.get_clusters(as_strings=False)
    except Exception as e:
        print(f"note: coreference resolution failed ({e}); skipping", file=sys.stderr)
        return None

    def sent_of(pos: int) -> int:
        for i, (a, b) in enumerate(sent_spans):
            if a <= pos < b:
                return i
        return len(sent_spans) - 1

    hits: list[list[tuple[str, int]]] = [[] for _ in sent_spans]
    for cluster in clusters:
        mentions = sorted(cluster)
        for prev, cur in zip(mentions, mentions[1:]):
            mention_text = text[cur[0] : cur[1]]
            first_word = mention_text.split()[0].lower().strip(",.;") if mention_text else ""
            is_anaphor = first_word in ANAPHOR_STARTERS or (
                first_word == "the" and len(mention_text.split()) <= 4
            )
            if not is_anaphor:
                continue
            dist = sent_of(cur[0]) - sent_of(prev[0])
            if dist <= RECENT_SENTS:
                continue
            antecedent = text[mentions[0][0] : mentions[0][1]]
            weight = 1 if dist <= DISTANT_SENTS else 2
            hits[sent_of(cur[0])].append(
                (f"far antecedent: '{mention_text}' -> '{antecedent}' ({dist} sents back)", weight)
            )
    return hits
