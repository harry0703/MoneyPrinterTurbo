import React from "react";
import { BaseProps, colors, MONO, seg, Stage, useT } from "./lib";

export type ByteCompareProps = BaseProps & {
  functions: string[];
  /** Índices (em `functions`) das funções que NÃO ficam idênticas. */
  different: number[];
  /** Funções que falham na tentativa 1 e passam na 2 ("o agente tenta de novo"). */
  retry: number[];
  /** Momento (0..1 da duração) em que a tentativa 2 corrige as funções de `retry`. */
  retryAt: number;
  /** Legenda dos bytes em cinza (ignorados na comparação). */
  ignored: string;
  original: string;
  recreated: string;
  result: string;
};

export const byteCompareDefaults: ByteCompareProps = {
  title: "Como saber se a cópia ficou igual?",
  note: "Ilustração: bytes e nomes de funções são exemplos",
  durationSeconds: 12,
  functions: ["main", "load_map", "draw_frame", "physics", "play_sound", "ai_think", "net_send", "save_game"],
  different: [5],
  retry: [2],
  retryAt: 0.78,
  ignored: "cinza: ignorado na comparação",
  original: "Original",
  recreated: "Recriado pela IA",
  result: "Segundo o autor: 83% das funções idênticas, byte a byte",
};

const hex = (seed: string, n: number): string[] => {
  let h = 2166136261;
  for (const ch of seed) {
    h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  }
  return Array.from({ length: n }, () => {
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h >>> 8) & 0xff).toString(16).padStart(2, "0");
  });
};

const ROW_H = 120;
const TOP = 360;
const BYTES = 6;

export const ByteCompare: React.FC<ByteCompareProps> = ({
  title,
  note,
  functions,
  different,
  retry,
  retryAt,
  ignored,
  original,
  recreated,
  result,
}) => {
  const t = useT();
  const same = functions.length - different.length;
  const done = seg(t, 0.15, 0.85);
  const revealed = done * functions.length;

  return (
    <Stage title={title} note={note}>
      <div
        style={{
          position: "absolute",
          top: 270,
          left: 70,
          right: 70,
          display: "flex",
          justifyContent: "space-between",
          color: colors.muted,
          fontSize: 38,
          opacity: seg(t, 0, 0.08),
        }}
      >
        <span>{original}</span>
        <span>{recreated}</span>
      </div>
      {functions.map((name, i) => {
        const a = hex(name, BYTES);
        const isRetry = retry.includes(i);
        const retried = t >= retryAt;
        const isDiff = different.includes(i) || (isRetry && !retried);
        const b = a.map((v, k) => {
          if (k === BYTES - 1) {
            return hex(`${name}-reloc`, 1)[0];
          }
          return isDiff && k === 3 ? "a7" : v;
        });
        const rowProgress = Math.min(1, Math.max(0, revealed - i));
        const shownBytes = Math.floor(rowProgress * BYTES);
        const finished = rowProgress >= 1;
        const verdict = isDiff ? colors.bad : colors.good;
        return (
          <div
            key={name}
            style={{
              position: "absolute",
              top: TOP + i * ROW_H,
              left: 70,
              right: 70,
              height: ROW_H - 16,
              borderRadius: 18,
              backgroundColor: colors.panel,
              border: `3px solid ${finished ? verdict : colors.line}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "0 28px",
              opacity: seg(t, 0.05 + i * 0.01, 0.12 + i * 0.01),
            }}
          >
            <div style={{ fontFamily: MONO, fontSize: 34, color: colors.text, width: 380 }}>
              <div style={{ color: colors.accent, fontSize: 26 }}>{name}()</div>
              {a.map((v, k) => (
                <span key={k} style={{ color: k === BYTES - 1 ? colors.muted : colors.text }}>
                  {v}{" "}
                </span>
              ))}
            </div>
            <div style={{ color: verdict, fontSize: 44, lineHeight: 1, opacity: finished ? 1 : 0, textAlign: "center" }}>
              {isDiff ? "≠" : "="}
              {isRetry && finished && (
                <div style={{ fontSize: 20, lineHeight: 1.1 }}>{retried ? "2ª tentativa" : "1ª tentativa"}</div>
              )}
            </div>
            <div style={{ fontFamily: MONO, fontSize: 34, color: colors.text, width: 380, textAlign: "right" }}>
              <div style={{ fontSize: 26, opacity: 0 }}>.</div>
              {b.slice(0, shownBytes).map((v, k) => (
                <span
                  key={k}
                  style={{ color: k === BYTES - 1 ? colors.muted : isDiff && k === 3 ? colors.bad : colors.text }}
                >
                  {v}{" "}
                </span>
              ))}
            </div>
          </div>
        );
      })}
      <div
        style={{
          position: "absolute",
          top: TOP + functions.length * ROW_H + 20,
          left: 0,
          right: 0,
          textAlign: "center",
          color: colors.good,
          fontSize: 44,
          padding: "0 60px",
          opacity: seg(t, 0.85, 0.95),
        }}
      >
        {result}
        <div style={{ color: colors.muted, fontSize: 30, marginTop: 8 }}>
          {same} de {functions.length} no exemplo · {ignored}
        </div>
      </div>
    </Stage>
  );
};
