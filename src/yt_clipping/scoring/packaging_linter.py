"""
Packaging & Metadata Quality Gate (Algorithmic mechanics adapted from title.py).
Strict metadata linter for generated YouTube Short titles, descriptions, and thumbnails:
1. Mobile Truncation Safety: Enforce max 40 chars for primary hook (ensuring subject survives
   mobile feed truncation) and hard ceiling at 60 characters.
2. Front-Loading: The first 3 words must not be generic stop words ('the', 'how to', 'this is').
3. Click-Surface Non-Duplication: Reject any thumbnail overlay text that repeats exact words of the title.
4. Vague Buzzword Elimination: Flag and replace lazy adjectives ('insane', 'mindblowing', 'crazy')
   with concrete metrics or proper nouns.
"""

from typing import List, Dict, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
import re

PRIMARY_HOOK_MAX_CHARS = 40
TITLE_HARD_CEILING = 60

GENERIC_STOP_PREFIX_REGEX = re.compile(
    r"^(?:how\s+to|this\s+is|what\s+is|there\s+is|the|a|an)\b[:\s-]*",
    re.IGNORECASE,
)

GENERIC_STOP_WORDS: Set[str] = {
    "the", "how", "to", "this", "is", "what", "there", "a", "an", "and", "of", "in", "it",
}

# Lazy adjectives to flag and replace
LAZY_ADJECTIVES_MAP: Dict[str, str] = {
    "insane": "10x",
    "insanely": "10x",
    "mindblowing": "counterintuitive",
    "mind-blowing": "counterintuitive",
    "crazy": "surprising",
    "crazier": "more surprising",
    "craziest": "most surprising",
    "shocking": "overlooked",
    "unbelievable": "verified",
    "unbelievably": "proven",
    "incredible": "extraordinary",
}


@dataclass
class LintIssue:
    """Represents a packaging rule violation or improvement opportunity."""
    rule: str
    severity: str  # ERROR, WARNING
    message: str
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PackagingLintReport:
    """Consolidated audit report for candidate title and thumbnail packaging."""
    is_valid: bool
    title: str
    cleaned_title: str
    issues: List[LintIssue] = field(default_factory=list)
    passed_mobile_truncation: bool = True
    passed_front_loading: bool = True
    passed_click_surface: bool = True
    passed_buzzword_check: bool = True
    primary_hook_chars: int = 0
    total_chars: int = 0
    detected_buzzwords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "title": self.title,
            "cleaned_title": self.cleaned_title,
            "issues": [i.to_dict() for i in self.issues],
            "passed_mobile_truncation": self.passed_mobile_truncation,
            "passed_front_loading": self.passed_front_loading,
            "passed_click_surface": self.passed_click_surface,
            "passed_buzzword_check": self.passed_buzzword_check,
            "primary_hook_chars": self.primary_hook_chars,
            "total_chars": self.total_chars,
            "detected_buzzwords": self.detected_buzzwords,
        }


class PackagingLinter:
    """
    Strict packaging linter for vertical video titles, hooks, and thumbnail overlays.
    """

    def __init__(
        self,
        primary_hook_max_chars: int = PRIMARY_HOOK_MAX_CHARS,
        title_hard_ceiling: int = TITLE_HARD_CEILING,
        buzzwords_map: Optional[Dict[str, str]] = None,
    ):
        self.primary_hook_max_chars = primary_hook_max_chars
        self.title_hard_ceiling = title_hard_ceiling
        self.buzzwords_map = buzzwords_map or LAZY_ADJECTIVES_MAP

    def extract_primary_hook(self, title: str) -> str:
        """
        Extracts the leading primary hook portion before title delimiters (| - : ? !).
        If no delimiter is found, the primary hook is the title itself.
        """
        cleaned = title.strip()
        # Find first delimiter
        delims = [":", "|", " - ", " – ", "?", "!"]
        first_delim_pos = len(cleaned)
        chosen_delim_len = 0

        for d in delims:
            pos = cleaned.find(d)
            if pos != -1 and pos < first_delim_pos:
                first_delim_pos = pos
                chosen_delim_len = len(d)

        if first_delim_pos < len(cleaned):
            # Include the delimiter mark if it is ? or !
            delimiter_char = cleaned[first_delim_pos : first_delim_pos + chosen_delim_len]
            if delimiter_char in ("?", "!"):
                return cleaned[: first_delim_pos + 1].strip()
            return cleaned[:first_delim_pos].strip()

        return cleaned

    def check_mobile_truncation(self, title: str) -> Tuple[bool, bool, int, int, List[LintIssue]]:
        """
        Verifies primary hook <= 40 chars and title <= 60 chars.
        Returns: (passed_ceiling, passed_hook, total_chars, hook_chars, issues).
        """
        cleaned = title.strip()
        total_len = len(cleaned)
        primary_hook = self.extract_primary_hook(cleaned)
        hook_len = len(primary_hook)

        issues: List[LintIssue] = []
        passed_ceiling = total_len <= self.title_hard_ceiling
        passed_hook = hook_len <= self.primary_hook_max_chars

        if not passed_ceiling:
            issues.append(
                LintIssue(
                    rule="mobile_ceiling_exceeded",
                    severity="ERROR",
                    message=(
                        f"Title has {total_len} characters, exceeding hard ceiling "
                        f"of {self.title_hard_ceiling} characters."
                    ),
                    suggestion=self.truncate_for_mobile(cleaned, self.title_hard_ceiling),
                )
            )

        if not passed_hook:
            issues.append(
                LintIssue(
                    rule="primary_hook_mobile_truncation",
                    severity="ERROR",
                    message=(
                        f"Primary hook has {hook_len} characters, exceeding mobile feed threshold "
                        f"of {self.primary_hook_max_chars} characters. Core subject risks truncation."
                    ),
                    suggestion=self.truncate_for_mobile(primary_hook, self.primary_hook_max_chars),
                )
            )

        return passed_ceiling, passed_hook, total_len, hook_len, issues

    def check_front_loading(self, title: str) -> Tuple[bool, List[LintIssue]]:
        """
        Verifies that the first 3 words are not generic stop words ('the', 'how to', 'this is').
        """
        cleaned = title.strip()
        issues: List[LintIssue] = []

        # 1. Regex generic stop phrases (including trailing colons and spaces)
        if match := GENERIC_STOP_PREFIX_REGEX.match(cleaned):
            prefix = match.group(0)
            stripped = cleaned[len(prefix) :].strip()
            capitalized_suggestion = stripped[0].upper() + stripped[1:] if stripped else cleaned
            issues.append(
                LintIssue(
                    rule="generic_stop_phrase_front",
                    severity="ERROR",
                    message=f"Title begins with generic stop phrase '{prefix.strip()}'. Front-load the core subject.",
                    suggestion=capitalized_suggestion,
                )
            )
            return False, issues

        # 2. Check if all of first 3 words are stop words
        words = [re.sub(r"[^\w]", "", w).lower() for w in cleaned.split() if re.sub(r"[^\w]", "", w)]
        if len(words) >= 3:
            first_three = words[:3]
            if all(w in GENERIC_STOP_WORDS for w in first_three):
                issues.append(
                    LintIssue(
                        rule="first_three_words_stop_words",
                        severity="ERROR",
                        message=(
                            f"First 3 words ({' '.join(first_three)}) are all generic stop words. "
                            f"Lead immediately with concrete nouns, verbs, or metrics."
                        ),
                        suggestion=" ".join(cleaned.split()[2:]),
                    )
                )
                return False, issues

        return True, issues

    def check_click_surface_duplication(
        self,
        title: str,
        thumbnail_text: str,
    ) -> Tuple[bool, List[LintIssue]]:
        """
        Rejects thumbnail overlay text that repeats the exact words of the title.
        Ensures click surfaces provide complementary curiosity rather than redundant clutter.
        """
        issues: List[LintIssue] = []
        if not thumbnail_text or not thumbnail_text.strip():
            return True, issues

        norm_title = re.sub(r"[^\w\s]", "", title.lower()).strip()
        norm_thumb = re.sub(r"[^\w\s]", "", thumbnail_text.lower()).strip()

        title_words = norm_title.split()
        thumb_words = norm_thumb.split()

        # 1. Exact match
        if norm_title == norm_thumb:
            issues.append(
                LintIssue(
                    rule="click_surface_exact_duplicate",
                    severity="ERROR",
                    message="Thumbnail overlay text is identical to the title.",
                    suggestion="Replace thumbnail text with complementary curiosity or visual tease.",
                )
            )
            return False, issues

        # 2. Word sequence phrase duplication (in either direction)
        if len(thumb_words) >= 2 and " ".join(thumb_words) in norm_title:
            issues.append(
                LintIssue(
                    rule="click_surface_phrase_repetition",
                    severity="ERROR",
                    message=f"Thumbnail text '{thumbnail_text}' repeats words directly from the title.",
                    suggestion="Use thumbnail to highlight an emotional reaction or unexpected outcome.",
                )
            )
            return False, issues

        if len(title_words) >= 2 and " ".join(title_words) in norm_thumb:
            issues.append(
                LintIssue(
                    rule="click_surface_phrase_repetition",
                    severity="ERROR",
                    message=f"Thumbnail text '{thumbnail_text}' repeats title words directly.",
                    suggestion="Use thumbnail to provide complementary curiosity rather than repeating title.",
                )
            )
            return False, issues

        # 3. Subset / Super-set containment
        set_title = set(title_words)
        set_thumb = set(thumb_words)
        if len(set_title) >= 2 and set_title.issubset(set_thumb):
            issues.append(
                LintIssue(
                    rule="click_surface_subset_repetition",
                    severity="ERROR",
                    message="Thumbnail text contains all key words from the title.",
                    suggestion="Differentiate thumbnail copy from video title.",
                )
            )
            return False, issues

        # 4. High Jaccard overlap (> 65%)
        if title_words and thumb_words:
            overlap = set_title.intersection(set_thumb)
            jaccard = len(overlap) / max(len(set_title.union(set_thumb)), 1)
            if jaccard >= 0.65:
                issues.append(
                    LintIssue(
                        rule="click_surface_high_redundancy",
                        severity="ERROR",
                        message=f"Thumbnail text shares {jaccard*100:.0f}% word overlap with title.",
                        suggestion="Differentiate thumbnail copy from video title.",
                    )
                )
                return False, issues

        return True, issues

    def detect_buzzwords(self, text: str) -> List[str]:
        """Identifies lazy adjectives like 'insane', 'mindblowing', 'crazy' in text."""
        detected = []
        words = re.findall(r"\b[\w-]+\b", text.lower())
        for w in words:
            if w in self.buzzwords_map and w not in detected:
                detected.append(w)
        return detected

    def replace_buzzwords(
        self,
        text: str,
        custom_replacements: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, List[str]]:
        """
        Replaces lazy adjectives with concrete metrics or precise descriptors.
        Preserves original capitalization (Title, UPPER, or lower).
        """
        replacements = custom_replacements or self.buzzwords_map
        detected: List[str] = []
        result = text

        for buzzword, replacement in replacements.items():
            pattern = re.compile(rf"\b{re.escape(buzzword)}\b", re.IGNORECASE)

            def _replacer(match: re.Match) -> str:
                original = match.group(0)
                detected.append(original.lower())
                if original.isupper():
                    return replacement.upper()
                elif original.istitle():
                    return replacement.capitalize()
                return replacement.lower()

            result = pattern.sub(_replacer, result)

        return result, list(set(detected))

    def truncate_for_mobile(self, text: str, max_chars: int = PRIMARY_HOOK_MAX_CHARS) -> str:
        """
        Intelligently truncates text to fit mobile limits without breaking words mid-way.
        """
        cleaned = text.strip()
        if len(cleaned) <= max_chars:
            return cleaned

        truncated = cleaned[:max_chars].rstrip()
        # Back off to last space
        last_space = truncated.rfind(" ")
        if last_space > int(max_chars * 0.6):
            truncated = truncated[:last_space].rstrip()

        return truncated

    def lint_title(
        self,
        title: str,
        thumbnail_text: Optional[str] = None,
    ) -> PackagingLintReport:
        """
        Executes full metadata linter pass on a Short title and optional thumbnail copy.
        """
        all_issues: List[LintIssue] = []

        # 1. Mobile Truncation Check
        passed_ceiling, passed_hook, total_chars, hook_chars, trunc_issues = self.check_mobile_truncation(title)
        all_issues.extend(trunc_issues)

        # 2. Front-Loading Check
        passed_front, front_issues = self.check_front_loading(title)
        all_issues.extend(front_issues)

        # 3. Click-Surface Duplication Check
        passed_click = True
        if thumbnail_text is not None:
            passed_click, click_issues = self.check_click_surface_duplication(title, thumbnail_text)
            all_issues.extend(click_issues)

        # 4. Buzzword Check & Cleaned Title
        cleaned_title, detected_buzzwords = self.replace_buzzwords(title)
        passed_buzzwords = len(detected_buzzwords) == 0

        if not passed_buzzwords:
            all_issues.append(
                LintIssue(
                    rule="lazy_buzzwords_detected",
                    severity="WARNING",
                    message=(
                        f"Detected vague buzzwords: {', '.join(detected_buzzwords)}. "
                        f"Replace with concrete metrics or proper nouns."
                    ),
                    suggestion=cleaned_title,
                )
            )

        # Title is valid if no ERROR severity issues exist and all core gates passed
        has_error = any(issue.severity == "ERROR" for issue in all_issues)
        is_valid = not has_error and passed_ceiling and passed_hook and passed_front and passed_click

        return PackagingLintReport(
            is_valid=is_valid,
            title=title,
            cleaned_title=cleaned_title,
            issues=all_issues,
            passed_mobile_truncation=passed_ceiling and passed_hook,
            passed_front_loading=passed_front,
            passed_click_surface=passed_click,
            passed_buzzword_check=passed_buzzwords,
            primary_hook_chars=hook_chars,
            total_chars=total_chars,
            detected_buzzwords=detected_buzzwords,
        )

    def sanitize_title(self, title: str, max_chars: Optional[int] = None) -> str:
        """
        Auto-corrects a title by:
        1. Replacing lazy buzzwords with concrete alternatives.
        2. Stripping generic stop prefixes.
        3. Enforcing mobile character boundaries.
        """
        ceiling = max_chars or self.title_hard_ceiling
        # Step 1: Replace buzzwords
        cleaned, _ = self.replace_buzzwords(title)

        # Step 2: Strip generic stop prefixes (including trailing colons and spaces)
        if match := GENERIC_STOP_PREFIX_REGEX.match(cleaned):
            prefix = match.group(0)
            stripped = cleaned[len(prefix) :].strip()
            if stripped:
                cleaned = stripped[0].upper() + stripped[1:]

        # Step 3: Enforce mobile limits
        if len(cleaned) > ceiling:
            cleaned = self.truncate_for_mobile(cleaned, ceiling)

        return cleaned
