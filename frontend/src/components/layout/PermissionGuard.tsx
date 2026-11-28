import React from 'react';
import { hasAnyPermission, hasPermission } from '../../config/navigation';
import { useAuth } from '../../context/AuthContext';
import { UserRole } from '../../types/navigation';

export interface PermissionGuardProps {
  /** Single required permission code */
  permission?: string;
  /** Grant access if user holds ANY of these permission codes */
  anyPermissions?: string[];
  /** Optional role allowlist (defense-in-depth alongside permissions) */
  roles?: UserRole[];
  /** Optional fallback UI when user lacks permission */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

export const PermissionGuard: React.FC<PermissionGuardProps> = ({
  permission,
  anyPermissions,
  roles,
  fallback = null,
  children,
}) => {
  const { user } = useAuth();
  if (!user) return <>{fallback}</>;

  if (roles && roles.length > 0 && !roles.includes(user.role)) {
    return <>{fallback}</>;
  }
  if (permission && !hasPermission(user, permission)) {
    return <>{fallback}</>;
  }
  if (anyPermissions && anyPermissions.length > 0 && !hasAnyPermission(user, anyPermissions)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
};
