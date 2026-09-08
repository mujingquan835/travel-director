from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from director.audio_packaging_guide import build_audio_packaging_advice, render_audio_packaging_markdown
from director.delivery import build_fast_mode_timeline
from director.hook_builder import HookConfig
from director.outro_builder import OutroConfig, build_outro_plan
from tests.director.test_delivery import sample_sfx_entries, sample_structure


def direction(sfx=None):
    return NS(sections=[NS(section_id='opening', start=0., end=60., climax=False,
        narrative_task='建立到达感', material_ids=[], material_gaps=[],
        visual_plan='入口由暗到明；是否有明确揭示点待确认',
        sfx_plan=sfx or [], packaging=[], reference_ids=[], music_change='自然推进')])


def timeline(target=60.):
    return build_fast_mode_timeline(sample_structure(), target, '/music.wav',
        creative_sections=direction().sections, sfx_entries=sample_sfx_entries())


def test_layering_is_conditional_and_each_layer_requires_visual_anchor():
    advice = build_audio_packaging_advice(timeline(), direction(), sample_structure())
    assert advice['hook']['status']['source_status'] == 'ready'
    assert advice['hook']['status']['advice_status'] == 'needs_visual_and_listening_review'
    layers = advice['hook']['layers']
    assert [item['function'] for item in layers] == ['推进','释放','转场主体','低频/尾音支撑','细节点缀']
    assert all(item['necessity'] == 'conditional' for item in layers)
    assert all(item['decision'] == 'use_only_if_visual_anchor_is_confirmed' for item in layers)
    assert layers[0]['candidate_status'] == 'provenance_only_unverified'
    assert '可以为零' in advice['principle']
    assert '不是固定叠加' in advice['anti_overdesign_rule']


def test_duck_recovery_segments_are_non_overlapping_advice_only():
    advice = build_audio_packaging_advice(timeline(), direction(), sample_structure())
    relationship = advice['hook']['bgm_relationship']
    segments = relationship['segments']
    assert segments[0]['end_exclusive'] == segments[1]['start']
    assert segments[1]['end_exclusive'] == segments[2]['start']
    assert relationship['status'] == 'parameter_proposal_needs_listening'
    assert advice['edited_or_mixed'] is False


def test_truncated_outro_does_not_reuse_source_ending_behavior():
    music = sample_structure().model_copy(update={'duration_seconds': 61.4})
    advice = build_audio_packaging_advice(timeline(), direction(), music)
    assert advice['outro']['source_music_ending_applicable'] is False
    assert '先试听' in advice['outro']['recommendation']
    assert advice['outro']['candidate_source'] is None
    assert advice['outro']['status']['advice_status'] == 'deferred'


def test_creative_sfx_proposal_needs_event_annotation_and_silence_is_allowed():
    with_proposal = build_audio_packaging_advice(timeline(), direction(['转场加一条 Whoosh']), sample_structure())
    proposal = with_proposal['sections'][0]['proposals'][0]
    assert '具体画面事件' in proposal['required_annotation']
    assert proposal['proposal_type'] == 'effect_layer'
    without = build_audio_packaging_advice(timeline(), direction(), sample_structure())
    markdown = '\n'.join(render_audio_packaging_markdown(without))
    assert '允许保留音乐、现场声或静默空间' in markdown
    assert '不执行混音' in markdown


def test_guardrails_and_source_sound_are_not_treated_as_effect_layers():
    advice = build_audio_packaging_advice(
        timeline(), direction(['保留入口现场底噪', '不为无声画面虚构事件音']), sample_structure())
    source, guardrail = advice['sections'][0]['proposals']
    assert source['proposal_type'] == 'source_sound_space'
    assert '可用原声' in source['required_annotation']
    assert guardrail['proposal_type'] == 'guardrail'
    assert '无需寻找音效层' in guardrail['required_annotation']


def test_unfrozen_paths_are_not_claimed_as_verified_assets():
    delivery = timeline()
    assert delivery.sfx_assets is None
    advice = build_audio_packaging_advice(delivery, direction(), sample_structure())
    assert advice['verified_assets'] == []
    assert '无冻结记录时路径只作来源参考' in advice['asset_note']


@pytest.mark.parametrize('config', [
    {'bgm_recovery_seconds': 0}, {'bgm_recovery_seconds': -1},
    {'hit_pre_trigger_seconds': -0.1}, {'hit_pre_trigger_seconds': 2.1},
    {'hit_volume': 1.1},
])
def test_hook_advice_config_rejects_invalid_boundaries(config):
    with pytest.raises(ValidationError):
        HookConfig(**config)


def test_outro_pre_end_cannot_silently_clamp_past_target():
    with pytest.raises(ValueError, match='must not exceed'):
        build_outro_plan(sample_structure(), sample_sfx_entries(),
                         OutroConfig(outro_pre_end_seconds=61), target_duration_seconds=60)
