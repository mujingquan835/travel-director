from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field
from director.schema import StrictModel


CATEGORY_KEYWORD_MAP: dict[str, list[str]] = {
    "旅行": ["旅拍风", "慢节奏｜vlog ｜游玩"],
    "旅拍": ["旅拍风", "慢节奏｜vlog ｜游玩"],
    "记录": ["旅拍风", "慢节奏｜vlog ｜游玩"],
    "vlog": ["慢节奏｜vlog ｜游玩"],
    "力量": ["快｜慢节奏｜力量感｜生命力"],
    "生命力": ["快｜慢节奏｜力量感｜生命力"],
    "古风": ["中国风"],
    "传统": ["中国风", "民族音乐"],
    "民族": ["民族音乐"],
    "快节奏": ["快节奏｜户外运动", "快节奏｜户外活动｜亲子游", "快节奏｜欢快青春｜游玩｜表演"],
    "运动": ["快节奏｜户外运动"],
    "活力": ["快节奏｜户外活动｜亲子游"],
    "高级": ["慢节奏｜高级感 奢侈品", "｜女性｜高级感"],
    "优雅": ["慢节奏｜高级感 奢侈品", "｜女性｜高级感"],
    "质感": ["慢节奏｜高级感 奢侈品"],
    "温柔": ["慢节奏｜慢摇 轻松 温柔"],
    "轻松": ["慢节奏｜慢摇 轻松 温柔", "慢节奏｜下午茶"],
    "午后": ["慢节奏｜下午茶"],
    "潮流": ["快节奏｜潮流｜涂鸦滑板街舞"],
    "街头": ["快节奏｜潮流｜涂鸦滑板街舞"],
    "嘔哈": ["快节奏｜潮流｜涂鸦滑板街舞"],
    "断点": ["断点｜穿插剪辑｜音效"],
    "卡点": ["断点｜穿插剪辑｜音效"],
    "战斗": ["快节奏｜激烈战斗｜拳击电竞赛事"],
    "电竞": ["快节奏｜激烈战斗｜拳击电竞赛事"],
    "电子": ["快节奏｜电子风"],
    "科技": ["科技范"],
    "晚会": ["快节奏｜晚会 高端 大气", "慢节奏｜酒室｜晚会｜大提琴"],
    "爵士": ["快节奏｜舞会 爵士"],
    "婚礼": ["婚礼类型"],
    "年会": ["活动年会 发布会｜总结"],
    "发布会": ["活动年会 发布会｜总结"],
    "轻音乐": ["轻音乐"],
    "古城": ["中国风", "民族音乐"],
    "沙漠": ["民族音乐"],
    "少女": ["快节奏｜少女风"],
    "可爱": ["俘皮可爱风"],
    "预告片": ["预告片"],
    "游戏": ["户外｜有趣｜皮卡丘｜游戏活动"],
    "活动": ["快节奏｜商场活动", "快节奏｜amg 活动", "活动预热"],
    "商场": ["快节奏｜商场活动"],
    "積极": ["快节奏｜积极向上"],
    "向上": ["快节奏｜积极向上"],
    "欢快": ["快节奏｜欢快青春｜游玩｜表演"],
    "青春": ["快节奏｜欢快青春｜游玩｜表演"],
    "圣诞": ["圣诞节"],
    "节日": ["快节奏｜欢庆｜节日", "圣诞节"],
    "政企": ["政企活动（传统）", "政企活动（非传统）"],
    "大气": ["快节奏｜晚会 高端 大气"],
    "展会": ["快节奏｜展会"],
    "团建": ["快节奏｜团建活动"],
    "亲子": ["快节奏｜户外活动｜亲子游"],
    "酒吧": ["快节奏｜酒吧"],
    "奢侈品": ["慢节奏｜高级感 奢侈品"],
}

class CatalogVersion(StrictModel):
    duration_seconds: float
    path: str

class CatalogTrack(StrictModel):
    track_id: str
    title: str
    category: str
    versions: dict[str, CatalogVersion]

class AudioCatalog(StrictModel):
    tracks: list[CatalogTrack]

class MusicRecommendation(StrictModel):
    track_id: str
    title: str
    category: str
    selected_version: str
    version_duration_seconds: float
    version_path: str
    match_score: float = Field(ge=0.0, le=1.0)
    match_reasons: list[str]

class RecommendationResult(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    target_duration_seconds: float
    query_keywords: list[str]
    matched_categories: list[str]
    recommendations: list[MusicRecommendation]


def extract_query_keywords(music_brief: str) -> list[str]:
    """
    Tokenize the music_brief text
    Extract Chinese keywords that match keys in CATEGORY_KEYWORD_MAP
    Return sorted unique keywords
    """
    found = set()
    for kw in CATEGORY_KEYWORD_MAP.keys():
        if kw in music_brief:
            found.add(kw)
    return sorted(list(found))


def match_categories(keywords: list[str]) -> list[str]:
    """
    For each keyword, look up matching categories
    Return unique categories sorted by match count (most matches first)
    """
    from collections import Counter
    counts = Counter()
    for kw in keywords:
        cats = CATEGORY_KEYWORD_MAP.get(kw, [])
        for cat in cats:
            counts[cat] += 1
            
    # Sort by count descending, then alphabetically by category
    sorted_cats = sorted(counts.keys(), key=lambda x: (-counts[x], x))
    return sorted_cats


def select_best_version(track: CatalogTrack, target_seconds: float) -> tuple[str, CatalogVersion]:
    """
    Given a CatalogTrack and target duration, select the best pre-made version
    Priority: prefer cutdowns within 10s of target, then closest cutdown, then full
    Return (version_tag, version)
    """
    cutdowns = {}
    full_version = None
    
    for tag, ver in track.versions.items():
        if tag.lower() in ("full", "完整版", "full_track"):
            full_version = (tag, ver)
        else:
            cutdowns[tag] = ver
            
    if not full_version and "full" in track.versions:
        full_version = ("full", track.versions["full"])
        
    valid_cutdowns = {t: v for t, v in cutdowns.items() if abs(v.duration_seconds - target_seconds) <= 10.0}
    if valid_cutdowns:
        best_tag = min(valid_cutdowns.keys(), key=lambda t: abs(valid_cutdowns[t].duration_seconds - target_seconds))
        return best_tag, valid_cutdowns[best_tag]
        
    if cutdowns:
        best_tag = min(cutdowns.keys(), key=lambda t: abs(cutdowns[t].duration_seconds - target_seconds))
        return best_tag, cutdowns[best_tag]
        
    if full_version:
        return full_version
        
    # fallback
    if track.versions:
        best_tag = min(track.versions.keys(), key=lambda t: abs(track.versions[t].duration_seconds - target_seconds))
        return best_tag, track.versions[best_tag]
        
    raise ValueError("Track has no versions")


def recommend_music(catalog: AudioCatalog, music_brief: str, target_duration_seconds: float, limit: int = 5) -> RecommendationResult:
    """
    Main entry point
    Extract keywords from brief
    Match to categories
    For each track in matched categories, score and rank
    Select best version for target duration
    Return top `limit` recommendations
    """
    keywords = extract_query_keywords(music_brief)
    matched_cats = match_categories(keywords)
    
    recommendations = []
    
    for track in catalog.tracks:
        if track.category in matched_cats:
            cat_rank = matched_cats.index(track.category)
            best_tag, best_ver = select_best_version(track, target_duration_seconds)
            dur_diff = abs(best_ver.duration_seconds - target_duration_seconds)
            
            cat_score = 1.0 - (cat_rank * 0.1)
            dur_penalty = dur_diff * 0.001
            score = max(0.0, min(1.0, cat_score - dur_penalty))
            
            reasons = [f"Matched category '{track.category}' from keywords"]
            
            recommendations.append(MusicRecommendation(
                track_id=track.track_id,
                title=track.title,
                category=track.category,
                selected_version=best_tag,
                version_duration_seconds=best_ver.duration_seconds,
                version_path=best_ver.path,
                match_score=round(score, 4),
                match_reasons=reasons
            ))
            
    recommendations.sort(key=lambda r: r.match_score, reverse=True)
    
    return RecommendationResult(
        target_duration_seconds=target_duration_seconds,
        query_keywords=keywords,
        matched_categories=matched_cats,
        recommendations=recommendations[:limit]
    )
