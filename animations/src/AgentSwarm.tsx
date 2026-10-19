import React from "react";
import { BaseProps, colors, seg, Stage, useT } from "./lib";

export type AgentSwarmProps = BaseProps & {
  agents: number;
  percent: number;
  caption: string;
};

export const agentSwarmDefaults: AgentSwarmProps = {
  title: "17 agentes de IA, um jogo",
  note: "Ilustração: cada quadrado é uma função do jogo",
  durationSeconds: 10,
  agents: 17,
  percent: 99,
  caption: "das funções recriadas",
};

const COLS = 20;
const ROWS = 18;
const CELL = 44;
const GAP = 4;
const HUES = [200, 160, 40, 280, 340, 100];

/** Ordem de preenchimento pseudoaleatória, mas determinística (sem Math.random no render). */
const order = Array.from({ length: COLS * ROWS }, (_, i) => i).sort(
  (a, b) => ((a * 7919) % 401) - ((b * 7919) % 401),
);
const rank = new Map(order.map((cell, r) => [cell, r]));

export const AgentSwarm: React.FC<AgentSwarmProps> = ({ title, note, agents, percent, caption }) => {
  const t = useT();
  const total = COLS * ROWS;
  const progress = seg(t, 0.12, 0.88);
  const filled = Math.round(progress * (percent / 100) * total);
  const shown = Math.round(progress * percent);
  const gridW = COLS * (CELL + GAP) - GAP;

  return (
    <Stage title={title} note={note}>
      <div
        style={{
          position: "absolute",
          top: 230,
          left: (1080 - gridW) / 2,
          width: gridW,
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          justifyContent: "center",
          opacity: seg(t, 0, 0.1),
        }}
      >
        {Array.from({ length: agents }, (_, a) => (
          <div
            key={a}
            style={{
              width: 34,
              height: 34,
              borderRadius: 17,
              backgroundColor: `hsl(${HUES[a % HUES.length]} 80% 60%)`,
            }}
          />
        ))}
      </div>
      <div
        style={{
          position: "absolute",
          top: 330,
          left: (1080 - gridW) / 2,
          width: gridW,
          display: "grid",
          gridTemplateColumns: `repeat(${COLS}, ${CELL}px)`,
          gap: GAP,
        }}
      >
        {Array.from({ length: total }, (_, i) => {
          const on = (rank.get(i) ?? 0) < filled;
          return (
            <div
              key={i}
              style={{
                width: CELL,
                height: CELL,
                borderRadius: 8,
                backgroundColor: on ? `hsl(${HUES[i % HUES.length]} 80% 60%)` : colors.panel,
              }}
            />
          );
        })}
      </div>
      <div
        style={{
          position: "absolute",
          top: 1250,
          left: 0,
          right: 0,
          textAlign: "center",
          color: colors.good,
          fontSize: 150,
          lineHeight: 1,
        }}
      >
        {shown}%
        <div style={{ color: colors.text, fontSize: 40, marginTop: 8 }}>{caption}</div>
      </div>
    </Stage>
  );
};
