#!/usr/bin/env python3
"""Score the documents in `docs/` against the house register.

The register is "spare reference": labelled facts, short declaratives, no narrator. What this
script looks for is the opposite of that — the handful of constructions that make a document
read as machine-written rather than written down.

It is a heuristic and it is meant to be. A score of zero is not the goal; an unexplained score
of forty is. Run it before and after editing a document and look at what moved.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

#: Constructions that signal an explanation rather than a record.
#:
#: Each one is a way of telling the reader how to feel about a fact instead of stating it.
#: "Deliberately" asks for credit. "Worth noting" claims the reader's attention rather than
#: earning it. "Not X, it is Y" stages a small reversal for effect. A reference document has
#: no use for any of them.
PATTERNS: dict[str, str] = {
    "editorialising": r"\b(deliberate(ly)?|on purpose|worth (stating|noting|saying)|"
    r"the (whole )?point (is|was|of)|the reason .{0,20}(is|was) that|crucially|importantly|"
    r"notably|it is worth)\b",
    "rhetorical reversal": r"\b(not (just |merely |only )?[a-z]+,? (it|they|that) (is|are|was)\b"
    r"|rather than a\b|is not a .{0,30}, it is\b)",
    "narrator": r"\b(I |we |our |us )\b|\byou (can|should|will|have|are|do)\b",
    "hedging": r"\b(arguably|essentially|effectively|fundamentally|simply put|in essence|"
    r"at the end of the day|it should be noted)\b",
    "vague intensifier": r"\b(robust|seamless|powerful|comprehensive|cutting-edge|best-in-class|"
    r"world-class|leverage(s|d)?|utilise|utilize)\b",
}


@dataclass
class Report:
    path: Path
    words: int = 0
    em_dashes: int = 0
    long_sentences: int = 0
    sentences: int = 0
    hits: dict[str, list[str]] = field(default_factory=dict)

    @property
    def score(self) -> int:
        """One point per offending construction, plus em-dashes above a plain-prose budget."""
        budget = self.words // 500  # roughly one em-dash per 500 words is unremarkable
        return sum(len(v) for v in self.hits.values()) + max(0, self.em_dashes - budget)

    @property
    def per_1000(self) -> float:
        return round(self.score * 1000 / self.words, 1) if self.words else 0.0


#: `As a scheduler, I can ...` — the Connextra user-story form.
#:
#: Stripped before the narrator check, because the first person here is the format rather than
#: a voice. Counting it flagged 37 "violations" in the PRD and would have argued for rewriting
#: every user story in the document into something that is no longer a user story. A measure
#: that pushes toward damaging correct work is worse than no measure.
USER_STORY = re.compile(r"\*?\*?As an? [^,]{2,40},\*?\*? ", re.I)


def _prose_only(text: str) -> str:
    """Reduce a document to the prose a reader reads in sentences.

    Headings go first. `### Epic 1.1 — Agency & User Management` is a label, and the dash in it
    is punctuation between a number and a name, not the rhetorical aside this script is looking
    for. Counting them put most of the PRD's em-dash score in its own table of contents.

    Tables, code fences, inline code, and link targets go for the same reason: none of them is
    a sentence, and all of them skew the per-word rates.
    """
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"^#{1,6} .*$", "", text, flags=re.M)
    text = re.sub(r"^\|.*$", "", text, flags=re.M)
    text = re.sub(r"`[^`]*`", "", text)
    return re.sub(r"\]\([^)]*\)", "]", text)


def _without_user_stories(text: str) -> str:
    """Blank first person where it is grammar or quotation rather than voice.

    Two cases. The clause a user story is required to open with, and anything inside double
    quotes — a document reporting that someone says "we think so" is not itself narrating.
    """
    out = []
    for line in text.splitlines():
        line = re.sub(r'"[^"]*"', '""', line)
        if USER_STORY.search(line):
            line = re.sub(r"\bI\b", "", USER_STORY.sub("", line))
        out.append(line)
    return "\n".join(out)


def inspect(path: Path) -> Report:
    raw = path.read_text(encoding="utf-8")
    prose = _prose_only(raw)
    report = Report(path=path, words=len(prose.split()))
    report.em_dashes = prose.count("—")

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", prose) if s.strip()]
    report.sentences = len(sentences)
    report.long_sentences = sum(1 for s in sentences if len(s.split()) > 35)

    narrator_free = _without_user_stories(prose)
    for label, pattern in PATTERNS.items():
        haystack = narrator_free if label == "narrator" else prose
        found = [m.group(0).strip() for m in re.finditer(pattern, haystack, flags=re.I)]
        if found:
            report.hits[label] = found
    return report


def main() -> int:
    verbose = "--verbose" in sys.argv
    reports = sorted(
        (inspect(p) for p in DOCS.glob("*.md")), key=lambda r: r.per_1000, reverse=True
    )

    print(f"{'document':<52} {'words':>6} {'score':>6} {'per 1k':>7} {'em—':>5} {'long':>5}")
    print("-" * 86)
    for r in reports:
        print(
            f"{r.path.name:<52} {r.words:>6} {r.score:>6} {r.per_1000:>7} "
            f"{r.em_dashes:>5} {r.long_sentences:>5}"
        )
        if verbose and r.hits:
            for label, found in sorted(r.hits.items()):
                sample = ", ".join(sorted(set(found))[:6])
                print(f"    {label:<20} {len(found):>3}  {sample}")

    total = sum(r.score for r in reports)
    words = sum(r.words for r in reports)
    print("-" * 86)
    print(f"{'TOTAL':<52} {words:>6} {total:>6} {round(total * 1000 / words, 1):>7}")
    return 0


if __name__ == "__main__":
    # Piping into `head` closes stdout early; that is a normal way to read this and not an error.
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0) from None
