# Nghiên cứu engine TTS — cập nhật 05/09/2026

## Kết luận

VieNeu‑TTS v3 Turbo là backend mặc định hợp lý nhất cho máy hiện tại: Intel i5‑12600K, RAM khoảng 32 GB, không có NVIDIA/CUDA. Nó chạy native Windows bằng ONNX, hỗ trợ tiếng Việt, clone từ 3–8 giây và giữ toàn bộ dữ liệu local.

Nguồn chính thức:

- [VieNeu‑TTS repository](https://github.com/pnnbao97/VieNeu-TTS)
- [VieNeu 3.4.0 trên PyPI](https://pypi.org/project/vieneu/3.4.0/)
- [VieNeu‑TTS v3 Turbo model card](https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo)
- [Apache‑2.0 license](https://github.com/pnnbao97/VieNeu-TTS/blob/main/LICENSE)
- [Thông số Intel i5‑12600K](https://www.intel.com/content/www/us/en/products/sku/134589/intel-core-i512600k-processor-20m-cache-up-to-4-90-ghz/specifications.html)

## Mẫu WAV đã cung cấp

- PCM 16-bit, mono, 48 kHz, dài 6,335 giây.
- Integrated loudness khoảng −16,18 LUFS; true peak −1,80 dBTP; không clipping.
- Khoảng 1,26 giây pause, còn xấp xỉ 5,07 giây speech-active.
- F0 median ước tính 147,7 Hz; dải biến thiên rộng và cadence nhanh, hợp kiểu nói hoạt bát.
- File sạch nhưng đã compress/gate tương đối rõ. Không nên denoise hoặc normalize thêm.

Mẫu đạt cửa sổ clone 3–8 giây của VieNeu. Điểm yếu là lượng tiếng nói thực còn ít, nên độ giống và cách phát âm có thể dao động khi tạo câu dài.

## MP3 biểu cảm dùng làm mẫu hành vi

Tệp MP3 dài 44,489 giây, stereo gần như dual-mono 44,1 kHz. Phân tích chỉ đọc cho thấy:

- Loudness khoảng −8,10 LUFS, true peak +0,40 dBTP và có sample overs. Mức master này quá nóng để sao chép; output của ứng dụng được giới hạn peak ở khoảng −1,5 dBFS.
- Có 25 khoảng nghỉ từ 120 ms trở lên, tổng 13,785 giây; phần lớn khoảng nghỉ nội bộ dài 0,21–0,91 giây.
- Median F0 xấp xỉ 168 Hz, với các block lớn dao động khoảng 143–249 Hz. Nhịp và cao độ thay đổi theo đoạn rõ hơn mẫu clone sạch.
- Hai kênh tương quan 0,9973, nên đầu ra mono vẫn phù hợp.

Kết luận: MP3 phù hợp làm mẫu **hành vi diễn** để thiết kế phạm vi tag, nhịp ngắt và DSP theo đoạn. Nó không phù hợp làm voice reference trực tiếp vì quá dài, quá lớn và đã nén mạnh. Không có ASR tiếng Việt local đủ tin cậy trong môi trường thử nghiệm, vì vậy nội dung trong ảnh chỉ được dùng làm ví dụ nhãn, không bị coi là lời chỉ dẫn hoặc transcript đã xác minh.

## Nghiên cứu audio tag

ElevenLabs mô tả audio tag v3 là chỉ dẫn ngôn ngữ tự nhiên, không phải một enum đóng. Tài liệu chính thức nêu các ví dụ như `laughs`, `whispers`, `sighs`, `sarcastic`, `curious`, `excited`, `mischievously`; hiệu quả còn phụ thuộc giọng được chọn. Vì vậy thư viện của dự án dùng catalog tiếng Việt ổn định nhưng vẫn cho tìm bằng alias Anh, gồm các ví dụ người dùng đã thu thập và thêm các nhóm tone, delivery, reaction, pause.

- [ElevenLabs prompting best practices](https://elevenlabs.io/docs/best-practices/prompting)
- [ElevenLabs audio tags](https://elevenlabs.io/blog/v3-audiotags)
- [Fish Audio model overview](https://docs.fish.audio/developer-guide/models-pricing/models-overview)

## Chẩn đoán output và thay đổi đã áp dụng

File `teu-voice-a023c41d4c93.wav` đúng PCM16 mono 48 kHz, không clipping, nhưng có dấu vết reset rất rõ: 17 lần tổng hợp độc lập, 18 khoảng zero dài từ 80 ms và tổng zero khoảng 6,53 giây. Bản này dài 27,252 giây, khoảng −19,85 LUFS; độ biến thiên F0 thấp hơn cả reference và MP3 cảm xúc. Đổi pitch cố định trên từng câu chỉ đổi màu giọng, không tạo được đường ngữ điệu bên trong câu.

Engine đã được đổi theo kết quả đo:

- Gộp tag sắc thái vào cùng nhóm gọi model; chỉ `@ngắt_*` và pause có chủ ý mới tạo ranh giới ở tầng ứng dụng. VieNeu vẫn tự chunk nội bộ với văn bản dài.
- Bỏ khoảng zero 90 ms tự động và cắt silence thừa ở mép mỗi lượt sinh.
- Bỏ pitch/gain theo mẩu khỏi đường render VieNeu để giữ formant và màu giọng tự nhiên.
- Master một lần sau khi ghép, mục tiêu RMS gần −16,5 dBFS, soft ceiling −1,5 dBFS.

Với đúng kịch bản kiểm tra, output mới dài 20,743 giây, còn 5 khoảng zero dài từ 80 ms với tổng 1,18 giây; loudness đo được khoảng −16,4 LUFS và true peak −1,7 dBFS. Phần còn phẳng đến từ giới hạn của model/reference trung tính, không còn do bộ ghép băm nhỏ waveform.

Một probe local tiếp theo tách hai clip phong cách dài 6 giây (`excited`, `funny`) từ audio hành vi rồi ghép **speaker embedding của mẫu clone** với **reference codes của clip phong cách**. Trên cùng câu thử, dải F0 p90–p10 tăng từ khoảng 4,90 lên 6,65 semitone với mẫu `excited` và 6,00 semitone với mẫu `funny`. Cosine speaker embedding đo được lần lượt khoảng 0,906 và 0,893 so với 0,864 ở baseline. Đây là phép đo định hướng trên một câu, không phải điểm chất lượng nghe chủ quan hay cam kết giữ danh tính tuyệt đối; vì vậy tính năng được để dạng công tắc A/B thử nghiệm.

## Giới hạn cần nói rõ

VieNeu v3 chỉ hỗ trợ thử nghiệm ba cue `[cười]`, `[thở dài]`, `[hắng giọng]`. Tham số `style` cũ đã deprecated và bị bỏ qua. Vì vậy ứng dụng không gửi tag lạ dạng dấu ngoặc vuông vào model: `@tag` được biên dịch thành ba cue gốc, punctuation và khoảng nghỉ có chủ ý, đồng thời giữ câu liền mạch. Những tag semantic phức tạp vẫn là mô phỏng; phong cách chủ yếu đến từ reference.

DeepSeek V4 là model text-only theo model card. Một LLM như vậy có thể đứng trước TTS để chọn tag/sửa dấu câu, nhưng không thể nâng vocoder, tạo tiếng cười hay biến đường F0 thành diễn xuất người thật. Endpoint tunnel do người dùng đưa không phải domain API DeepSeek chính thức; không gửi dữ liệu/khóa vào đó và không hard-code bí mật. Khóa đã dán trong hội thoại cần được thu hồi rồi tạo lại.

- [DeepSeek V4 model card](https://fe-static.deepseek.com/chat/transparency/deepseek-V4-model-card-EN.pdf)
- [DeepSeek API chính thức](https://api-docs.deepseek.com/)

## Các lựa chọn mạnh hơn nhưng không phù hợp làm mặc định local

### Higgs Audio / Higgs TTS 3

Higgs có clone zero-shot, tiếng Việt và điều khiển emotion/prosody/SFX phong phú hơn. Tuy nhiên model nhiều tỷ tham số, luồng self-host phù hợp Linux/WSL và GPU NVIDIA khoảng 24–40 GB VRAM. Không hợp phần cứng hiện tại.

- [Higgs TTS 3 model card](https://huggingface.co/bosonai/higgs-tts-3-4b)
- [Boson voice guide](https://docs.boson.ai/models/higgs-tts/voices)

### Fish Audio S2 Pro / S2.1 Pro

Fish S2 hỗ trợ natural-language emotion tags, voice cloning, tốc độ native và model card liệt kê tiếng Việt trong 83 ngôn ngữ. Self-host khuyến nghị GPU 24 GB; API dễ dùng hơn nhưng voice sẽ rời máy. Đây là ứng viên đầu tiên nên A/B cho chế độ cloud expressive; tài liệu API hiện hỗ trợ WAV 44,1 kHz và chế độ chất lượng `normal`.

- [Fish Speech repository](https://github.com/fishaudio/fish-speech)
- [Fish model overview](https://docs.fish.audio/developer-guide/models-pricing/models-overview)
- [Fish TTS API](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech)
- [Fish emotion controls](https://docs.fish.audio/developer-guide/core-features/emotions)
- [Fish terms](https://fish.audio/terms/)

### ElevenLabs v3

Eleven v3 hỗ trợ tiếng Việt và cue biểu diễn đa dạng; Instant Voice Cloning phù hợp hơn khi có 1–2 phút audio sạch. Đây là phương án hosted nên A/B khi chất lượng cảm xúc quan trọng hơn quyền riêng tư. Có thể tắt sử dụng dữ liệu mới để cải thiện model.

- [ElevenLabs models and languages](https://elevenlabs.io/docs/overview/models)
- [Audio tag prompting](https://elevenlabs.io/docs/best-practices/prompting)
- [Voice cloning](https://elevenlabs.io/docs/eleven-api/concepts/voice-cloning)
- [Data usage controls](https://elevenlabs.io/docs/help-center/legal/is-my-data-used-to-improve-eleven-labs-ai-models)

## Hướng phát triển tiếp

- Thu 30–60 giây làm thư viện nguồn, rồi cắt ba reference 3–8 giây theo phong cách và chọn reference theo tag.
- Sinh 3–4 biến thể cùng kịch bản rồi xếp hạng/chọn thủ công.
- Thêm adapter Fish S2.1 Pro trước, sau đó A/B với ElevenLabs v3 và Higgs TTS 3; chỉ upload sau khi người dùng chủ động chọn và cung cấp đúng API key TTS.
- Nếu cần fine-tune giọng riêng, chuẩn bị tối thiểu 10–30 phút audio đã cắt câu và transcript chính xác; nên thuê GPU thay vì train trên máy này.
