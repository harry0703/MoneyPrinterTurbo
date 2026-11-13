import { ArrowRight, BookmarkSimple, Cube, ImageSquare, Prohibit, UploadSimple, X } from '@phosphor-icons/react';
import { useRef, useState } from 'react';
import { api } from '../api.js';
import { formatBytes, SectionHead, Segmented } from '../ui.jsx';

const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'webp'];
const HINTS = {
  upload3d: 'Models rigged like Chiku (nodes named head, jaw, eyeL, eyeR, wingL, wingR) blink and move their jaw with the voice. Any other model bobs, turns and talks. Export without Draco compression.',
  image: 'A PNG with a transparent background stands on the disc like a sticker; a photo becomes a round portrait. A still image bounces with the voice but can’t lip-sync.',
  saved: 'Files you put in storage/motion/characters show up here.',
  none: 'No host: the captions take the full width of the video.',
};

const fits = (mode, ch) => Boolean(ch) && (mode === 'saved' ? ch.id.startsWith('preset-')
  : ch.id.startsWith('up-') && ch.kind === (mode === 'image' ? 'image' : 'glb'));

export function Character({ form, update, options, setPreview, onNext }) {
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);
  const mode = form.charMode;
  const current = fits(mode, form.character) ? form.character : null;
  const isImage = mode === 'image';
  const limitMb = isImage ? options.limits.image_mb : options.limits.glb_mb;

  const modes = [
    { value: 'upload3d', label: '3D model', icon: <Cube size={18} weight="bold" aria-hidden="true" /> },
    { value: 'image', label: 'Image', icon: <ImageSquare size={18} weight="bold" aria-hidden="true" /> },
    ...(options.characters.length ? [{ value: 'saved', label: 'Saved', icon: <BookmarkSimple size={18} weight="bold" aria-hidden="true" /> }] : []),
    { value: 'none', label: 'No character', icon: <Prohibit size={18} weight="bold" aria-hidden="true" /> },
  ];

  function chooseMode(next) {
    setError('');
    const keep = fits(next, form.character);
    update({ charMode: next, ...(keep ? {} : { character: null }) });
    if (!keep) setPreview({ kind: 'none', url: null });
    else api.characterUrl(form.character.id).then((url) => setPreview({ kind: form.character.kind, url })).catch(() => {});
  }

  async function take(file) {
    setError('');
    const ext = file.name.toLowerCase().split('.').pop();
    if (isImage ? !IMAGE_EXT.includes(ext) : ext !== 'glb') {
      setError(isImage ? 'Use a PNG, JPG or WebP image.' : 'Use a .glb file (binary glTF).');
      return;
    }
    if (file.size > limitMb * 1048576) {
      setError(`That file is ${formatBytes(file.size)}; the limit is ${limitMb} MB.`);
      return;
    }
    setUploading(true);
    try {
      const saved = await api.upload(file);
      update({ character: { ...saved, size: file.size } });
      setPreview({ kind: saved.kind, url: URL.createObjectURL(file) });
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  }

  function choosePreset(preset) {
    setError('');
    update({ character: preset });
    api.characterUrl(preset.id).then((url) => setPreview({ kind: preset.kind, url })).catch((e) => setError(e.message));
  }

  function remove() {
    update({ character: null });
    setPreview({ kind: 'none', url: null });
  }

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files[0]) take(e.dataTransfer.files[0]);
  };

  return (
    <>
      <SectionHead title="Character">The host who speaks every line. The preview shows it on the video’s sticker disc, exactly as it will render.</SectionHead>
      <Segmented label="Host type" name="char-mode" value={mode} options={modes} onChange={chooseMode} />

      {(mode === 'upload3d' || mode === 'image') && (
        <div className="stack">
          {current ? (
            <div className="file-chip">
              <span className="file-icon" aria-hidden="true">{current.kind === 'glb' ? <Cube size={22} weight="bold" /> : <ImageSquare size={22} weight="bold" />}</span>
              <div className="file-meta">
                <strong>{current.name}</strong>
                <span>{current.kind === 'glb' ? '3D model' : 'Image'}{current.size ? `, ${formatBytes(current.size)}` : ''}</span>
              </div>
              <button type="button" className="btn btn-quiet" onClick={() => inputRef.current.click()}>Replace</button>
              <button type="button" className="icon-btn" aria-label="Remove character" onClick={remove}><X size={18} weight="bold" /></button>
            </div>
          ) : (
            <div className={`drop${dragging ? ' is-dragging' : ''}${error ? ' is-error' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
              <UploadSimple size={34} weight="bold" aria-hidden="true" />
              <p className="drop-title">{uploading ? 'Checking the file…' : isImage ? 'Drop an image here' : 'Drop a .glb model here'}</p>
              <p className="drop-sub">or <button type="button" className="link-btn" disabled={uploading} onClick={() => inputRef.current.click()}>browse your files</button></p>
              <p className="drop-meta">{isImage ? `PNG, JPG or WebP, up to ${limitMb} MB` : `Binary glTF, up to ${limitMb} MB`}</p>
            </div>
          )}
          <input ref={inputRef} type="file" hidden accept={isImage ? '.png,.jpg,.jpeg,.webp' : '.glb'}
            onChange={(e) => { if (e.target.files[0]) take(e.target.files[0]); e.target.value = ''; }} />
          {error && <p className="field-error" role="alert">{error}</p>}
        </div>
      )}

      {mode === 'saved' && (
        <div className="presets" role="radiogroup" aria-label="Saved characters">
          {options.characters.map((p) => (
            <button key={p.id} type="button" role="radio" aria-checked={current?.id === p.id}
              className={`preset${current?.id === p.id ? ' is-on' : ''}`} onClick={() => choosePreset(p)}>
              {p.kind === 'glb' ? <Cube size={20} weight="bold" aria-hidden="true" /> : <ImageSquare size={20} weight="bold" aria-hidden="true" />}
              <span>{p.name}</span>
            </button>
          ))}
          {error && <p className="field-error" role="alert">{error}</p>}
        </div>
      )}

      <p className="section-note">{HINTS[mode]}</p>
      <div className="panel-foot">
        <button type="button" className="btn btn-secondary" onClick={onNext}>Next: Script writer <ArrowRight size={18} weight="bold" aria-hidden="true" /></button>
      </div>
    </>
  );
}
