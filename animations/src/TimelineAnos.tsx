import React from "react";
import { BaseProps, colors, seg, Stage, useT } from "./lib";

export type AppPair = { from: string; to: string };

export type TimelineAnosProps = BaseProps & {
  before: string;
  after: string;
  /** Largura da barra "agora" em relação à "antes" (0..1); escala ilustrativa. */
  ratio: number;
  apps: AppPair[];
};

export const timelineAnosDefaults: TimelineAnosProps = {
  title: "O que levava anos, agora leva semanas",
  note: "Escala ilustrativa; veja as fontes na descrição",
  durationSeconds: 10,
  before: "Antes: anos",
  after: "Agora: semanas",
  ratio: 0.08,
  apps: [
    { from: "Photoshop", to: "alternativa livre" },
    { from: "Premiere", to: "alternativa livre" },
    { from: "Word", to: "alternativa livre" },
    { from: "Excel", to: "alternativa livre" },
    { from: "AutoCAD", to: "alternativa livre" },
  ],
};

const BAR_W = 880;

export const TimelineAnos: React.FC<TimelineAnosProps> = ({ title, note, before, after, ratio, apps }) => {
  const t = useT();
  const beforeW = seg(t, 0.08, 0.4) * BAR_W;
  const afterW = seg(t, 0.4, 0.55) * BAR_W * ratio;

  return (
    <Stage title={title} note={note}>
      <div style={{ position: "absolute", top: 290, left: 100, color: colors.text, fontSize: 48 }}>{before}</div>
      <div
        style={{
          position: "absolute",
          top: 360,
          left: 100,
          width: beforeW,
          height: 90,
          borderRadius: 20,
          backgroundColor: colors.bad,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 500,
          left: 100,
          color: colors.text,
          fontSize: 48,
          opacity: seg(t, 0.4, 0.45),
        }}
      >
        {after}
      </div>
      <div
        style={{
          position: "absolute",
          top: 570,
          left: 100,
          width: afterW,
          height: 90,
          borderRadius: 20,
          backgroundColor: colors.good,
        }}
      />
      {apps.map((app, i) => {
        const appear = seg(t, 0.58 + i * 0.07, 0.65 + i * 0.07);
        return (
          <div
            key={app.from}
            style={{
              position: "absolute",
              top: 740 + i * 125,
              left: 100,
              width: 880,
              height: 105,
              borderRadius: 22,
              backgroundColor: colors.panel,
              border: `3px solid ${colors.line}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "0 36px",
              fontSize: 44,
              opacity: appear,
              translate: `${(1 - appear) * 60}px 0`,
            }}
          >
            <span style={{ color: colors.text }}>{app.from}</span>
            <span style={{ color: colors.accent }}>→</span>
            <span style={{ color: colors.good }}>{app.to}</span>
          </div>
        );
      })}
    </Stage>
  );
};
