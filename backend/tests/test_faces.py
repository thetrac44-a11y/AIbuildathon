from datetime import datetime

import numpy as np
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import faces
from app.core.security import get_db_dependency, load_authenticated_user
from app.db.connection import get_connection, init_db
from app.main import app
from app.services.face_engine import decrypt_templates, get_face_engine


class FakeEngine:
    def extract(self, image):
        if image == 'bad':
            raise HTTPException(422, 'bad quality')
        vector = np.zeros(128, dtype=np.float32)
        vector[1 if image.startswith('other') else 0] = 1
        return vector


@pytest.fixture
def rig(tmp_path, monkeypatch):
    path = tmp_path / 'face.db'
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO departments VALUES ('D', 'Test')")
    for identifier, role in [('HR', 'hr'), ('E1', 'employee'), ('E2', 'employee')]:
        conn.execute('''INSERT INTO employees(employee_id, full_name, department_id, position, start_date, role)
                        VALUES (?, ?, 'D', 'Test', '2026-01-01', ?)''', (identifier, identifier, role))
        conn.execute('INSERT INTO users(user_id, username, password_hash, employee_id) VALUES (?, ?, ?, ?)',
                     (identifier, identifier, 'unused', identifier))
    conn.commit()
    user = load_authenticated_user(conn, 'HR')
    conn.close()

    def db():
        connection = get_connection(path)
        try:
            yield connection
        finally:
            connection.close()

    monkeypatch.setenv('FACE_ENCRYPTION_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(faces, 'now_local', lambda: datetime(2026, 12, 5, 10, 0))  # Saturday
    app.dependency_overrides[get_db_dependency] = db
    app.dependency_overrides[faces.hr_only] = lambda: user
    app.dependency_overrides[get_face_engine] = FakeEngine
    with TestClient(app) as client:
        yield client, path
    app.dependency_overrides.clear()


def enrollment(employee='E1', prefix='face'):
    return {'employee_id': employee, 'consent': True, 'images': [prefix + str(i) for i in range(3)]}


def test_consent_quality_encryption_duplicate_and_delete(rig):
    client, path = rig
    body = enrollment()
    assert client.post('/api/faces/enroll', json={**body, 'consent': False}).status_code == 422
    assert client.post('/api/faces/enroll', json={**body, 'images': ['bad', 'face1', 'face2']}).status_code == 422
    assert client.post('/api/faces/enroll', json={**body, 'images': ['a', 'a', 'a']}).status_code == 422
    assert client.post('/api/faces/enroll', json=body).status_code == 200
    conn = get_connection(path)
    row = conn.execute('SELECT * FROM face_profiles').fetchone()
    assert row['consent_text'] == faces.CONSENT_TEXT
    assert decrypt_templates(row['encrypted_embeddings']).shape == (3, 128)
    assert 'encrypted_embeddings' not in client.get('/api/faces/employees').text
    assert client.post('/api/faces/enroll', json=enrollment('E2')).status_code == 409
    assert client.delete('/api/faces/profiles/E1').status_code == 200
    assert conn.execute('SELECT COUNT(*) FROM face_profiles').fetchone()[0] == 0
    assert client.post('/api/faces/scan', json={'image': 'face', 'mode': 'check_in'}).status_code == 422
    conn.close()


def test_attendance_duplicate_leave_weekend_audit(rig, monkeypatch):
    client, path = rig
    assert client.post('/api/faces/enroll', json=enrollment()).status_code == 200
    scan = lambda mode: client.post('/api/faces/scan', json={'image': 'face', 'mode': mode})
    assert scan('check_out').status_code == 409
    result = scan('check_in')
    assert result.status_code == 200, result.text
    assert result.json()['attendance']['source'] == 'face'
    assert result.json()['attendance']['check_in'] == '2026-12-05 10:00:00'
    assert scan('check_out').status_code == 409
    monkeypatch.setattr(faces, 'now_local', lambda: datetime(2026, 12, 5, 17, 30))
    assert scan('check_out').status_code == 200
    monkeypatch.setattr(faces, 'now_local', lambda: datetime(2026, 12, 5, 17, 31))
    assert scan('check_out').status_code == 409
    conn = get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM anomalies WHERE rule_code='R7'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM activity_logs WHERE entity_type='attendance'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM face_scan_logs WHERE result='success'").fetchone()[0] == 2
    conn.execute("INSERT INTO leave_requests(employee_id, leave_type, from_date, to_date, reason, status) VALUES ('E1', 'annual', '2026-12-07', '2026-12-07', 'test', 'approved')")
    conn.commit()
    monkeypatch.setattr(faces, 'now_local', lambda: datetime(2026, 12, 7, 10, 0))
    assert scan('check_in').status_code == 409
    assert conn.execute("SELECT COUNT(*) FROM attendance WHERE work_date='2026-12-07'").fetchone()[0] == 0
    conn.close()


def test_ambiguous_match_and_wrong_key_fail_closed(rig, monkeypatch):
    client, path = rig
    assert client.post('/api/faces/enroll', json=enrollment()).status_code == 200
    conn = get_connection(path)
    conn.execute("INSERT INTO face_profiles SELECT 'E2', encrypted_embeddings, model_version, sample_count, consent_text, consent_at, registered_by FROM face_profiles WHERE employee_id='E1'")
    conn.commit()
    result = client.post('/api/faces/scan', json={'image': 'face', 'mode': 'check_in'})
    assert result.status_code == 422
    monkeypatch.setenv('FACE_ENCRYPTION_KEY', Fernet.generate_key().decode())
    assert client.post('/api/faces/scan', json={'image': 'face', 'mode': 'check_in'}).status_code == 503
    assert conn.execute('SELECT COUNT(*) FROM attendance').fetchone()[0] == 0
    conn.close()


def test_unauthenticated_and_employee_cannot_manage_or_scan(rig):
    client, path = rig
    app.dependency_overrides.pop(faces.hr_only)
    assert client.get('/api/faces/employees').status_code == 401
    from app.core.security import create_access_token
    token, _, _ = create_access_token('E1', 'E1')
    headers = {'Authorization': f'Bearer {token}'}
    assert client.get('/api/faces/employees', headers=headers).status_code == 403
    assert client.post('/api/faces/enroll', json=enrollment(), headers=headers).status_code == 403
    assert client.post('/api/faces/scan', json={'image': 'face', 'mode': 'check_in'}, headers=headers).status_code == 403
    assert client.delete('/api/faces/profiles/E1', headers=headers).status_code == 403
