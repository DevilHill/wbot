import { createContext, useContext, type ButtonHTMLAttributes } from 'react';
import type { Session } from './types';

export const IdentityContext = createContext<Session | null>(null);
export function usePermission(permission: string) {
  const identity = useContext(IdentityContext);
  return identity?.mode === 'local' || Boolean(identity?.permissions?.includes(permission));
}

export function PermissionButton({ permission, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { permission: string }) {
  const allowed = usePermission(permission);
  if (!allowed) return props.className === 'table-title' ? <span className="table-title">{children}</span> : null;
  return <button {...props}>{children}</button>;
}
