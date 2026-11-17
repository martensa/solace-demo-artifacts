"""Text checks of ``stage_proposal`` (UC1-BUILD-SPEC 11.3 step 7, G0-09).

* Clean: NFC, remove soft hyphens (U+00AD), control and format characters (line breaks
  and tabs become spaces), collapse whitespace.
* Cut ``headline`` > 70, ``rationale`` > 240, ``facts_line`` > 120 characters at a word
  end with "…".
* Template instead of the agent's headline and rationale when either names a euro
  amount (``\\d+,\\d{2}\\s*€``) other than the old price, the new price or ``ref30``, a
  percentage (``\\d+(,\\d+)? %``) that is not allowed (the shown reduction, or a number
  of the candidate's facts or of its evidence ``numbers`` except the date and the price
  change of ``last_change``), or when the headline lacks the first word of the article
  name. A foreign amount or percentage in ``facts_line``
  replaces it with the engine facts.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import texts
from .policy import TextLimits

EURO_AMOUNT = re.compile(r"(\d+,\d{2})\s*€")
PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# a date or a price change of the evidence numbers ("last_change=2027-01-11 12,99->14,49",
# 9.4) is no percentage (UC1-32: since 160 characters, S3 carries it to the engine)
NOT_A_PERCENT = re.compile(r"\d{4}-\d{2}-\d{2}|\d+(?:[.,]\d+)?\s*(?:->|→)\s*\d+(?:[.,]\d+)?")
SOFT_HYPHEN = "­"
WHITESPACE_CONTROLS = "\t\n\r\v\f  "


@dataclass(frozen=True)
class ProposalTexts:
    headline: str
    rationale: str
    facts_line: str
    source: str  # ai | template


def clean(text: str) -> str:
    """NFC, no soft hyphen, no control/format characters, single spaces."""
    text = unicodedata.normalize("NFC", text).replace(SOFT_HYPHEN, "")
    chars = []
    for ch in text:
        if ch in WHITESPACE_CONTROLS:
            chars.append(" ")
        elif unicodedata.category(ch) not in ("Cc", "Cf"):
            chars.append(ch)
    return " ".join("".join(chars).split())


def foreign_amounts(text: str, allowed: set[str]) -> list[str]:
    """Euro amounts in ``text`` that are not in ``allowed`` (labels like ``"9,99"``)."""
    return [a for a in EURO_AMOUNT.findall(text) if a not in allowed]


def _decimal_comma(token: str) -> str:
    return token.replace(".", ",")


def number_tokens(texts_: Iterable[str]) -> set[str]:
    """Every number of ``texts_`` with a decimal comma, plus its rounded integer
    (``"46.7"`` -> ``{"46,7", "47"}``): the percentages a text may name (11.3 step 7)."""
    out: set[str] = set()
    for text in texts_:
        for token in NUMBER.findall(text or ""):
            out.add(_decimal_comma(token))
            try:
                out.add(str(Decimal(token.replace(",", ".")).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP)))
            except InvalidOperation:
                continue
    return out


def allowed_percents(shown: int, facts: str, evidence_numbers: str) -> set[str]:
    """11.3 step 7: the shown reduction plus every number of the candidate's ``facts`` and
    of its evidence ``numbers``, without the dates and price changes of ``numbers``."""
    return {str(shown)} | number_tokens([facts, NOT_A_PERCENT.sub(" ", evidence_numbers)])


def foreign_percents(text: str, allowed: set[str]) -> list[str]:
    """Percent values in ``text`` that are not in ``allowed`` (``"47"``, ``"46,7"``)."""
    return [p for p in (_decimal_comma(v) for v in PERCENT.findall(text)) if p not in allowed]


def names_article(headline: str, article_name: str) -> bool:
    """True when the headline contains the first word of the article name."""
    words = article_name.split()
    return bool(words) and words[0].casefold() in headline.casefold()


def proposal_texts(headline: str, rationale: str, facts_line: str, *, article_name: str,
                   reason: str, facts: str, allowed_amounts: set[str],
                   limits: TextLimits,
                   allowed_percents: set[str] | None = None) -> ProposalTexts:
    """The checked texts of a proposal; ``source`` tells whether the agent's headline and
    rationale survived (``ai``) or the templates replaced them (``template``).
    ``allowed_percents`` ``None`` = only the numbers of ``facts``."""
    headline, rationale, facts_line = clean(headline), clean(rationale), clean(facts_line)
    percents = number_tokens([facts]) if allowed_percents is None else allowed_percents
    use_template = (not headline or not rationale
                    or bool(foreign_amounts(headline, allowed_amounts))
                    or bool(foreign_amounts(rationale, allowed_amounts))
                    or bool(foreign_percents(headline, percents))
                    or bool(foreign_percents(rationale, percents))
                    or not names_article(headline, article_name))
    if (not facts_line or foreign_amounts(facts_line, allowed_amounts)
            or foreign_percents(facts_line, percents)):
        facts_line = facts
    if use_template:
        return ProposalTexts(
            headline=texts.template_headline(article_name, reason, limits.headline_max),
            rationale=texts.shorten(facts.rstrip(".") + ".", limits.rationale_max),
            facts_line=texts.shorten(facts_line, limits.facts_line_max), source="template")
    return ProposalTexts(headline=texts.shorten(headline, limits.headline_max),
                         rationale=texts.shorten(rationale, limits.rationale_max),
                         facts_line=texts.shorten(facts_line, limits.facts_line_max),
                         source="ai")
