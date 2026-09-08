from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from director.audio_packaging_guide import build_audio_packaging_advice, render_audio_packaging_markdown
from director.creative_schema import CreativeAudioIntent, SectionAudioIntent
from director.delivery import build_fast_mode_timeline
from director.hook_builder import HookConfig
from director.outro_builder import OutroConfig, build_outro_plan
from director.schema import MusicStructureSection
from tests.director.test_delivery import sample_sfx_entries, sample_structure


def direction(sfx=None, *, global_intent=None, section_intent=None, end=60.):
    return NS(audio_intent=global_intent, sections=[NS(section_id='opening', start=0., end=end, climax=False,
        narrative_task='建立到达感', material_ids=[], material_gaps=[],
        visual_plan='入口由暗到明；是否有明确揭示点待确认',
        sfx_plan=sfx or [], packaging=[], reference_ids=[], music_change='自然推进',
        audio_intent=section_intent)])
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


def test_explicit_user_hook_disable_suppresses_ready_source_plan():
    intent = CreativeAudioIntent(source='user_explicit', hook_policy='disabled',
                                 reason='用户要求开场直接保留现场声')
    advice = build_audio_packaging_advice(timeline(), direction(global_intent=intent), sample_structure())
    assert advice['hook']['status']['source_status'] == 'ready'
    assert advice['hook']['status']['advice_status'] == 'disabled_by_higher_priority_intent'
    assert advice['hook']['layers'] == []
    assert advice['hook']['bgm_relationship'] is None
    assert advice['hook']['effective_intent']['hook_policy']['source'] == 'user_explicit'


def test_user_global_intent_beats_section_creative_proposal():
    global_intent = CreativeAudioIntent(
        source='user_explicit', original_sound_priority='foreground', reason='用户要突出现场声')
    section_intent = SectionAudioIntent(
        source='creative_proposal', original_sound_priority='normal', reason='创意提案希望音乐完整')
    result = direction(['转场加一条 Whoosh'], global_intent=global_intent)
    result.sections[0].audio_intent = section_intent
    advice = build_audio_packaging_advice(timeline(), result, sample_structure())
    effective = advice['sections'][0]['effective_intent']['original_sound_priority']
    assert (effective['value'], effective['source'], effective['scope']) == (
        'foreground', 'user_explicit', 'global')
    assert advice['sections'][0]['proposals'][0]['status'] == 'lower_priority_than_original_sound'


def test_section_user_intent_wins_same_provenance_by_specificity():
    global_intent = CreativeAudioIntent(
        source='user_explicit', silence_priority='normal', reason='全片默认不断音乐')
    section_intent = SectionAudioIntent(
        source='user_explicit', silence_priority='required', reason='本段明确留出静默')
    result = direction(['峰值加冲击音'], global_intent=global_intent)
    result.sections[0].audio_intent = section_intent
    advice = build_audio_packaging_advice(timeline(), result, sample_structure())
    section = advice['sections'][0]
    assert section['effective_intent']['silence_priority']['value'] == 'required'
    assert section['effective_intent']['silence_priority']['scope'] == 'section'
    assert section['priority_order'][0] == 'required_silence'
    assert section['proposals'][0]['status'] == 'suppressed_by_required_silence'


def test_cross_scope_space_conflict_keeps_higher_priority_policy():
    global_intent = CreativeAudioIntent(
        source='user_explicit', original_sound_priority='foreground', reason='用户要求保留现场声')
    section_intent = SectionAudioIntent(
        source='creative_proposal', silence_priority='required', reason='创意提案建议全静默')
    result = direction(global_intent=global_intent)
    result.sections[0].audio_intent = section_intent
    effective = build_audio_packaging_advice(timeline(), result, sample_structure())['sections'][0]['effective_intent']
    assert effective['original_sound_priority']['value'] == 'foreground'
    assert effective['silence_priority']['value'] == 'normal'
    assert effective['silence_priority']['overridden_by'] == 'higher_priority_original_sound'


def test_free_text_is_not_promoted_to_structured_intent():
    advice = build_audio_packaging_advice(
        timeline(), direction(['保留入口现场底噪']), sample_structure())
    effective = advice['sections'][0]['effective_intent']['original_sound_priority']
    assert effective['value'] == 'normal'
    assert effective['source'] == 'default'
    assert advice['sections'][0]['proposals'][0]['proposal_type'] == 'source_sound_space'


def test_creative_boundary_stays_fixed_when_music_boundary_is_near_or_mismatched():
    music = sample_structure().model_copy(update={'sections': [
        MusicStructureSection(start=0, end=29.7, role='intro', energy=.3, confidence=.8),
        MusicStructureSection(start=29.7, end=60, role='rise', energy=.6, confidence=.8),
    ]})
    near = build_audio_packaging_advice(timeline(), direction(end=30.), music)['sections'][0]
    boundary = near['boundary_alignment']['end']
    assert boundary['status'] == 'near'
    assert boundary['creative_boundary'] == 30.
    assert boundary['nearest_music_boundary'] == 29.7
    assert boundary['review_window'] == [29.7, 30.]

    far_music = music.model_copy(update={'sections': [
        MusicStructureSection(start=0, end=25, role='intro', energy=.3, confidence=.8),
        MusicStructureSection(start=25, end=60, role='rise', energy=.6, confidence=.8),
    ]})
    mismatch = build_audio_packaging_advice(timeline(), direction(end=30.), far_music)['sections'][0]
    assert mismatch['boundary_alignment']['end']['status'] == 'mismatch'
    assert mismatch['end'] == 30.
    assert mismatch['boundary_alignment']['end']['offset_seconds'] == -5.
    assert mismatch['boundary_alignment']['end']['review_window'] == [29.5, 30.5]


def test_unreliable_and_truncated_boundaries_remain_explicit_unknowns():
    unreliable = sample_structure().model_copy(update={'confidence': .5})
    unknown = build_audio_packaging_advice(timeline(), direction(end=30.), unreliable)['sections'][0]
    assert unknown['boundary_alignment']['end']['status'] == 'music_boundary_unavailable'
    truncated = sample_structure().model_copy(update={'duration_seconds': 61.4})
    final = build_audio_packaging_advice(timeline(), direction(), truncated)['sections'][0]
    assert final['boundary_alignment']['end']['status'] == 'target_cut_unanalyzed'
    assert final['boundary_alignment']['end']['nearest_music_boundary'] is None


def test_boundary_tolerance_must_be_positive():
    with pytest.raises(ValueError, match='positive'):
        build_audio_packaging_advice(timeline(), direction(), sample_structure(), 0)


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
