"""Creative direction boundary tests: reject unsupported evidence and stale inputs."""
import copy
import importlib
import pytest

from tests.director.test_director_treatment import build_city_treatment


def build_creative_payload(*, source_hashes, brief, material_ids):
    fields = brief.normalized_fields
    return {
        "schema_version": "1.0.0", "kind": "creative_direction",
        "source_hashes": dict(source_hashes),
        "target_duration_seconds": fields.target_duration_seconds,
        "location": fields.location, "orientation": fields.orientation,
        "user_preferences": ["按本次素材组织，不套用参考片"],
        "reference_policy": "brief_only", "selected_references": [],
        "sections": [{"section_id": "journey", "start": 0, "end": fields.target_duration_seconds,
                      "narrative_task": "建立地点并观察生活", "material_ids": sorted(material_ids),
                      "material_gaps": ["高潮素材尚待确认"], "visual_plan": "远景与生活细节交替",
                      "music_change": "从稀疏进入展开，最后收束", "sfx_plan": [], "packaging": [],
                      "reference_ids": [], "climax": False}],
        "music_brief": "服务生活观察，预留细节空间", "vocals": fields.vocals or "unspecified",
        "music_prompts": [{"direction_id": f"direction-{i}", "title": title,
                           "generation_prompt": prompt, "fit_reason": "为生活细节留空间",
                           "variation": title, "section_ids": ["journey"]}
                          for i, title, prompt in [(1,"疏朗","轻柔器乐，逐渐展开后自然收束"),
                                                   (2,"律动","克制节奏，细节段留白，末尾落点"),
                                                   (3,"抒情","舒展旋律，层次渐增，温和结束")]],
    }


def context():
    treatment, observations, _, brief = build_city_treatment()
    ids = {o.material.material_id for o in observations.items}
    hashes = {"brief": "a" * 64, "treatment": "b" * 64, "reference_library": "c" * 64}
    from director.intent_matcher import build_project_coverage, build_intent_decisions
    coverage = build_project_coverage(observations, build_intent_decisions(observations, brief))
    payload = build_creative_payload(source_hashes=hashes, brief=brief,
                                     material_ids=set(treatment.core_materials + treatment.candidate_materials))
    return payload, dict(source_hashes=hashes, brief=brief, treatment=treatment, coverage=coverage, material_ids=ids)


def module():
    import importlib.util
    assert importlib.util.find_spec("director.creative_schema"), "creative direction validator is missing"
    return importlib.import_module("director.creative_schema")


def test_accepts_grounded_direction_without_forcing_reference():
    payload, kwargs = context()
    result = module().validate_creative_direction(payload, **kwargs)
    assert result.location == "开封"
    assert result.sections[0].end == 60
    assert len(result.music_prompts) == 3


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(extra=True), lambda p: p.update(target_duration_seconds=float("nan")),
    lambda p: p.update(target_duration_seconds="60"), lambda p: p.update(location="别处"),
    lambda p: p.update(orientation="landscape"), lambda p: p["source_hashes"].update(brief="d"*64),
    lambda p: p["source_hashes"].update(unexpected="d"*64),
    lambda p: p["sections"][0].update(start=1), lambda p: p["sections"][0].update(end=59),
    lambda p: p["sections"][0].update(material_ids=[], material_gaps=[]),
    lambda p: p["sections"][0].update(material_ids=["sha256:"+"f"*64]),
    lambda p: p["sections"][0].update(reference_ids=["case1"]),
    lambda p: p["sections"][0].update(visual_plan="  "),
    lambda p: p["music_prompts"][0].update(generation_prompt="长"*201),
    lambda p: p["music_prompts"][0].update(section_ids=["missing"]),
    lambda p: p["music_prompts"][0].update(variation=" "),
    lambda p: p["music_prompts"].pop(),
    lambda p: p["music_prompts"][1].update(direction_id="direction-1"),
    lambda p: p["music_prompts"][1].update(generation_prompt=p["music_prompts"][0]["generation_prompt"]),
    lambda p: p.update(user_preferences=[]), lambda p: p.update(reference_policy="custom"),
])
def test_rejects_invalid_contract(mutation):
    payload, kwargs = context()
    mutation(payload)
    with pytest.raises(ValueError):
        module().validate_creative_direction(payload, **kwargs)


def selected(payload):
    payload.update(reference_policy="default_library", selected_references=[{
        "reference_id": "case2", "start": 0, "end": 180,
        "observation_ids": ["case2-title"], "fit_reason": "地点标题留白"}])


def test_reference_selection_is_bounded_and_observation_grounded():
    payload, kwargs = context()
    selected(payload)
    assert module().validate_creative_direction(payload, **kwargs).selected_references[0].end == 180
    for changes in ({"end":181}, {"observation_ids":["case1-title"]}, {"observation_ids":[]}, {"start":30}):
        invalid = copy.deepcopy(payload)
        invalid["selected_references"][0].update(changes)
        with pytest.raises(ValueError):
            module().validate_creative_direction(invalid, **kwargs)


def test_explicit_vocals_and_missing_climax_cannot_be_overridden():
    payload, kwargs = context()
    kwargs["brief"].normalized_fields.vocals = "instrumental_only"
    with pytest.raises(ValueError):
        module().validate_creative_direction(payload, **kwargs)
    payload["vocals"] = "instrumental_only"
    kwargs["coverage"].missing_director_functions = ["climax"]
    payload["sections"][0].update(climax=True, material_gaps=[])
    with pytest.raises(ValueError):
        module().validate_creative_direction(payload, **kwargs)


def test_packaged_library_retains_visual_evidence_and_unheard_audio():
    lib = module().load_reference_library()
    assert len(lib["references"]) == 4
    assert all(r["audio_listened"] is False and r["observations"] for r in lib["references"])
    assert len(module().reference_library_sha256()) == 64


def test_custom_alias_cannot_expand_case_two_range():
    payload, kwargs = context()
    alias = copy.deepcopy(module().load_reference_library()['references'][1])
    alias.update(reference_id='new-id', url=alias['url'] + '?share=1', end=200)
    payload['custom_references'] = [alias]
    with pytest.raises(ValueError, match='range'):
        module().validate_creative_direction(payload, **kwargs)


def test_custom_reference_requires_evidence_and_cannot_override_defaults():
    payload, kwargs = context()
    custom = copy.deepcopy(module().load_reference_library()["references"][0])
    payload.update(custom_references=[custom])
    with pytest.raises(ValueError):
        module().validate_creative_direction(payload, **kwargs)
    custom["reference_id"] = "my-reference"
    payload.update(reference_policy="custom", selected_references=[{
        "reference_id":"my-reference", "start":0,"end":100,
        "observation_ids":["case1-title"],"fit_reason":"参考标题关系"}])
    assert module().validate_creative_direction(payload, **kwargs).reference_policy == "custom"
    custom["observations"][0]["evidence_path"] = " "
    with pytest.raises(ValueError):
        module().validate_creative_direction(payload, **kwargs)


def test_rejected_material_is_invalid_even_if_present_in_manifest():
    payload, kwargs = context()
    rejected = "sha256:" + "e" * 64
    kwargs["material_ids"].add(rejected)
    kwargs["treatment"].reject_suggestions.append(rejected)
    payload["sections"][0]["material_ids"] = [rejected]
    with pytest.raises(ValueError, match="rejected"):
        module().validate_creative_direction(payload, **kwargs)


@pytest.mark.parametrize("next_start", [19.9, 20.1])
def test_sections_reject_overlap_and_gap(next_start):
    payload, kwargs = context()
    second = copy.deepcopy(payload["sections"][0])
    second.update(section_id="ending", start=next_start)
    payload["sections"][0]["end"] = 20
    payload["sections"].append(second)
    with pytest.raises(ValueError, match="contiguous"):
        module().validate_creative_direction(payload, **kwargs)


def test_library_load_does_not_depend_on_cwd_or_leak_mutations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lib = module().load_reference_library()
    lib["references"].clear()
    assert len(module().load_reference_library()["references"]) == 4


@pytest.mark.parametrize("artifact", ["treatment", "coverage"])
def test_creative_direction_requires_completed_source_artifacts(artifact):
    payload, kwargs = context()
    kwargs[artifact].status = "partial"
    with pytest.raises(ValueError, match="completed"):
        module().validate_creative_direction(payload, **kwargs)


def test_creative_direction_rejects_unsupported_treatment_inferences():
    payload, kwargs = context()
    kwargs["treatment"].unsupported_inferences = ["无证据的地点判断"]
    with pytest.raises(ValueError, match="unsupported"):
        module().validate_creative_direction(payload, **kwargs)


def test_reference_library_evidence_paths_are_relative_and_resolvable():
    lib = module().load_reference_library()
    for ref in lib["references"]:
        assert not ref["audio_notes"].startswith("/"), "audio_notes should not hardcode root paths"
        for obs in ref["observations"]:
            assert not obs["evidence_path"].startswith("/"), f"path must be relative: {obs['evidence_path']}"
            resolved = module().resolve_reference_evidence(obs["evidence_path"])
            assert resolved.is_file(), f"evidence file must exist: {resolved}"

    resolved_lib = module().load_reference_library(resolve_paths=True)
    for ref in resolved_lib["references"]:
        for obs in ref["observations"]:
            assert obs["evidence_path"].startswith("/"), f"path must be absolute when resolved: {obs['evidence_path']}"
            assert module().Path(obs["evidence_path"]).is_file()


def test_resolve_reference_evidence_respects_env_overrides(tmp_path, monkeypatch):
    custom_root = tmp_path / "custom_root"
    custom_root.mkdir()
    fake_img = custom_root / "evidence/case1/t002.5.jpg"
    fake_img.parent.mkdir(parents=True)
    fake_img.write_text("fake", encoding="utf-8")

    monkeypatch.setenv("TRAVEL_DIRECTOR_REFERENCE_ROOT", str(custom_root))
    resolved = module().resolve_reference_evidence("evidence/case1/t002.5.jpg")
    assert resolved == fake_img.resolve()
