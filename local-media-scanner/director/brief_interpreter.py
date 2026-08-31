"""Deterministic creative-brief normalization and offline confirmation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from director.schema import UserCreativeBrief
from director.visual_schema import (
    BRIEF_FIELD_NAMES,
    REQUIRED_BRIEF_FIELDS,
    BriefConfirmation,
    NormalizedBriefFields,
    NormalizedIntentDraft,
    ProviderCapabilities,
    ProviderIssue,
    RawCreativeBrief,
    SourceSpan,
)


STYLE_KEYWORDS = ("明亮", "纪实", "电影感", "治愈", "清新", "复古", "克制")
MOOD_KEYWORDS = ("温暖", "探索", "松弛", "热烈", "宁静", "安静", "怀旧", "欢快")
TRAVEL_TYPE_KEYWORDS = (
    "城市漫游",
    "自然旅行",
    "亲子旅行",
    "人文旅行",
    "美食旅行",
    "自驾旅行",
    "度假旅行",
)
INSTRUMENT_KEYWORDS = ("木吉他", "钢琴", "弦乐", "合成器", "中国鼓", "笛子")


def _raw_sources(field: str, text: str, keywords: Iterable[str]) -> list[SourceSpan]:
    sources: list[SourceSpan] = []
    for keyword in keywords:
        for match in re.finditer(re.escape(keyword), text):
            sources.append(
                SourceSpan(
                    field=field,
                    source_kind="raw_description",
                    text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                )
            )
    return sorted(sources, key=lambda item: (item.start or 0, item.end or 0))


def _unique(values: Iterable[Any]) -> list[Any]:
    output: list[Any] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output


def _duration_sources(text: str) -> tuple[list[tuple[int, SourceSpan]], list[ProviderIssue]]:
    candidates: list[tuple[int, SourceSpan]] = []
    issues: list[ProviderIssue] = []
    occupied: list[tuple[int, int]] = []
    combined = re.compile(r"(?P<minutes>\d+)\s*分(?:钟)?(?:\s*(?P<seconds>\d+)\s*秒)?")
    for match in combined.finditer(text):
        value = int(match.group("minutes")) * 60 + int(match.group("seconds") or 0)
        occupied.append(match.span())
        source = SourceSpan(
            field="target_duration_seconds",
            text=match.group(0),
            start=match.start(),
            end=match.end(),
        )
        if 30 <= value <= 180:
            candidates.append((value, source))
        else:
            issues.append(
                ProviderIssue(
                    code="duration_out_of_range",
                    message="target duration must be between 30 and 180 seconds",
                    field="target_duration_seconds",
                )
            )
    for match in re.finditer(r"(?P<seconds>\d+)\s*秒", text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied):
            continue
        value = int(match.group("seconds"))
        source = SourceSpan(
            field="target_duration_seconds",
            text=match.group(0),
            start=match.start(),
            end=match.end(),
        )
        if 30 <= value <= 180:
            candidates.append((value, source))
        else:
            issues.append(
                ProviderIssue(
                    code="duration_out_of_range",
                    message="target duration must be between 30 and 180 seconds",
                    field="target_duration_seconds",
                )
            )
    return candidates, issues


def _keyword_value_sources(
    field: str, text: str, mapping: dict[str, Any]
) -> list[tuple[Any, SourceSpan]]:
    output: list[tuple[Any, SourceSpan]] = []
    for keyword, value in mapping.items():
        for source in _raw_sources(field, text, [keyword]):
            output.append((value, source))
    return output


class DeterministicBriefInterpreter:
    """Parse only explicit text and structured hints; never infer missing intent."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="deterministic_brief",
            local_only=True,
            supports_abstention=True,
            requires_model_weights=False,
        )

    def normalize(self, brief: RawCreativeBrief) -> NormalizedIntentDraft:
        text = brief.raw_description
        raw_values: dict[str, list[Any]] = {field: [] for field in BRIEF_FIELD_NAMES}
        sources: list[SourceSpan] = []
        issues: list[ProviderIssue] = []

        location_matches = list(
            re.finditer(r"在(?P<location>[\u4e00-\u9fff]{2,8})(?=拍|做|录|旅行|旅拍|游玩)", text)
        )
        for match in location_matches:
            value = match.group("location")
            raw_values["location"].append(value)
            sources.append(
                SourceSpan(
                    field="location",
                    text=value,
                    start=match.start("location"),
                    end=match.end("location"),
                )
            )

        for field, keywords in (
            ("travel_type", TRAVEL_TYPE_KEYWORDS),
            ("style", STYLE_KEYWORDS),
            ("mood", MOOD_KEYWORDS),
            ("instrument_preferences", INSTRUMENT_KEYWORDS),
        ):
            field_sources = _raw_sources(field, text, keywords)
            sources.extend(field_sources)
            raw_values[field].extend(source.text for source in field_sources)

        duration_candidates, duration_issues = _duration_sources(text)
        issues.extend(duration_issues)
        for value, source in duration_candidates:
            raw_values["target_duration_seconds"].append(value)
            sources.append(source)

        mapped_sources = {
            "orientation": _keyword_value_sources(
                "orientation",
                text,
                {"竖屏": "portrait", "9:16": "portrait", "横屏": "landscape", "16:9": "landscape"},
            ),
            "rhythm": _keyword_value_sources(
                "rhythm",
                text,
                {
                    "快节奏": "high",
                    "节奏快": "high",
                    "慢节奏": "low",
                    "舒缓": "low",
                    "中等节奏": "medium",
                    "节奏适中": "medium",
                },
            ),
            "vocals": _keyword_value_sources(
                "vocals",
                text,
                {
                    "纯音乐": "instrumental_only",
                    "不要人声": "instrumental_only",
                    "器乐优先": "instrumental_preferred",
                    "可以有人声": "allowed",
                    "可有人声": "allowed",
                },
            ),
        }
        for field, candidates in mapped_sources.items():
            for value, source in candidates:
                raw_values[field].append(value)
                sources.append(source)

        normalized: dict[str, Any] = {}
        conflicts: set[str] = set()
        composable = {"travel_type", "style", "mood"}
        for field in BRIEF_FIELD_NAMES:
            values = _unique(raw_values[field])
            if field == "instrument_preferences":
                normalized[field] = values
            elif field in composable:
                normalized[field] = "、".join(values) if values else None
            elif len(values) == 1:
                normalized[field] = values[0]
            elif len(values) > 1:
                normalized[field] = None
                conflicts.add(field)
            else:
                normalized[field] = None

        if brief.optional_structured_hints:
            hint_fields = NormalizedBriefFields.model_validate(
                brief.optional_structured_hints
            ).model_dump(mode="json")
            for field in brief.optional_structured_hints:
                hint_value = hint_fields[field]
                sources.append(
                    SourceSpan(
                        field=field,
                        source_kind="structured_hint",
                        text=json.dumps(hint_value, ensure_ascii=False),
                    )
                )
                current = normalized[field]
                if field == "instrument_preferences":
                    normalized[field] = _unique([*current, *hint_value])
                elif current is not None and current != hint_value:
                    normalized[field] = None
                    conflicts.add(field)
                elif current is None and field not in conflicts:
                    normalized[field] = hint_value

        parsed_fields = NormalizedBriefFields.model_validate(normalized)
        unknown = [
            field
            for field in BRIEF_FIELD_NAMES
            if getattr(parsed_fields, field) is None
            or (field == "instrument_preferences" and not parsed_fields.instrument_preferences)
        ]
        review = sorted(
            set(conflicts)
            | {
                field
                for field in REQUIRED_BRIEF_FIELDS
                if getattr(parsed_fields, field) is None
            }
        )
        return NormalizedIntentDraft(
            status="partial" if review else "completed",
            raw_description=text,
            provider="deterministic_brief",
            normalized_fields=parsed_fields,
            source_spans=sorted(
                sources,
                key=lambda item: (
                    item.start is None,
                    item.start if item.start is not None else 0,
                    item.field,
                ),
            ),
            unknown_fields=unknown,
            conflicting_fields=sorted(conflicts),
            review_required_fields=review,
            issues=issues,
        )

    def normalize_legacy(self, brief: UserCreativeBrief) -> NormalizedIntentDraft:
        fields = NormalizedBriefFields(
            location=brief.location,
            travel_type=brief.travel_type,
            target_duration_seconds=brief.target_duration_seconds,
            orientation=brief.orientation,
            style=brief.style,
            mood=brief.mood,
            rhythm=brief.rhythm,
            vocals=brief.vocals,
            instrument_preferences=brief.instrument_preferences,
        )
        payload = fields.model_dump(mode="json")
        sources = [
            SourceSpan(
                field=field,
                source_kind="legacy_structured_brief",
                text=json.dumps(value, ensure_ascii=False),
            )
            for field, value in payload.items()
            if value is not None and value != "" and value != []
        ]
        unknown = [
            field
            for field, value in payload.items()
            if value is None or value == []
        ]
        return NormalizedIntentDraft(
            status="completed",
            raw_description="从 V0.1 结构化 Brief 迁移",
            provider="legacy_brief_adapter",
            normalized_fields=fields,
            source_spans=sources,
            unknown_fields=unknown,
        )


def _canonical_field_payload(fields: NormalizedBriefFields) -> dict[str, Any]:
    return fields.model_dump(mode="json")


def validate_brief_confirmation(
    confirmation: BriefConfirmation,
    draft: NormalizedIntentDraft,
    draft_sha256: str,
) -> None:
    if confirmation.draft_sha256 != draft_sha256:
        raise ValueError("brief confirmation draft hash mismatch")
    if confirmation.status != "completed":
        raise ValueError("brief confirmation must be completed")
    try:
        datetime.fromisoformat(confirmation.confirmed_at)
    except ValueError as exc:
        raise ValueError("confirmed_at must be an ISO timestamp") from exc
    original = _canonical_field_payload(draft.normalized_fields)
    confirmed = _canonical_field_payload(confirmation.normalized_fields)
    changed = sorted(
        field for field in BRIEF_FIELD_NAMES if original[field] != confirmed[field]
    )
    if sorted(confirmation.changed_fields) != changed:
        raise ValueError("changed_fields does not match draft differences")


def render_brief_review(
    draft: NormalizedIntentDraft,
    output: Path,
    *,
    draft_sha256: str,
) -> Path:
    """Render an offline form that exports a hash-bound confirmation."""

    fields = draft.normalized_fields.model_dump(mode="json")
    sources = "".join(
        f"<li><code>{escape(source.field)}</code> · {escape(source.source_kind)} · {escape(source.text)}</li>"
        for source in draft.source_spans
    )
    options = {
        "orientation": ["", "portrait", "landscape"],
        "rhythm": ["", "low", "medium", "high"],
        "vocals": ["", "instrumental_only", "instrumental_preferred", "allowed"],
    }
    rows: list[str] = []
    for field in BRIEF_FIELD_NAMES:
        value = fields[field]
        classes = " required" if field in REQUIRED_BRIEF_FIELDS else ""
        if field in options:
            control = "<select>" + "".join(
                f'<option value="{escape(option)}"{" selected" if option == value else ""}>{escape(option or "未确认")}</option>'
                for option in options[field]
            ) + "</select>"
        else:
            shown = "、".join(value) if isinstance(value, list) else (value or "")
            input_type = "number" if field == "target_duration_seconds" else "text"
            control = f'<input type="{input_type}" value="{escape(str(shown))}">'
        state = []
        if field in draft.unknown_fields:
            state.append("unknown")
        if field in draft.conflicting_fields:
            state.append("conflict")
        rows.append(
            f'<tr data-field="{field}" class="{" ".join(state)}"><th>{field}</th><td class="control{classes}">{control}</td><td>{escape(", ".join(state) or "parsed")}</td></tr>'
        )
    original_json = json.dumps(fields, ensure_ascii=False).replace("<", "\\u003c")
    required_json = json.dumps(REQUIRED_BRIEF_FIELDS, ensure_ascii=False)
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>用户描述确认</title>
<style>body{{font-family:system-ui;background:#111;color:#eee;padding:24px;max-width:1000px;margin:auto}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #444;padding:8px;text-align:left}}input,select{{box-sizing:border-box;width:100%;background:#222;color:#eee;border:1px solid #666;padding:8px}}.unknown,.conflict{{background:#3a2714}}code{{color:#9fd}}button{{margin:16px 0;padding:10px 14px}}</style>
<h1>用户描述规范化确认</h1><blockquote>{escape(draft.raw_description)}</blockquote><p>黄色行表示未知或冲突；必须确认后才能进入导演推理。</p>
<button id="download">下载 brief_confirmation.json</button><table><thead><tr><th>字段</th><th>确认值</th><th>状态</th></tr></thead><tbody>{''.join(rows)}</tbody></table><h2>字段来源</h2><ul>{sources}</ul>
<script>const original={original_json};const required={required_json};document.getElementById('download').addEventListener('click',()=>{{const values={{}};document.querySelectorAll('[data-field]').forEach(row=>{{const field=row.dataset.field;let value=row.querySelector('input,select').value.trim();if(field==='target_duration_seconds')value=value?Number(value):null;else if(field==='instrument_preferences')value=value?value.split('、').map(v=>v.trim()).filter(Boolean):[];else value=value||null;values[field]=value;}});const missing=required.filter(field=>values[field]===null||values[field]==='');const changed=Object.keys(values).filter(field=>JSON.stringify(values[field])!==JSON.stringify(original[field])).sort();const payload={{schema_version:'0.2.0',status:missing.length?'partial':'completed',draft_sha256:'{draft_sha256}',normalized_fields:values,changed_fields:changed,confirmed_at:new Date().toISOString()}};const blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='brief_confirmation.json';link.click();URL.revokeObjectURL(link.href);}});</script></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
