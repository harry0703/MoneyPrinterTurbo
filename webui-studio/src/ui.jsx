import { Info, Warning } from '@phosphor-icons/react';
import { useId } from 'react';

// Label above, control, then hint or error below; the control gets the id and describedby wiring.
export function Field({ label, hint, error, counter, children }) {
  const id = useId();
  const noteId = `${id}-note`;
  return (
    <div className={`field${error ? ' has-error' : ''}`}>
      <div className="field-top">
        <label htmlFor={id}>{label}</label>
        {counter && <span className="counter" aria-hidden="true">{counter}</span>}
      </div>
      {children(id, hint || error ? noteId : undefined)}
      {(error || hint) && <p id={noteId} className={error ? 'field-error' : 'field-hint'}>{error || hint}</p>}
    </div>
  );
}

// A radio group drawn as pills. options: [{value, label, icon?}]
export function Segmented({ label, value, options, onChange, name }) {
  return (
    <fieldset className="seg-group">
      <legend>{label}</legend>
      <div className="seg">
        {options.map((o) => (
          <label key={o.value} className={`seg-item${o.value === value ? ' is-on' : ''}`}>
            <input type="radio" name={name} value={o.value} checked={o.value === value} onChange={() => onChange(o.value)} />
            {o.icon}
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function Notice({ tone = 'info', title, children, action }) {
  const Icon = tone === 'info' ? Info : Warning;
  return (
    <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon size={22} weight="bold" aria-hidden="true" />
      <div className="notice-body">
        {title && <strong>{title}</strong>}
        <div>{children}</div>
      </div>
      {action}
    </div>
  );
}

export function SectionHead({ title, children }) {
  return (
    <header className="section-head">
      <h2>{title}</h2>
      {children && <p>{children}</p>}
    </header>
  );
}

export const formatBytes = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
