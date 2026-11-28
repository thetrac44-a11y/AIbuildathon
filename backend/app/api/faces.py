"""HR-operated face enrollment and kiosk. All identification is consent based."""
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import AuthenticatedUser, get_db_dependency, require_roles, write_activity_log
from app.schemas.common import RoleEnum
from app.services.face_engine import (
    MODEL_VERSION, cipher, decrypt_templates, encrypt_templates, get_face_engine,
)

router = APIRouter(prefix='/api/faces', tags=['Face attendance'])
hr_only = require_roles(RoleEnum.hr)
CONSENT_TEXT = ('Tôi đồng ý sử dụng dữ liệu khuôn mặt để đăng ký và chấm công tại công ty. '
                'Hệ thống chỉ lưu vector đặc trưng đã mã hóa, không lưu ảnh webcam. '
                'Tôi có thể yêu cầu HR thu hồi đồng ý và xóa hồ sơ khuôn mặt.')


class Enrollment(BaseModel):
    employee_id: str = Field(min_length=1, max_length=100)
    consent: Literal[True]
    images: list[str] = Field(min_length=3, max_length=6)


class Scan(BaseModel):
    mode: Literal['check_in', 'check_out']
    image: str = Field(max_length=1_400_000)


def now_local():
    return datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).replace(tzinfo=None, microsecond=0)


def profiles(conn):
    return conn.execute('''SELECT f.*, e.full_name, e.employment_status FROM face_profiles f
                           JOIN employees e USING(employee_id)''').fetchall()


def similarity(vector, row):
    if row['model_version'] != MODEL_VERSION:
        raise HTTPException(503, 'Hồ sơ dùng model khác. HR cần đăng ký lại.')
    return float(np.max(decrypt_templates(row['encrypted_embeddings']) @ vector))


@router.get('/employees')
def employees(user: AuthenticatedUser = Depends(hr_only), conn=Depends(get_db_dependency)):
    return {'consent_text': CONSENT_TEXT, 'items': [dict(r) for r in conn.execute('''
        SELECT e.employee_id, e.full_name, f.consent_at, f.sample_count
        FROM employees e LEFT JOIN face_profiles f USING(employee_id)
        WHERE e.employment_status = 'active' ORDER BY e.employee_id''')],
        'liveness_enabled': False}


@router.post('/enroll')
def enroll(body: Enrollment, user: AuthenticatedUser = Depends(hr_only),
           conn=Depends(get_db_dependency), engine=Depends(get_face_engine)):
    cipher()  # Fail before processing biometric input if key is missing.
    if any(len(image) > 1_400_000 for image in body.images):
        raise HTTPException(422, 'Ảnh quá lớn.')
    if len({hashlib.sha256(i.encode()).digest() for i in body.images}) != len(body.images):
        raise HTTPException(422, 'Hãy chụp các ảnh riêng biệt, không gửi lại cùng một ảnh.')
    vectors = np.array([engine.extract(image) for image in body.images])
    if float(np.min(vectors @ vectors.T)) < 0.363:
        raise HTTPException(422, 'Các ảnh chưa nhất quán cùng một người. Vui lòng chụp lại.')
    conn.execute('BEGIN IMMEDIATE')
    try:
        employee = conn.execute("SELECT * FROM employees WHERE employee_id=? AND employment_status='active'",
                                (body.employee_id,)).fetchone()
        if not employee:
            raise HTTPException(404, 'Không tìm thấy nhân viên đang hoạt động.')
        for row in profiles(conn):
            if row['employee_id'] == body.employee_id:
                raise HTTPException(409, 'Nhân viên đã đăng ký. Xóa hồ sơ cũ trước khi đăng ký lại.')
            if max(similarity(v, row) for v in vectors) >= float(os.getenv('FACE_MATCH_THRESHOLD', '0.45')):
                raise HTTPException(409, 'Khuôn mặt có thể đã thuộc hồ sơ khác. HR cần kiểm tra.')
        timestamp = now_local().isoformat(' ')
        conn.execute('INSERT INTO face_profiles VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (body.employee_id, encrypt_templates(vectors), MODEL_VERSION, len(vectors),
                      CONSENT_TEXT, timestamp, user.user_id))
        write_activity_log(conn, user.user_id, 'face_enroll', 'face_profile', body.employee_id,
                           after_obj={'sample_count': len(vectors), 'consent_at': timestamp,
                                      'consent_text': CONSENT_TEXT, 'model': MODEL_VERSION})
        conn.commit()
        return {'message': 'Đã đăng ký khuôn mặt.', 'employee_id': body.employee_id}
    except Exception:
        conn.rollback()
        raise


@router.delete('/profiles/{employee_id}')
def remove(employee_id: str, user: AuthenticatedUser = Depends(hr_only), conn=Depends(get_db_dependency)):
    conn.execute('PRAGMA secure_delete=ON')
    with conn:
        result = conn.execute('DELETE FROM face_profiles WHERE employee_id=?', (employee_id,))
        if not result.rowcount:
            raise HTTPException(404, 'Chưa có hồ sơ khuôn mặt.')
        write_activity_log(conn, user.user_id, 'face_revoke_delete', 'face_profile', employee_id)
    return {'message': 'Đã thu hồi và xóa hồ sơ khuôn mặt khỏi dữ liệu hoạt động.'}


@router.post('/scan')
def scan(body: Scan, user: AuthenticatedUser = Depends(hr_only),
         conn=Depends(get_db_dependency), engine=Depends(get_face_engine)):
    employee_id, score = None, None
    try:
        cipher()
        vector = engine.extract(body.image)
        # Serialize matching with enrollment/deletion and all attendance writes.
        conn.execute('BEGIN IMMEDIATE')
        candidates = sorted([(similarity(vector, row), row) for row in profiles(conn)
                             if row['employment_status'] == 'active'], key=lambda pair: pair[0], reverse=True)
        threshold = float(os.getenv('FACE_MATCH_THRESHOLD', '0.45'))
        margin = float(os.getenv('FACE_MATCH_MARGIN', '0.08'))
        if not candidates or candidates[0][0] < threshold:
            raise HTTPException(422, 'Không nhận diện đủ tin cậy. Chưa ghi nhận công.')
        score, employee = candidates[0]
        if len(candidates) > 1 and score - candidates[1][0] < margin:
            raise HTTPException(422, 'Kết quả gần nhiều hồ sơ. Chưa ghi nhận công; liên hệ HR.')
        employee_id = employee['employee_id']
        now = now_local()
        timestamp, day = now.isoformat(' '), now.date().isoformat()
        last = conn.execute("SELECT scanned_at FROM face_scan_logs WHERE employee_id=? AND result='success' ORDER BY id DESC LIMIT 1",
                            (employee_id,)).fetchone()
        if last and (now - datetime.fromisoformat(last['scanned_at'])).total_seconds() < 30:
            raise HTTPException(409, 'Đã ghi nhận gần đây. Chờ ít nhất 30 giây.')
        if conn.execute("SELECT 1 FROM leave_requests WHERE employee_id=? AND status='approved' AND ? BETWEEN from_date AND to_date",
                        (employee_id, day)).fetchone():
            raise HTTPException(409, 'Ngày nghỉ đã được duyệt. HR cần xác minh trước khi ghi công.')
        current = conn.execute('SELECT * FROM attendance WHERE employee_id=? AND work_date=?',
                               (employee_id, day)).fetchone()
        before = dict(current) if current else None
        if current and current['status'] == 'on_leave':
            raise HTTPException(409, 'Không ghi đè ngày nghỉ đã lưu.')
        if body.mode == 'check_in':
            if current and (current['check_in'] or current['check_out']):
                raise HTTPException(409, 'Ngày này đã có giờ chấm công. HR cần kiểm tra nếu muốn điều chỉnh.')
            conn.execute('''INSERT INTO attendance(employee_id, work_date, check_in, status, source)
                VALUES (?, ?, ?, 'present', 'face') ON CONFLICT(employee_id, work_date)
                DO UPDATE SET check_in=excluded.check_in, status='present', source='face' ''',
                         (employee_id, day, timestamp))
        else:
            if not current or not current['check_in']:
                raise HTTPException(409, 'Chưa Check-in, không thể Check-out.')
            if current['check_out']:
                raise HTTPException(409, 'Đã Check-out. Không ghi đè giờ ra.')
            if timestamp <= current['check_in']:
                raise HTTPException(409, 'Giờ ra phải sau giờ vào.')
            conn.execute("UPDATE attendance SET check_out=?, source='face', status='present' WHERE id=?",
                         (timestamp, current['id']))
        after = dict(conn.execute('SELECT * FROM attendance WHERE employee_id=? AND work_date=?',
                                  (employee_id, day)).fetchone())
        conn.execute('''INSERT INTO face_scan_logs(employee_id, actor_user_id, mode, result, score, scanned_at)
                        VALUES (?, ?, ?, 'success', ?, ?)''', (employee_id, user.user_id, body.mode, score, timestamp))
        write_activity_log(conn, user.user_id, f'face_{body.mode}', 'attendance', str(after['id']), before, after)
        # Existing R7 scanner will enrich this monthly record when run again.
        if now.weekday() >= 5 or conn.execute('SELECT 1 FROM holidays WHERE holiday_date=?', (day,)).fetchone():
            conn.execute('''INSERT INTO anomalies(employee_id, department_id, rule_code, anomaly_type,
                severity, period, evidence, explanation, dedup_key)
                VALUES (?, (SELECT department_id FROM employees WHERE employee_id=?), 'R7',
                'weekend_punch', 'low', ?, ?, ?, ?) ON CONFLICT(dedup_key) DO UPDATE SET
                evidence=excluded.evidence, explanation=excluded.explanation''',
                (employee_id, employee_id, day[:7], json.dumps({'work_date': day, 'source': 'face'}),
                 'Chấm công ngoài ngày làm việc thông thường; HR cần xác minh.', f'R7:{employee_id}:{day[:7]}'))
        conn.commit()
        return {'message': 'Đã ghi nhận giờ vào.' if body.mode == 'check_in' else 'Đã ghi nhận giờ ra.',
                'employee_id': employee_id, 'full_name': employee['full_name'], 'attendance': after,
                'similarity': round(score, 4)}
    except HTTPException as exc:
        conn.rollback()
        conn.execute('''INSERT INTO face_scan_logs(employee_id, actor_user_id, mode, result, score, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?)''', (employee_id, user.user_id, body.mode,
                                           f'rejected_{exc.status_code}', score, now_local().isoformat(' ')))
        conn.commit()
        raise
