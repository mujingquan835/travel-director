"""Offline review forms and audited confirmation import for V0.2."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from html import escape
from pathlib import Path
from typing import Any

from director.agent_batches import MaterialFrameMap, RepresentativeFrame
from director.evaluation import VisualConfirmation, sha256_file
from director.skill_workflow import (
    ChatReviewBatch,
    PreparedVisualReview,
    choose_review_route,
)
from director.visual_schema import (
    ClipObservationBatch,
    DirectorReview,
    DirectorTreatment,
    EvidenceRef,
    ObservationAssertion,
)


_REVIEW_FIELD_ORDER = (
    "technical_usability",
    "content_families",
    "setting",
    "lighting",
    "people_presence",
    "people_count_band",
    "subject_candidates",
    "activity_candidates",
)

_REVIEW_FIELD_LABELS = {
    "technical_usability": ("这段画面能否使用？", "只看清晰度、曝光和抖动是否影响观看"),
    "content_families": ("画面拍到了什么？", "可多选"),
    "setting": ("这是室内还是室外？", "只按画面中可见环境判断"),
    "lighting": ("画面的光线是什么状态？", "选最接近的一项"),
    "people_presence": ("画面里有人吗？", "远处可辨认的人也算"),
    "people_count_band": ("画面里大约有多少人？", "不需要精确数数"),
    "subject_candidates": ("画面主要拍的是什么？", "用普通中文填写，多项用顿号隔开"),
    "activity_candidates": ("画面中正在发生什么？", "例如：步行、参观、乘车；多项用顿号隔开"),
}

_REVIEW_ENUM_OPTIONS = {
    "technical_usability": (("usable", "可用"), ("unusable", "不可用"), ("review_required", "还需要查看原片")),
    "setting": (("outdoor", "室外"), ("indoor", "室内"), ("mixed", "室内外混合"), ("unknown", "无法判断")),
    "lighting": (("daylight", "日间自然光"), ("night", "夜景"), ("artificial", "人工灯光"), ("mixed", "混合光"), ("unknown", "无法判断")),
    "people_presence": (("present", "有人"), ("absent", "没有人"), ("unknown", "无法判断")),
    "people_count_band": (("none", "无人"), ("single", "1 人"), ("few", "少量人物"), ("crowd", "人群"), ("unknown", "无法判断")),
}

_CONTENT_FAMILY_OPTIONS = (
    ("urban", "城市街景"),
    ("nature", "自然风景"),
    ("culture_architecture", "文化或建筑"),
    ("food", "美食"),
    ("transport", "交通出行"),
    ("lodging", "住宿"),
    ("attraction_activity", "景点或游玩"),
    ("performance_event", "演出或活动"),
    ("people", "人物"),
    ("detail", "细节特写"),
    ("other", "其他"),
)


def _review_control(field: str) -> tuple[str, str]:
    if field == "content_families":
        choices = "".join(
            f'<label class="choice"><input type="checkbox" value="{value}"><span>{escape(label)}</span></label>'
            for value, label in _CONTENT_FAMILY_OPTIONS
        )
        return "multi", f'<div class="choice-grid answer-value">{choices}</div>'
    if field in _REVIEW_ENUM_OPTIONS:
        options = '<option value="">请选择</option>' + "".join(
            f'<option value="{value}">{escape(label)}</option>'
            for value, label in _REVIEW_ENUM_OPTIONS[field]
        )
        return "enum", f'<select class="answer-value">{options}</select>'
    return "list", '<input class="answer-value" type="text" placeholder="直接输入中文">'


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def _embed_frame(frame: RepresentativeFrame) -> tuple[str, str]:
    path = Path(frame.path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"missing local representative frame: {frame.path}")
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type is None or not mime_type.startswith("image/"):
        raise ValueError(f"representative frame must be a local image: {frame.path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}", f"t={frame.timestamp:.3f}s"


def render_visual_review(
    observations: ClipObservationBatch,
    frame_paths: dict[str, list[Path | RepresentativeFrame]],
    output: Path,
    *,
    source_observations_sha256: str | None = None,
) -> Path:
    """Render an offline form that exports an audited visual confirmation."""

    source_hash = source_observations_sha256 or hashlib.sha256(
        _canonical_bytes(observations.model_dump(mode="json"))
    ).hexdigest()
    cards: list[str] = []
    review_rows: list[dict[str, Any]] = []
    for item in observations.items:
        material_id = item.material.material_id
        unresolved = set(item.review_required_fields) | set(item.unknown_fields)
        if not unresolved:
            continue
        assertions = {row.field: row for row in item.assertions}
        images = "".join(
            (
                f'<figure><img src="{escape(src)}" alt="representative frame">'
                f'<figcaption>{escape(label)}</figcaption></figure>'
            )
            for src, label in [
                _embed_frame(
                    frame if isinstance(frame, RepresentativeFrame) else RepresentativeFrame(path=str(frame), timestamp=0.0)
                )
                for frame in frame_paths.get(material_id, [])
            ]
        )
        fields = [field for field in _REVIEW_FIELD_ORDER if field in unresolved]
        fields.extend(sorted(unresolved - set(_REVIEW_FIELD_ORDER)))
        controls: list[str] = []
        for field in fields:
            original = assertions.get(field)
            original_value = original.value if original else None
            original_status = original.status if original else "abstained"
            row = {
                "material_id": material_id,
                "field": field,
                "original_value": original_value,
                "original_status": original_status,
            }
            review_rows.append(row)
            row_index = len(review_rows) - 1
            question, hint = _REVIEW_FIELD_LABELS.get(field, (field, ""))
            control_kind, control = _review_control(field)
            controls.append(
                f"""<section class="field" data-review-index="{row_index}" data-control-kind="{control_kind}">
<div class="question"><h3>{escape(question)}</h3><p>{escape(hint)}</p></div>
<div class="answer">{control}</div>
<label class="uncertain"><input class="keep-unknown" type="checkbox"> 这张看不清，保留为未知</label>
<input class="reviewer-note" placeholder="补充说明（可不填）">
</div>"""
            )
        cards.append(
            f"""<article>
<h2>{escape(item.material.relative_path)}</h2>
<div class="meta">时长 {item.material.duration_seconds:.2f} 秒 · {'竖屏' if item.material.orientation == 'portrait' else '横屏'}</div>
<div class="frames">{images or '<span class="warning">没有可用代表帧</span>'}</div>
<div class="fields">{''.join(controls) or '<p>没有待确认字段</p>'}</div>
</article>"""
        )
    rows_json = _json_for_script(review_rows)
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>旅行导演 · 画面人工确认</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#101114;color:#f3f4f6;margin:0;padding:24px}}main{{max-width:1180px;margin:auto}}article{{background:#1b1d22;border:1px solid #30333a;border-radius:14px;padding:18px;margin:18px 0}}h1{{margin:0 0 6px}}h2{{font-size:17px;word-break:break-all}}.lead,.meta,.question p{{color:#aeb4c0}}.meta,figcaption{{font-size:12px}}.frames{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin:14px 0}}.frames figure{{margin:0}}.frames img{{width:100%;max-height:360px;object-fit:contain;background:#000;border-radius:8px}}figcaption{{margin-top:4px;color:#aeb4c0}}.field{{display:grid;grid-template-columns:minmax(240px,0.8fr) minmax(320px,1.6fr);gap:12px 22px;align-items:start;padding:18px 0;border-top:1px solid #30333a}}.question h3{{margin:0 0 5px;font-size:17px}}.question p{{margin:0;font-size:13px}}select,input{{box-sizing:border-box;width:100%;background:#111318;color:#f3f4f6;border:1px solid #555b68;border-radius:8px;padding:10px}}.choice-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:8px}}.choice{{display:flex;align-items:center;gap:7px;background:#111318;border:1px solid #444954;border-radius:8px;padding:9px}}.choice input,.uncertain input{{width:auto}}.uncertain{{grid-column:2;color:#cbd0da;font-size:13px}}.reviewer-note{{grid-column:2}}button{{background:#6d5dfc;color:white;border:0;border-radius:9px;padding:12px 17px;cursor:pointer;font-size:15px}}.toolbar{{position:sticky;top:0;background:#101114ee;padding:12px 0;z-index:2;display:flex;justify-content:flex-end}}.warning{{color:#f0b45a}}@media(max-width:800px){{.field{{grid-template-columns:1fr}}.uncertain,.reviewer-note{{grid-column:1}}}}
</style></head><body><main>
<div class="toolbar"><button id="download">生成画面确认文件</button></div>
<h1>请帮旅行导演看懂这 {len(cards)} 段画面</h1><p class="lead">只回答眼前能看到的内容。看不清可直接勾选“保留为未知”，不需要理解技术字段。</p>
{''.join(cards)}
</main><script>
const baseRows={rows_json};
document.getElementById('download').addEventListener('click',()=>{{
  try{{
    const items=[];
    document.querySelectorAll('[data-review-index]').forEach(node=>{{
      const base=baseRows[Number(node.dataset.reviewIndex)];
      const unknown=node.querySelector('.keep-unknown').checked;
      let value=null;
      if(!unknown){{
        if(node.dataset.controlKind==='multi') value=[...node.querySelectorAll('.answer-value input:checked')].map(input=>input.value);
        else if(node.dataset.controlKind==='list') value=node.querySelector('.answer-value').value.split(/[、，,;；]/).map(v=>v.trim()).filter(Boolean);
        else value=node.querySelector('.answer-value').value;
        if(value===''||(Array.isArray(value)&&value.length===0)) throw new Error('还没有回答：'+node.querySelector('h3').textContent);
      }}
      items.push({{...base,confirmed_value:value,confirmed_status:unknown?'abstained':'confirmed',reviewer_note:node.querySelector('.reviewer-note').value||'用户根据代表帧人工确认',changed_at:new Date().toISOString()}});
    }});
    const payload={{schema_version:'0.2.0',source_observations_sha256:'{source_hash}',status:'completed',reviewer:'manual-review',items}};
    const blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}});
    const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download='visual_confirmation.json'; link.click(); URL.revokeObjectURL(link.href);
  }}catch(error){{alert(error.message);}}
}});
</script></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def prepare_visual_review(
    observations: ClipObservationBatch,
    frame_map: MaterialFrameMap,
    output_dir: Path,
    *,
    force_local_page: bool = False,
    source_observations_sha256: str | None = None,
) -> PreparedVisualReview:
    """Prepare the selected local review channel without opening a browser."""

    route = choose_review_route(
        observations, force_local_page=force_local_page
    )
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    chat_batches = [
        ChatReviewBatch(
            material_ids=[question.material_id for question in questions],
            questions=questions,
        )
        for start in range(0, len(route.questions), 3)
        for questions in [route.questions[start : start + 3]]
    ] if route.channel == "chat" else []

    html_path: str | None = None
    confirmation_path: str | None = None
    if route.channel == "local_page":
        html = root / "visual_review.html"
        frames = {
            item.material.material_id: item.frames
            for item in frame_map.items
        }
        render_visual_review(
            observations,
            frames,
            html,
            source_observations_sha256=source_observations_sha256,
        )
        html_path = str(html)
        confirmation_path = str(root / "visual_confirmation.json")

    prepared = PreparedVisualReview(
        route=route,
        chat_batches=chat_batches,
        html_path=html_path,
        confirmation_path=confirmation_path,
    )
    (root / "review_route.json").write_text(
        prepared.model_dump_json(indent=2), encoding="utf-8"
    )
    return prepared


def validate_visual_confirmation_against_observations(
    confirmation: VisualConfirmation,
    observations: ClipObservationBatch,
    source_observations_sha256: str,
) -> None:
    if confirmation.source_observations_sha256 != source_observations_sha256:
        raise ValueError("visual confirmation source hash mismatch")
    by_material = {
        item.material.material_id: item for item in observations.items
    }
    confirmed_keys = {(row.material_id, row.field) for row in confirmation.items}
    allowed_values: dict[str, set[str]] = {
        "technical_usability": {"usable", "unusable", "review_required"},
        "content_families": {
            "urban",
            "nature",
            "culture_architecture",
            "food",
            "transport",
            "lodging",
            "attraction_activity",
            "performance_event",
            "people",
            "detail",
            "other",
            "unknown",
        },
        "setting": {"indoor", "outdoor", "mixed", "unknown"},
        "lighting": {"daylight", "night", "artificial", "mixed", "unknown"},
        "people_presence": {"present", "absent", "unknown"},
        "people_count_band": {"none", "single", "few", "crowd", "unknown"},
    }
    for row in confirmation.items:
        try:
            item = by_material[row.material_id]
        except KeyError as exc:
            raise ValueError(f"unknown material_id: {row.material_id}") from exc
        assertions = {assertion.field: assertion for assertion in item.assertions}
        allowed_fields = (
            set(assertions) | set(item.unknown_fields) | set(item.review_required_fields)
        )
        if row.field not in allowed_fields:
            raise ValueError(f"unknown field for material: {row.field}")
        original = assertions.get(row.field)
        expected_value = original.value if original else None
        expected_status = original.status if original else "abstained"
        if row.original_value != expected_value or row.original_status != expected_status:
            raise ValueError(f"original value drifted for field: {row.field}")
        if row.confirmed_status == "confirmed":
            if row.field in {"subject_candidates", "activity_candidates"}:
                if not isinstance(row.confirmed_value, list) or not all(
                    isinstance(value, str) and value.strip()
                    for value in row.confirmed_value
                ):
                    raise ValueError(f"invalid list value for field: {row.field}")
            elif row.field == "content_families":
                if (
                    not isinstance(row.confirmed_value, list)
                    or not row.confirmed_value
                    or not all(
                        isinstance(value, str)
                        and value in allowed_values[row.field]
                        for value in row.confirmed_value
                    )
                ):
                    raise ValueError(f"invalid enum value for field: {row.field}")
            elif row.field in allowed_values:
                if (
                    not isinstance(row.confirmed_value, str)
                    or row.confirmed_value not in allowed_values[row.field]
                ):
                    raise ValueError(f"invalid enum value for field: {row.field}")
            else:
                raise ValueError(f"confirmation field has no value contract: {row.field}")
    if confirmation.status == "completed":
        required = {
            (item.material.material_id, field)
            for item in observations.items
            for field in item.review_required_fields
        }
        missing = required - confirmed_keys
        if missing:
            raise ValueError(f"completed confirmation is missing {len(missing)} fields")


def apply_visual_confirmation(
    observations: ClipObservationBatch,
    confirmation: VisualConfirmation,
    confirmation_path: Path,
) -> ClipObservationBatch:
    """Apply confirmed fields without mutating or overwriting the draft artifact."""

    confirmation_hash = sha256_file(confirmation_path)
    updated = ClipObservationBatch.model_validate(
        observations.model_dump(mode="json")
    )
    by_material = {
        item.material.material_id: item for item in updated.items
    }
    for index, row in enumerate(confirmation.items):
        item = by_material[row.material_id]
        assertions = {assertion.field: assertion for assertion in item.assertions}
        evidence = EvidenceRef(
            material_id=row.material_id,
            artifact_path=str(confirmation_path),
            field_path=f"items[{index}]",
            source_kind="user_confirmation",
            status=row.confirmed_status,
            confidence=1.0 if row.confirmed_status == "confirmed" else None,
            sha256=confirmation_hash,
        )
        replacement = ObservationAssertion(
            field=row.field,
            value=row.confirmed_value,
            status=row.confirmed_status,
            confidence=1.0 if row.confirmed_status == "confirmed" else None,
            evidence_refs=[evidence],
        )
        if row.field in assertions:
            item.assertions = [
                replacement if assertion.field == row.field else assertion
                for assertion in item.assertions
            ]
        else:
            item.assertions.append(replacement)
        item.review_required_fields = [
            field for field in item.review_required_fields if field != row.field
        ]
        if row.confirmed_status == "confirmed":
            item.unknown_fields = [
                field for field in item.unknown_fields if field != row.field
            ]
        item.observation_status = "assisted"
    updated.mode = "assisted"
    updated.status = (
        "completed"
        if not any(item.review_required_fields for item in updated.items)
        else "partial"
    )
    return updated


def _treatment_memberships(treatment: DirectorTreatment) -> dict[str, str]:
    memberships: dict[str, str] = {}
    for bucket, material_ids in (
        ("core", treatment.core_materials),
        ("candidate", treatment.candidate_materials),
        ("redundant", treatment.redundant_materials),
        ("reject_suggestion", treatment.reject_suggestions),
        ("review_required", treatment.review_required),
    ):
        for material_id in material_ids:
            memberships[material_id] = bucket
    return memberships


def render_director_review(treatment: DirectorTreatment, output: Path) -> Path:
    """Render a separate director override ledger without source ranges."""

    treatment_hash = hashlib.sha256(
        _canonical_bytes(treatment.model_dump(mode="json"))
    ).hexdigest()
    memberships = _treatment_memberships(treatment)
    rows = "".join(
        f"""<tr data-material="{escape(material_id)}" data-original="{escape(bucket)}"><td>{escape(material_id)}</td><td>{escape(bucket)}</td><td><select class="bucket_override"><option value="">不修改</option>{''.join(f'<option value="{name}">{name}</option>' for name in ('core','candidate','redundant','reject_suggestion','review_required'))}</select></td><td><input class="functions" placeholder="opening,emotion"></td><td><label><input type="checkbox" class="force_include"> force_include</label><label><input type="checkbox" class="force_exclude"> force_exclude</label></td><td><input class="note" placeholder="修改理由"></td></tr>"""
        for material_id, bucket in sorted(memberships.items())
    )
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>导演判断复核</title>
<style>body{{font-family:system-ui;background:#111;color:#eee;padding:24px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #444;padding:8px}}input,select{{background:#222;color:#eee;border:1px solid #555;padding:6px}}button{{margin:16px 0;padding:10px 14px}}</style>
<h1>导演判断复核</h1><p>{escape(treatment.logline)}</p><p>这里只修改 bucket、导演职责和强制保留/排除，不设置时间区间。</p>
<button id="download">下载 director_review.json</button><table><thead><tr><th>material_id</th><th>原桶位</th><th>bucket_override</th><th>职责</th><th>强制动作</th><th>备注</th></tr></thead><tbody>{rows}</tbody></table>
<script>document.getElementById('download').addEventListener('click',()=>{{const overrides=[];document.querySelectorAll('[data-material]').forEach(row=>{{const bucket=row.querySelector('.bucket_override').value;const funcs=row.querySelector('.functions').value.split(',').map(v=>v.trim()).filter(Boolean);const include=row.querySelector('.force_include').checked;const exclude=row.querySelector('.force_exclude').checked;const note=row.querySelector('.note').value;if(bucket||funcs.length||include||exclude||note)overrides.push({{material_id:row.dataset.material,original_bucket:row.dataset.original,bucket_override:bucket||null,director_function_overrides:funcs,force_include:include,force_exclude:exclude,user_note:note||null,changed_at:new Date().toISOString()}});}});const payload={{schema_version:'0.2.0',treatment_sha256:'{treatment_hash}',status:'completed',mode:overrides.length?'assisted':'automatic',overrides,confirmed_at:new Date().toISOString()}};const blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='director_review.json';link.click();URL.revokeObjectURL(link.href);}});</script></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def build_automatic_director_review(treatment: DirectorTreatment) -> DirectorReview:
    """Accept an unchanged treatment without opening any review page."""

    treatment_hash = hashlib.sha256(
        _canonical_bytes(treatment.model_dump(mode="json"))
    ).hexdigest()
    return DirectorReview(
        treatment_sha256=treatment_hash,
        status="completed",
        mode="automatic",
        overrides=[],
        confirmed_at=None,
    )


def validate_director_review(
    review: DirectorReview,
    treatment: DirectorTreatment,
) -> None:
    expected_hash = hashlib.sha256(
        _canonical_bytes(treatment.model_dump(mode="json"))
    ).hexdigest()
    if review.treatment_sha256 != expected_hash:
        raise ValueError("director review treatment hash mismatch")
    memberships = _treatment_memberships(treatment)
    seen: set[str] = set()
    for override in review.overrides:
        if override.material_id in seen:
            raise ValueError("duplicate director override")
        seen.add(override.material_id)
        if override.material_id not in memberships:
            raise ValueError(f"unknown director material_id: {override.material_id}")
        if override.original_bucket != memberships[override.material_id]:
            raise ValueError("director override original bucket drifted")
