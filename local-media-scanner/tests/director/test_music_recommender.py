from __future__ import annotations

import pytest
from director.music_recommender import (
    extract_query_keywords,
    match_categories,
    select_best_version,
    recommend_music,
    CatalogTrack,
    CatalogVersion,
    AudioCatalog
)

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
        versions={
            "full": CatalogVersion(duration_seconds=180.0, path="/path/full"),
            "30s": CatalogVersion(duration_seconds=30.0, path="/path/30s"),
            "60s": CatalogVersion(duration_seconds=60.0, path="/path/60s")
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
        versions={
            "full": CatalogVersion(duration_seconds=180.0, path="/path/full"),
            "30s": CatalogVersion(duration_seconds=30.0, path="/path/30s"),
            "czg3": CatalogVersion(duration_seconds=58.0, path="/path/czg3")
        }
    )
    # Prefer czg3 for 60s target (diff 2s <= 10s)
    tag, version = select_best_version(track, 60.0)
    assert tag == "czg3"

def test_unknown_keywords():
    brief = "这不包含任何已知关键词"
    keywords = extract_query_keywords(brief)
    assert len(keywords) == 0
    categories = match_categories(keywords)
    assert len(categories) == 0
    
    catalog = AudioCatalog(tracks=[])
    result = recommend_music(catalog, brief, 30.0)
    assert len(result.recommendations) == 0

def test_recommend_music_score_ranking():
    catalog = AudioCatalog(tracks=[
        CatalogTrack(
            track_id="1",
            title="Track 1",
            category="旅拍风",
            versions={
                "30s": CatalogVersion(duration_seconds=30.0, path="/1/30s"),
                "full": CatalogVersion(duration_seconds=120.0, path="/1/full")
            }
        ),
        CatalogTrack(
            track_id="2",
            title="Track 2",
            category="旅拍风",
            versions={
                "40s": CatalogVersion(duration_seconds=40.0, path="/2/40s"),
                "full": CatalogVersion(duration_seconds=120.0, path="/2/full")
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
