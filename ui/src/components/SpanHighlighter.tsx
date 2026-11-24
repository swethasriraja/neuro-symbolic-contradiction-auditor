import React from "react";

interface SpanHighlighterProps {
  fullText: string;
  charStart: number;
  charEnd: number;
  isVerified: boolean;
}

/**
 * Highlights a substring in fullText using character offsets provided by the API.
 * Never performs fuzzy or client-side text searches.
 * Handles boundary conditions (0-offset, end-offset, out-of-bounds) and Unicode strings.
 */
export const SpanHighlighter: React.FC<SpanHighlighterProps> = ({
  fullText,
  charStart,
  charEnd,
  isVerified,
}) => {
  if (!fullText) return <pre className="source-text-block">No text available.</pre>;

  const safeStart = Math.max(0, Math.min(charStart, fullText.length));
  const safeEnd = Math.max(safeStart, Math.min(charEnd, fullText.length));

  const prefix = fullText.slice(0, safeStart);
  const target = fullText.slice(safeStart, safeEnd);
  const suffix = fullText.slice(safeEnd);

  const highlightClass = isVerified ? "span-highlight-verified" : "span-highlight-unverified";

  return (
    <pre className="source-text-block">
      <span>{prefix}</span>
      <mark
        className={highlightClass}
        data-testid="highlighted-span"
        title={isVerified ? "Verified Citation" : "Unverified Citation (Failed Verification)"}
      >
        {target}
      </mark>
      {!isVerified && (
        <span className="unverified-tag" data-testid="unverified-tag">
          [⚠️ UNVERIFIED SPAN]
        </span>
      )}
      <span>{suffix}</span>
    </pre>
  );
};
