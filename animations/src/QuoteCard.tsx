import React from "react";
import { colors, Stage } from "./lib";

export type QuoteCardProps = {
  /** Fonte e data, no topo (ex.: "Blog de Maurice Heumann · 9 out 2026"). */
  source: string;
  /** Endereço da fonte, no rodapé. */
  url: string;
  /** Trecho exato da fonte (entre aspas) ou resumo nosso, conforme `isQuote`. */
  text: string;
  /** Parte de `text` destacada. */
  highlight: string;
  isQuote: boolean;
  /** Rótulo pequeno acima do texto: "Trecho do blog", "Resumo da matéria"... */
  label: string;
  /** Linha extra opcional abaixo do texto principal. */
  extra: string;
};

export const quoteCardDefaults: QuoteCardProps = {
  source: "Fonte · data",
  url: "exemplo.com",
  text: "Trecho de exemplo da fonte.",
  highlight: "exemplo",
  isQuote: true,
  label: "Trecho",
  extra: "",
};

const Highlighted: React.FC<{ text: string; highlight: string }> = ({ text, highlight }) => {
  const i = highlight ? text.indexOf(highlight) : -1;
  if (i < 0) {
    return <>{text}</>;
  }
  return (
    <>
      {text.slice(0, i)}
      <span style={{ color: colors.accent }}>{highlight}</span>
      {text.slice(i + highlight.length)}
    </>
  );
};

export const QuoteCard: React.FC<QuoteCardProps> = ({ source, url, text, highlight, isQuote, label, extra }) => {
  const size = text.length > 170 ? 54 : text.length > 110 ? 62 : 72;
  return (
    <Stage title={source} note={url}>
      <div
        style={{
          position: "absolute",
          top: 330,
          left: 70,
          right: 70,
          bottom: 460,
          borderRadius: 32,
          backgroundColor: colors.panel,
          border: `4px solid ${colors.line}`,
          padding: "50px 56px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          gap: 36,
        }}
      >
        <div style={{ color: colors.muted, fontSize: 36 }}>{label}</div>
        <div style={{ color: colors.text, fontSize: size, lineHeight: 1.25 }}>
          {isQuote ? "“" : ""}
          <Highlighted text={text} highlight={highlight} />
          {isQuote ? "”" : ""}
        </div>
        {extra ? <div style={{ color: colors.muted, fontSize: 38, lineHeight: 1.3 }}>{extra}</div> : null}
      </div>
    </Stage>
  );
};
