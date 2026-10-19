import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export type HelloChartProps = {
  title: string;
  values: number[];
};

export const helloChartDefaults: HelloChartProps = {
  title: "Hello Remotion",
  values: [30, 55, 80, 45, 95],
};

export const HelloChart: React.FC<HelloChartProps> = ({ title, values }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const max = Math.max(...values);
  const chartHeight = height * 0.5;
  const barWidth = (width * 0.8) / values.length;

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a", alignItems: "center", justifyContent: "center" }}>
      <div style={{ color: "white", fontSize: Math.min(width, height) * 0.08, fontFamily: "sans-serif", marginBottom: 40 }}>
        {title}
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", height: chartHeight, gap: barWidth * 0.1 }}>
        {values.map((value, i) => {
          const progress = spring({ frame: frame - i * 4, fps, config: { damping: 200 } });
          const h = interpolate(progress, [0, 1], [0, (value / max) * chartHeight]);
          return <div key={i} style={{ width: barWidth * 0.9, height: h, backgroundColor: "#38bdf8", borderRadius: 8 }} />;
        })}
      </div>
    </AbsoluteFill>
  );
};
