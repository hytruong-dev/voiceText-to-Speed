# Kế hoạch nâng cấp giọng cá nhân và cách diễn đạt vlog

Ngày lập: 14/09/2026. Cơ sở: mã nguồn nhánh `dev` được kiểm tra trong phiên tư vấn.

Trạng thái: **đề xuất triển khai**, chưa phải danh sách tính năng đã hoàn thành. Tài liệu này không thay đổi chức năng tạo giọng.

## 1. Mục tiêu

Tạo tiếng Việt từ văn bản bằng giọng của người dùng, đồng thời có nhịp nói, nhấn nhá và cách diễn đạt gần với việc người dùng trò chuyện trước camera.

Cần đánh giá riêng ba khía cạnh:

- **Đúng người:** âm sắc, giọng vùng miền và cách phát âm có giống chủ giọng không?
- **Tự nhiên:** có liền mạch, tránh đều đều hoặc ngắt bất thường không?
- **Diễn đạt phù hợp:** điểm nhấn, câu hỏi, mở đầu, câu đùa và cảm xúc có đúng ngữ cảnh không?

Không cam kết giống 100%. Điểm tương đồng embedding không được hiển thị như phần trăm giống người thật. Chất lượng cuối cùng phải được chủ giọng nghe và xác nhận.

## 2. Những gì đã thấy trong code

Các nhận định dưới đây dựa trên code, chưa phải kết luận từ việc nghe bản xuất mới nhất.

- `src/teu_voice/engine.py`: bộ tạo giọng hiện tại là VieNeu qua ONNX. Khi clone, code đặt pitch và gain bằng 0, không áp dụng tốc độ theo tag và giới hạn tốc độ chung trong khoảng 0.97–1.03. Đây là lựa chọn bảo vệ danh tính giọng, nhưng hạn chế tác dụng của các tag mô phỏng.
- `src/teu_voice/emotions.py`: nhiều sắc thái được chuyển thành dấu câu và tham số, không phải token cảm xúc riêng của mô hình. Các biến thể cười cùng dùng cue gần nhất, không phải các kiểu diễn xuất độc lập.
- `src/teu_voice/engine.py`: chế độ serverless chia nhóm thành đoạn tối đa khoảng 100 ký tự và thêm khoảng nghỉ giữa các phần. Điều này có nguy cơ làm đứt mạch diễn đạt; cần so sánh thực nghiệm với chạy local.
- `src/teu_voice/engine.py`: hàm chỉnh tốc độ dùng resampling, nên tốc độ và cao độ thay đổi cùng nhau. Không nên coi đây là xử lý giữ nguyên cao độ.
- `src/teu_voice/static/app.js`: khi gửi tác vụ clone, giao diện hiện gửi tốc độ bằng 1. Vì vậy, thay đổi cao độ do tốc độ chưa phải nghi phạm chính của luồng clone mặc định.
- Chuyển phong cách hiện có thể thay reference codes nhưng giữ speaker embedding. Không thể mặc định cách ghép này giữ nguyên danh tính giọng; phải kiểm chứng, đặc biệt khi mẫu phong cách thuộc người khác.

## 3. Hướng giải quyết được chọn

Giữ VieNeu làm phương án hiện có. Thêm chế độ chất lượng cao để thử nghiệm độc lập, bắt đầu với OmniVoice. Chỉ chuyển mặc định nếu thử nghiệm trên giọng người dùng cho kết quả tốt hơn.

Ưu tiên theo thứ tự: mẫu đúng cách diễn đạt → đối chiếu mô hình → giữ mạch câu → điều khiển cảm xúc → tối ưu tốc độ chạy.

Không dùng chỉnh pitch, tăng âm lượng hoặc thêm hàng loạt tag để thay thế khả năng diễn đạt của mô hình. Không bắt đầu bằng fine-tuning khi chưa đo được giới hạn của giải pháp dùng mẫu tham chiếu.

## 4. Các giai đoạn thực hiện

### Giai đoạn 0 — Lập bản chuẩn để so sánh

1. Ghi lại commit, phiên bản thư viện, cấu hình, môi trường local/serverless và phần cứng thực tế.
2. Chọn một mẫu tham chiếu cố định và bộ kịch bản kiểm thử chưa có trong mẫu thu.
3. Xuất bản chuẩn với VieNeu: tốc độ 1, không chuyển phong cách, không xử lý làm đổi âm sắc.
4. Lưu audio và metadata: engine, model revision, mã mẫu, tham số, seed nếu hỗ trợ, thời gian tạo và sample rate thực tế.
5. So sánh cùng nội dung giữa local và serverless để xác định ảnh hưởng của chia đoạn.

Kết quả: có bản chuẩn có thể tái tạo, không đánh giá chỉ bằng trí nhớ nghe.

### Giai đoạn 1 — Hồ sơ giọng có nhiều cách diễn đạt

Chuẩn bị vài bản thu bằng chính giọng người dùng: trò chuyện bình thường, mở đầu hào hứng, kể chuyện dí dỏm và tâm sự nhẹ nhàng. Có thể thu mỗi bản dài vài chục giây để chọn đoạn tốt; độ dài đưa vào mô hình tuân theo yêu cầu từng engine.

- Giữ cùng mic, khoảng cách và phòng; tránh nhạc, vang phòng, clipping và xử lý khử ồn mạnh.
- Lưu bản gốc riêng, không ghi đè khi tiền xử lý.
- Chọn đoạn trọn ý, không cắt mất phụ âm đầu/cuối; lưu bản chép lời chính xác.
- Gắn nhãn phong cách và nguồn mẫu. Chỉ dùng mẫu thuộc người dùng hoặc đã được cho phép.
- Với OmniVoice, bắt đầu bằng đoạn tham chiếu 3–10 giây theo tài liệu chính thức; không nối mọi bản thu thành một mẫu dài.
- Lưu nhiều mẫu là thư viện tham chiếu, **không có nghĩa đã huấn luyện mô hình riêng**.

Mở rộng hồ sơ hiện tại trong `data/profiles/` theo hướng tương thích ngược. Mỗi mẫu có ID, đường dẫn, transcript, nhãn phong cách và thông tin kiểm tra audio. Chưa chốt schema trước khi kiểm tra code quản lý hồ sơ tại thời điểm triển khai.

### Giai đoạn 2 — Tích hợp OmniVoice theo cơ chế tùy chọn

1. Tạo môi trường cài đặt riêng để tránh xung đột PyTorch và bộ phụ thuộc VieNeu hiện tại.
2. Kiểm tra tải mô hình, bộ nhớ và thời gian tạo một câu ngắn trên phần cứng thực tế. Không suy tốc độ CPU từ benchmark GPU của nhà phát triển.
3. Viết adapter OmniVoice sau giao diện `SpeechEngine`; giữ VieNeu hoạt động khi OmniVoice chưa được cài hoặc không khả dụng.
4. Truyền audio tham chiếu và transcript; cache clone prompt với khóa gồm mã mẫu, revision mô hình và cấu hình liên quan. Đổi mẫu phải vô hiệu cache cũ.
5. Bổ sung lựa chọn engine cho API, hàng đợi và giao diện; lỗi model phải hiển thị rõ, không âm thầm đổi engine.
6. Trả metadata sample rate thực tế. OmniVoice xuất 24 kHz theo tài liệu; loại bỏ giả định mọi kết quả đều 48 kHz ở nơi hiển thị và ghép audio. Tăng sample rate không tự tăng chất lượng.
7. Dùng điều chỉnh tốc độ native khi engine hỗ trợ; không áp dụng thêm một lượt chỉnh tốc độ ngoài ý muốn.

Các tên file mới, route và kiểu dữ liệu sẽ được chốt sau kiểm tra luồng hiện hành; mục tiêu là thay đổi nhỏ, có test, không viết lại toàn bộ ứng dụng.

### Giai đoạn 3 — Chỉ đạo cách nói và xử lý tag

Giữ trải nghiệm nhập `@` hiện tại. Bổ sung bảng khả năng theo engine để phân biệt:

- Hỗ trợ native: chuyển sang đúng cue mô hình có tài liệu hỗ trợ.
- Hỗ trợ qua mẫu: chọn mẫu phong cách của chính người dùng để thử nghiệm.
- Chỉ mô phỏng hoặc chưa hỗ trợ: thông báo rõ, không hứa mức biểu cảm không có.

Không ánh xạ tất cả tag tiếng Việt sang một lệnh tùy ý rồi mặc định mô hình hiểu. Không đổi mẫu ở từng từ; chọn theo đoạn có ý nghĩa và kiểm tra hiện tượng đổi giọng giữa đoạn.

Thêm bước **biên tập lời thoại tùy chọn**: chuyển văn viết thành văn nói, đề xuất điểm nhấn và khoảng nghỉ. Luôn giữ nguyên ý, số liệu, tên riêng và trải nghiệm thực tế; không tự bịa chuyện cá nhân. Người dùng được xem và chấp nhận bản sửa trước khi tạo audio. Giữ bản gốc để hoàn tác.

Mô hình ngôn ngữ chỉ giúp biên tập lời thoại; không thay thế mô hình tạo âm thanh. Không nhúng API key vào frontend hoặc tài liệu, không ghi khóa vào log.

### Giai đoạn 4 — Giữ mạch câu và tách tác vụ nặng

- Chia theo câu hoặc cụm ý trong giới hạn engine, tránh cắt cứng theo ký tự khi không cần thiết.
- Giữ ngữ cảnh đủ dài nhưng vẫn đo RAM, thời gian và độ ổn định; không bỏ mọi giới hạn độ dài.
- Phân biệt khoảng nghỉ do người dùng yêu cầu với khoảng nghỉ do ghép đoạn. Không cộng hai lần.
- Giữ hơi thở và phần nói nhỏ; chỉ cắt padding khi đã xác định an toàn.
- Chỉ cân bằng âm lượng nhẹ sau ghép, tránh nén mạnh làm mất tương phản cảm xúc.

Nếu giới hạn serverless làm giảm chất lượng hoặc không đủ bộ nhớ cho engine mới, giữ web/API hiện tại nhưng chuyển tổng hợp sang worker local hoặc máy GPU riêng. Worker cần xác thực, hàng đợi giới hạn, timeout, dọn file tạm và trạng thái lỗi rõ ràng. Không mở worker công khai không xác thực.

Không thuê GPU, phát sinh phí hoặc gửi bản thu lên bên thứ ba nếu chưa được người dùng đồng ý.

### Giai đoạn 5 — Đánh giá rồi mới chọn mặc định

Dùng tối thiểu năm dạng nội dung: trò chuyện, mở đầu vlog, kể chuyện hài, câu hỏi và đoạn dài. Có thêm tên riêng, số và từ khó trong tiếng Việt. Với cấu hình có ngẫu nhiên, tạo nhiều lần để tránh chọn một kết quả may mắn.

Thử lần lượt từng yếu tố, không đổi tất cả cùng lúc:

1. VieNeu hiện tại làm bản chuẩn.
2. VieNeu với mẫu diễn đạt phù hợp.
3. OmniVoice dùng cùng mẫu và văn bản.
4. Cấu hình tốt hơn kết hợp biên tập lời thoại đã được duyệt.

Ẩn tên engine khi nghe A/B, cân bằng mức nghe, để chủ giọng chấm riêng độ giống, tự nhiên và diễn đạt trên thang 1–5. Ghi thêm lỗi mất/lặp từ, sai phát âm, đổi giọng và khoảng ngắt bất thường. Đo thời gian tạo, RAM/VRAM và tỷ lệ tác vụ thất bại.

Tiêu chí chọn mặc định đề xuất:

- Chủ giọng ưu tiên phương án mới ở ít nhất 4/5 dạng nội dung.
- Độ giống giọng không giảm theo đánh giá của chủ giọng.
- Không xuất hiện lỗi mất/lặp từ hoặc đổi giọng nghiêm trọng trong bộ kiểm thử.
- Thời gian chờ và tài nguyên nằm trong mức người dùng chấp nhận, chốt sau benchmark phần cứng.

Nếu không đạt, giữ engine hiện tại và lưu kết quả thử nghiệm; không tuyên bố cải thiện chỉ vì điểm embedding tăng.

## 5. Kiểm thử kỹ thuật và khả năng quay lại

- Unit test: ánh xạ tag theo engine, vô hiệu cache khi đổi mẫu, metadata sample rate, tốc độ không bị xử lý hai lần, chia đoạn và khoảng nghỉ.
- Integration test bằng engine giả: tạo job, chọn engine, báo engine thiếu phụ thuộc, tải audio và xử lý lỗi worker.
- Smoke test với mô hình thật: câu ngắn, đoạn dài và mẫu cá nhân; kiểm tra WAV đọc được, sample rate, clipping, thời gian tạo và nghe thực tế.
- Chạy lại bộ test hiện có, kiểm tra giao diện upload/mic, autocomplete `@`, tiến độ và phát audio.
- Không ghi đè hồ sơ hay bản thu gốc. Mọi engine mới là tùy chọn; cấu hình cũ tiếp tục chạy được.
- Triển khai từng giai đoạn bằng thay đổi nhỏ. Nếu có hồi quy, tắt lựa chọn engine mới thay vì xóa dữ liệu người dùng.

## 6. Nếu vẫn chưa đạt

Chỉ sau A/B mới cân nhắc fine-tuning với tập bản thu có transcript và quyền sử dụng rõ ràng, hoặc engine khác có điều khiển diễn đạt phù hợp. Chưa đưa ra số phút dữ liệu hay chi phí cố định khi chưa chọn quy trình huấn luyện.

Nếu mục tiêu là tái hiện chính xác một màn diễn cụ thể, có thể thử luồng thu lời thoại hướng dẫn hoặc speech-to-speech. Đây là hướng khác với text-to-speech hoàn toàn tự động, cần kiểm tra khả năng bảo toàn giọng và được người dùng chọn riêng.

## 7. Tài liệu tham khảo

- [OmniVoice — cài đặt, clone prompt, tốc độ và cue](https://github.com/k2-fsa/OmniVoice)
- [OmniVoice — ngôn ngữ hỗ trợ](https://github.com/k2-fsa/OmniVoice/blob/master/docs/languages.md)
- [OmniVoice — lưu ý về mẫu và chỉ dẫn phong cách](https://github.com/k2-fsa/OmniVoice/blob/master/docs/tips.md)

Các API và yêu cầu thư viện phải được kiểm tra lại, ghim phiên bản khi triển khai. Tài liệu nhà phát triển không thay thế thử nghiệm trên tiếng Việt và giọng người dùng.
