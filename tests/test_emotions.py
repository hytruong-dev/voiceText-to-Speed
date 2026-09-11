import re

import pytest

from teu_voice.emotions import EMOTION_TAGS, compile_emotion_script, tag_catalog


def spoken_words(text: str) -> list[str]:
    without_cues = re.sub(r"\[(?:cười|thở dài|hắng giọng)\]", "", text)
    return re.findall(r"[\wÀ-ỹ]+", without_cues.lower(), flags=re.UNICODE)


@pytest.mark.parametrize(
    ("typed", "expected_id", "canonical"),
    [
        ("excited", "excited", "@hào_hứng"),
        ("delighted", "delighted", "@hân_hoan"),
        ("giddy", "giddy", "@phấn_khích"),
        ("amazed", "amazed", "@kinh_ngạc"),
        ("smug", "smug", "@tự_mãn"),
        ("cocky", "cocky", "@ngạo_nghễ"),
        ("giggles", "giggle", "@cười_khúc_khích"),
        ("mock gasp", "mock_gasp", "@há_hốc_giả"),
        ("surprised", "surprised", "@bất_ngờ"),
        ("laughs loudly", "laugh_loud", "@cười_lớn"),
        ("big hearty laugh", "hearty_laugh", "@cười_sảng_khoái"),
        ("bursts out laughing", "burst_laugh", "@phì_cười"),
        ("chuckles", "chuckle", "@cười_khẽ"),
        ("hài hước", "funny", "@hài_hước"),
        ("hai huoc", "funny", "@hài_hước"),
    ],
)
def test_user_examples_and_aliases_compile(typed: str, expected_id: str, canonical: str) -> None:
    plan = compile_emotion_script(f"@{typed} Đây là một câu thử nghiệm vui vẻ.")
    assert expected_id in plan.tag_ids
    assert canonical in plan.display_text
    assert "[" not in plan.display_text


def test_tags_are_scoped_to_the_following_segment() -> None:
    plan = compile_emotion_script(
        "Mở đầu tự nhiên. @hài_hước Đây là phần vui. @tỉnh_bơ Đây là câu chốt."
    )
    assert len(plan.segments) == 3
    assert plan.segments[0].tag_ids == ()
    assert plan.segments[1].tag_ids == ("funny",)
    assert plan.segments[2].tag_ids == ("deadpan",)
    assert plan.segments[1].speed_multiplier != plan.segments[2].speed_multiplier


def test_blank_line_expires_a_tag() -> None:
    plan = compile_emotion_script("@buồn Đoạn đầu rất dài và chậm.\n\nĐoạn sau bình thường.")
    assert len(plan.segments) == 2
    assert plan.segments[0].tag_ids == ("sad",)
    assert plan.segments[1].tag_ids == ()
    assert plan.segments[1].pause_before_ms == 450


def test_native_cues_stay_private_and_only_supported_cues_reach_engine() -> None:
    plan = compile_emotion_script(
        "@cười_khẽ Hê hê. @thở_dài Chuyện đời. @hắng_giọng Xin nghe đây."
    )
    assert "[" not in plan.display_text
    assert "[cười]" in plan.engine_text
    assert "[thở dài]" in plan.engine_text
    assert "[hắng giọng]" in plan.engine_text
    assert not re.search(r"\[(?!cười\]|thở dài\]|hắng giọng\]).+?\]", plan.engine_text)
    assert "engine_text" not in plan.preview_dict()


def test_every_spoken_word_is_preserved() -> None:
    plan = compile_emotion_script(
        "Người ta bảo tôi dậy sớm. @hài_hước Tôi nghe xong rồi ngủ tiếp! @cười Hê hê."
    )
    expected = "Người ta bảo tôi dậy sớm. Tôi nghe xong rồi ngủ tiếp! Hê hê."
    assert spoken_words(plan.engine_text) == spoken_words(expected)


def test_unknown_square_bracket_and_model_tokens_are_rejected() -> None:
    with pytest.raises(ValueError, match="Không nhận ra tag"):
        compile_emotion_script("@không_tồn_tại Xin chào")
    with pytest.raises(ValueError, match="dấu ngoặc vuông"):
        compile_emotion_script("[excited] Xin chào")
    with pytest.raises(ValueError, match="dấu ngoặc vuông"):
        compile_emotion_script("<|emotion_999|> Xin chào")


def test_email_is_not_treated_as_an_emotion_tag() -> None:
    text = "Gửi thư tới hello@example.com để biết thêm chi tiết."
    plan = compile_emotion_script(text)
    assert plan.display_text == text
    assert plan.engine_text == text
    assert plan.tag_ids == ()


def test_tags_only_and_too_many_tags_are_rejected() -> None:
    with pytest.raises(ValueError, match="ít nhất một từ"):
        compile_emotion_script("@hài_hước @cười")
    with pytest.raises(ValueError, match="tối đa 64"):
        compile_emotion_script(("@cười " * 65) + "Xin chào")


def test_segment_effects_are_safely_bounded() -> None:
    plan = compile_emotion_script(
        "@bất_ngờ @hét_lớn @cười_lớn @cười_sảng_khoái Chuyện này thật không thể tin nổi!"
    )
    segment = plan.segments[0]
    assert 0.82 <= segment.speed_multiplier <= 1.18
    assert -1.5 <= segment.pitch_steps <= 1.5
    assert -6.0 <= segment.gain_db <= 3.0
    assert 0.70 <= segment.temperature <= 0.95


def test_catalog_has_unique_ids_mentions_and_support_metadata() -> None:
    catalog = tag_catalog()
    assert len(catalog) >= 40
    assert len({tag.id for tag in EMOTION_TAGS}) == len(EMOTION_TAGS)
    assert len({tag.mention for tag in EMOTION_TAGS}) == len(EMOTION_TAGS)
    assert all(item["support_label"] for item in catalog)
    assert {item["fidelity"] for item in catalog} >= {
        "native",
        "hybrid",
        "approximate",
        "deterministic",
    }
