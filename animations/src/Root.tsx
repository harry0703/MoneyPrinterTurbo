import { Composition } from "remotion";
import { AgentSwarm, agentSwarmDefaults } from "./AgentSwarm";
import { ByteCompare, byteCompareDefaults } from "./ByteCompare";
import { HelloChart, helloChartDefaults } from "./HelloChart";
import { durationMetadata, FPS } from "./lib";
import { QuoteCard, quoteCardDefaults } from "./QuoteCard";
import { ReverseFlow, reverseFlowDefaults } from "./ReverseFlow";
import { TimelineAnos, timelineAnosDefaults } from "./TimelineAnos";

// Formato do brief (9:16). Para 16:9/1:1 passe --width/--height ao render; os layouts são 9:16.
const W = 1080;
const H = 1920;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="HelloChart"
        component={HelloChart}
        durationInFrames={90}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={helloChartDefaults}
      />
      <Composition
        id="HelloChartWide"
        component={HelloChart}
        durationInFrames={90}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={helloChartDefaults}
      />
      <Composition
        id="ReverseFlow"
        component={ReverseFlow}
        durationInFrames={reverseFlowDefaults.durationSeconds * FPS}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={reverseFlowDefaults}
        calculateMetadata={durationMetadata}
      />
      <Composition
        id="AgentSwarm"
        component={AgentSwarm}
        durationInFrames={agentSwarmDefaults.durationSeconds * FPS}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={agentSwarmDefaults}
        calculateMetadata={durationMetadata}
      />
      <Composition
        id="ByteCompare"
        component={ByteCompare}
        durationInFrames={byteCompareDefaults.durationSeconds * FPS}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={byteCompareDefaults}
        calculateMetadata={durationMetadata}
      />
      <Composition
        id="TimelineAnos"
        component={TimelineAnos}
        durationInFrames={timelineAnosDefaults.durationSeconds * FPS}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={timelineAnosDefaults}
        calculateMetadata={durationMetadata}
      />
      <Composition
        id="QuoteCard"
        component={QuoteCard}
        durationInFrames={1}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={quoteCardDefaults}
      />
    </>
  );
};
