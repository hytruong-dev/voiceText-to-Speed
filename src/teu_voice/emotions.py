from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class EmotionTag:
    id: str
    token: str
    name: str
    category: str
    kind: str
    icon: str
    description: str
    aliases: tuple[str, ...] = ()
    native_cue: str | None = None
    speed: float = 1.0
    pitch_steps: float = 0.0
    gain_db: float = 0.0
    temperature_delta: float = 0.0
    punctuation: str = "natural"
    pause_ms: int = 0
    fidelity: str = "approximate"
    popular: bool = False

    @property
    def mention(self) -> str:
        return f"@{self.token}"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["mention"] = self.mention
        payload["aliases"] = list(self.aliases)
        payload["support_label"] = {
            "native": "Gốc",
            "deterministic": "Biên tập",
            "hybrid": "Cue + biên tập",
            "approximate": "Mô phỏng",
        }[self.fidelity]
        if self.fidelity == "approximate":
            payload["description"] = (
                f"Chỉ đạo sắc thái {self.name.lower()}; VieNeu local chỉ mô phỏng "
                "bằng ngữ cảnh và dấu câu."
            )
        elif self.fidelity == "hybrid":
            payload["description"] = (
                f"Biến thể {self.name.lower()} dùng cue VieNeu gần nhất; "
                "không phải hiệu ứng native riêng."
            )
        return payload


def _tag(
    id: str,
    token: str,
    name: str,
    category: str,
    kind: str,
    icon: str,
    description: str,
    aliases: tuple[str, ...] = (),
    **effects: object,
) -> EmotionTag:
    return EmotionTag(
        id=id,
        token=token,
        name=name,
        category=category,
        kind=kind,
        icon=icon,
        description=description,
        aliases=aliases,
        **effects,
    )


# Vietnamese-first names with English aliases make the user's ElevenLabs-style
# examples searchable without exposing square-bracket syntax in the editor.
EMOTION_TAGS = (
    _tag("happy", "vui_vẻ", "Vui vẻ", "Vui & năng lượng", "tone", "☀", "Sáng giọng và nhanh nhẹ.", ("happy", "happily", "cheerfully", "vui ve"), speed=1.03, pitch_steps=0.25, punctuation="bright", popular=True),
    _tag("excited", "hào_hứng", "Hào hứng", "Vui & năng lượng", "tone", "✦", "Tăng năng lượng, cao độ và nhịp đọc.", ("excited", "excitedly", "hao hung"), speed=1.08, pitch_steps=0.65, gain_db=0.8, temperature_delta=0.06, punctuation="excited", popular=True),
    _tag("delighted", "hân_hoan", "Hân hoan", "Vui & năng lượng", "tone", "❋", "Vui ấm, tươi và có điểm nhấn.", ("delighted", "elated", "han hoan"), speed=1.04, pitch_steps=0.4, gain_db=0.3, punctuation="bright"),
    _tag("giddy", "phấn_khích", "Phấn khích", "Vui & năng lượng", "tone", "⚡", "Nhanh, cao và giàu biến động hơn.", ("giddy", "phan khich", "sung sướng", "sung suong"), speed=1.10, pitch_steps=0.8, gain_db=0.5, temperature_delta=0.08, punctuation="excited"),
    _tag("amazed", "kinh_ngạc", "Kinh ngạc", "Vui & năng lượng", "tone", "✺", "Nhấc cao độ, có nhịp lấy đà.", ("amazed", "in awe", "awe", "kinh ngac"), speed=0.98, pitch_steps=0.75, gain_db=0.5, punctuation="surprised"),
    _tag("curious", "tò_mò", "Tò mò", "Vui & năng lượng", "tone", "?", "Nhẹ, sáng và nhấc giọng ở câu hỏi.", ("curious", "curiously", "to mo"), speed=0.98, pitch_steps=0.35, punctuation="curious"),
    _tag("warm", "ấm_áp", "Ấm áp", "Vui & năng lượng", "tone", "◌", "Mềm, chậm nhẹ và gần gũi.", ("warm", "warmly", "friendly", "am ap"), speed=0.95, pitch_steps=-0.2, gain_db=-0.7, temperature_delta=-0.03, punctuation="soft"),
    _tag("confident", "tự_tin", "Tự tin", "Vui & năng lượng", "tone", "◆", "Chắc nhịp, rõ điểm rơi và đầy đặn hơn.", ("confident", "confidently", "tu tin"), speed=0.98, pitch_steps=-0.15, gain_db=0.8, punctuation="emphasis"),

    _tag("funny", "hài_hước", "Hài hước", "Hài & trêu đùa", "tone", "◡", "Tạo nhịp có duyên, không tự chèn tiếng cười.", ("funny", "humorous", "witty", "dí dỏm", "di dom", "hai huoc"), speed=1.02, pitch_steps=0.15, punctuation="comic", popular=True),
    _tag("teasing", "trêu_đùa", "Trêu đùa", "Hài & trêu đùa", "tone", "⌁", "Nhẹ, tinh nghịch và nhấn câu chốt.", ("teasing", "playfully", "bantering", "cà khịa", "ca khia", "treu dua"), speed=1.03, pitch_steps=0.25, punctuation="comic", popular=True),
    _tag("smug", "tự_mãn", "Tự mãn", "Hài & trêu đùa", "tone", "⌐", "Chậm hơn, thấp giọng và đắc ý.", ("smug", "đắc ý", "dac y", "tu man"), speed=0.95, pitch_steps=-0.45, punctuation="drawn"),
    _tag("cocky", "ngạo_nghễ", "Ngạo nghễ", "Hài & trêu đùa", "tone", "↗", "Tự tin, hơi lớn và có độ nghênh.", ("cocky", "boastful", "ngao nghe"), pitch_steps=-0.3, gain_db=0.8, punctuation="emphasis"),
    _tag("sarcastic", "mỉa_mai", "Mỉa mai", "Hài & trêu đùa", "tone", "≈", "Chậm, thấp và kéo nhịp cuối.", ("sarcastic", "sarcastically", "dry", "mia mai"), speed=0.93, pitch_steps=-0.55, gain_db=-0.5, punctuation="drawn"),
    _tag("deadpan", "tỉnh_bơ", "Tỉnh bơ", "Hài & trêu đùa", "tone", "—", "Phẳng, chậm và tiết chế cảm xúc.", ("deadpan", "flatly", "tinh bo"), speed=0.90, pitch_steps=-0.7, gain_db=-1.0, temperature_delta=-0.08, punctuation="flat", popular=True),
    _tag("mischievous", "tinh_nghịch", "Tinh nghịch", "Hài & trêu đùa", "tone", "◈", "Nhanh nhẹ, sáng và láu lỉnh.", ("mischievous", "mischievously", "tinh nghich"), speed=1.04, pitch_steps=0.35, temperature_delta=0.04, punctuation="comic"),

    _tag("surprised", "bất_ngờ", "Bất ngờ", "Bất ngờ & kịch tính", "tone", "!", "Nhấc cao độ và tăng lực ở điểm bật.", ("surprised", "startled", "bat ngo"), speed=1.05, pitch_steps=0.85, gain_db=0.8, temperature_delta=0.05, punctuation="surprised", popular=True),
    _tag("mock_gasp", "há_hốc_giả", "Há hốc giả", "Bất ngờ & kịch tính", "tone", "◯", "Khoảng khựng kịch tính rồi bật cao độ.", ("mock gasp", "excited gasp", "happy gasp", "fake gasp", "ha hoc gia"), speed=0.96, pitch_steps=1.0, punctuation="gasp"),
    _tag("dramatic", "kịch_tính", "Kịch tính", "Bất ngờ & kịch tính", "tone", "◆", "Chậm lấy đà, ngắt rõ và tăng lực.", ("dramatic", "dramatically", "kich tinh"), speed=0.94, gain_db=0.7, temperature_delta=0.05, punctuation="dramatic"),
    _tag("nervous", "lo_lắng", "Lo lắng", "Bất ngờ & kịch tính", "tone", "≋", "Nhanh nhẹ, hơi cao và nhỏ hơn.", ("nervous", "nervously", "worried", "lo lang"), speed=1.06, pitch_steps=0.3, gain_db=-1.0, punctuation="hesitant"),
    _tag("scared", "sợ_hãi", "Sợ hãi", "Bất ngờ & kịch tính", "tone", "△", "Cao, nhanh và có nhịp ngập ngừng.", ("scared", "fearful", "terrified", "so hai"), speed=1.08, pitch_steps=0.7, gain_db=-0.4, temperature_delta=0.06, punctuation="hesitant"),
    _tag("angry", "tức_giận", "Tức giận", "Bất ngờ & kịch tính", "tone", "▴", "Mạnh, nhanh và dồn lực.", ("angry", "furious", "frustrated", "tuc gian"), speed=1.04, pitch_steps=-0.15, gain_db=2.0, temperature_delta=0.05, punctuation="emphasis"),
    _tag("sad", "buồn", "Buồn", "Bất ngờ & kịch tính", "tone", "◒", "Chậm, thấp và nhỏ hơn.", ("sad", "sorrowful", "upset", "crying", "buon"), speed=0.88, pitch_steps=-0.6, gain_db=-1.5, temperature_delta=-0.03, punctuation="drawn"),
    _tag("emotional", "xúc_động", "Xúc động", "Bất ngờ & kịch tính", "tone", "◇", "Chậm, mềm và có khoảng thở.", ("emotional", "moved", "regretful", "xuc dong"), speed=0.91, pitch_steps=0.1, gain_db=-1.0, punctuation="drawn"),
    _tag("calm", "bình_tĩnh", "Bình tĩnh", "Bất ngờ & kịch tính", "tone", "○", "Đều, chậm nhẹ và tiết chế.", ("calm", "calmly", "resigned", "binh tinh"), speed=0.92, pitch_steps=-0.2, gain_db=-0.8, temperature_delta=-0.08, punctuation="flat"),

    _tag("whisper", "thì_thầm", "Thì thầm", "Cách thể hiện", "delivery", "☾", "Hạ âm lượng, cao độ và nhịp bằng DSP.", ("whisper", "whispers", "whispering", "quietly", "thi tham"), speed=0.92, pitch_steps=-0.65, gain_db=-5.0, punctuation="drawn", popular=True),
    _tag("shout", "hét_lớn", "Hét lớn", "Cách thể hiện", "delivery", "▲", "Tăng lực, độ sáng và nhấn câu.", ("shout", "shouts", "shouting", "yelling", "yells", "hét", "het", "het lon"), speed=1.03, pitch_steps=0.25, gain_db=2.8, temperature_delta=0.04, punctuation="excited"),
    _tag("soft", "nhẹ_nhàng", "Nhẹ nhàng", "Cách thể hiện", "delivery", "≈", "Chậm nhẹ, nhỏ và mềm hơn.", ("soft", "softly", "gently", "nói nhỏ", "noi nho", "nhe nhang"), speed=0.92, pitch_steps=-0.25, gain_db=-3.0, temperature_delta=-0.04, punctuation="drawn"),
    _tag("rushed", "dồn_dập", "Dồn dập", "Cách thể hiện", "delivery", "»", "Tăng tốc rõ rệt và giảm khoảng ngắt.", ("rushed", "fast", "quickly", "nhanh", "nhanh chóng", "don dap"), speed=1.15, pitch_steps=0.2, punctuation="excited"),
    _tag("slow", "chậm_rãi", "Chậm rãi", "Cách thể hiện", "delivery", "…", "Kéo chậm nhịp đọc, giữ câu liền mạch.", ("slow", "slowly", "chậm", "cham", "cham rai"), speed=0.84, pitch_steps=-0.2, punctuation="drawn"),
    _tag("drawn_out", "kéo_dài", "Kéo dài", "Cách thể hiện", "delivery", "↝", "Kéo nhịp cuối câu để tăng biểu cảm.", ("drawn out", "elongated", "keo dai"), speed=0.88, punctuation="drawn"),
    _tag("hesitate", "ngập_ngừng", "Ngập ngừng", "Cách thể hiện", "delivery", "⋯", "Thêm nhịp lửng và khoảng do dự.", ("hesitate", "hesitates", "hesitant", "stammers", "stutter", "ngap ngung"), speed=0.91, punctuation="hesitant"),
    _tag("emphasis", "nhấn_mạnh", "Nhấn mạnh", "Cách thể hiện", "delivery", "●", "Tăng lực và làm rõ điểm rơi.", ("emphasis", "emphasize", "strongly", "nhan manh"), gain_db=1.2, punctuation="emphasis"),

    _tag("laugh", "cười", "Cười", "Phản ứng & tiếng cười", "reaction", "◡", "Cue cười gốc của VieNeu.", ("laugh", "laughs", "laughing", "cuoi"), native_cue="cười", fidelity="native", popular=True),
    _tag("chuckle", "cười_khẽ", "Cười khẽ", "Phản ứng & tiếng cười", "reaction", "◡", "Cue cười gốc, được hạ lực nhẹ.", ("chuckle", "chuckles", "chuckling", "light chuckle", "cuoi khe"), native_cue="cười", gain_db=-1.0, fidelity="hybrid", popular=True),
    _tag("giggle", "cười_khúc_khích", "Cười khúc khích", "Phản ứng & tiếng cười", "reaction", "ᵔ", "Cue cười gốc với cao độ sáng hơn.", ("giggle", "giggles", "giggling", "cuoi khuc khich"), native_cue="cười", speed=1.06, pitch_steps=0.65, fidelity="hybrid"),
    _tag("laugh_loud", "cười_lớn", "Cười lớn", "Phản ứng & tiếng cười", "reaction", "◉", "Cue cười gốc và tăng lực.", ("laughs loudly", "loud laugh", "laughs harder", "cuoi lon"), native_cue="cười", gain_db=2.0, fidelity="hybrid"),
    _tag("hearty_laugh", "cười_sảng_khoái", "Cười sảng khoái", "Phản ứng & tiếng cười", "reaction", "☀", "Cue cười gốc, mở và mạnh hơn.", ("big hearty laugh", "belly laugh", "with genuine belly laugh", "cuoi sang khoai"), native_cue="cười", speed=0.96, pitch_steps=-0.2, gain_db=2.3, fidelity="hybrid"),
    _tag("burst_laugh", "phì_cười", "Phì cười", "Phản ứng & tiếng cười", "reaction", "✹", "Cue cười bật nhanh tại đúng vị trí tag.", ("bursts out laughing", "starts laughing", "snorts", "phi cuoi"), native_cue="cười", speed=1.05, pitch_steps=0.3, gain_db=1.0, fidelity="hybrid"),
    _tag("sigh", "thở_dài", "Thở dài", "Phản ứng & tiếng cười", "reaction", "⌄", "Cue thở dài gốc của VieNeu.", ("sigh", "sighs", "frustrated sigh", "sigh of relief", "tho dai"), native_cue="thở dài", speed=0.96, gain_db=-1.0, fidelity="native"),
    _tag("clear_throat", "hắng_giọng", "Hắng giọng", "Phản ứng & tiếng cười", "reaction", "·", "Cue hắng giọng gốc của VieNeu.", ("clear throat", "clears throat", "hang giong"), native_cue="hắng giọng", fidelity="native"),
    _tag("exhale", "thở_hắt", "Thở hắt", "Phản ứng & tiếng cười", "reaction", "↘", "Fallback bằng cue thở dài ngắn và hạ lực.", ("exhale", "exhales", "tho hat"), native_cue="thở dài", gain_db=-1.5, fidelity="hybrid"),
    _tag("gasp", "há_hốc", "Há hốc", "Phản ứng & tiếng cười", "reaction", "○", "Mô phỏng bằng khoảng khựng và bật cao độ.", ("gasp", "gasps", "gulp", "gulps", "ha hoc"), pause_ms=180, speed=0.97, pitch_steps=0.9, punctuation="gasp"),

    _tag("pause_short", "ngắt_ngắn", "Ngắt ngắn", "Nhịp & khoảng nghỉ", "pause", "Ⅰ", "Chèn khoảng nghỉ khoảng 0,2 giây.", ("short pause", "brief pause", "ngat ngan"), pause_ms=200, fidelity="deterministic"),
    _tag("pause_medium", "ngắt_vừa", "Ngắt vừa", "Nhịp & khoảng nghỉ", "pause", "Ⅱ", "Chèn khoảng nghỉ khoảng 0,45 giây.", ("pause", "medium pause", "beat", "tạm dừng", "tam dung", "ngat vua"), pause_ms=450, fidelity="deterministic", popular=True),
    _tag("pause_long", "ngắt_dài", "Ngắt dài", "Nhịp & khoảng nghỉ", "pause", "Ⅲ", "Chèn khoảng nghỉ khoảng 0,9 giây.", ("long pause", "dramatic pause", "ngat dai"), pause_ms=900, fidelity="deterministic"),
)


TAG_BY_ID = {tag.id: tag for tag in EMOTION_TAGS}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    ascii_like = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[\s_-]+", "_", ascii_like).strip("_")


def _forms(tag: EmotionTag) -> set[str]:
    base = {tag.id, tag.token, tag.token.replace("_", " "), tag.name, *tag.aliases}
    return {item for item in base if item}


_TAG_BY_FORM: dict[str, EmotionTag] = {}
for _emotion_tag in EMOTION_TAGS:
    for _form in _forms(_emotion_tag):
        key = _fold(_form)
        previous = _TAG_BY_FORM.get(key)
        if previous is not None and previous.id != _emotion_tag.id:
            raise RuntimeError(f"Emotion alias '{_form}' is ambiguous.")
        _TAG_BY_FORM[key] = _emotion_tag


def _form_pattern(form: str) -> str:
    words = [word for word in re.split(r"[\s_-]+", form.strip()) if word]
    return r"[\s_-]+".join(re.escape(word) for word in words)


_PATTERN_FORMS = sorted(
    {form for tag in EMOTION_TAGS for form in _forms(tag)},
    key=lambda item: (len(item), item),
    reverse=True,
)
_KNOWN_TAG_RE = re.compile(
    r"(?<![\w@])@(?P<tag>" + "|".join(_form_pattern(form) for form in _PATTERN_FORMS) + r")(?![\w])",
    re.IGNORECASE | re.UNICODE,
)
_UNKNOWN_TAG_RE = re.compile(r"(?<![\w@])@(?P<tag>[\wÀ-ỹ-]+)", re.UNICODE)
_INTERNAL_TOKEN_RE = re.compile(
    r"\[[^\]\n]{1,48}\]|<\|emotion_[^|>]*\|>",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class EmotionSegment:
    engine_text: str
    tag_ids: tuple[str, ...] = ()
    speed_multiplier: float = 1.0
    pitch_steps: float = 0.0
    gain_db: float = 0.0
    temperature: float = 0.8
    pause_before_ms: int = 0

    def public_dict(self) -> dict[str, object]:
        return {
            "tag_ids": list(self.tag_ids),
            "pause_before_ms": self.pause_before_ms,
        }


@dataclass(frozen=True, slots=True)
class EmotionPlan:
    display_text: str
    engine_text: str
    tag_ids: tuple[str, ...]
    segments: tuple[EmotionSegment, ...]
    warnings: tuple[str, ...]

    def preview_dict(self) -> dict[str, object]:
        return {
            "performance_text": self.display_text,
            "emotion_tags": list(self.tag_ids),
            "segments": [segment.public_dict() for segment in self.segments],
            "segment_count": len(self.segments),
            "wrapper_group_count": natural_render_group_count(self.segments),
            "warnings": list(self.warnings),
        }


def natural_render_group_count(segments: tuple[EmotionSegment, ...]) -> int:
    """Count wrapper-level model calls after explicit pause boundaries."""

    if not segments:
        return 0
    return 1 + sum(bool(segment.pause_before_ms) for segment in segments[1:])


def _clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _apply_punctuation(text: str, modes: set[str]) -> str:
    if not text:
        return text
    # Never inject mid-sentence ellipsis. VieNeu treats "…" as a hard silence
    # boundary, which breaks otherwise continuous clauses (e.g. @chậm_rãi
    # turning "tìm góc yên tĩnh" into "tìm… góc yên tĩnh"). Pace comes from
    # tag speed multipliers and the global speed slider instead.
    if modes & {"bright", "excited", "surprised", "emphasis"}:
        text = re.sub(r"[.]$", "!", text)
        if text[-1] not in "!?…":
            text += "!"
    if "curious" in modes and text[-1] not in "?!…":
        text += "?"
    if "dramatic" in modes and "\n\n" not in text:
        sentences = re.split(r"(?<=[.!?…])\s+", text, maxsplit=1)
        if len(sentences) == 2:
            text = "\n\n".join(sentences)
    return text


def _segment_for(text: str, tags: list[EmotionTag]) -> EmotionSegment | None:
    spoken = _clean_text(text)
    if not spoken:
        return None
    cues = " ".join(f"[{tag.native_cue}]" for tag in tags if tag.native_cue)
    modes = {tag.punctuation for tag in tags}
    directed = _apply_punctuation(spoken, modes)
    engine_text = _clean_text(f"{cues} {directed}" if cues else directed)
    speed = 1.0
    for tag in tags:
        speed *= tag.speed
    return EmotionSegment(
        engine_text=engine_text,
        tag_ids=tuple(dict.fromkeys(tag.id for tag in tags)),
        speed_multiplier=round(max(0.82, min(1.18, speed)), 3),
        pitch_steps=round(max(-1.5, min(1.5, sum(tag.pitch_steps for tag in tags))), 2),
        gain_db=round(max(-6.0, min(3.0, sum(tag.gain_db for tag in tags))), 2),
        temperature=round(max(0.70, min(0.95, 0.8 + sum(tag.temperature_delta for tag in tags))), 2),
        pause_before_ms=max((tag.pause_ms for tag in tags), default=0),
    )


def _append_scoped_segments(
    segments: list[EmotionSegment],
    text: str,
    pending_tags: list[EmotionTag],
) -> bool:
    """Append text and expire directives at the first blank line."""

    if not text.strip():
        return False
    paragraphs = re.split(r"\n\n+", text)
    appended = False
    for index, paragraph in enumerate(paragraphs):
        segment = _segment_for(paragraph, pending_tags if index == 0 else [])
        if segment is not None:
            if index > 0 and segment.pause_before_ms == 0:
                segment = EmotionSegment(
                    engine_text=segment.engine_text,
                    tag_ids=segment.tag_ids,
                    speed_multiplier=segment.speed_multiplier,
                    pitch_steps=segment.pitch_steps,
                    gain_db=segment.gain_db,
                    temperature=segment.temperature,
                    pause_before_ms=450,
                )
            segments.append(segment)
            appended = True
    return appended


def compile_emotion_script(text: str) -> EmotionPlan:
    cleaned = _clean_text(text)
    if not cleaned:
        raise ValueError("Vui lòng nhập nội dung cần đọc.")
    if _INTERNAL_TOKEN_RE.search(cleaned):
        raise ValueError("Không dùng tag dạng dấu ngoặc vuông. Hãy gõ @ và chọn cảm xúc từ danh sách.")

    matches = list(_KNOWN_TAG_RE.finditer(cleaned))
    if len(matches) > 64:
        raise ValueError("Mỗi lượt chỉ nên dùng tối đa 64 tag cảm xúc.")
    masked = list(cleaned)
    for match in matches:
        masked[match.start() : match.end()] = " " * (match.end() - match.start())
    unknown = _UNKNOWN_TAG_RE.search("".join(masked))
    if unknown:
        raise ValueError(
            f"Không nhận ra tag @{unknown.group('tag')}. Gõ @ trong ô nội dung để chọn tag có sẵn."
        )

    display_parts: list[str] = []
    segments: list[EmotionSegment] = []
    used_tags: list[EmotionTag] = []
    pending_tags: list[EmotionTag] = []
    cursor = 0
    for match in matches:
        preceding = cleaned[cursor : match.start()]
        display_parts.append(preceding)
        if _append_scoped_segments(segments, preceding, pending_tags):
            pending_tags = []

        tag = _TAG_BY_FORM[_fold(match.group("tag"))]
        used_tags.append(tag)
        display_parts.append(tag.mention)
        if tag.kind == "tone":
            pending_tags = [item for item in pending_tags if item.kind != "tone"]
        elif tag.kind == "delivery":
            pending_tags = [item for item in pending_tags if item.kind != "delivery"]
        pending_tags.append(tag)
        cursor = match.end()

    tail = cleaned[cursor:]
    display_parts.append(tail)
    _append_scoped_segments(segments, tail, pending_tags)
    if not segments:
        raise ValueError("Kịch bản cần có ít nhất một từ để đọc, không thể chỉ gồm tag.")

    display_text = _clean_text("".join(display_parts))
    engine_text = "\n\n".join(segment.engine_text for segment in segments)
    tag_ids = tuple(dict.fromkeys(tag.id for tag in used_tags))
    warnings: list[str] = []
    if any(tag.fidelity == "approximate" for tag in used_tags):
        warnings.append(
            "VieNeu local không có token cảm xúc cho các tag sắc thái; "
            "ứng dụng giữ câu liền mạch và chỉ dùng ngữ cảnh, nhịp, dấu câu để mô phỏng."
        )
    if any(tag.fidelity == "hybrid" for tag in used_tags):
        warnings.append(
            "Các biến thể phản ứng dùng một trong ba cue VieNeu gần nhất, "
            "không phải âm thanh native riêng cho từng tag."
        )
    return EmotionPlan(
        display_text=display_text,
        engine_text=engine_text,
        tag_ids=tag_ids,
        segments=tuple(segments),
        warnings=tuple(warnings),
    )


def tag_catalog() -> list[dict[str, object]]:
    return [tag.to_dict() for tag in EMOTION_TAGS]
