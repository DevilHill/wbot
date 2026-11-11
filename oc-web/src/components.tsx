import { useEffect, useRef, type ReactNode } from 'react';
import { ArrowUpRight, Search, X, type LucideIcon } from 'lucide-react';
import { stateLabels } from './format';
import type { ParameterDefinition } from './types';

export function StatusBadge({ state }: { state: string }) {
  return <span className={`status status-${state}`}><i />{stateLabels[state] ?? state}</span>;
}

export function EmptyState({ icon: Icon, title, children, action }: { icon: LucideIcon; title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon size={26} strokeWidth={1.5} /></span><h3>{title}</h3><p>{children}</p>{action}</div>;
}

export function SearchBox({ value, onChange, placeholder = '搜索名称…' }: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="search-box"><Search size={16} /><span className="sr-only">{placeholder}</span><input type="search" value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

export function Dialog({ title, description, children, onClose, busy = false, wide = false }: { title: string; description?: string; children: ReactNode; onClose: () => void; busy?: boolean; wide?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const previousFocus = document.activeElement;
    element?.showModal();
    return () => {
      element?.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, []);
  return <dialog className={`dialog ${wide ? 'dialog-wide' : ''}`} ref={dialog} aria-labelledby="dialog-title" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="dialog-heading"><div><h2 id="dialog-title">{title}</h2>{description && <p>{description}</p>}</div><button className="icon-button" type="button" aria-label="关闭对话框" disabled={busy} onClick={onClose}><X size={20} /></button></div>
    {children}
  </dialog>;
}

export function FormFooter({ busy, label, onClose, disabled = false }: { busy: boolean; label: string; onClose: () => void; disabled?: boolean }) {
  return <footer className="dialog-footer"><button className="button secondary" type="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" type="submit" disabled={busy || disabled}>{busy ? '正在处理…' : label}<ArrowUpRight size={15} /></button></footer>;
}

export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="welcome-row"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

export function ParameterFields({ definitions, values, onChange, optional = false }: { definitions: Record<string, ParameterDefinition>; values: Record<string, string>; onChange: (values: Record<string, string>) => void; optional?: boolean }) {
  if (!Object.keys(definitions).length) return <p className="muted inset-note">这个自动化无需填写参数。</p>;
  return <div className="parameter-fields">{Object.entries(definitions).map(([name, definition]) => <label className="field" key={name}>
    <span>{name}{definition.required && !optional && <em> *</em>}<small className="type-label">{definition.type}</small></span>
    {definition.type === 'boolean' ? <select value={values[name] ?? ''} required={definition.required && !optional && definition.default === undefined} onChange={event => onChange({ ...values, [name]: event.target.value })}>
      <option value="">使用默认值 / 不传入</option><option value="true">是（true）</option><option value="false">否（false）</option>
    </select> : <input type={definition.type === 'string' ? 'text' : 'number'} step={definition.type === 'integer' ? 1 : 'any'} value={values[name] ?? ''} onChange={event => onChange({ ...values, [name]: event.target.value })} required={definition.required && !optional && definition.type !== 'string' && definition.default === undefined} />}
    {definition.description && <small>{definition.description}</small>}
  </label>)}</div>;
}
