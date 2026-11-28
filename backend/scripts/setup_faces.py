"""Run from backend: python scripts/setup_faces.py. Never resets existing attendance."""
import hashlib
import os
from pathlib import Path
import sys
from urllib.request import urlopen

from cryptography.fernet import Fernet
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    model_dir = ROOT / 'models'
    model_dir.mkdir(exist_ok=True)
    models = [('face_detection_yunet', 'face_detection_yunet_2023mar.onnx', 200_000,
               '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'),
              ('face_recognition_sface', 'face_recognition_sface_2021dec.onnx', 30_000_000,
               '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79')]
    for folder, name, minimum, expected in models:
        target = model_dir / name
        if not target.exists():
            url = f'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{folder}/{name}'
            print(f'Downloading {name} from OpenCV Zoo...')
            with urlopen(url, timeout=120) as response:
                content = response.read(50_000_001)
            if not minimum <= len(content) <= 50_000_000:
                raise RuntimeError(f'Invalid model download: {name}')
            if hashlib.sha256(content).hexdigest() != expected:
                raise RuntimeError(f'Model checksum mismatch: {name}')
            target.write_bytes(content)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'Model checksum mismatch: {name}')
        print(f'{name}: SHA256 {hashlib.sha256(target.read_bytes()).hexdigest()}')
    env_file = ROOT / '.env'
    values = dotenv_values(env_file)
    if not values.get('FACE_ENCRYPTION_KEY') and not os.getenv('FACE_ENCRYPTION_KEY'):
        # Never replace a key when encrypted profiles already exist.
        from app.db.connection import get_connection, init_db
        init_db()
        conn = get_connection()
        try:
            if conn.execute('SELECT COUNT(*) FROM face_profiles').fetchone()[0]:
                raise RuntimeError('Existing profiles found. Restore original encryption key; do not generate a replacement.')
        finally:
            conn.close()
        with env_file.open('a', encoding='utf-8') as handle:
            handle.write('\nFACE_ENCRYPTION_KEY=' + Fernet.generate_key().decode() + '\n')
        print('Created encryption key in backend/.env (ignored by Git). Keep a protected backup.')
    from app.db.connection import init_db
    init_db()
    print('Face schema ready. Existing application data preserved.')


if __name__ == '__main__':
    os.chdir(ROOT)
    main()
