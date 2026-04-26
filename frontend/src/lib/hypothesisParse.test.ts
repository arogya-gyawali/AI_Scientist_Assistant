import { describe, it, expect } from "vitest";
import { mockParseHypothesis } from "./hypothesisParse";

const SUCCINATE_SDH = `If the concentration of the substrate (succinate) is increased, then the rate of SDH activity (measured by reduction of DCIP absorbance) will increase, because more substrate molecules are available to bind to the enzyme's active site`;

const ECOLI_GLUCOSE = `We hypothesize that increasing glucose concentration in M9 minimal media will reduce the specific growth rate of E. coli K-12 above 10 mM, due to catabolite repression of alternative carbon utilization pathways under aerobic conditions at 37 °C.`;

describe("mockParseHypothesis", () => {
  it("extracts if/then/because enzymology-style hypotheses (SDH, succinate, DCIP)", () => {
    const p = mockParseHypothesis(SUCCINATE_SDH);
    expect(p.independent).toMatch(/concentration of the substrate|succinate/i);
    expect(p.dependent).toMatch(/SDH activity/i);
    expect(p.dependent).toMatch(/DCIP/);
    expect(p.subject).toBe("SDH");
    expect(p.expected).toBeTruthy();
  });

  it("still supports growth/catabolite-style phrasing (glucose, E. coli)", () => {
    const p = mockParseHypothesis(ECOLI_GLUCOSE);
    expect(p.independent).toMatch(/glucose|M9|media/i);
    expect(p.dependent).toMatch(/growth|rate|E\.|coli/i);
    expect(p.conditions).toMatch(/37|aerobic|M9|mM|°C/i);
    expect(p.expected).toMatch(/catabolite|repression|Positive|Negative|correlation/i);
    expect(p.subject).toMatch(/E\.|coli|K-12|MG1655/i);
  });

  it("does not collapse enzyme abbreviations to two-letter prefixes (SD vs SDH)", () => {
    const p = mockParseHypothesis("If the rate of SDH activity is increased, then the signal will increase.");
    expect(p.subject).not.toBe("SD");
    expect(p.independent).toMatch(/SDH|rate|activity/i);
  });

  it("catabolite path does not throw when independent is set but dependent must be inferred", () => {
    // Covers tryCataboliteStyle fallback that uses `lower` on the prose string.
    const p = mockParseHypothesis("Increasing temperature in the reactor vessel without a clear will/shall clause.");
    expect(p.independent).toMatch(/temperature/i);
    expect(p).toBeDefined();
  });
});
