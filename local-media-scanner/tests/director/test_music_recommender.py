from __future__ import annotations

import pytest
from director.music_recommender import (
    extract_query_keywords,
    match_categories,
    select_best_version,
    recommend_music,
)

from director.audio_catalog import AudioCatalog, CatalogTrack, CatalogVersion


def make_version(tag, duration, path):
    return CatalogVersion(version_tag=tag, duration_seconds=duration,
                          relative_path=path, format="wav")


def test_extract_query_keywords():
    brief = "我们需要一段旅行和vlog风格的音乐，稍微有点力量感"
    keywords = extract_query_keywords(brief)
    assert "旅行" in keywords
    assert "vlog" in keywords
    assert "力量" in keywords
    assert "力量感" not in keywords  # "力量" is in the map, "力量感" is in the values

def test_match_categories():
    keywords = ["旅行", "古风"]
    # 旅行 -> ["旅拍风", "慢节奏｜vlog ｜游玩"]
    # 古风 -> ["中国风"]
    categories = match_categories(keywords)
    assert "旅拍风" in categories
    assert "中国风" in categories
    assert "慢节奏｜vlog ｜游玩" in categories

def test_select_best_version_exact_cutdown():
    track = CatalogTrack(
        track_id="1",
        title="Test",
        category="TestCat",
        keywords=[],
        versions={
            "full": make_version("full", 180.0, "path/full.wav"),
            "30s": make_version("30s", 30.0, "path/30s.wav"),
            "60s": make_version("60s", 60.0, "path/60s.wav")
        }
    )
    # Prefer 30s for 30s target
    tag, version = select_best_version(track, 30.0)
    assert tag == "30s"

def test_select_best_version_closest_cutdown():
    track = CatalogTrack(
        track_id="1",
        title="Test",
        category="TestCat",
        keywords=[],
        versions={
            "full": make_version("full", 180.0, "path/full.wav"),
            "30s": make_version("30s", 30.0, "path/30s.wav"),
            "czg3": make_version("czg3", 58.0, "path/czg3.wav")
        }
    )
    # A 58s cut cannot cover a 60s timeline; use the eligible full version.
    tag, version = select_best_version(track, 60.0)
    assert tag == "full"

def test_unknown_keywords():
    brief = "这不包含任何已知关键词"
    keywords = extract_query_keywords(brief)
    assert len(keywords) == 0
    categories = match_categories(keywords)
    assert len(categories) == 0
    
    catalog = AudioCatalog(music_root="/library/音乐", sfx_root="/library/音效", sfx=[], scan_timestamp="test", tracks=[])
    result = recommend_music(catalog, brief, 30.0)
    assert len(result.recommendations) == 0

def test_recommend_music_score_ranking():
    catalog = AudioCatalog(music_root="/library/音乐", sfx_root="/library/音效", sfx=[], scan_timestamp="test", tracks=[
        CatalogTrack(
            track_id="1",
            title="Track 1",
            category="旅拍风",
            keywords=["旅拍"],
            versions={
                "30s": make_version("30s", 30.0, "1/30s.wav"),
                "full": make_version("full", 120.0, "1/full.wav")
            }
        ),
        CatalogTrack(
            track_id="2",
            title="Track 2",
            category="旅拍风",
            keywords=["旅拍"],
            versions={
                "40s": make_version("other", 40.0, "2/40s.wav"),
                "full": make_version("full", 120.0, "2/full.wav")
            }
        )
    ])
    
    brief = "旅行" # matches "旅拍风"
    result = recommend_music(catalog, brief, 30.0)
    
    assert len(result.recommendations) == 2
    # Closer duration match = higher score
    assert result.recommendations[0].track_id == "1"
    assert result.recommendations[1].track_id == "2"
    assert result.recommendations[0].match_score > result.recommendations[1].match_score

    assert result.recommendations[0].version_path == "/library/音乐/1/30s.wav"


@pytest.mark.parametrize("duration", [59.999, 601])
def test_no_eligible_version_is_not_recommended(duration):
    track = CatalogTrack(track_id="short", title="short", category="旅拍风", keywords=[],
                         versions={"full": make_version("full", duration, "short.wav")})
    catalog = AudioCatalog(music_root="/library", sfx_root="/sfx", scan_timestamp="test",
                           tracks=[track], sfx=[])
    assert recommend_music(catalog, "旅行", 60).recommendations == []
