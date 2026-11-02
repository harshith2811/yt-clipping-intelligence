"""
Standalone Short Viability Validator ('yt-shorts' rule).
Enforces the 'Survives Without Context' criteria before a candidate is approved for rendering:
1. Complete Thought Opening: Must not begin with dangling pronouns ('he', 'they', 'that thing') referring to unstated prior context.
2. The Narrative Turn: Must contain a claim followed by proof, complication, or emotional shift.
3. Clean Resolution: Must end on a definitive punchline or declarative statement, not a trailing sentence fragment.
4. Loop Hook: Evaluates and crafts seamless cyclical continuity from the closing frame into the opening frame.
"""

from typing import List, Dict, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
import re

from ..contracts.models import HighlightCandidate, Transcript


# Dangling opener pronouns that reference unstated prior conversational context
DANGLING_PRONOUNS: Set[str] = {
    "he", "she", "him", "her", "they", "them", "his", "their", "theirs",
}

# Idiomatic impersonal phrases starting with 'it' or 'they' that ARE valid standalone hooks
VALID_IMPERSONAL_HOOK_PREFIXES: Tuple[str, ...] = (
    "they said", "they told us", "they warned", "they never", "they didn't", "they wouldn't",
    "they don't want you to", "they claim", "it turns out", "it is", "it was", "it's time",
    "it takes", "it seems", "it sounds",
)

DANGLING_DEMONSTRATIVES: Tuple[str, ...] = (
    "that thing", "that person", "that place", "that guy", "that woman",
    "those things", "those people", "these things", "these people",
)

# Narrative Claim markers
CLAIM_INDICATORS: Set[str] = {
    "is", "are", "was", "were", "think", "believe", "found", "created",
    "built", "discovered", "rule", "secret", "truth", "problem", "always",
    "never", "every", "most", "everyone", "nobody", "impossible", "simple",
    "best", "worst", "only", "fact",
}

# Narrative Turn markers (Proof, Complication, or Emotional Shift)
PROOF_MARKERS: Set[str] = {
    "because", "shows", "proved", "evidence", "data", "result", "results",
    "numbers", "example", "actually", "in fact", "turns out", "for instance",
    "calculated", "tested", "proves", "measured",
}

COMPLICATION_MARKERS: Set[str] = {
    "but", "however", "except", "yet", "instead", "suddenly", "although",
    "problem is", "catch is", "even though", "despite", "unfortunately",
    "the issue", "trouble", "catch", "twist",
}

EMOTIONAL_SHIFT_MARKERS: Set[str] = {
    "shocking", "terrified", "excited", "unbelievable", "couldn't believe",
    "mindblowing", "insane", "game changer", "realized", "devastating",
    "amazing", "astonished", "fear", "craziest", "wild",
}

# Leading connectors and fillers that precede substantive thought openers
LEADING_CONNECTORS: Set[str] = {
    "and", "because", "so", "or", "then", "like", "basically", "literally", "well", "but", "uh", "um",
}

# Trailing single-word fragments indicating an unresolved sentence ending
TRAILING_CONJUNCTIONS: Set[str] = {
    "and", "or", "so", "because", "but", "which", "that", "like", "if",
    "when", "with", "as", "than", "to", "of", "in", "for", "the", "a", "an",
    "uh", "um", "then",
}

# Multi-word trailing filler phrases
MULTI_WORD_TRAILING_PHRASES: Tuple[str, ...] = (
    "you know", "kind of", "sort of", "or something",
)

DEFINITIVE_PAYOFF_ENDINGS: Tuple[str, ...] = (
    "changes everything", "that's why", "that is why", "the bottom line",
    "the point is", "worth it", "not worth it", "never again", "every single time",
    "and that's that", "lesson learned", "period", "guaranteed", "no doubt",
)


@dataclass
class ViabilityCheckResult:
    """Detailed audit of candidate short standalone viability."""
    is_viable: bool
    complete_thought_opening: bool
    narrative_turn: bool
    clean_resolution: bool
    loop_hook_score: float                  # 0.0 to 10.0
    loop_hook_suggestion: str
    overall_viability_score: float          # 0.0 to 100.0
    opening_critique: str
    narrative_critique: str
    resolution_critique: str
    reasons_for_rejection: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_viable": self.is_viable,
            "complete_thought_opening": self.complete_thought_opening,
            "narrative_turn": self.narrative_turn,
            "clean_resolution": self.clean_resolution,
            "loop_hook_score": round(self.loop_hook_score, 1),
            "loop_hook_suggestion": self.loop_hook_suggestion,
            "overall_viability_score": round(self.overall_viability_score, 1),
            "opening_critique": self.opening_critique,
            "narrative_critique": self.narrative_critique,
            "resolution_critique": self.resolution_critique,
            "reasons_for_rejection": self.reasons_for_rejection,
        }


class ShortViabilityValidator:
    """
    Validates that a video candidate survives completely without outside context.
    """

    def __init__(
        self,
        min_loop_score_warning: float = 4.0,
    ):
        self.min_loop_score_warning = min_loop_score_warning

    def validate_complete_thought_opening(self, text: str) -> Tuple[bool, str]:
        """
        Criterion 1: Complete Thought Opening.
        Verifies that the opening does not rely on dangling pronouns referring to unstated prior context.
        """
        cleaned = text.strip()
        if not cleaned:
            return False, "Candidate transcript is completely empty."

        words = [re.sub(r"[^\w]", "", w).lower() for w in cleaned.split() if re.sub(r"[^\w]", "", w)]
        if not words:
            return False, "No valid linguistic tokens found in candidate opening."

        text_lower = cleaned.lower()

        # Check explicit dangling demonstrative phrases ("that thing", "those people") on full text
        for dem in DANGLING_DEMONSTRATIVES:
            if text_lower.startswith(dem):
                return False, f"Opens with dangling demonstrative '{dem}' referring to unstated prior context."

        # Check if opened with connector/filler before inspecting core subject
        idx = 0
        while idx < len(words) and words[idx] in LEADING_CONNECTORS:
            idx += 1

        substantive_words = words[idx:] if idx < len(words) else words
        substantive_text = " ".join(substantive_words)

        # Check demonstrative phrases after leading connectors (e.g. "And that thing...")
        for dem in DANGLING_DEMONSTRATIVES:
            if substantive_text.startswith(dem):
                return False, f"Opens with dangling demonstrative '{dem}' referring to unstated prior context."

        first_word = substantive_words[0] if substantive_words else words[0]

        # Check dangling pronouns
        if first_word in DANGLING_PRONOUNS:
            # Check if this matches a known valid provocative hook ("they said you couldn't")
            if any(substantive_text.startswith(prefix) for prefix in VALID_IMPERSONAL_HOOK_PREFIXES):
                return True, "Opens with intentional provocative collective hook."
            return False, f"Opens with dangling pronoun '{first_word}' with no prior referent."

        return True, "Complete thought opening with established subject."

    def validate_narrative_turn(self, text: str) -> Tuple[bool, str]:
        """
        Criterion 2: The Narrative Turn.
        Verifies that the text contains a claim followed by proof, complication, or emotional shift.
        """
        cleaned = text.strip()
        words = [re.sub(r"[^\w]", "", w).lower() for w in cleaned.split() if re.sub(r"[^\w]", "", w)]
        if len(words) < 8:
            return False, "Clip is too brief (< 8 words) to form a complete narrative turn."

        text_lower = cleaned.lower()

        # Detect claim presence in early-to-mid section
        first_half = words[: max(len(words) // 2, 6)]
        second_half = words[min(len(words) // 3, 4) :]

        has_claim = any(w in CLAIM_INDICATORS for w in first_half) or any(
            w in {"secret", "why", "how", "never", "best", "worst"} for w in first_half
        )

        # Detect turn elements in second portion
        has_proof = any(w in PROOF_MARKERS for w in second_half)
        has_complication = any(w in COMPLICATION_MARKERS for w in second_half)
        has_emotional_shift = any(w in EMOTIONAL_SHIFT_MARKERS for w in second_half) or any(
            phrase in text_lower for phrase in ["turns out", "problem is", "in fact", "actually"]
        )

        turn_types = []
        if has_proof:
            turn_types.append("proof/evidence")
        if has_complication:
            turn_types.append("complication/contrast")
        if has_emotional_shift:
            turn_types.append("emotional shift/revelation")

        if has_claim and turn_types:
            return True, f"Narrative turn present: claim anchored with {', '.join(turn_types)}."
        elif turn_types:
            # Turn present even if claim was informal
            return True, f"Narrative progression established via {', '.join(turn_types)}."
        elif has_claim:
            return False, "Clip makes a claim but ends without proof, complication, or emotional shift."
        else:
            return False, "Monotonic commentary lacking narrative tension or revelation."

    def validate_clean_resolution(self, text: str) -> Tuple[bool, str]:
        """
        Criterion 3: Clean Resolution.
        Verifies that the clip ends on a definitive punchline or complete declarative statement,
        not a trailing sentence fragment or dangling conjunction.
        """
        cleaned = text.strip()
        if not cleaned:
            return False, "Candidate transcript is empty."

        # Check trailing ellipsis
        if cleaned.endswith("...") or cleaned.endswith("…"):
            return False, "Clip trails off with unfinished ellipsis."

        # Extract normalized words
        words = cleaned.split()
        if not words:
            return False, "No words in transcript."

        norm_words = [re.sub(r"[^\w]", "", w).lower() for w in words if re.sub(r"[^\w]", "", w)]
        last_word_norm = norm_words[-1] if norm_words else ""

        # Check trailing multi-word filler phrases (e.g. 'you know', 'kind of')
        if len(norm_words) >= 2:
            tail_2 = " ".join(norm_words[-2:])
            if tail_2 in MULTI_WORD_TRAILING_PHRASES:
                return False, f"Ends on trailing filler phrase '{tail_2}'."
        if len(norm_words) >= 3:
            tail_3 = " ".join(norm_words[-3:])
            if tail_3 in MULTI_WORD_TRAILING_PHRASES:
                return False, f"Ends on trailing filler phrase '{tail_3}'."

        # Reject trailing conjunctions/prepositions
        if last_word_norm in TRAILING_CONJUNCTIONS:
            return False, f"Ends on trailing conjunction/fragment '{last_word_norm}'."

        text_lower = cleaned.lower()

        # Check bonus payoff endings
        for payoff in DEFINITIVE_PAYOFF_ENDINGS:
            if text_lower.endswith(payoff) or payoff in " ".join(words[-6:]).lower():
                return True, f"Clean resolution on definitive payoff: '{payoff}'."

        # Punctuation check
        if cleaned[-1] in {".", "!", "?"}:
            return True, "Clean declarative sentence resolution."
        elif cleaned[-1] in {'"', "'"} and len(cleaned) > 1 and cleaned[-2] in {".", "!", "?"}:
            return True, "Clean quoted sentence resolution."

        return False, "Sentence ends without definitive terminal punctuation."

    def evaluate_loop_hook(
        self,
        opening_text: str,
        closing_text: str,
    ) -> Tuple[float, str, str]:
        """
        Criterion 4: Loop Hook Continuity.
        Evaluates and crafts seamless looping from the final line into the opening frame.
        Returns: (loop_score, rationale, loop_hook_suggestion).
        """
        op_words = [re.sub(r"[^\w]", "", w).lower() for w in opening_text.split() if re.sub(r"[^\w]", "", w)]
        cl_words = [re.sub(r"[^\w]", "", w).lower() for w in closing_text.split() if re.sub(r"[^\w]", "", w)]

        if not op_words or not cl_words:
            return 5.0, "Insufficient text to score loop continuity.", ""

        first_op_word = op_words[0]
        last_cl_word = cl_words[-1]
        op_subject = " ".join(op_words[:3])

        # Syntactic bridge: ending poses question or preposition that opening answers
        if closing_text.strip().endswith("?") and first_op_word not in {"why", "how", "what"}:
            return 9.5, "Seamless loop: final question resolved immediately by opening frame.", ""

        # Ending leads into subject ("and that is why...", "which brings us to...")
        closing_phrase = " ".join(cl_words[-4:])
        if any(bridge in closing_phrase for bridge in ["reason why", "way to", "leads to", "because of", "explains why"]):
            return 9.0, f"Strong syntactic loop: '{closing_phrase}' flows directly into opening frame.", ""

        # Semantic loop: shared subject or keywords between closing and opening
        common_keywords = set(cl_words[-6:]).intersection(set(op_words[:6])) - {
            "the", "a", "an", "is", "it", "to", "in", "and", "that", "this", "of"
        }
        if common_keywords:
            kw = list(common_keywords)[0]
            return 8.5, f"Thematic loop: closing echoes key concept '{kw}' from opening frame.", ""

        # Default suggestion
        suggested = f"...and that's exactly why {op_subject}"
        return 7.0, "Satisfactory narrative cycle.", suggested

    def validate_candidate(
        self,
        candidate: HighlightCandidate,
        transcript: Optional[Transcript] = None,
    ) -> ViabilityCheckResult:
        """
        Validates complete Short Viability against the four 'Survives Without Context' criteria.
        """
        text = candidate.transcript_text.strip()
        if not text and transcript:
            matching = [
                s.text for s in transcript.segments
                if s.end >= candidate.start_seconds and s.start <= candidate.end_seconds
            ]
            text = " ".join(matching).strip()

        # 1. Opening Thought
        op_ok, op_critique = self.validate_complete_thought_opening(text)

        # 2. Narrative Turn
        turn_ok, turn_critique = self.validate_narrative_turn(text)

        # 3. Clean Resolution
        res_ok, res_critique = self.validate_clean_resolution(text)

        # 4. Loop Hook (preserve terminal punctuation so question bridges are correctly detected)
        sentences = [s.strip() for s in re.findall(r"[^.!?]+(?:[.!?]+|$)", text) if s.strip()]
        opening_sent = sentences[0] if sentences else text
        closing_sent = sentences[-1] if sentences else text
        loop_score, loop_critique, loop_suggestion = self.evaluate_loop_hook(opening_sent, closing_sent)

        reasons: List[str] = []
        if not op_ok:
            reasons.append(op_critique)
        if not turn_ok:
            reasons.append(turn_critique)
        if not res_ok:
            reasons.append(res_critique)

        is_viable = op_ok and turn_ok and res_ok

        # Overall Viability Composite (0 to 100)
        overall_score = (
            (35.0 if op_ok else 5.0) +
            (35.0 if turn_ok else 5.0) +
            (20.0 if res_ok else 5.0) +
            (loop_score * 1.0)
        )

        return ViabilityCheckResult(
            is_viable=is_viable,
            complete_thought_opening=op_ok,
            narrative_turn=turn_ok,
            clean_resolution=res_ok,
            loop_hook_score=loop_score,
            loop_hook_suggestion=loop_suggestion,
            overall_viability_score=round(overall_score, 1),
            opening_critique=op_critique,
            narrative_critique=turn_critique,
            resolution_critique=res_critique,
            reasons_for_rejection=reasons,
        )
