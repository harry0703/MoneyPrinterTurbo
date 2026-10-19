import { loadFont } from "@remotion/fonts";
import React, { useEffect, useState } from "react";
import {
  AbsoluteFill,
  continueRender,
  delayRender,
  Easing,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const FPS = 30;

export const colors = {
  bg: "#0b1020",
  panel: "#141b34",
  line: "#2a355f",
  text: "#f1f5f9",
  muted: "#94a3b8",
  accent: "#38bdf8",
  good: "#34d399",
  warn: "#fbbf24",
  bad: "#f87171",
};

export const FONT = "BeVietnamPro, sans-serif";
export const MONO = "ui-monospace, Menlo, Consolas, monospace";

/** Props comuns: `durationSeconds` define a duração exata do clipe (cena do shotlist). */
export type BaseProps = {
  title: string;
  note: string;
  durationSeconds: number;
};

export const durationMetadata = <P extends BaseProps>({ props }: { props: P }) => ({
  durationInFrames: Math.max(1, Math.round(props.durationSeconds * FPS)),
});

/** Tempo normalizado 0..1 ao longo da composição: as animações se ajustam a qualquer duração. */
export const useT = (): number => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return durationInFrames <= 1 ? 1 : frame / (durationInFrames - 1);
};

/** Progresso 0..1 (com easing) do trecho [from, to] do tempo normalizado. */
export const seg = (t: number, from: number, to: number): number =>
  interpolate(t, [from, to], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.33, 1, 0.68, 1),
  });

const fontReady = (): Promise<void> =>
  loadFont({
    family: "BeVietnamPro",
    url: staticFile("BeVietnamPro-Bold.ttf"),
    weight: "700",
  });

/** Fundo, título e nota "ilustrativo". Mantém a faixa inferior (~22%) livre para a legenda. */
export const Stage: React.FC<{ title: string; note: string; children: React.ReactNode }> = ({
  title,
  note,
  children,
}) => {
  const [handle] = useState(() => delayRender("font"));
  useEffect(() => {
    fontReady()
      .catch(() => undefined)
      .then(() => continueRender(handle));
  }, [handle]);
  const t = useT();
  const enter = seg(t, 0, 0.08);

  return (
    <AbsoluteFill style={{ backgroundColor: colors.bg, fontFamily: FONT }}>
      <div
        style={{
          position: "absolute",
          top: 90,
          left: 70,
          right: 70,
          color: colors.text,
          fontSize: 64,
          lineHeight: 1.15,
          opacity: enter,
          translate: `0 ${(1 - enter) * -30}px`,
        }}
      >
        {title}
      </div>
      {children}
      <div
        style={{
          position: "absolute",
          top: 1530,
          left: 70,
          right: 70,
          color: colors.muted,
          fontSize: 30,
          opacity: seg(t, 0.1, 0.2),
        }}
      >
        {note}
      </div>
    </AbsoluteFill>
  );
};
