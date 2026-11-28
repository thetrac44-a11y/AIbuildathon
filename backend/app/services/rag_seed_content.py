from __future__ import annotations

from typing import Dict, Tuple

# Real, structured Vietnamese HR policy corpus matching actual business rules in
# backend/app/core/config.py, operations.py, anomaly_service.py, and permissions.py.
# Keyed by company_documents.storage_path for idempotent placeholder upgrades (never overwrites user-uploaded docs).
BASELINE_RAG_POLICY_CONTENT: Dict[str, Tuple[str, str]] = {
    "policies/noi_quy_lao_dong_2026.md": (
        "2026-01-01",
        """# Nội quy lao động Công ty 2026 (Phiên bản v2.0)

## Điều 1. Thời giờ làm việc tiêu chuẩn
Giờ làm việc hành chính tiêu chuẩn của công ty áp dụng từ Thứ Hai đến Thứ Sáu hằng tuần:
- Giờ bắt đầu ca làm việc: 08:30 sáng.
- Giờ kết thúc ca làm việc: 17:30 chiều.
- Thời gian nghỉ trưa: 01 giờ (từ 12:00 đến 13:00), không tính vào giờ công thực tế.
- Tổng số giờ công tiêu chuẩn mỗi ngày làm việc đầy đủ là 8,0 giờ công.
- Thứ Bảy và Chủ Nhật là ngày nghỉ hàng tuần theo quy định.

## Điều 2. Ngày nghỉ lễ, Tết hưởng nguyên lương
Nhân viên được nghỉ làm việc và hưởng nguyên lương vào các ngày lễ, Tết theo quy định của pháp luật và lịch nghỉ công ty công bố hằng năm, bao gồm: Tết Dương lịch (01/01), Ngày Giải phóng miền Nam (30/04), Ngày Quốc tế Lao động (01/05), Ngày Quốc khánh (02/09) và các ngày nghỉ bù theo thông báo của bộ phận Nhân sự.

## Điều 3. Quy định làm thêm giờ (Overtime - OT) và làm việc cuối tuần
Nhân viên làm thêm giờ vào buổi tối, Thứ Bảy, Chủ Nhật hoặc ngày lễ phải lập đơn đề nghị làm thêm giờ (overtime_requests) và được Trưởng phòng trực tiếp hoặc bộ phận Nhân sự phê duyệt trước khi thực hiện.
Trường hợp chấm công vào cuối tuần hoặc ngày lễ nhưng chưa có đơn tăng ca được phê duyệt sẽ được hệ thống ghi nhận dấu hiệu R7 để đối chiếu xác minh, không tự động tính phụ cấp tăng ca khi chưa có xác nhận hợp lệ.

## Điều 4. Bảo mật tài khoản và hướng dẫn đổi mật khẩu
Mỗi nhân viên được cấp một tài khoản đăng nhập cá nhân gắn với mã nhân viên và vai trò RBAC tương ứng. Nhân viên chịu trách nhiệm bảo mật thông tin đăng nhập, không chia sẻ mật khẩu cho người khác.
Để tự đổi mật khẩu tài khoản của mình, nhân viên truy cập màn hình Hồ sơ cá nhân (/profile), chọn chức năng Đổi mật khẩu, nhập mật khẩu hiện tại và mật khẩu mới (tối thiểu 6 ký tự).
Trường hợp quên mật khẩu hoặc tài khoản bị khóa, nhân viên liên hệ bộ phận Nhân sự (đối với tài khoản nghiệp vụ) hoặc Quản trị hệ thống Admin để hỗ trợ đặt lại mật khẩu.

## Điều 5. Nguyên tắc kỷ luật và xác minh trung tính
Mọi dấu hiệu bất thường về chấm công hoặc nghỉ phép do hệ thống phát hiện chỉ mang tính chất cảnh báo kỹ thuật hỗ trợ kiểm tra, tuyệt đối không phải là kết luận kỷ luật hay cáo buộc vi phạm. Trưởng phòng và bộ phận Nhân sự có trách nhiệm trao đổi xác minh thực tế với nhân viên trước khi đưa ra quyết định xử lý.
""",
    ),
    "policies/quy_che_cham_cong_nghi_phep.md": (
        "2026-01-01",
        """# Quy chế chấm công, đi muộn và nghỉ phép (Phiên bản v1.4)

## Điều 1. Quy định chấm công hằng ngày và thời gian ân hạn đi muộn
Tất cả nhân viên thực hiện chấm công vào ca và ra ca đầy đủ qua thiết bị máy chấm công hoặc Face Kiosk nhận diện khuôn mặt.
- Giờ bắt đầu làm việc chuẩn là 08:30:00.
- Thời gian ân hạn đi muộn (grace period) là 5 phút (đến hết 08:35:00).
- Nhân viên có giờ vào sau 08:35:00 (tức trễ trên 5 phút so với 08:30:00) được hệ thống ghi nhận là đi muộn (is_late = 1) và tính số phút đi muộn từ mốc 08:30:00.
- Khi làm việc từ 5 giờ trở lên trong ngày, hệ thống tự động khấu trừ 1,0 giờ nghỉ trưa để tính giờ công thực tế.

## Điều 2. Xử lý thiếu chấm công và điều chỉnh công
Nhân viên quên chấm công vào hoặc chấm công ra (thiếu check-in hoặc check-out) cần báo lại Trưởng phòng và gửi yêu cầu đối chiếu bổ sung cho bộ phận Nhân sự (HR) trước ngày chốt công cuối tháng.
Chỉ bộ phận Nhân sự (HR) mới có thẩm quyền điều chỉnh bản ghi chấm công trên hệ thống, bắt buộc ghi rõ lý do điều chỉnh và lưu đầy đủ nhật ký kiểm toán (activity_logs). Nhân sự không được phép tự điều chỉnh dữ liệu chấm công của chính mình.

## Điều 3. Quỹ phép năm và cách tính số ngày nghỉ phép
Mỗi nhân viên chính thức làm việc đủ năm được cấp quỹ phép năm tiêu chuẩn là 12 ngày/năm (có thể điều chỉnh theo thâm niên hoặc thỏa thuận hợp đồng lao động).
Cách tính số ngày nghỉ của mỗi đơn nghỉ phép trên hệ thống được tính theo số ngày lịch bao gồm cả ngày bắt đầu và ngày kết thúc (calendar days inclusive: to_date - from_date + 1).
Quỹ phép năm chỉ bị khấu trừ thực tế sau khi đơn nghỉ phép năm (annual) được phê duyệt (status = approved); đơn ở trạng thái chờ duyệt (pending) chưa trừ vào số ngày đã sử dụng nhưng sẽ được kiểm tra tránh trùng khoảng ngày.

## Điều 4. Quy trình tạo đơn, hủy đơn và phân cấp phê duyệt nghỉ phép
1. Tạo đơn nghỉ phép: Nhân viên tạo đơn tại màn hình Đơn nghỉ phép (/leaves), chọn đúng loại nghỉ (Phép năm - annual, Nghỉ ốm - sick, Việc riêng - personal, Không lương - unpaid), nhập thời gian và lý do rõ ràng. Đối với nghỉ ốm từ 02 ngày trở lên cần bổ sung giấy xác nhận của cơ sở y tế khi HR yêu cầu.
2. Hủy đơn nghỉ phép: Nhân viên chỉ được tự hủy đơn nghỉ phép của chính mình khi đơn vẫn đang ở trạng thái chờ duyệt (pending). Đơn đã được duyệt hoặc đã bị từ chối không thể tự hủy.
3. Phân cấp phê duyệt:
   - Trưởng phòng (Manager): Phê duyệt hoặc từ chối đơn của nhân viên thuộc phòng ban mình quản lý; không được tự duyệt đơn của chính mình và không duyệt đơn của cấp quản lý khác.
   - Bộ phận Nhân sự (HR): Phê duyệt đơn toàn công ty, đơn của cấp Trưởng phòng và xử lý các trường hợp ngoại lệ.
   - Ban Điều hành (Executive): Phê duyệt các đơn nghỉ phép đặc biệt được đánh dấu yêu cầu phê duyệt cấp cao (requires_executive_approval = true).
4. Khi từ chối đơn nghỉ phép, người duyệt bắt buộc phải ghi rõ lý do từ chối.
""",
    ),
    "policies/cam_nang_canh_bao_r1_r8.md": (
        "2026-01-01",
        """# Cẩm nang định nghĩa và quy trình xử lý cảnh báo R1-R8 (Phiên bản v1.1)

## Mục 1. Nguyên tắc sử dụng cảnh báo R1-R8
Hệ thống kiểm toán chấm công tự động vận hành 08 quy tắc xác định bằng SQL (R1 đến R8) nhằm hỗ trợ Trưởng phòng và Nhân sự phát hiện sớm các dấu hiệu bất thường cần đối chiếu. Mọi cảnh báo R1-R8 đều mang tính trung tính, là cơ sở rà soát dữ liệu chứ chưa phải kết luận vi phạm kỷ luật.

## Mục 2. Định nghĩa chi tiết 08 quy tắc cảnh báo R1-R8

### Quy tắc R1 (Đi muộn lặp lại - late_repeated)
Kích hoạt ở phạm vi cá nhân khi nhân viên có từ 5 ngày trở lên trong cùng một tháng vào làm sau giờ quy định quá 5 phút (sau 08:35:00). Mức độ cảnh báo: thấp hoặc trung bình tùy tần suất.

### Quy tắc R2 (Thiếu dữ liệu chấm công - missing_punch)
Kích hoạt khi nhân viên có từ 2 ngày trở lên trong tháng ở trạng thái đi làm nhưng thiếu giờ vào hoặc thiếu giờ ra. Cần đối chiếu bổ sung để tránh tính thiếu công.

### Quy tắc R3 (Giờ công thấp lặp lại - low_hours)
Kích hoạt khi nhân viên có từ 5 ngày trở lên trong tháng có tổng giờ công thực tế dưới 7,0 giờ/ngày.

### Quy tắc R4 (Nghỉ phép sát kỳ lễ - leave_near_holiday)
Kích hoạt khi nhân viên có nhiều đơn nghỉ phép đã duyệt nằm trong khoảng ±3 ngày quanh một ngày lễ công ty.

### Quy tắc R5 (Nghỉ phép tập trung cấp phòng - leave_cluster)
Kích hoạt ở phạm vi phòng ban (scope = department) khi tỷ lệ nhân sự cùng nghỉ phép đã duyệt trong một ngày đạt từ 25% quân số phòng ban trở lên. Nhân viên thường không nhìn thấy cảnh báo R5 cấp phòng để bảo vệ dữ liệu đồng nghiệp.

### Quy tắc R6 (Giờ chấm công giống hệt từng giây - identical_punch)
Kích hoạt ở mức độ cao (high) khi nhân viên có từ 5 ngày trở lên trong tháng ghi nhận giờ vào và giờ ra trùng khớp tuyệt đối đến từng giây. Cần ưu tiên kiểm tra thiết bị chấm công, lỗi đồng bộ dữ liệu hoặc dữ liệu import.

### Quy tắc R7 (Chấm công cuối tuần hoặc ngày lễ không có đơn OT - weekend_punch)
Kích hoạt khi nhân viên có bản ghi chấm công vào Thứ Bảy, Chủ Nhật hoặc ngày lễ nhưng chưa có đơn làm thêm giờ (overtime_requests) được phê duyệt cho ngày đó.

### Quy tắc R8 (Nghỉ phép năm vượt quỹ phép - leave_over_balance)
Kích hoạt khi tổng số ngày phép năm đã duyệt (tính theo ngày lịch) vượt quá số dư quỹ phép năm được cấp của nhân viên.

## Mục 3. Quy trình xử lý cảnh báo dành cho Trưởng phòng và HR
1. Tiếp nhận và đối chiếu bằng chứng nghiệp vụ: Mở chi tiết cảnh báo tại màn hình Cảnh báo bất thường (/anomalies) để xem các chỉ số xác minh (số ngày, tỷ lệ %, danh sách ngày hoặc nhân sự liên quan).
2. Xác minh thực tế:
   - Đối với R1, R2, R3: Trao đổi với nhân viên, kiểm tra lịch công tác ngoài văn phòng hoặc lỗi máy chấm công; nếu thiếu giờ vào/ra thì HR thực hiện điều chỉnh công có lý do.
   - Đối với R5 (Nghỉ trùng cấp phòng): Trưởng phòng rà soát kế hoạch bàn giao công việc và điều phối nhân lực dự phòng trong ngày có tỷ lệ nghỉ phép cao, phối hợp HR nếu ảnh hưởng vận hành.
   - Đối với R6 (Mức cao): Ưu tiên kiểm tra nguồn dữ liệu (biometric / kiosk / file Excel import) và nhật ký thiết bị trước khi kết luận.
   - Đối với R7, R8: Đối chiếu đơn làm thêm giờ bổ sung (R7) hoặc trao đổi chuyển đổi phần phép vượt quỹ sang nghỉ không lương/điều chỉnh quỹ theo chính sách (R8).
3. Cập nhật trạng thái xử lý: Trưởng phòng (trong phạm vi phòng mình) hoặc HR (toàn công ty) chọn Xác nhận (confirmed) hoặc Bỏ qua (dismissed) kèm ghi chú xử lý rõ ràng để lưu vào nhật ký kiểm toán.
""",
    ),
}
