# Chấm công khuôn mặt — prototype YuNet / SFace

Tích hợp trên React/TypeScript + FastAPI + SQLite hiện có. Không dùng repo InsightFace cho luồng này.

## Cài đặt và chạy

Workspace đã được chuẩn bị dependencies, model và database demo: từ thư mục `AIbuildathon`, chạy `powershell -ExecutionPolicy Bypass -File .\run-demo.ps1`, rồi mở `http://localhost:5173/face-attendance`. Giữ terminal chạy; Ctrl+C kết thúc demo. Script dùng Python virtualenv và Node portable trong workspace, hoặc Node trên PATH. Các bước dưới đây dành cho cài lại trên máy khác.

Trong `backend`, dùng Python 3.11–3.12:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python scripts/setup_faces.py
# Chỉ seed nếu chưa có nhân viên; không dùng --reset trên dữ liệu đang sử dụng.
.venv/Scripts/python -m app.db.seed
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Trong `frontend`: `npm install`, rồi `npm run dev`. Đăng nhập HR bằng tài khoản demo có sẵn (`hr@company.vn`, mật khẩu seed mặc định `Demo@123`, trừ khi đã thay đổi). Mở **Máy chấm công khuôn mặt** (`/face-attendance`).

Script setup tải hai model ONNX chính thức từ OpenCV Zoo, in SHA256 và tạo khóa Fernet trong `backend/.env` nếu chưa có. Không tự thay khóa cũ. Bảo vệ và sao lưu khóa riêng khỏi database; mất khóa không giải mã được embedding. Không commit `.env` hoặc model. Cấu hình qua `FACE_YUNET_MODEL`, `FACE_SFACE_MODEL`, `FACE_ENCRYPTION_KEY` nếu cần đường dẫn hoặc kho bí mật riêng.

Máy điện thoại truy cập qua LAN cần HTTPS, cấu hình CORS/proxy đúng; HTTP localhost chỉ dùng trên chính thiết bị chạy trình duyệt. Không có offline.

## Luồng demo

1. HR mở đăng ký, chọn nhân viên đang hoạt động, trình bày nội dung đồng ý và chỉ xác nhận khi nhân viên trực tiếp đồng ý.
2. Bật camera, chụp 3–6 ảnh riêng biệt với góc hơi khác nhau. Không dùng ảnh trùng. Backend từ chối thiếu/nhiều mặt, mặt quá nhỏ, ảnh mờ hoặc ánh sáng không phù hợp; kiểm tra các ảnh thuộc cùng người và trùng hồ sơ khác.
3. Lưu embedding chuẩn hóa được mã hóa xác thực Fernet, model version, nội dung/thời điểm đồng ý và người đăng ký vào `face_profiles`. Không lưu ảnh gốc. Ảnh tạm trong trình duyệt được xóa khi hoàn tất, đổi nhân viên/chế độ hoặc chụp lại.
4. Trong tab chấm công, nhân viên chọn Check-in/Check-out, chủ động quét. HR đăng nhập vận hành kiosk; API không mở tìm danh tính cho tài khoản nhân viên hoặc khách.
5. Tìm trong các hồ sơ đã đồng ý còn hoạt động; cosine tối thiểu `FACE_MATCH_THRESHOLD=0.45`, khoảng cách với ứng viên thứ hai tối thiểu `FACE_MATCH_MARGIN=0.08`. Đây là ngưỡng khởi đầu, không phải xác suất chính xác hoặc ngưỡng đã nghiệm thu; cần hiệu chỉnh với nhóm thử nghiệm.
6. Ghi giờ máy chủ theo Asia/Ho_Chi_Minh, `attendance.source=face`. Chặn lượt thành công cách nhau dưới 30 giây trên mọi thiết bị, không cho ra khi chưa vào hoặc ghi đè giờ cũ. Bảo vệ đơn nghỉ đã duyệt và bản ghi on_leave. Ghi log lượt quét hợp lệ đến endpoint (không chứa ảnh/embedding); lỗi xác thực/validation và thiếu model bị chặn trước endpoint không tạo scan log.
7. Cuối tuần/ngày lễ vẫn ghi `present` để các view tính giờ; tạo bất thường R7. Audit lưu trước/sau bản ghi attendance. Lịch và báo cáo dùng chung dữ liệu; tải lại các trang để xem cập nhật. Chạy bộ quét bất thường hiện có để làm mới các quy tắc R1–R8 khác.
8. HR chọn hồ sơ đã đăng ký để thu hồi/xóa. Đăng ký lại cần xóa hồ sơ cũ và có đồng ý mới. Xóa chỉ tác động dữ liệu hoạt động; bản sao lưu cần quy trình hết hạn riêng.

## Giới hạn và kiểm thử

**Chưa có liveness/chống ảnh giả.** YuNet/SFace chỉ phát hiện và nhận diện; không tuyên bố chống ảnh in, ảnh điện thoại hoặc video. Chỉ dùng prototype thử nghiệm có giám sát. Chưa có luồng yêu cầu bổ sung công mới hoặc trang sửa công mới trong thay đổi này.

P95 2 giây chưa được xác nhận. Kiểm thử thực tế cần webcam, người đồng ý và thiết bị kiosk đích. Chạy `python -m pytest tests/test_faces.py` và `npm run build`; test API thay engine bằng vector xác định để kiểm tra nghiệp vụ, không chứng minh chất lượng nhận diện.

Nguồn kỹ thuật: [OpenCV FaceDetectorYN / FaceRecognizerSF](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html), [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet), [SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface). Xem license từng model tại nguồn.
