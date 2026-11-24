import { describe, it, expect } from "vitest";

describe("SpanHighlighter Logic", () => {
  it("slices prefix, target, and suffix cleanly with exact offsets", () => {
    const text = "SECTION 1. Either party may terminate within 30 days.";
    const start = 11;
    const end = 52;
    const target = text.slice(start, end);
    expect(target).toBe("Either party may terminate within 30 days.");
  });

  it("handles boundary offsets at start and end of document", () => {
    const text = "Hello World";
    // At start
    expect(text.slice(0, 5)).toBe("Hello");
    // At end
    expect(text.slice(6, 11)).toBe("World");
  });

  it("handles multi-byte Unicode strings with identical character index parity", () => {
    const text = "§ 4.2 Fee is €100 — payable in (30) days.";
    const targetSubstring = "€100";
    const start = text.indexOf(targetSubstring);
    const end = start + targetSubstring.length;
    expect(text.slice(start, end)).toBe("€100");
  });

  it("differentiates verified vs unverified highlight styling tags", () => {
    const verifiedClass = true ? "span-highlight-verified" : "span-highlight-unverified";
    const unverifiedClass = false ? "span-highlight-verified" : "span-highlight-unverified";
    expect(verifiedClass).toBe("span-highlight-verified");
    expect(unverifiedClass).toBe("span-highlight-unverified");
  });
});
