"""Isolated Kaifeng acceptance; hand-authored plan, no scanner/provider invocation.

Run from package root with .venv/bin/python scripts/accept_reference_av.py.
The source project is read-only; each execution creates a new acceptance folder.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import wave
import math
import array

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'prototype/runs/travel-project-3d14b9a84b'
OUTPUT = ROOT.parent / 'outputs/reference-av-acceptance'


def read(path):
    return json.loads(path.read_text())


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def tone(path, frequency):
    rate = 22050
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        samples = array.array('h', (int(7000 * math.sin(2 * math.pi * frequency * i / rate)
                    * (1 if (i % (rate // 2)) < 600 else .015)) for i in range(rate * 60)))
        output.writeframes(samples.tobytes())


def main():
    original = hashes(SOURCE)
    assert read(SOURCE / 'project_state.json')['completed_artifact_hashes'].get('music_asset') is None
    OUTPUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='kaifeng-', dir=OUTPUT))
    project = work / 'project'
    shutil.copytree(SOURCE, project)
    input_path = read(SOURCE / 'visual/run_contract.json')['input_root']
    brief = read(SOURCE / 'brief.json')['raw_description']

    def run(label, project_path=project, *extra):
        command = [str(ROOT / '.venv/bin/travel-director'), 'run', '--input', input_path,
                   '--brief', brief, '--project', str(project_path), *map(str, extra)]
        result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
        value = json.loads(result.stdout)
        save(work / f'{label}.json', value)
        assert value['external_call_count'] == 0
        return value

    request_result = run('01-request')
    assert request_result['status'] == 'needs_creative_direction', request_result
    request = read(Path(request_result['actions'][0]['result_path']))
    materials = read(project / 'visual/clip_observations.json')['items']
    def ids(*names):
        return [next(m['material']['material_id'] for m in materials
                     if name in m['material']['relative_path']) for name in names]
    sections = [
        dict(section_id='enter', start=0, end=10, narrative_task='夜间抵达，建立开封地点',
             material_ids=ids('IMG_0232','IMG_0235'), material_gaps=['需逐帧确认竖屏裁切后的可用净时长'],
             visual_plan='街口车辆与夜间城门交替；横屏素材按主体安全区规划竖屏裁切',
             music_change='稀疏短动机入场，前两秒给环境空间',
             sfx_plan=['设计建议：街声先行；原音尚未听辨，不能视为已具备'],
             packaging=['开封，小面积地点标题'], reference_ids=['case2']),
        dict(section_id='explore', start=10, end=25, narrative_task='从入口走向具体地点与细节',
             material_ids=ids('IMG_0261','IMG_0273','IMG_0245'),
             material_gaps=['现有短片净时长及动作衔接待核验，不足15秒需补充探索镜头'],
             visual_plan='日间入口与牌楼建立空间，灯笼细节作为跨时段插叙；不伪造同一时间连续动作',
             music_change='加入轻脉冲，细节处短减层', sfx_plan=['拟留脚步与近景动作声空位，具体声源待后续确认'],
             packaging=['不用持续字幕'], reference_ids=['case2','case4']),
        dict(section_id='experience', start=25, end=45, narrative_task='用行进体验展开，替代无素材依据的强高潮',
             material_ids=ids('IMG_0271'), material_gaps=['同行身份和亲密互动未确认','当前选中行进镜头不足20秒，需补充可用人物或行进素材','未确认高潮素材'],
             visual_plan='以已见人群背影与行进为基础，后续补充近景；不把游客认定为同行人',
             music_change='旋律适度展开，密度克制，不依赖高密度爆发',
             sfx_plan=['为脚步及人群环境预留短窗口，声源尚待核实'], packaging=['保持画面主体，不增章节卡'],
             reference_ids=['case2']),
        dict(section_id='return', start=45, end=60, narrative_task='回访地景并收束，明确结尾缺口',
             material_ids=ids('IMG_0236','IMG_0235'),
             material_gaps=['没有已确认的结尾镜头','现有水面短片无法独自覆盖15秒，需补更长停留或离开镜头'],
             visual_plan='拟回访夜间城门与水面灯影；不把回访规划描述为已具备完整结尾',
             music_change='逐层减少，末尾保留可剪尾音', sfx_plan=['计划保留环境尾声，不默认已有可用水声'],
             packaging=['可选小字：开封·旅行片段'], reference_ids=['case4']),
    ]
    prompts = [
        ('步行脉冲','60秒城市旅行配乐，贴近步行的轻脉冲，短小旋律动机，温润音色。开头稀疏，随后轻巧展开，中段给街声与人物动作留空，后段适度抬升，最后减层并留下自然尾音。整体有探索感，鼓点克制。','以轻脉冲承接街口与行进'),
        ('旋律留白','60秒纪实旅行配乐，以简短可记忆的旋律和疏朗和声推进。前段轻轻进入，探索段增加层次，人物段旋律更完整但保持留白，末段回到开头动机并缓缓收束。音色有温度，节奏适中，为环境声预留空间。','旋律回访对应地景回访'),
        ('质感行进','60秒城市漫游配乐，以柔和低频脉动、细碎轻打击与空气感长音构成层次。开头少量声音，进入街区后逐渐展开，人物段减少铺底让动作突出，后段维持克制张力，结尾逐步撤去节奏，保留安静余韵。','以质感与减层区分段落，而非强高潮'),
    ]
    plan = dict(schema_version='1.0.0', kind='creative_direction', source_hashes=request['source_hashes'],
                target_duration_seconds=60, location='开封', orientation='portrait',
                user_preferences=['纪实，兼顾城市氛围与同行体验','优先真实素材，缺高潮和结尾不强行编造','两首失败配乐只作拒绝记录，不导入'],
                reference_policy='default_library', custom_references=[], selected_references=[
                    dict(reference_id='case2',start=10,end=180,observation_ids=['case2-title','case2-detail','case2-person'],
                         fit_reason='借鉴地点标题和人物环境交替，不搬用新西兰地点、横屏或180秒后的方法'),
                    dict(reference_id='case4',start=4,end=64,observation_ids=['case4-title','case4-hands','case4-ending'],
                         fit_reason='借鉴细节与地景收束方法；本项目没有理网素材，不照搬动作、海浪或配器')],
                sections=sections, music_brief='为60秒竖屏开封纪实短片服务：进入、探索、体验展开、回访收束。素材高潮及结尾不足，音乐保持可分段、可减层，不以强高潮掩盖缺口。以下为创作建议而非参考片听辨事实；人声意图未指定。',
                vocals='unspecified', music_prompts=[dict(direction_id=f'option-{i}',title=title,generation_prompt=text,
                  fit_reason=reason,variation=reason,section_ids=[s['section_id'] for s in sections])
                  for i,(title,text,reason) in enumerate(prompts,1)])
    response = Path(request['response_path'])
    save(response, plan)
    save(work / 'session-authored-plan.json', plan)
    # Display artifact respects reference -> AV table -> brief -> prompts order.
    lines=['# 开封隔离验收方案','', '仅用于验收，不写入真实项目。规划时间不是实际音乐切点；净素材不足已列为缺口。','', '## 参考选择','']
    for ref in plan['selected_references']:
        lines.append(f"- {ref['reference_id']} {ref['start']}–{ref['end']}秒：{ref['fit_reason']}")
    lines += ['', '## 声画联合段落表','', '|计划时间|叙事任务|素材ID与缺口|画面组织|音乐变化|音效留位|包装|','|---|---|---|---|---|---|---|']
    for row in sections:
        cells=[f"{row['start']}–{row['end']}秒",row['narrative_task'],'；'.join(row['material_ids']+row['material_gaps']),row['visual_plan'],row['music_change'],'；'.join(row['sfx_plan']),'；'.join(row['packaging'])]
        lines.append('|'+'|'.join(cells)+'|')
    lines += ['', '## 音乐需求','',plan['music_brief'],'','## 三条提示词','']
    for title,text,reason in prompts:
        lines += [f'### {title}', '', text, '', f'变化理由：{reason}', '']
    (work / '方案.md').write_text('\n'.join(lines))
    assert run('02-submit',project,'--creative-response',response)['status']=='waiting_for_music'
    before_repeat=hashes(project)
    assert run('03-repeat',project,'--creative-response',response)['status']=='waiting_for_music'
    assert hashes(project)==before_repeat
    first,second=work/'test-only-440.wav',work/'test-only-660.wav'
    tone(first,440); tone(second,660)
    assert run('04-import',project,'--music',first)['status']=='waiting_for_timeline'
    parent_before=hashes(project)
    version=run('05-version',project,'--music',second,'--new-music-version')
    assert version['status']=='waiting_for_timeline'
    child=Path(version['project_path'])
    assert child != project and hashes(project)==parent_before
    child_before=hashes(child)
    assert run('06-version-repeat',project,'--music',second,'--new-music-version')['project_path']==str(child)
    assert hashes(child)==child_before
    assert hashes(SOURCE)==original
    project_hashes = hashes(project)
    assert all(project_hashes.get(name)==digest for name,digest in original.items() if name.startswith('visual/'))
    save(work/'acceptance.json',dict(status='passed',source_project=str(SOURCE),isolated_project=str(project),
         replacement_project=str(child),original_hashes=original,original_unchanged=True,
         visual_evidence_unchanged=True,repeat_reused=True,external_call_count=0,
         test_audio_only=True,rejected_audio_imported=False,prompt_lengths=[len(p[1]) for p in prompts],
         final_status='waiting_for_timeline'))
    print(work)


if __name__=='__main__':
    main()
