import { ArrowRight, ArrowSquareOut, Check, FilmSlate } from '@phosphor-icons/react';
import { useEffect, useRef } from 'react';

// [id, label, short label for the phone-width tab strip]
const ITEMS = [
  ['character', 'Character', 'Character'],
  ['writer', 'Script writer', 'Writer'],
  ['video', 'Video', 'Video'],
  ['output', 'Output', 'Output'],
];

function badge(id, done, job) {
  if (id === 'output') return job?.status === 'done' ? 'done' : job && !['failed', 'cancelled'].includes(job.status) ? 'live' : 'todo';
  return done[id] ? 'done' : 'todo';
}

export function Rail({ section, onSelect, done, job, hint, canGenerate, onGenerate }) {
  const listRef = useRef(null);

  // Keep the current tab visible when the rail becomes a scrolling strip on phones.
  useEffect(() => {
    listRef.current?.querySelector('[aria-current]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [section]);

  return (
    <nav className="rail" aria-label="Studio sections">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true"><FilmSlate size={22} weight="bold" /></span>
        <div>
          <strong>Motion Studio</strong>
          <a href="https://github.com/harry0703/MoneyPrinterTurbo" target="_blank" rel="noopener noreferrer">
            for MoneyPrinterTurbo <ArrowSquareOut size={13} weight="bold" aria-hidden="true" />
          </a>
        </div>
      </div>
      <ol className="rail-list" ref={listRef}>
        {ITEMS.map(([id, label, short]) => {
          const state = badge(id, done, job);
          return (
            <li key={id}>
              <button type="button" className={`rail-item${section === id ? ' is-current' : ''}`} aria-current={section === id ? 'step' : undefined}
                onClick={() => onSelect(id)}>
                <span className={`rail-badge is-${state}`} aria-hidden="true">{state === 'done' && <Check size={14} weight="bold" />}</span>
                <span className="label-long">{label}</span>
                <span className="label-short" aria-hidden="true">{short}</span>
                <span className="sr-only">{state === 'done' ? ', complete' : state === 'live' ? ', in progress' : ''}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="rail-foot">
        <button type="button" className="btn btn-primary btn-wide" disabled={!canGenerate} onClick={onGenerate}>
          Generate video <ArrowRight size={18} weight="bold" aria-hidden="true" />
        </button>
        <p className="rail-hint" aria-live="polite">{hint}</p>
      </div>
    </nav>
  );
}
