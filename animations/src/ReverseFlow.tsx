import React from "react";
import { interpolate } from "remotion";
import { BaseProps, colors, seg, Stage, useT } from "./lib";

export type ReverseFlowProps = BaseProps & { steps: string[] };

export const reverseFlowDefaults: ReverseFlowProps = {
  title: "Como a IA abre um programa fechado",
  note: "Esquema ilustrativo do processo",
  durationSeconds: 14,
  steps: [
    "Programa fechado\n(só o executável)",
    "Desmontagem\n(código de máquina)",
    "Mapa das funções",
    "Agentes de IA\nreescrevem o código",
    "Código novo que\nroda igual",
  ],
};

const NODE_H = 190;
const GAP = 70;
const TOP = 270;

export const ReverseFlow: React.FC<ReverseFlowProps> = ({ title, note, steps }) => {
  const t = useT();
  const n = steps.length;
  const slot = 0.9 / n;
  const packetY = interpolate(t, [0.05, 0.95], [0, (n - 1) * (NODE_H + GAP)], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <Stage title={title} note={note}>
      <div
        style={{
          position: "absolute",
          left: 92,
          top: TOP + NODE_H / 2,
          width: 6,
          height: (n - 1) * (NODE_H + GAP),
          backgroundColor: colors.line,
          opacity: seg(t, 0.03, 0.08),
        }}
      />
      {steps.map((label, i) => {
        const appear = seg(t, 0.05 + i * slot, 0.05 + i * slot + 0.06);
        const lit = seg(t, 0.05 + i * slot + 0.04, 0.05 + i * slot + 0.1);
        const y = TOP + i * (NODE_H + GAP);
        const last = i === n - 1;
        return (
          <React.Fragment key={i}>
            {!last && (
              <div
                style={{
                  position: "absolute",
                  left: 540 - 3,
                  top: y + NODE_H,
                  width: 6,
                  height: GAP,
                  backgroundColor: colors.line,
                  opacity: appear,
                }}
              />
            )}
            <div
              style={{
                position: "absolute",
                left: 130,
                top: y,
                width: 820,
                height: NODE_H,
                borderRadius: 28,
                backgroundColor: colors.panel,
                border: `4px solid ${lit > 0.5 ? (last ? colors.good : colors.accent) : colors.line}`,
                display: "flex",
                alignItems: "center",
                gap: 34,
                paddingLeft: 40,
                opacity: appear,
                scale: String(0.92 + 0.08 * appear),
              }}
            >
              <div
                style={{
                  width: 84,
                  height: 84,
                  borderRadius: 42,
                  backgroundColor: last ? colors.good : colors.accent,
                  color: colors.bg,
                  fontSize: 48,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                {i + 1}
              </div>
              <div style={{ color: colors.text, fontSize: 46, lineHeight: 1.2, whiteSpace: "pre-line" }}>
                {label}
              </div>
            </div>
          </React.Fragment>
        );
      })}
      <div
        style={{
          position: "absolute",
          left: 92 - 18 + 3,
          top: TOP + NODE_H / 2 - 18 + packetY,
          width: 36,
          height: 36,
          borderRadius: 18,
          backgroundColor: colors.warn,
          boxShadow: `0 0 30px ${colors.warn}`,
          opacity: seg(t, 0.03, 0.08) * (1 - seg(t, 0.94, 0.99)),
        }}
      />
    </Stage>
  );
};
