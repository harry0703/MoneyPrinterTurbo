import { ArrowRight } from '@phosphor-icons/react';
import { Field, SectionHead } from '../ui.jsx';

export function Brief({ form, update, voices, missing, busy, finished, onGenerate, onGo }) {
  const languages = [...new Set(voices.map((v) => v.language))];
  const blocked = missing.length > 0 || busy || finished;
  let footHint = null;
  if (finished) footHint = <button type="button" className="link-btn" onClick={() => onGo('output')}>Your Short is ready</button>;
  else if (busy) footHint = <button type="button" className="link-btn" onClick={() => onGo('output')}>A video is being made</button>;
  else if (missing.length) footHint = <button type="button" className="link-btn" onClick={() => onGo(missing[0][0])}>{missing[0][1]}</button>;
  return (
    <>
      <SectionHead title="Video">What the Short is about. The AI turns this into a 35 to 55 second script with scenes.</SectionHead>

      <Field label="Title" hint="Also used as your YouTube title." counter={`${form.title.length}/100`}>
        {(id, describedBy) => (
          <input id={id} aria-describedby={describedBy} className="input input-lg" maxLength={100} value={form.title}
            onChange={(e) => update({ title: e.target.value })} placeholder="Minimum due is the costliest mistake" />
        )}
      </Field>

      <Field label="Topic">
        {(id) => (
          <input id={id} className="input" maxLength={300} value={form.topic} onChange={(e) => update({ topic: e.target.value })}
            placeholder="Why paying only the credit card minimum due costs you" />
        )}
      </Field>

      <Field label="Description" counter={`${form.description.length}/3000`}
        hint="Key points, numbers and facts to cover. The AI is told not to invent statistics, so include the numbers you want on screen.">
        {(id, describedBy) => (
          <textarea id={id} aria-describedby={describedBy} className="input" rows={6} maxLength={3000} value={form.description}
            onChange={(e) => update({ description: e.target.value })}
            placeholder={'₹20,000 bill, ₹1,000 minimum due paid\nAbout 3.5% a month on the rest, 42% a year\nRule: always pay the total amount due'} />
        )}
      </Field>

      <Field label="Voice and language" hint="The script is written in the voice’s language.">
        {(id, describedBy) => (
          <select id={id} aria-describedby={describedBy} className="input" value={form.voice} onChange={(e) => update({ voice: e.target.value })}>
            {languages.map((lang) => (
              <optgroup key={lang} label={lang}>
                {voices.filter((v) => v.language === lang).map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </optgroup>
            ))}
          </select>
        )}
      </Field>

      <div className="panel-foot">
        {footHint && <span className="foot-hint">{footHint}</span>}
        <button type="button" className="btn btn-primary" disabled={blocked} onClick={onGenerate}>
          Generate video <ArrowRight size={18} weight="bold" aria-hidden="true" />
        </button>
      </div>
    </>
  );
}
