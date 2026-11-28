import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FaceAttendancePage } from '../pages/FaceAttendancePage';

describe('Face kiosk consent and camera lifecycle', () => {
  afterEach(() => vi.restoreAllMocks());
  it('requires consent before opening enrollment camera and stops tracks on unmount', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => ({
      consent_text: 'Tôi đồng ý thử nghiệm', items: [{ employee_id: 'E1', full_name: 'Test', consent_at: null }],
    }) } as Response);
    const stop = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] });
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
    const view = render(<FaceAttendancePage />);
    fireEvent.click(screen.getByRole('button', { name: 'Đăng ký / quản lý hồ sơ' }));
    await screen.findByRole('option', { name: 'E1 — Test' });
    expect(screen.getByRole('button', { name: 'Bật webcam' })).toBeDisabled();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'E1' } });
    expect(screen.getByRole('button', { name: 'Bật webcam' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Bật webcam' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Tắt webcam' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Hoàn tất đăng ký' })).toBeDisabled();
    view.unmount();
    expect(stop).toHaveBeenCalledTimes(1);
  });
});
