import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { apiFetch, getStoredToken, setStoredToken } from '../lib/api';
import { UserRole } from '../types/navigation';

export interface AuthUser {
  user_id: string;
  username: string;
  employee_id: string;
  full_name: string;
  role: UserRole;
  department_id: string;
  department_name: string;
  position: string;
  manager_id?: string | null;
  manager_name?: string | null;
  start_date: string;
  annual_leave_balance: number;
  used_annual_leave: number;
  remaining_annual_leave: number;
  employment_status: string;
  email?: string | null;
  phone?: string | null;
  must_change_password: boolean;
  permissions?: string[];
  allowed_screens: string[];
}

export interface ToastMessage {
  id: number;
  type: 'success' | 'error' | 'info';
  text: string;
}

export const AVAILABLE_PERIODS = [
  { value: '2026-11', label: 'Tháng 11/2026' },
  { value: '2026-10', label: 'Tháng 10/2026' },
  { value: '2026-09', label: 'Tháng 09/2026' },
  { value: '2026-08', label: 'Tháng 08/2026' },
  { value: '2026-07', label: 'Tháng 07/2026' },
  { value: '2026-06', label: 'Tháng 06/2026' },
];

interface AuthContextValue {
  user: AuthUser | null;
  isLoadingAuth: boolean;
  selectedPeriod: string;
  setSelectedPeriod: (period: string) => void;
  login: (username: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refreshProfile: () => Promise<void>;
  toasts: ToastMessage[];
  showToast: (text: string, type?: 'success' | 'error' | 'info') => void;
  dismissToast: (id: number) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{
  initialTestUser?: AuthUser | null;
  children: React.ReactNode;
}> = ({ initialTestUser, children }) => {
  const [user, setUser] = useState<AuthUser | null>(initialTestUser ?? null);
  const [isLoadingAuth, setIsLoadingAuth] = useState<boolean>(initialTestUser === undefined);
  const [selectedPeriod, setSelectedPeriod] = useState<string>('2026-10');
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (text: string, type: 'success' | 'error' | 'info' = 'success') => {
      const id = Date.now() + Math.floor(Math.random() * 1000);
      setToasts((prev) => [...prev, { id, type, text }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 4200);
    },
    []
  );

  const refreshProfile = useCallback(async () => {
    const token = getStoredToken();
    if (!token) {
      setUser(null);
      setIsLoadingAuth(false);
      return;
    }
    try {
      const me = await apiFetch<AuthUser>('/auth/me');
      setUser(me);
    } catch {
      setStoredToken(null);
      setUser(null);
    } finally {
      setIsLoadingAuth(false);
    }
  }, []);

  useEffect(() => {
    if (initialTestUser !== undefined) {
      setIsLoadingAuth(false);
      return;
    }
    refreshProfile();
  }, [initialTestUser, refreshProfile]);

  const login = useCallback(
    async (username: string, password: string): Promise<AuthUser> => {
      const res = await apiFetch<{ access_token: string; user: AuthUser }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      setStoredToken(res.access_token);
      setUser(res.user);
      showToast(`Xin chào ${res.user.full_name} (${res.user.role.toUpperCase()})`, 'success');
      return res.user;
    },
    [showToast]
  );

  const logout = useCallback(async () => {
    try {
      await apiFetch('/auth/logout', { method: 'POST' });
    } catch {
      // Clear local session even if server logout fails
    } finally {
      setStoredToken(null);
      setUser(null);
      showToast('Đã đăng xuất an toàn.', 'info');
    }
  }, [showToast]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoadingAuth,
        selectedPeriod,
        setSelectedPeriod,
        login,
        logout,
        refreshProfile,
        toasts,
        showToast,
        dismissToast,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used inside an AuthProvider');
  }
  return ctx;
}
