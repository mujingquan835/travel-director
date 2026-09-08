"""Planning-only music breakdown. Never select, cut, mix or render media."""
from pathlib import Path
import os
import tempfile

from director.project import ProjectConflict, _canonical_bytes, _sha256_bytes, _sha256_file


def build_guide(direction, music):
    target = direction.target_duration_seconds
    if target > music.duration_seconds + 1e-6:
        raise ProjectConflict('music does not cover the proposed guide duration')
    rows = []
    cursor = 0.0
    for section in direction.sections:
        if abs(section.start-cursor) > 1e-6 or section.end <= section.start or section.end > target + 1e-6:
            raise ProjectConflict('creative sections must cover the guide continuously')
        cursor = section.end
        overlaps = [dict(start=max(s.start, section.start), end=min(s.end, section.end),
                         role=s.role, energy=s.energy, confidence=s.confidence)
                    for s in music.sections if s.start < section.end and s.end > section.start]
        reliable = [s for s in overlaps if s['confidence'] >= .6 and music.confidence >= .6]
        roles = {s['role'] for s in reliable}
        if not reliable:
            pacing, reason = '待试听后确定切换密度；优先完整呈现画面动作。', '音乐分段依据不足，不自动推荐快切。'
        elif len(roles) > 1:
            pacing, reason = '按下列音乐子段分别试听与安排密度，转折附近考虑留白；不对整段统一快切或放慢。', '此创意段跨越不同音乐分析候选，短暂的段尾变化不能代表整段。'
        elif 'breath' in roles or 'outro' in roles:
            pacing, reason = '建议停留或长镜头；若段内有变化，再局部调整。', '分析含呼吸或收束候选段，避免机械切换。'
        elif section.climax and roles.intersection({'rise', 'climax'}):
            pacing, reason = '可尝试局部快切，对比动作或景别；其余位置留出停顿。', '创意高潮与音乐推进候选重叠；这是编排建议，需试听复核。'
        else:
            pacing, reason = '建议常规切换或保留完整动作，在乐句转折处考虑换画面。', '按叙事任务安排密度，不把每个节拍当作必切点。'
        if section.climax and not roles.intersection({'rise', 'climax'}):
            reason += ' 创意希望抬升，但音乐分析尚不支持高潮对应；需试听后调整创意时段或切换密度。'
        rows.append(dict(section_id=section.section_id, start=section.start, end=section.end,
            narrative_task=section.narrative_task, picture_suggestion=section.visual_plan,
            pacing_suggestion=pacing, suggestion_reason=reason, music_evidence=overlaps,
            beat_references=[t for t in music.beats_seconds if section.start <= t < section.end],
            downbeat_references=[t for t in music.downbeats_seconds if section.start <= t < section.end],
            material_gaps=section.material_gaps,
            music_change_proposal=section.music_change, sfx_proposals=section.sfx_plan))
    if abs(cursor-target) > 1e-6:
        raise ProjectConflict('creative sections do not cover target duration')
    return dict(schema_version='1.0.0', mode='fast', artifact_kind='music_visual_guidance',
        target_duration_seconds=target, bpm_estimate=music.bpm, analysis_confidence=music.confidence,
        music_edited=False, footage_edited=False, external_call_count=0,
        boundary='音乐时间均为原曲参考坐标；不裁切音乐或画面，不生成素材入出点。节拍仅供参考，不是必切点。',
        ending_note='目标截点尚未分析，不能用原曲结尾行为推断此处听感。' if target < music.duration_seconds-1e-6 else '原曲结尾分析也需试听复核。',
        sections=rows)


def render_markdown(guide):
    lines = ['# 快速模式：音乐分段与画面建议', '', guide['boundary'],
             '分段沿用创意方案；音乐角色为分析候选，不宣称已精确识别乐句或试听认可。',
             '快切、停留及画面内容是建议，由用户自行剪辑。', '', guide['ending_note'], '',
             '| 音乐时间 | 建议画面 / 叙事任务 | 切换建议与理由 | 音乐分析依据 | 素材缺口 |',
             '|---|---|---|---|---|']
    for row in guide['sections']:
        evidence = '; '.join(f"{s['start']:.2f}–{s['end']:.2f}s {s['role']}，能量 {s['energy']:.2f}，置信度 {s['confidence']:.2f}" for s in row['music_evidence']) or '无可靠分段'
        cells = [f"{row['start']:.2f}–{row['end']:.2f}s", row['picture_suggestion']+' / '+row['narrative_task'],
            row['pacing_suggestion']+' '+row['suggestion_reason'], evidence, '; '.join(row['material_gaps']) or '未记录；不代表素材已充分']
        lines.append('| '+' | '.join(c.replace('|','\\|').replace('\n',' ') for c in cells)+' |')
    lines += ['', '完整节拍参考见 JSON；这些标记不要求每拍切镜头。慢速模式仅可使用代表静帧占位，本交付不生成静帧展示或视频。', '']
    return '\n'.join(lines).encode()


def publish(path, data):
    if path.is_symlink():
        raise ProjectConflict('guide artifact must not be redirected')
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent) as temp:
        temp.write(data)
        temp.flush()
        try:
            os.link(temp.name, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ProjectConflict('existing guide artifact differs; preserve it for inspection')


def record_guide(paths):
    from director.creative_direction import _context, load_creative
    from director.audio_import import load_music_evidence
    from director.timeline_delivery_store import validate_timeline_delivery
    validate_timeline_delivery(paths)
    hashes, _ = _context(paths)
    creative = load_creative(paths, validate_sources=False)
    evidence = load_music_evidence(paths)
    if creative is None or evidence is None:
        raise ProjectConflict('guide requires verified creative and music evidence')
    guide = build_guide(creative[0], evidence[1])
    guide['inputs'] = dict(visual_hashes=hashes,
        creative_sha256=_sha256_bytes(_canonical_bytes(creative[0].model_dump(mode='json'))),
        music_structure_sha256=_sha256_file(paths.music_structure),
        timeline_receipt_sha256=_sha256_file(paths.root/'delivery/receipt.json'),
        algorithm_sha256=_sha256_file(Path(__file__)))
    data = _canonical_bytes(guide)
    root = paths.root/'guidance'/_sha256_bytes(data)[:20]
    if root.is_symlink() or root.parent.is_symlink():
        raise ProjectConflict('guide directory must not be redirected')
    md = render_markdown(guide)
    for name, content in [('music_visual_guide.json', data), ('music_visual_guide.md', md),
                          ('receipt.json', _canonical_bytes(dict(guide_sha256=_sha256_bytes(data), markdown_sha256=_sha256_bytes(md))))]:
        publish(root/name, content)
    return dict(music_visual_guide=str(root/'music_visual_guide.json'),
                music_visual_guide_markdown=str(root/'music_visual_guide.md'), guidance_receipt=str(root/'receipt.json'))
