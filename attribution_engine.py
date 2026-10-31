"""
Root entrypoint for AttributionEngine.
Allows direct execution or import via `import attribution_engine`.
"""

from src.yt_clipping.discovery.attribution_engine import (
    AttributionEngine,
    CreatorPolicy,
    AttributionPackage,
)

__all__ = ["AttributionEngine", "CreatorPolicy", "AttributionPackage"]

if __name__ == "__main__":
    engine = AttributionEngine()
    pkg = engine.format_attribution(
        video_id="5ZqolNRkxvM",
        creator_name="Decoding the Zodiac",
        creator_handle="@lemmino",
        category_tags=["truecrime", "mystery"],
    )
    print("Attribution Package:")
    for k, v in pkg.to_dict().items():
        print(f"  {k:<20}: {v}")
