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
        fields = sorted(set(item.review_required_fields) | set(item.unknown_fields))
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
            controls.append(
                f"""<div class="field" data-review-index="{row_index}">
<label>{escape(field)}</label>
<div class="original">原值：{escape(json.dumps(original_value, ensure_ascii=False))} · {escape(original_status)}</div>
<select class="confirmed-status"><option value="confirmed">确认/修订</option><option value="abstained">仍然未知</option></select>
<textarea class="confirmed-value" placeholder='输入合法 JSON，例如 ["urban"] 或 "outdoor"'></textarea>
<input class="reviewer-note" placeholder="确认理由或备注">
</div>"""
            )
        cards.append(
            f"""<article>
<h2>{escape(item.material.relative_path)}</h2>
<div class="meta">{item.material.duration_seconds:.2f}s · {escape(item.material.orientation)} · {escape(material_id)}</div>
<div class="frames">{images or '<span class="warning">没有可用代表帧</span>'}</div>
<div class="fields">{''.join(controls) or '<p>没有待确认字段</p>'}</div>
</article>"""
        )
    rows_json = _json_for_script(review_rows)
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>旅行导演 · 画面人工确认</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#101114;color:#f3f4f6;margin:0;padding:24px}}main{{max-width:1180px;margin:auto}}article{{background:#1b1d22;border:1px solid #30333a;border-radius:14px;padding:18px;margin:18px 0}}h1{{margin-top:0}}h2{{font-size:17px;word-break:break-all}}.meta,.original{{color:#aeb4c0;font-size:12px}}.frames{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin:14px 0}}.frames figure{{margin:0}}.frames img{{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:8px}}figcaption{{margin-top:4px;color:#aeb4c0;font-size:12px}}.field{{display:grid;grid-template-columns:180px 150px 1fr 1fr;gap:8px;align-items:center;padding:10px 0;border-top:1px solid #30333a}}select,textarea,input{{box-sizing:border-box;width:100%;background:#111318;color:#f3f4f6;border:1px solid #444954;border-radius:7px;padding:8px}}textarea{{min-height:44px}}button{{background:#6d5dfc;color:white;border:0;border-radius:9px;padding:11px 16px;cursor:pointer}}.toolbar{{position:sticky;top:0;background:#101114ee;padding:12px 0;z-index:2}}.warning{{color:#f0b45a}}@media(max-width:800px){{.field{{grid-template-columns:1fr}}}}
</style></head><body><main>
<div class="toolbar"><label>复核人 <input id="reviewer" value="manual-review"></label> <button id="download">下载 visual_confirmation.json</button></div>
<h1>画面人工确认</h1><p>只修正画面观察；不填写剪辑起止区间。候选或未知字段必须保留确认理由。</p>
{''.join(cards)}
</main><script>
const baseRows={rows_json};
document.getElementById('download').addEventListener('click',()=>{{
  const items=[];
  document.querySelectorAll('[data-review-index]').forEach(node=>{{
    const base=baseRows[Number(node.dataset.reviewIndex)];
    const status=node.querySelector('.confirmed-status').value;
    const raw=node.querySelector('.confirmed-value').value.trim();
    let value=null;
    if(status==='confirmed'){{if(!raw){{throw new Error('确认值不能为空：'+base.field)}} value=JSON.parse(raw);}}
    items.push({{...base,confirmed_value:value,confirmed_status:status,reviewer_note:node.querySelector('.reviewer-note').value,changed_at:new Date().toISOString()}});
  }});
  const payload={{schema_version:'0.2.0',source_observations_sha256:'{source_hash}',status:'completed',reviewer:document.getElementById('reviewer').value||'manual-review',items}};
  const blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}});
  const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download='visual_confirmation.json'; link.click(); URL.revokeObjectURL(link.href);
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
