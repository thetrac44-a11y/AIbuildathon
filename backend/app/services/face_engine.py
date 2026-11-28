"""CPU YuNet/SFace adapter. No frames or plaintext templates are written to disk."""
import base64
import binascii
import os
import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

MODEL_VERSION = 'yunet-2023mar+sface-2021dec-v1'
MODEL_DIR = Path(__file__).resolve().parents[2] / 'models'


def cipher():
    try:
        return Fernet(os.environ.get('FACE_ENCRYPTION_KEY', '').encode('ascii'))
    except (ValueError, UnicodeError):
        raise HTTPException(503, 'Chưa cấu hình FACE_ENCRYPTION_KEY hợp lệ ở backend.')


def encrypt_templates(vectors):
    return cipher().encrypt(np.asarray(vectors, dtype='<f4').tobytes()).decode('ascii')


def decrypt_templates(value):
    try:
        vectors = np.frombuffer(cipher().decrypt(value.encode('ascii')), dtype='<f4').reshape(-1, 128)
        if not len(vectors) or not np.isfinite(vectors).all():
            raise ValueError()
        return vectors
    except (InvalidToken, ValueError):
        raise HTTPException(503, 'Không đọc được hồ sơ khuôn mặt. Kiểm tra khóa mã hóa; không tạo khóa mới thay thế.')


class FaceEngine:
    def __init__(self):
        detector = Path(os.getenv('FACE_YUNET_MODEL', str(MODEL_DIR / 'face_detection_yunet_2023mar.onnx')))
        recognizer = Path(os.getenv('FACE_SFACE_MODEL', str(MODEL_DIR / 'face_recognition_sface_2021dec.onnx')))
        if not detector.is_file() or not recognizer.is_file():
            raise HTTPException(503, 'Thiếu model YuNet/SFace. Chạy scripts/setup_faces.py trước.')
        self.detector = cv2.FaceDetectorYN.create(str(detector), '', (320, 320), 0.9)
        self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer), '')
        self.lock = threading.Lock()

    def extract(self, data_url):
        try:
            prefix, encoded = data_url.split(',', 1)
            if prefix != 'data:image/jpeg;base64':
                raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
            # Webcam clients send JPEGs capped at 960px; reject oversized headers before decode.
            if len(raw) > 1_000_000:
                raise ValueError()
            image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if image is None or max(image.shape[:2]) > 1920:
                raise ValueError()
        except (ValueError, binascii.Error, cv2.error):
            raise HTTPException(422, 'Ảnh JPEG không hợp lệ hoặc quá lớn.')
        h, w = image.shape[:2]
        with self.lock:
            self.detector.setInputSize((w, h))
            _, faces = self.detector.detect(image)
            if faces is None or len(faces) != 1:
                raise HTTPException(422, 'Cần đúng một khuôn mặt trong khung hình.')
            face = faces[0]
            x, y, fw, fh = [int(v) for v in face[:4]]
            if min(fw, fh) < 80 or x < 0 or y < 0 or x + fw > w or y + fh > h:
                raise HTTPException(422, 'Đưa toàn bộ khuôn mặt gần và vào giữa camera.')
            gray = cv2.cvtColor(image[y:y+fh, x:x+fw], cv2.COLOR_BGR2GRAY)
            if not 45 <= float(gray.mean()) <= 220:
                raise HTTPException(422, 'Ánh sáng không phù hợp. Vui lòng điều chỉnh ánh sáng.')
            if cv2.Laplacian(gray, cv2.CV_64F).var() < 40:
                raise HTTPException(422, 'Ảnh mờ. Giữ yên và chụp lại.')
            aligned = self.recognizer.alignCrop(image, face)
            vector = self.recognizer.feature(aligned).flatten().copy()
        norm = float(np.linalg.norm(vector))
        if vector.shape != (128,) or not np.isfinite(vector).all() or norm <= 0:
            raise HTTPException(422, 'Không tạo được đặc trưng khuôn mặt.')
        return vector / norm


@lru_cache(maxsize=1)
def get_face_engine():
    try:
        return FaceEngine()
    except cv2.error:
        raise HTTPException(503, 'Không tải được model YuNet/SFace. Kiểm tra file ONNX.')
