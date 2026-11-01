"""
Sentence-Level Linguistic Classifier for Narrative Arc Detection.
Splits transcript into sentence-level units and classifies each sentence's
narrative role (HOOK, CONTEXT, ESCALATION, REVELATION, PAYOFF, FILLER, SPONSOR)
using deterministic linguistic pattern matching. Zero external dependencies.
Runs in < 5ms for a 10-minute transcript.
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from ..contracts.models import Transcript, TranscriptSegment, WordTimestamp


# Sentence narrative role constants
HOOK = "HOOK"
CONTEXT = "CONTEXT"
ESCALATION = "ESCALATION"
REVELATION = "REVELATION"
PAYOFF = "PAYOFF"
FILLER = "FILLER"
SPONSOR = "SPONSOR"

# --- Pattern Definitions ---

SPONSOR_PHRASES = frozenset({
    "sponsor", "sponsored", "use code", "link in description", "discount",
    "percent off", "patreon", "merch", "displate", "nordvpn", "expressvpn",
    "audible", "skillshare", "squarespace", "brilliant.org", "curiositystream",
    "surfshark", "dashlane", "lastpass", "raid shadow legends", "buy now",
})

HOOK_QUESTION_WORDS = frozenset({
    "why", "how", "what", "is", "can", "will", "should", "does", "did",
    "have", "has", "are", "do", "could", "would",
})

HOOK_BOLD_ABSOLUTES = frozenset({
    "never", "always", "the only", "the best", "the worst", "no one",
    "everyone", "nobody", "everything", "nothing", "impossible",
    "game changer", "game-changer", "once and for all",
})

HOOK_PROVOCATIVE = frozenset({
    "they said", "everyone thinks", "nobody expects", "you won't believe",
    "here's the thing", "here is the thing", "the thing is", "let me tell you",
    "i need to tell you", "stop doing", "stop using", "they wouldn't",
    "they didn't", "they told me", "people don't realize",
    "here is", "here's", "the secret", "secret to", "secret of",
})

HOOK_IMPERATIVES = frozenset({
    "look", "listen", "stop", "watch", "imagine", "think", "consider",
    "forget", "remember", "notice", "check", "see",
})

ESCALATION_MARKERS = frozenset({
    "but", "however", "not just", "even more", "on top of that", "and then",
    "it gets", "that's not all", "wait", "here's where", "the crazy thing",
    "what's more", "more importantly", "not only", "way more",
    "it somehow", "somehow", "on the other hand",
})

REVELATION_TRIGGERS = frozenset({
    "turns out", "actually", "in fact", "the real reason", "the truth is",
    "here's the thing", "fun fact", "it doesn't work", "they didn't",
    "there's no", "it's not", "that's not", "what they don't tell you",
    "the secret is", "realized", "discovered", "it turns out",
    "the honest answer", "spoiler", "plot twist",
})

RHETORICAL_CLOSING_PATTERNS = frozenset({
    "would you", "could you", "what do you", "have you", "how about",
    "do you think", "will you", "should you", "can you", "after seeing",
})

PAYOFF_CONCLUSION_MARKERS = frozenset({
    "my take", "at the end of the day", "the bottom line", "so yeah",
    "that's why", "and that's", "the point is", "in conclusion",
    "all in all", "final thoughts", "so i'm", "i'm fine with",
    "i'm cool with", "that seems to be", "either way",
})

PAYOFF_EMOTION_RESOLUTION = frozenset({
    "love it", "hate it", "incredible", "awesome", "terrible", "amazing",
    "beautiful", "insane", "sick", "peace", "let me know", "that's it",
    "worth it", "not worth it", "makes a big difference",
    "might be really nice", "pretty cool",
})

PAYOFF_CLIMAX_MARKERS = frozenset({
    "changes everything", "blow your mind", "completely", "solution",
    "the reason is", "that is how", "that's how", "that is why", "that's why",
    "turns out", "it turns out", "in fact", "the point is", "my take",
    "at the end of the day", "the bottom line", "so yeah", "and that's",
    "i'm fine with", "i'm cool with", "worth it", "not worth it",
    "makes a big difference", "pretty cool", "peace", "let me know",
})

WEAK_OPENERS = frozenset({
    "and", "or", "but", "so", "because", "then", "which", "he", "she",
    "uh", "um", "like", "also", "it",
})

PROVOCATIVE_THEY_HOOKS = (
    "they said", "they told", "they warned", "they promised",
    "they claimed", "they wouldn't", "they didn't", "they never",
)

CONTRAST_BUT_HOOKS = (
    "but actually", "but wait", "but here's", "but why",
    "but the truth", "but what", "but somehow",
)

WEAK_ENDINGS = frozenset({
    "kind of", "sort of", "i guess", "i don't know", "whatever",
    "you know", "or something", "or whatever",
})

FILLER_STARTERS = frozenset({"uh", "um", "like", "yeah"})

ABBREVIATIONS = frozenset({
    "mr.", "mrs.", "dr.", "vs.", "etc.", "e.g.", "i.e.", "u.s.", "u.k.",
    "a.m.", "p.m.", "inc.", "ltd.", "st.", "ft.",
})


@dataclass
class ClassifiedSentence:
    """A sentence extracted from transcript with its narrative role classification."""
    text: str
    start: float
    end: float
    sentence_type: str = CONTEXT
    confidence: float = 0.8
    word_count: int = 0
    words: List[WordTimestamp] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.01)


class SentenceClassifier:
    """
    Splits transcript into sentence-level units and classifies each sentence's
    narrative role using deterministic linguistic pattern matching.

    Performance: < 5ms for a 654s (10-minute) video with 380 segments.
    """

    def __init__(self, min_sentence_words: int = 3):
        self.min_sentence_words = min_sentence_words

    def classify_transcript(self, transcript: Transcript) -> List[ClassifiedSentence]:
        """
        Splits transcript into sentences using word-level timestamps,
        then classifies each sentence's narrative role.

        Returns sentences sorted chronologically by start time.
        """
        sentences = self._split_into_sentences(transcript)
        if not sentences:
            return []

        total_duration = transcript.duration_seconds or (sentences[-1].end if sentences else 1.0)
        classified: List[ClassifiedSentence] = []

        for i, sent in enumerate(sentences):
            position_ratio = sent.start / max(total_duration, 1.0)
            prev_type = classified[-1].sentence_type if classified else None

            sent_type, confidence = self._classify_sentence(
                text=sent.text,
                prev_type=prev_type,
                position_ratio=position_ratio,
                is_first=(i == 0),
                is_last=(i == len(sentences) - 1),
            )

            sent.sentence_type = sent_type
            sent.confidence = confidence
            classified.append(sent)

        return classified

    def _split_into_sentences(self, transcript: Transcript) -> List[ClassifiedSentence]:
        """
        Splits transcript into sentences using word-level timestamps for precise boundaries.
        Falls back to segment-level splitting when word timestamps are unavailable.
        """
        # Collect all words with timestamps across all segments
        all_words: List[WordTimestamp] = []
        seg_terminal_word_ids = set()

        for seg in transcript.segments:
            if seg.words:
                all_words.extend(seg.words)
                if seg.text.strip().endswith(('.', '!', '?')):
                    seg_terminal_word_ids.add(id(seg.words[-1]))

        if not all_words:
            # Fallback: use segments directly as sentence proxies
            return self._split_segments_into_sentences(transcript.segments)

        sentences: List[ClassifiedSentence] = []
        current_words: List[WordTimestamp] = []

        for word in all_words:
            current_words.append(word)
            raw_word = word.word.strip()

            # Check if this word ends a sentence
            is_seg_end = id(word) in seg_terminal_word_ids
            if raw_word.endswith(('.', '!', '?')) or is_seg_end:
                # Don't split on abbreviations
                cleaned = raw_word.lower()
                if cleaned in ABBREVIATIONS:
                    continue

                # Don't create tiny "sentences" (< min_sentence_words)
                # unless it's a strong exclamation
                if len(current_words) < self.min_sentence_words and not raw_word.endswith('!'):
                    continue

                sentence_text = ' '.join(w.word for w in current_words).strip()
                if sentence_text:
                    sentences.append(ClassifiedSentence(
                        text=sentence_text,
                        start=current_words[0].start,
                        end=current_words[-1].end,
                        word_count=len(current_words),
                        words=list(current_words),
                    ))
                current_words = []

        # Handle remaining words (no terminal punctuation — unterminated final sentence)
        if current_words:
            sentence_text = ' '.join(w.word for w in current_words).strip()
            if sentence_text and len(current_words) >= self.min_sentence_words:
                sentences.append(ClassifiedSentence(
                    text=sentence_text,
                    start=current_words[0].start,
                    end=current_words[-1].end,
                    word_count=len(current_words),
                    words=list(current_words),
                ))

        return sentences

    def _split_segments_into_sentences(
        self, segments: List[TranscriptSegment]
    ) -> List[ClassifiedSentence]:
        """Fallback: splits segments into sentences when word timestamps are unavailable."""
        sentences: List[ClassifiedSentence] = []
        accumulated_text = ""
        acc_start: Optional[float] = None
        acc_end = 0.0

        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue

            if acc_start is None:
                acc_start = seg.start

            accumulated_text += (" " if accumulated_text else "") + text
            acc_end = seg.end

            if text.endswith(('.', '!', '?')):
                word_count = len(accumulated_text.split())
                if word_count >= self.min_sentence_words:
                    sentences.append(ClassifiedSentence(
                        text=accumulated_text.strip(),
                        start=acc_start,
                        end=acc_end,
                        sentence_type=CONTEXT,
                        word_count=word_count,
                    ))
                    accumulated_text = ""
                    acc_start = None

        # Handle remaining
        if accumulated_text.strip() and acc_start is not None:
            sentences.append(ClassifiedSentence(
                text=accumulated_text.strip(),
                start=acc_start,
                end=acc_end,
                sentence_type=CONTEXT,
                word_count=len(accumulated_text.split()),
            ))

        return sentences

    def _classify_sentence(
        self,
        text: str,
        prev_type: Optional[str],
        position_ratio: float,
        is_first: bool,
        is_last: bool,
    ) -> Tuple[str, float]:
        """
        Classifies a sentence into its narrative role using multi-signal pattern matching.
        Returns (sentence_type, confidence).
        """
        # Strip leading quote markers (">>") from YouTube transcript formatting
        clean_text = text.strip()
        if clean_text.startswith(">>"):
            clean_text = clean_text.lstrip(">").strip()
        lower = clean_text.lower()
        words = clean_text.split()
        first_word = words[0].lower().rstrip('.,!?;:') if words else ""

        # Priority 1: Sponsor detection (highest priority — must be excluded)
        if any(sp in lower for sp in SPONSOR_PHRASES):
            return SPONSOR, 0.95

        # Priority 2: Filler detection (short, low-information sentences)
        if (first_word in FILLER_STARTERS and len(words) < 8 and
                not any(t in lower for t in REVELATION_TRIGGERS) and
                not any(t in lower for t in ESCALATION_MARKERS)):
            return FILLER, 0.7

        # Compute scores for each candidate type
        hook_score = self._score_as_hook(clean_text, lower, first_word, words, is_first, position_ratio)
        revelation_score = self._score_as_revelation(clean_text, lower, words)
        payoff_score = self._score_as_payoff(clean_text, lower, words, is_last, position_ratio)
        escalation_score = self._score_as_escalation(clean_text, lower, first_word, prev_type)

        # Pick highest scoring type
        scores = {
            HOOK: hook_score,
            REVELATION: revelation_score,
            PAYOFF: payoff_score,
            ESCALATION: escalation_score,
        }

        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        # Only classify as non-CONTEXT if score is above threshold
        if best_score >= 2.0:
            confidence = min(0.5 + best_score * 0.08, 0.95)
            return best_type, confidence

        return CONTEXT, 0.6

    def _score_as_hook(
        self, text: str, lower: str, first_word: str,
        words: list, is_first: bool, position_ratio: float,
    ) -> float:
        """Scores how likely this sentence is a HOOK (attention-grabbing opener)."""
        score = 0.0

        # Check if question is a rhetorical closing question
        is_closing_question = text.strip().endswith('?') and any(lower.startswith(q) or q in lower for q in RHETORICAL_CLOSING_PATTERNS)

        # Question opening (first word is question word AND sentence ends with ?)
        if first_word in HOOK_QUESTION_WORDS and text.strip().endswith('?') and not is_closing_question:
            score += 3.0
        elif first_word in HOOK_QUESTION_WORDS and not is_closing_question:
            score += 1.5

        # Bold absolute claims ("never", "always", "the only", etc.)
        if any(ba in lower for ba in HOOK_BOLD_ABSOLUTES):
            score += 2.0

        # Provocative patterns ("they said", "everyone thinks", etc.)
        if any(p in lower for p in HOOK_PROVOCATIVE):
            score += 2.5

        # Imperative openings ("Look", "Listen", "Stop", etc.)
        if first_word in HOOK_IMPERATIVES:
            score += 2.0

        # Direct "you" address in first 20 chars
        if first_word == "you" or "you " in lower[:20]:
            score += 1.0

        # Short and punchy (under 12 words)
        if len(words) <= 12:
            score += 0.5

        # Quoted speech (>> markers or leading quotes)
        if text.strip().startswith(">>") or text.strip().startswith('"'):
            score += 1.0

        # Weak/dangling opener penalty — critical for "strong start"
        is_they_hook = (first_word == "they" and any(lower.startswith(th) for th in PROVOCATIVE_THEY_HOOKS))
        is_but_hook = (first_word == "but" and any(lower.startswith(bh) for bh in CONTRAST_BUT_HOOKS))

        if first_word in WEAK_OPENERS and not is_but_hook:
            score -= 2.5
        elif first_word == "they" and not is_they_hook:
            score -= 2.0

        # Anaphoric opening penalty (refers back to previous explanation)
        if lower.startswith("that ") or lower.startswith("and that"):
            score -= 1.5

        # Position boost (hooks more likely near topic transitions)
        if is_first:
            score += 1.0

        return score

    def _score_as_revelation(self, text: str, lower: str, words: list) -> float:
        """Scores how likely this sentence is a REVELATION (surprise/insight)."""
        score = 0.0

        # Revelation trigger phrases
        matched = sum(1 for t in REVELATION_TRIGGERS if t in lower)
        score += matched * 2.0

        # Contains "!" (excitement/surprise)
        if "!" in text:
            score += 1.0

        # Short, punchy revelation
        if len(words) <= 15 and matched > 0:
            score += 0.5

        return score

    def _score_as_payoff(
        self, text: str, lower: str, words: list,
        is_last: bool, position_ratio: float,
    ) -> float:
        """Scores how likely this sentence is a PAYOFF (conclusion/resolution)."""
        score = 0.0

        # Climax markers ("changes everything", "blow your mind", "completely", etc.)
        if any(c in lower for c in PAYOFF_CLIMAX_MARKERS):
            score += 2.5

        # Rhetorical closing question
        is_closing_question = text.strip().endswith('?') and any(lower.startswith(q) or q in lower for q in RHETORICAL_CLOSING_PATTERNS)
        if is_closing_question:
            score += 3.5
        elif text.strip().endswith('?'):
            score += 2.0

        # Anaphoric resolution ("that changes...", "that's why...")
        if lower.startswith("that ") or lower.startswith("and that"):
            score += 1.0

        # Conclusion markers ("my take", "at the end of the day", etc.)
        if any(m in lower for m in PAYOFF_CONCLUSION_MARKERS):
            score += 2.5

        # Emotional resolution ("love it", "awesome", "peace", etc.)
        if any(e in lower for e in PAYOFF_EMOTION_RESOLUTION):
            score += 2.0

        # Strong terminal punctuation
        if text.strip().endswith('!'):
            score += 1.0

        # Position boost (payoffs more likely later in the video)
        if position_ratio > 0.7:
            score += 0.5
        if is_last:
            score += 0.5

        # Weak ending penalty
        last_30 = lower[-30:] if len(lower) > 30 else lower
        if any(w in last_30 for w in WEAK_ENDINGS):
            score -= 1.5

        return score

    def _score_as_escalation(
        self, text: str, lower: str, first_word: str, prev_type: Optional[str],
    ) -> float:
        """Scores how likely this sentence is an ESCALATION (tension builder)."""
        score = 0.0

        # Escalation markers ("but", "however", "not just", "even more", etc.)
        if any(m in lower for m in ESCALATION_MARKERS):
            score += 2.0

        # "But" / "However" at start is a classic escalation signal
        if first_word in ("but", "however"):
            score += 1.5

        # Following a HOOK or CONTEXT makes escalation more structurally likely
        if prev_type in (HOOK, CONTEXT):
            score += 0.5

        return score
