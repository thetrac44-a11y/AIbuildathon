import React, { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../lib/api';

interface Employee { employee_id: string; full_name: string; consent_at: string | null; sample_count: number | null }
interface Employees { items: Employee[]; consent_text: string }
interface ScanResult { message: string; full_name: string; attendance: { check_in: string | null; check_out: string | null } }

export const FaceAttendancePage: React.FC = () => {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const mounted = useRef(true);
  const [camera, setCamera] = useState(false);
  const [starting, setStarting] = useState(false);
  const [tab, setTab] = useState<'scan' | 'enroll'>('scan');
  const [data, setData] = useState<Employees>({ items: [], consent_text: '' });
  const [employeeId, setEmployeeId] = useState('');
  const [consent, setConsent] = useState(false);
  const [images, setImages] = useState<string[]>([]);
  const [mode, setMode] = useState<'check_in' | 'check_out'>('check_in');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const selected = data.items.find(e => e.employee_id === employeeId);
  const load = async () => {
    const result = await apiFetch<Employees>('/faces/employees');
    if (mounted.current) setData(result);
  };
  const stop = () => {
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setCamera(false);
  };
  useEffect(() => {
    mounted.current = true;
    void load().catch(e => setError(e.message));
    return () => { mounted.current = false; stream.current?.getTracks().forEach(t => t.stop()); };
  }, []);
  const start = async () => {
    setError(''); setStarting(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera cần HTTPS hoặc localhost và trình duyệt hỗ trợ webcam.');
      const media = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: 'user', width: { ideal: 960 }, height: { ideal: 720 } } });
      if (!mounted.current) { media.getTracks().forEach(t => t.stop()); return; }
      stream.current = media;
      if (video.current) { video.current.srcObject = media; await video.current.play(); }
      setCamera(true);
    } catch (e) { stop(); setError(e instanceof Error ? e.message : 'Không thể mở camera. Kiểm tra quyền truy cập.'); }
    finally { setStarting(false); }
  };
  const snapshot = () => {
    const player = video.current;
    if (!player || !player.videoWidth || !camera) throw new Error('Camera chưa sẵn sàng.');
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 960 / player.videoWidth);
    canvas.width = Math.round(player.videoWidth * scale); canvas.height = Math.round(player.videoHeight * scale);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Không chụp được ảnh.');
    context.drawImage(player, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.9);
  };
  const capture = () => {
    try { const image = snapshot(); setImages(old => [...old, image]); setError(''); }
    catch (e) { setError((e as Error).message); }
  };
  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const enroll = () => perform(async () => {
    const response = await apiFetch<{ message: string }>('/faces/enroll', { method: 'POST', body: JSON.stringify({ employee_id: employeeId, consent, images }) });
    setImages([]); setConsent(false); setMessage(response.message); stop(); await load();
  });
  const scan = () => perform(async () => {
    const response = await apiFetch<ScanResult>('/faces/scan', { method: 'POST', body: JSON.stringify({ mode, image: snapshot() }) });
    setMessage(`${response.full_name}: ${response.message} Vào: ${response.attendance.check_in || '—'} · Ra: ${response.attendance.check_out || '—'}`);
  });
  const revoke = () => {
    if (!window.confirm('Xóa hồ sơ khuôn mặt và thu hồi đồng ý? Muốn đăng ký lại cần có sự đồng ý mới.')) return;
    void perform(async () => {
      const response = await apiFetch<{ message: string }>(`/faces/profiles/${encodeURIComponent(employeeId)}`, { method: 'DELETE' });
      setImages([]); setConsent(false); setMessage(response.message); await load();
    });
  };
  const button = 'rounded-xl px-4 py-2 font-medium bg-blue-600 text-white disabled:opacity-40';
  return <div className="space-y-5">
    <div><h1 className="text-2xl font-bold">Máy chấm công khuôn mặt</h1><p className="text-slate-500">Kiosk do HR vận hành · YuNet + SFace · Ca 08:30–17:30</p></div>
    <p className="rounded-xl bg-amber-50 p-4 text-amber-900">Bản demo chưa có kiểm tra người thật (liveness), có thể bị đánh lừa bằng ảnh hoặc video. Chỉ sử dụng với người đã đồng ý tham gia thử nghiệm.</p>
    <div className="flex gap-3">{(['scan', 'enroll'] as const).map(value => <button key={value} disabled={busy} className={`${button} ${tab === value ? '' : '!bg-slate-500'}`} onClick={() => { setTab(value); setImages([]); setConsent(false); setMessage(''); setError(''); stop(); }}>{value === 'scan' ? 'Chấm công' : 'Đăng ký / quản lý hồ sơ'}</button>)}</div>
    {error && <div role="alert" className="rounded-xl bg-red-50 p-4 text-red-700">{error}</div>}
    {message && <div role="status" className="rounded-xl bg-green-50 p-4 text-green-800">{message}</div>}
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="space-y-4 rounded-2xl border bg-white p-5">
        <video ref={video} autoPlay playsInline muted aria-label="Xem trước webcam" className="aspect-video w-full rounded-xl bg-slate-900 object-contain" style={{ transform: 'scaleX(-1)' }} />
        <div className="flex gap-3"><button className={button} disabled={camera || busy || starting || (tab === 'enroll' && (!consent || !employeeId || !!selected?.consent_at))} onClick={() => void start()}>{starting ? 'Đang mở…' : 'Bật webcam'}</button><button className={button} disabled={!camera || busy} onClick={stop}>Tắt webcam</button></div>
        <p className="text-sm text-slate-500">Một người trong khung hình, đủ sáng và không che mặt. Không lưu ảnh webcam gốc; ảnh đăng ký chỉ ở bộ nhớ trang trước khi gửi.</p>
      </section>
      <section className="space-y-4 rounded-2xl border bg-white p-5">
        {tab === 'scan' ? <>
          <h2 className="text-lg font-semibold">Chọn thao tác trước khi quét</h2>
          <label className="block">Chế độ <select className="ml-3 rounded border p-2" disabled={busy} value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="check_in">Check-in — Giờ vào</option><option value="check_out">Check-out — Giờ ra</option></select></label>
          <button className={button} disabled={!camera || busy} onClick={() => void scan()}>{busy ? 'Đang xử lý…' : 'Quét và ghi nhận'}</button>
          <p className="text-sm text-slate-500">Chặn quét trùng 30 giây. Không Check-out khi chưa Check-in, không ghi đè giờ đã ghi hoặc ngày nghỉ đã duyệt.</p>
          <p className="text-sm text-slate-500">Sau khi thành công, dữ liệu được ghi ngay vào Attendance. Tải lại Dashboard, Reports và Anomalies để xem dữ liệu mới.</p>
        </> : <>
          <label className="block font-medium">Nhân viên<select className="mt-2 w-full rounded border p-2" value={employeeId} disabled={busy} onChange={e => { setEmployeeId(e.target.value); setImages([]); setConsent(false); stop(); }}><option value="">Chọn nhân viên</option>{data.items.map(e => <option key={e.employee_id} value={e.employee_id}>{e.employee_id} — {e.full_name}{e.consent_at ? ' (đã đăng ký)' : ''}</option>)}</select></label>
          {selected?.consent_at ? <><p>Đã đăng ký {selected.sample_count} ảnh · Đồng ý lúc {selected.consent_at}</p><button className={button} disabled={busy} onClick={revoke}>Thu hồi / xóa hồ sơ</button></> : <>
            <p className="rounded bg-slate-50 p-3 text-sm">{data.consent_text || 'Đang tải nội dung đồng ý…'}</p>
            <label className="flex gap-2"><input type="checkbox" checked={consent} disabled={busy || !employeeId || !data.consent_text} onChange={e => { setConsent(e.target.checked); if (!e.target.checked) { setImages([]); stop(); } }} />Nhân viên đã đọc và trực tiếp xác nhận đồng ý nội dung trên trước HR.</label>
            <p>Chụp 3–6 ảnh riêng biệt: chính diện, hơi nghiêng trái và phải. Backend kiểm tra chất lượng khi hoàn tất.</p>
            <div className="flex gap-2"><button className={button} disabled={!camera || !consent || busy || images.length >= 6} onClick={capture}>Chụp ảnh ({images.length}/6)</button><button className={button} disabled={busy || !images.length} onClick={() => setImages([])}>Chụp lại</button></div>
            <div className="grid grid-cols-3 gap-2">{images.map((image, i) => <img className="rounded" key={i} src={image} alt={`Ảnh đăng ký ${i + 1}`} />)}</div>
            <button className={button} disabled={busy || !consent || !employeeId || images.length < 3} onClick={() => void enroll()}>{busy ? 'Đang kiểm tra…' : 'Hoàn tất đăng ký'}</button>
          </>}
        </>}
      </section>
    </div>
  </div>;
};
