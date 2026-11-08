import { ArrowRight, ArrowSquareOut, Eye, EyeSlash, LockSimple } from '@phosphor-icons/react';
import { useId, useState } from 'react';
import { Field, SectionHead, Segmented } from '../ui.jsx';

export function Writer({ form, update, providers, apiKey, setApiKey, onNext }) {
  const [showKey, setShowKey] = useState(false);
  const listId = useId();
  const provider = providers.find((p) => p.id === form.provider) ?? providers[0];
  if (!provider) return null;
  const takesKey = provider.needs_key || provider.id === 'custom';

  function pick(id) {
    const next = providers.find((p) => p.id === id);
    update({ provider: id, model: next.models[0] ?? '', baseUrl: next.default_base_url ?? '' });
  }

  const modelHint = provider.models.length
    ? `Suggested: ${provider.models.join(', ')}. Any model your account offers works.`
    : 'The model name your endpoint expects.';

  return (
    <>
      <SectionHead title="Script writer">The AI that writes the script, plans every scene and drafts your YouTube details.</SectionHead>
      <Segmented label="Provider" name="provider" value={provider.id} options={providers.map((p) => ({ value: p.id, label: p.label }))} onChange={pick} />

      <Field label="Model" hint={modelHint}>
        {(id, describedBy) => (
          <>
            <input id={id} aria-describedby={describedBy} className="input" list={listId} value={form.model}
              onChange={(e) => update({ model: e.target.value })} autoComplete="off" spellCheck={false} />
            <datalist id={listId}>{provider.models.map((m) => <option key={m} value={m} />)}</datalist>
          </>
        )}
      </Field>

      {(provider.needs_base_url || provider.default_base_url) && (
        <Field label="Base URL" hint={provider.id === 'ollama' ? 'Where Ollama is running. The default works for a local install.' : 'Your OpenAI-compatible endpoint, for example https://api.example.com/v1'}>
          {(id, describedBy) => (
            <input id={id} aria-describedby={describedBy} className="input" type="url" value={form.baseUrl}
              placeholder={provider.default_base_url ?? 'https://'} onChange={(e) => update({ baseUrl: e.target.value })} autoComplete="off" spellCheck={false} />
          )}
        </Field>
      )}

      {takesKey && (
        <>
          <Field label={provider.needs_key ? 'API key' : 'API key (optional)'}>
            {(id) => (
              <div className="input-group">
                <input id={id} className="input" type={showKey ? 'text' : 'password'} value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                  autoComplete="off" spellCheck={false} placeholder={provider.needs_key ? `Paste your ${provider.label} key` : ''} />
                <button type="button" className="icon-btn" aria-label={showKey ? 'Hide key' : 'Show key'} aria-pressed={showKey} onClick={() => setShowKey((v) => !v)}>
                  {showKey ? <EyeSlash size={20} weight="bold" /> : <Eye size={20} weight="bold" />}
                </button>
              </div>
            )}
          </Field>
          <div className="key-note">
            <LockSimple size={22} weight="bold" aria-hidden="true" />
            <p>
              Your key goes from this app’s server straight to {provider.id === 'custom' ? 'your endpoint' : provider.label} for
              this video, then it’s dropped. It isn’t saved, logged or sent anywhere else, so you’ll paste it again after
              reloading the page.
            </p>
          </div>
          {provider.key_url && (
            <a className="text-link" href={provider.key_url} target="_blank" rel="noopener noreferrer">
              Get your {provider.label} key <ArrowSquareOut size={14} weight="bold" aria-hidden="true" />
            </a>
          )}
        </>
      )}

      <div className="panel-foot">
        <button type="button" className="btn btn-secondary" onClick={onNext}>Next: Video <ArrowRight size={18} weight="bold" aria-hidden="true" /></button>
      </div>
    </>
  );
}
