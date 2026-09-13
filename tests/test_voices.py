from teu_voice.voices import default_builtin_voice, list_builtin_voices, preferred_region


def test_default_region_prefers_saigon() -> None:
    assert preferred_region() == "nam"
    voices = list_builtin_voices()
    assert voices
    assert all(voice.region in {"Nam", "Trung", ""} for voice in voices)
    assert voices[0].region == "Nam"
    assert default_builtin_voice() == voices[0].id
    assert voices[0].label.startswith(voices[0].id)
    assert "[object Object]" not in voices[0].label
