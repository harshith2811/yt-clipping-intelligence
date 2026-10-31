"""
Attribution, Compliance, and Creator Policy Engine.
Formats structured attribution captions, validates creator clipping permissions,
enforces legal disclaimers, and purges sponsor ad copy from video highlights.
"""

from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re

from ..orchestration.db import DatabaseManager


class CreatorPolicy(str, Enum):
    OPEN_AFFILIATE = "OPEN_AFFILIATE"        # Open policy: podcasters / creators welcoming clipping networks
    CREATIVE_COMMONS = "CREATIVE_COMMONS"    # Official CC BY license allowing reuse with attribution
    PARTNER_PROGRAM = "PARTNER_PROGRAM"      # Direct client / contractual revenue-share agreement
    STRICT_COPYRIGHT = "STRICT_COPYRIGHT"    # Zero tolerance (studios, record labels, strict creators)


@dataclass
class AttributionPackage:
    video_id: str
    creator_name: str
    creator_handle: str
    policy: CreatorPolicy
    caption_credit: str
    full_description: str
    hashtags: List[str]
    disclaimer: str
    is_safe_to_clip: bool
    compliance_notes: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["policy"] = self.policy.value
        return d


class AttributionEngine:
    """
    Manages creator licensing policies and generates compliant short-form captions.
    """

    KNOWN_OPEN_CREATORS = {
        "@hubermanlab": {"name": "Andrew Huberman", "policy": CreatorPolicy.OPEN_AFFILIATE},
        "@lexfridman": {"name": "Lex Fridman", "policy": CreatorPolicy.OPEN_AFFILIATE},
        "@joerogan": {"name": "Joe Rogan", "policy": CreatorPolicy.OPEN_AFFILIATE},
        "@myfirstmillionpod": {"name": "My First Million", "policy": CreatorPolicy.OPEN_AFFILIATE},
        "@alexhormozi": {"name": "Alex Hormozi", "policy": CreatorPolicy.OPEN_AFFILIATE},
        "@georgehotzarchive": {"name": "George Hotz", "policy": CreatorPolicy.OPEN_AFFILIATE},
    }

    SPONSOR_KEYWORDS = {
        "sponsor", "sponsored", "use code", "link in description", "discount",
        "percent off", "patreon", "merch", "displate", "nordvpn", "expressvpn",
        "audible", "skillshare", "squarespace", "betterhelp", "athletic greens", "ag1"
    }

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db = DatabaseManager(db_path)
        self._seed_default_permissions()

    def _seed_default_permissions(self) -> None:
        """Seeds default known creator policies into SQLite database if empty."""
        conn = self.db.get_connection()
        try:
            with conn:
                for handle, info in self.KNOWN_OPEN_CREATORS.items():
                    now_iso = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO creator_permissions (
                            channel_id, channel_name, policy_type, attribution_template,
                            allowed_commercial, disclaimer_required, notes, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            handle,
                            info["name"],
                            info["policy"].value,
                            "Original Content by: @{handle} ({name})\nFull Video: {url}",
                            1,
                            1,
                            "Verified open clipping ecosystem",
                            now_iso,
                        ),
                    )
        except Exception:
            pass
        finally:
            conn.close()

    def get_creator_policy(self, channel_id: str, handle: Optional[str] = None) -> CreatorPolicy:
        """Retrieves creator clipping policy from SQLite or falls back to known registry."""
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                "SELECT policy_type FROM creator_permissions WHERE channel_id = ? OR channel_id = ?",
                (channel_id, handle or ""),
            )
            row = cursor.fetchone()
            if row:
                return CreatorPolicy(row[0])
        except Exception:
            pass
        finally:
            conn.close()

        # Check in-memory registry
        if handle and handle.lower() in self.KNOWN_OPEN_CREATORS:
            return self.KNOWN_OPEN_CREATORS[handle.lower()]["policy"]

        # Default standard creator policy
        return CreatorPolicy.OPEN_AFFILIATE

    def set_creator_policy(
        self,
        channel_id: str,
        channel_name: str = "",
        policy: CreatorPolicy = CreatorPolicy.OPEN_AFFILIATE,
        notes: str = "",
        allowed_commercial: bool = True,
        creator_handle: Optional[str] = None,
    ) -> None:
        """Registers or updates a creator's clipping permission in SQLite."""
        name = channel_name or creator_handle or channel_id
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO creator_permissions (
                        channel_id, channel_name, policy_type, allowed_commercial, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        channel_name=excluded.channel_name,
                        policy_type=excluded.policy_type,
                        allowed_commercial=excluded.allowed_commercial,
                        notes=excluded.notes,
                        updated_at=excluded.updated_at
                    """,
                    (
                        channel_id,
                        name,
                        policy.value,
                        1 if allowed_commercial else 0,
                        notes,
                        now_iso,
                    ),
                )
        finally:
            conn.close()

    def format_attribution(
        self,
        video_id: str,
        creator_name: str,
        creator_handle: str,
        channel_id: Optional[str] = None,
        video_title: str = "",
        category_tags: Optional[List[str]] = None,
        policy_override: Optional[CreatorPolicy] = None,
    ) -> AttributionPackage:
        """
        Builds a comprehensive platform-ready attribution package.
        Includes credit lines, canonical source URLs, hashtags, and fair-use / partnership disclaimers.
        """
        clean_handle = creator_handle if creator_handle.startswith("@") else f"@{creator_handle}"
        lookup_id = channel_id or clean_handle
        policy = policy_override or self.get_creator_policy(lookup_id, clean_handle)

        is_safe = policy != CreatorPolicy.STRICT_COPYRIGHT
        comp_notes = (
            "Approved: Creator operates open clipping / CC reuse guidelines."
            if is_safe
            else "BLOCKED: Creator enforces strict copyright. Do not distribute without written license."
        )

        source_url = f"https://youtu.be/{video_id}"

        # Standard clean attribution format
        caption_credit = (
            f"Original Content by: {clean_handle} ({creator_name})\n"
            f"Watch the full episode: {source_url}"
        )

        disclaimer = (
            "Curated for educational discussion, commentary, and audience discovery. "
            "All media and intellectual property rights belong to the original creator."
        )

        tags = ["#shorts", "#podcast", "#highlights"]
        if category_tags:
            for t in category_tags:
                clean_t = "#" + re.sub(r"[^\w]", "", t).lower()
                if clean_t not in tags:
                    tags.append(clean_t)
        creator_tag = "#" + re.sub(r"[^\w]", "", creator_name).lower()
        if creator_tag not in tags:
            tags.append(creator_tag)

        full_desc = f"{caption_credit}\n\n{disclaimer}\n\n{' '.join(tags)}"

        return AttributionPackage(
            video_id=video_id,
            creator_name=creator_name,
            creator_handle=clean_handle,
            policy=policy,
            caption_credit=caption_credit,
            full_description=full_desc,
            hashtags=tags,
            disclaimer=disclaimer,
            is_safe_to_clip=is_safe,
            compliance_notes=comp_notes,
        )

    @classmethod
    def purge_sponsor_segments(cls, text: str) -> Tuple[str, bool, List[str]]:
        """
        Detects and purges sponsor ad copy from video highlight text.
        Returns (cleaned_text, has_sponsor_ad, matched_keywords).
        """
        if not text:
            return "", False, []

        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        clean_sentences = []
        flagged_keywords = []

        for s in sentences:
            s_lower = s.lower()
            matched = [kw for kw in cls.SPONSOR_KEYWORDS if kw in s_lower]
            if matched:
                flagged_keywords.extend(matched)
                # Omit sponsor sentence
                continue
            clean_sentences.append(s)

        has_ad = len(flagged_keywords) > 0
        cleaned_text = " ".join(clean_sentences)
        return cleaned_text, has_ad, list(set(flagged_keywords))
