# Hồ sơ giọng cá nhân

Mẫu hiện tại lấy từ `Record (online-voice-recorder.com).mp3` do người dùng cung cấp. File gốc dài 11,328 giây, được giữ tại `data/profiles/my-voice/original.mp3`. Đoạn 0,35–7,80 giây được chọn vì kết thúc trong khoảng nghỉ và vừa giới hạn 8 giây của engine. Bản WAV được giải mã về PCM16 mono 48 kHz, không EQ/khử ồn/nén. Mẫu mặc định trước đó được sao lưu cùng thư mục.

Mặc định mới: tắt chuyển phong cách ở UI/API/engine, tắt khử ồn khi chọn upload, tốc độ 1×. Thông tin người nói và mã tham chiếu đều lấy từ cùng mẫu. Đây là hồ sơ tham chiếu bền vững, chưa phải model đã fine-tune.

Chạy `scripts/verify_personal_voice.py` bằng Python trong `.venv` để sinh câu kiểm tra và báo cáo JSON cạnh WAV trong `outputs`. Cosine embedding không phải phần trăm giống giọng, và không thay thế đánh giá nghe. Chưa có kết quả A/B đủ để khẳng định mức cải thiện so với bản người dùng đánh giá 60–70%.

Tiếp theo: thu thư viện 5–10 phút cùng người nói/mic, chọn mẫu trung tính và cảm xúc riêng. Thử 15–20 câu chưa có trong mẫu và chấm độ giống, phát âm, tự nhiên, cảm xúc. Thử Fish/clone chuyên nghiệp cần tài khoản TTS phù hợp; chưa tích hợp hoặc gửi mẫu sang cloud trong đợt này. Đoạn thu ngắn hiện tại không đủ để thực hiện lộ trình huấn luyện riêng.
