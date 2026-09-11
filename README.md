# Tếu Voice Studio

Ứng dụng text-to-speech tiếng Việt có `@tag` cảm xúc, clone màu giọng từ WAV và chạy hoàn toàn trên máy cá nhân.

![Local](https://img.shields.io/badge/runtime-local-171a22?style=flat-square) ![Vietnamese](https://img.shields.io/badge/language-Vietnamese-d8ff58?style=flat-square&labelColor=171a22) ![Engine](https://img.shields.io/badge/engine-VieNeu_v3_Turbo-ff795f?style=flat-square&labelColor=171a22)

## Chạy dự án

Yêu cầu: Windows 10/11, kết nối mạng cho lần cài đầu, và khoảng 2 GB dung lượng trống (nên chừa 2,5 GB). Không cần GPU NVIDIA.

```powershell
.\setup.ps1
.\run.ps1
```

Sau đó mở [http://127.0.0.1:8765](http://127.0.0.1:8765).

Lần tạo giọng đầu tiên sẽ tải model về `.cache/`. Các lần sau chạy offline. File mẫu riêng nằm ở `data/voice_reference.wav`; file sinh ra nằm trong `outputs/`. Cả hai đều bị Git bỏ qua mặc định.

## Dùng qua Internet (ngrok)

Cách này cho phép truy cập từ bất kỳ đâu, không cần cùng WiFi.

**Yêu cầu một lần:** Đăng ký tài khoản miễn phí tại [ngrok.com](https://ngrok.com), lấy authtoken tại [dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken).

Lần đầu — lưu token:
```powershell
.\run-ngrok.ps1 -NgrokAuthToken "YOUR_TOKEN_HERE"
```

Từ lần sau (token đã được lưu):
```powershell
.\run-ngrok.ps1
```

Terminal sẽ in URL dạng:
```
https://xxxx-xx-xx-xxx.ngrok-free.app/?access_key=...
```

Gửi URL đó cho bất kỳ ai — họ có thể mở trên điện thoại, máy khác mạng, v.v. URL thay đổi mỗi lần khởi động (tài khoản Free). Nếu muốn URL cố định, nâng cấp lên gói ngrok có tên miền tĩnh.

> **Bảo mật:** URL ngrok kèm `access_key` đã đủ bảo vệ nội dung audio và API. Không đưa URL này lên mạng xã hội hay chat công khai. Nhấn `Ctrl+C` để đóng tunnel ngay khi dùng xong.

**Cài ngrok (nếu chưa có):**
```powershell
winget install ngrok.ngrok
```

## Dùng trong mạng nội bộ

Trên máy này, chạy:

```powershell
.\run.ps1 -LanAddress 172.28.0.166
```

Terminal sẽ in một URL dạng `http://172.28.0.166:8765/?access_key=...`. Mở hoặc gửi **nguyên URL đó** cho thiết bị cùng mạng nội bộ. Khóa được tạo ngẫu nhiên mỗi lần chạy; không đưa URL này lên Internet hay chat công khai. Nếu Windows hỏi tường lửa, chỉ cho phép **Private networks**, không chọn Public networks.

Server chỉ cho phép loopback hoặc một IPv4 private cụ thể, không bind `0.0.0.0` và không chấp nhận IP public. API, mẫu giọng và WAV sinh ra đều cần khóa; CSS/JavaScript tĩnh không chứa audio riêng. Khi truy cập bằng IP LAN qua HTTP, tính năng **Thu mic** của trình duyệt có thể bị chặn vì browser yêu cầu HTTPS; hãy thu mic tại `localhost` hoặc dùng tải WAV trên thiết bị nội bộ.

## Dùng nhanh

1. Nhập nội dung tiếng Việt và gõ `@` ở nơi muốn đổi cách diễn.
2. Gõ tiếp tên cảm xúc, dùng `↑`/`↓` để chọn rồi nhấn `Enter` hoặc `Tab`. Ví dụ `@hài hước` được chuẩn hóa thành `@hài_hước`.
3. Chỉnh **Tốc độ toàn bài** từ 0,75× đến 1,35×.
4. Giữ **Thử phong cách từ mẫu khác** ở trạng thái tắt để ưu tiên đúng giọng bạn. Chỉ bật để so sánh; mẫu khác có thể làm thay đổi màu giọng.
5. Chọn **Thu mic** để tạo WAV sạch trực tiếp trên trình duyệt, hoặc tải WAV 3–8 giây khác. Đọc liên tục 6–8 giây bằng đúng mic/khoảng cách bạn thường dùng; công cụ sẽ chặn mẫu bị clipping.
6. Nhấn **Xem chỉ đạo**, xác nhận quyền sử dụng giọng rồi tạo WAV.

Thư viện hiện có 45 tag, tìm được bằng tiếng Việt có dấu, không dấu và alias tiếng Anh. Tag điều khiển đoạn ngay sau nó, kết thúc khi gặp tag khác hoặc dòng trống. Parser không đổi hay bịa từ được nói.

Mức hỗ trợ được hiển thị ngay trong thư viện:

- **Gốc:** `@cười`, `@thở_dài`, `@hắng_giọng` dùng cue thử nghiệm mà VieNeu hỗ trợ.
- **Cue + biên tập:** các biến thể như `@cười_khẽ`, `@cười_lớn` dùng cue gần nhất; đây không phải cue native riêng.
- **Biên tập:** các tag khoảng nghỉ tạo silence có thời lượng xác định.
- **Mô phỏng:** cảm xúc semantic như `@hài_hước`, `@tỉnh_bơ`, `@bất_ngờ` dùng ngữ cảnh, nhịp và dấu câu. Đây không phải emotion token native của model.

Cú pháp dấu ngoặc vuông chỉ tồn tại bên trong adapter cho ba cue gốc và không xuất hiện trong giao diện hay API công khai.

## Vì sao dùng VieNeu‑TTS

- Bản v3 Turbo hỗ trợ native Windows, CPU/ONNX và không cần PyTorch.
- Clone tức thì từ 3–8 giây audio, đúng với mẫu 6,34 giây của dự án.
- Hỗ trợ tiếng Việt/Anh, đầu ra 48 kHz và cue phi ngôn ngữ.
- Code/model Apache‑2.0; dữ liệu giọng không phải gửi tới API bên ngoài.
- Model phục vụ clone chiếm khoảng 637 MB ở FP32; package Python chỉ khoảng 1,2 MB. Tổng môi trường + cache trên máy thử nghiệm khoảng 1,9 GB.

Xem phân tích và các lựa chọn khác tại [docs/RESEARCH.md](docs/RESEARCH.md).

## Chế độ chất lượng và hiệu năng

Mặc định là `fp32` để ưu tiên chất lượng. CPU Intel i5‑12600K của máy này có AVX2 VNNI, nên có thể thử `int8` để nhẹ và nhanh hơn:

```powershell
$env:TEU_VOICE_PRECISION = "int8"
.\run.ps1
```

Nếu output INT8 bị rè hoặc méo, quay lại `fp32`. Model INT8 và FP32 được cache riêng.

## Mẫu giọng tốt hơn

Mẫu hiện tại sạch và dùng tốt cho demo, nhưng chỉ có khoảng 5,1 giây tiếng nói thực. Để giữ giọng ổn định hơn, nên thu thêm:

- 30–60 giây giọng sạch làm thư viện nguồn, rồi cắt các đoạn tốt nhất dài 3–8 giây đúng cửa sổ của VieNeu.
- Ba mẫu 3–8 giây riêng: trung tính, vui/dí dỏm, và deadpan/châm biếm.
- Cùng micro/phòng; không nhạc, reverb hoặc người thứ hai.
- Giữ master WAV mono 48 kHz/16-bit, peak khoảng −3 đến −1,5 dBFS.

VieNeu học phong cách chủ yếu từ reference. Một clip vui đúng nhịp thường tạo khác biệt lớn hơn DSP hậu kỳ.

Không model clone tức thì nào bảo đảm “giống 100%”: mic, khoảng cách, nén âm thanh, nội dung câu đọc và giới hạn 3–8 giây đều ảnh hưởng. Bản phát hành này ưu tiên màu của **mẫu mic vừa thu** thay vì mặc định giữ mẫu demo cũ; hãy so sánh một câu ngắn ở cùng tốc độ trước khi tạo bài dài.

### Chuyển phong cách thử nghiệm

Nếu có `data/style_references/excited.wav` và `funny.wav`, ứng dụng cho phép bật/tắt A/B ngay dưới phần chọn giọng. Engine dùng embedding của người nói từ mẫu clone nhưng lấy reference codes biểu cảm từ clip phong cách tương ứng. Cách này cải thiện nhịp và độ biến thiên trên máy hiện tại mà không gửi audio ra ngoài, nhưng mới chỉ có hai nhóm rộng và không biến 45 tag thành 45 emotion token native.

## Kiến trúc

- FastAPI phục vụ UI và API nội bộ tại `127.0.0.1`.
- Bộ biên dịch emotion parse alias `@tag`, chuẩn hóa token và giữ phạm vi chỉ đạo rõ ràng.
- `VieneuEngine` gom tag liền nhau vào cùng nhóm gọi model, chỉ tách ở `@ngắt_*`, loại bỏ silence số thừa ở mép và master toàn bài gần −16 LUFS với peak an toàn. VieNeu vẫn có thể tự chia nội bộ khi văn bản dài.
- Khi bật chuyển phong cách, mỗi nhóm chọn reference `excited` hoặc `funny` theo chỉ đạo trội; có thể tắt để nghe đúng A/B với cùng giọng và kịch bản.
- `JobManager` chạy tác vụ nền với hàng đợi giới hạn; output chỉ được công khai sau khi WAV hoàn tất và hợp lệ.
- Upload tạm được xóa sau khi sinh giọng; output và voice reference không được commit.
- Server chỉ bind loopback và chặn request khác nguồn trên API/audio/reference để bảo vệ dữ liệu giọng local.

API tương tác có tại [http://127.0.0.1:8765/api/docs](http://127.0.0.1:8765/api/docs) khi server đang chạy.

## Kiểm thử

```powershell
.\.tools\uv\bin\uv.exe run pytest
```

Test dùng fake engine, không tải model và không tạo voice thật. Bộ test bao phủ parser tag, alias, phạm vi từng đoạn, bảo mật token nội bộ, tốc độ, DSP, API và hàng đợi.

## Giới hạn chất lượng cần biết

DeepSeek và các model chat tương tự chỉ xử lý **văn bản**: chúng có thể gợi ý tag hoặc sửa kịch bản, nhưng không tạo prosody hay waveform. Muốn các tag như `@bất_ngờ`, `@thì_thầm`, `@hài_hước` được diễn thật thay vì mô phỏng, cần một backend audio-native như Fish Audio S2.1 Pro, ElevenLabs v3 hoặc Higgs TTS 3, hoặc cần nhiều reference cảm xúc của cùng người nói. Không ghi API key trực tiếp vào source hay commit lên Git.

Smoke test bằng model thật (lần đầu sẽ tải weights):

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_synthesize.py
```

## Quyền sử dụng giọng

Chỉ clone giọng của chính bạn hoặc giọng đã có sự đồng ý rõ ràng. Tệp đính kèm không tự chứng minh quyền sử dụng; ứng dụng vì vậy bắt buộc xác nhận consent trước mỗi lượt clone.
