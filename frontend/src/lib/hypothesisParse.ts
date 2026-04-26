/**
 * Heuristic, deterministic parser for the Hypothesis "Parse" action (no LLM).
 * Tuned for common forms: "If … then …", catabolite-style "Increasing …", and
 * concise assay/enzyme wording (abbreviations like SDH, DCIP are preserved).
 */

export type MockParsedFields = {
  subject: string;
  independent: string;
  dependent: string;
  conditions: string;
  expected: string;
};

const EMPTY: MockParsedFields = {
  subject: "",
  independent: "",
  dependent: "",
  conditions: "",
  expected: "",
};

function trimPunct(s: string): string {
  return s.replace(/[.,;:]+$/, "").trim();
}

/** Dedupe, trim, cap length for a joined conditions string. */
function mergeSnippets(
  parts: string[],
  opts: { maxLen?: number; maxParts?: number } = {},
): string {
  const maxLen = opts.maxLen ?? 200;
  const maxParts = opts.maxParts ?? 4;
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of parts) {
    const s = raw.replace(/\s+/g, " ").trim();
    if (s.length < 2) continue;
    const k = s.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(s);
    if (out.length >= maxParts) break;
  }
  let j = out.join(" · ");
  if (j.length > maxLen) j = j.slice(0, maxLen - 1).trim() + "…";
  return j;
}

/**
 * Model organism / binomial and common cell-line hints for subject when the
 * headline noun is not enough.
 */
function tryOrganismHint(t: string): string {
  const s = t.replace(/\s+/g, " ").trim();
  const known = s.match(
    /\b((?:E\.|B\.|C\.|H\.|M\.|S\.|D\.|P\.|O\.)\s+[\w.-]+(?:\s+[\w.-]+){0,4})\b/iu,
  );
  if (known) {
    const h = trimPunct(known[1]!);
    if (h.length >= 4) return h;
  }
  const heLa = s.match(
    /\b(HeLa|CHO|HEK-?293T?|A549|NIH-?3T3|RAW\s*264\.7)\b/iu,
  );
  if (heLa) return heLa[1]!;
  return "";
}

/**
 * "because / due to / as a result of …" — one clause to enrich the expected field.
 */
function tryRationaleFragment(t: string): string {
  const s = t.replace(/\s+/g, " ");
  const patterns: RegExp[] = [
    /\b(?:as\s+a\s+result\s+of|due\s+to|owing\s+to|because|since)\s+([^.]+)/i,
    /\bgiven\s+([^.]+)/i,
  ];
  for (const re of patterns) {
    const m = s.match(re);
    if (m) {
      const frag = trimPunct(m[1]!.trim());
      if (frag.length >= 8) return frag.length > 220 ? frag.slice(0, 217) + "…" : frag;
    }
  }
  return "";
}

/**
 * "If the IV is changed, then the DV will change …" (optional "because …").
 */
function tryIfThenBecause(t: string): MockParsedFields | null {
  const ifThen = t.match(
    /if\s+(.+?)\s+is\s+(increased|decreased|varied|changed|reduced|raised|lowered)\b\s*,\s*then\s+(.+?)\s+will\s+(increase|decrease|rise|fall|drop|decline|improve|remain|change|be)\b/iu,
  );
  if (!ifThen) return null;

  const ifClause = trimPunct(ifThen[1]);
  const manVerb = (ifThen[2] ?? "").toLowerCase();
  const thenClause = trimPunct(ifThen[3]);
  const willVerb = (ifThen[4] ?? "").toLowerCase();

  const independent = ifClause.replace(/^(?:the|a|an)\s+/iu, "") || ifClause;
  const dependent = thenClause;

  let subject = "";
  const fromRateOf = thenClause.match(
    /(?:^|\s)(?:the\s+)?rate\s+of\s+((?:[A-Z][A-Za-z0-9-]*)(?:\s+(?:[A-Z][A-Za-z0-9-]*|[a-z][a-z]+))*)\s+activity/i,
  );
  if (fromRateOf) {
    const head = fromRateOf[1].split(/\s+/);
    if (head[0] && head[0].length >= 2) subject = head[0];
  }
  if (!subject) {
    const fromActivity = thenClause.match(
      /\b((?:[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*))\s+activity(?:\s|\(|$)/i,
    );
    if (fromActivity) {
      const w = fromActivity[1].split(/\s+/);
      if (w[0] && w[0].length >= 2) subject = w[0];
    }
  }
  if (!subject) {
    const fromEnzyme = t.match(
      /(?:\b|')(?:the\s+)?enzyme(?:'s|\s+)(?:\w+\s+)*([A-Z][A-Za-z0-9-]{1,5})\b/iu,
    );
    if (fromEnzyme) subject = fromEnzyme[1];
  }

  const conditions = grabAssayConditions(t);

  const incMan = new Set(["increased", "raised", "varied", "changed"]);
  const decMan = new Set(["decreased", "reduced", "lowered"]);
  const incOut = new Set([
    "increase",
    "rise",
    "improve",
    "change",
  ]);
  const decOut = new Set([
    "decrease",
    "fall",
    "drop",
    "decline",
  ]);
  let expected = "";
  if (incOut.has(willVerb)) {
    if (incMan.has(manVerb) || (manVerb === "varied" && willVerb === "increase")) {
      expected = "Positive correlation expected";
    } else if (decMan.has(manVerb) && (willVerb === "increase" || willVerb === "rise")) {
      expected = "Dependence as stated in the if/then-clause (manipulation and outcome in opposite sense)";
    } else {
      expected = "Outcome expected to " + (ifThen[4] ?? "change");
    }
  } else if (decOut.has(willVerb) && (incMan.has(manVerb) || decMan.has(manVerb))) {
    expected = "Negative correlation expected";
  } else {
    expected = "Outcome expected to " + (ifThen[4] ?? "change as stated in the then-clause");
  }

  return {
    subject,
    independent,
    dependent,
    conditions,
    expected,
  };
}

/**
 * Pulls out concrete assay / growth context: temps, molarity, pH, gas phase,
 * named media, timing. Multiple hits are joined for a denser "Conditions" field.
 */
function grabAssayConditions(t: string): string {
  const s = t.replace(/\s+/g, " ");
  const out: string[] = [];

  for (const re of [
    /\bpH\s*[\d.]+\b/gi,
    /\b\d{1,2}\s*°\s*C\b/gi,
    /\b\d{1,2}°C\b/gi,
  ]) {
    const mm = s.match(re);
    if (mm) for (const x of mm) out.push(trimPunct(x));
  }

  for (const re of [/\b\d+(?:[–-]\d+)?\s*(?:mM|µM|uM|μM|nM)\b/gi]) {
    const mm = s.match(re);
    if (mm) for (const x of mm) out.push(trimPunct(x));
  }

  const inMedia = s.match(
    /\bin\s+((?:M9|LB|DMEM|RPMI|MD|MM|PBS|Tris|HEPES|MOPS|minimal|synthetic|defined)(?:\s+[\w\-,]+)*\s*(?:media|broth|buffer|minimal\s+media)?)/gi,
  );
  if (inMedia) {
    for (const block of inMedia) {
      const rest = block.replace(/^\s*in\s+/i, "").replace(/\s+/g, " ");
      if (rest.length >= 2) out.push(trimPunct(rest));
    }
  }

  if (/\banaerobic/i.test(s)) out.push("anaerobic");
  else if (/\baerobic/i.test(s)) out.push("aerobic");

  if (/(?:\b|\/)(?:co-?culture|serum-free|high-?glucose)(?:\b|\/)/i.test(s)) {
    const lab = s.match(
      /(?:\b|\/)(co-?culture|serum-free|high-?glucose)(?:\b|\/)/i,
    );
    if (lab) out.push(lab[1]!.toLowerCase());
  }

  if (/\bshaking\b|orbital|rotat(?:e|ing)\s+incubator/i.test(s)) {
    out.push("shaking / orbital");
  }

  if (/\bovernight\b/i.test(s)) out.push("overnight");
  const hr = s.match(/\b\d{1,3}\s*(?:h|hr|hour)s?\b/i);
  if (hr) out.push(trimPunct(hr[0]!));

  const paren = s.match(
    /\(([^)]{0,40}(?:mM|µM|nM|μM|uM|°C|pH)[^)]{0,40})\)/i,
  );
  if (paren) out.push(trimPunct(paren[1]!));

  if (out.length) return mergeSnippets(out, { maxLen: 220, maxParts: 6 });

  const s2 = s.match(
    /\b(\d{1,2}\s*°C|\d+\s*(?:mM|µM|nM|uM|μM|mM|pH)\b[^.,;)]{0,50})/i,
  );
  if (s2) return trimPunct(s2[1] ?? s2[0]);
  const inBuffer = s.match(
    /in\s+((?:PBS|tris|HEPES|M9|MOPS|phosphate|buffer|media)[\w\-,\s]{2,50})/i,
  );
  if (inBuffer) return trimPunct(inBuffer[1]);
  return "";
}

/**
 * Catabolite / growth-style: "Increasing X will reduce Y / increase Y …"
 */
function tryCataboliteStyle(t: string): Partial<MockParsedFields> {
  const lower = t.toLowerCase();
  const out: Partial<MockParsedFields> = {};
  const grab = (re: RegExp) => {
    const m = t.match(re);
    return m ? trimPunct(m[1] ?? m[0]) : "";
  };

  // Stop at the outcome verb, not the first "in ..." (keeps e.g. "in M9 minimal media").
  let indep = grab(
    /(?:increasing|decreasing|varying|changing)\s+(.+?)(?=\s+(?:will|should|shall|is\s+expected|reduces?|increases?)\b)/i,
  );
  if (!indep) {
    indep = grab(
      /(?:increasing|decreasing|varying|changing)\s+([\w().\-,°\s]+?)(?=\s+(?:will|on|in|for|reduces?|increases?|is)\b)/i,
    );
  }
  if (indep) out.independent = indep.replace(/\s+/g, " ").trim();

  const dep1 = grab(
    /(?:reduce|increase|affect|change)s?\s+(?:the\s+)?((?:[A-Z][A-Za-z0-9-]*\s+)?rate\s+of[\w().\-,°\s]+?)(?=\s+(?:of|above|below|when|under|due|in\b))/i,
  );
  const dep2 = grab(
    /(?:will|should)\s+(?:increase|decrease|reduce|change|affect)\s+([\w().\-,°\s]+?)(?=\s+(?:under|when|at|in\b|due|because|above|below|\()|$)/i,
  );
  // "will reduce/increase the specific growth rate … above …" (full DV, stops at threshold / clause end).
  const dep3 = grab(
    /(?:will|should)\s+(?:reduce|increase|decrease)\s+(.+?)(?=\s+above|\s+under|,\s*due|due to|because|\.)\b/iu,
  );
  out.dependent = dep1 || dep2 || dep3;

  if (!out.dependent) {
    const w = lower.match(
      /will\s+(?:increase|decrease|reduce|change|affect)\b[^.,;]*/,
    );
    if (w) {
      const full = t.match(
        new RegExp(escapeReg(w[0]!.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), "i"),
      );
      if (full) {
        const before = t.slice(0, t.indexOf(full[0]!));
        const beforeTail = before.match(/((?:[A-Z][A-Za-z0-9-]*\s+){0,4}[\w().\-,°\s]+?)\s*$/i);
        if (beforeTail) out.dependent = trimPunct(beforeTail[1]!);
      }
    }
  }

  const cond = grab(
    /(?:under|at|in)\s+([\w\-,°.\s/]+?(?:conditions?|media|°\s*C|°C|pH|environment)|(?:aerobic|anaerobic)(?:[,\s]+[\w\-°.\s/]+?)?)/i,
  );
  if (cond) out.conditions = cond;

  const assay = grabAssayConditions(t);
  if (assay) {
    out.conditions = out.conditions
      ? mergeSnippets([out.conditions, assay], { maxLen: 240 })
      : assay;
  }

  return out;
}

function escapeReg(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Merges organism line + "because / due to" tail into subject / expected.
 */
function enrichParsed(t: string, f: MockParsedFields): MockParsedFields {
  const org = tryOrganismHint(t);
  const rat = tryRationaleFragment(t);

  let { subject, expected, independent, dependent, conditions } = f;
  subject = subject.trim();
  const looksWeak =
    /^(?:specific|signal|the|a|an|its|this|that)$/i.test(subject) ||
    subject.length < 2;
  if (!subject && org) subject = org;
  else if (org && (looksWeak || !subject)) subject = org;
  else if (org) {
    const o0 = org.toLowerCase().split(/\s+/)[0] ?? "";
    if (o0 && !subject.toLowerCase().includes(o0)) {
      if (subject.length < 2) subject = org;
    }
  }

  expected = expected.trim();
  if (rat) {
    if (!expected) expected = rat;
    else if (
      expected.length < 55 &&
      !expected.toLowerCase().includes(rat.slice(0, 15).toLowerCase())
    ) {
      expected = `${expected} — ${rat}`.replace(/\s+/g, " ");
      if (expected.length > 300) expected = expected.slice(0, 297) + "…";
    }
  }

  return {
    subject,
    independent: independent.trim(),
    dependent: dependent.trim(),
    conditions: conditions.trim(),
    expected,
  };
}

// Greedy "of|in|on" + head noun — avoids "SD" from "SDH" (non-greedy +? bug).
function grabSubjectOfPhrase(t: string): string {
  const m = t.match(
    /(?:\b|\.)\s*of\s+((?:[A-Z][A-Za-z0-9-]*)(?:\s+(?:(?:[A-Z][A-Za-z0-9-]*)|[a-z][a-z]+|(?:[A-Z]{2,}(?:H|\d+)?))(?!\s*activity\b))*)(?=\s*(?:,|under|at|in\b|measured|activity\b|will|\.))|\bof\s+((?:[A-Z][A-Za-z0-9-]*)(?:\s+[a-z()][\w().\-,°\s]+?))(?=\s*(?:,|then|and|or|under|at|in\b|is\b|measured|will|\.))/i,
  );
  if (m) return trimPunct(m[1] || m[2] || "");
  return "";
}

function legacyMockParse(t: string, lower: string): MockParsedFields {
  if (!t) return { ...EMPTY };

  const grab = (re: RegExp) => {
    const m = t.match(re);
    return m ? trimPunct(m[1] ?? m[0]) : "";
  };

  // Preferred: "the rate/level/amount of Y …"
  const rateOf = grab(
    /(?:the\s+)?(?:rate|level|amount|signal|activity)\s+of\s+([\w().\-,°/]+?)(?=\s*(?:,|\(|measured|will|under|at|in\b|is\b|as\b|\.))/i,
  );
  // "concentration of X (Y)" for IV
  const concOf = grab(
    /concentration\s+of\s+([\w().\-,°/]+?)(?=\s*(?:,|\(|\)|is|will|can|as\b|under|at|in\b|\.))/i,
  );

  const subjectFrom = rateOf
    ? rateOf
    : concOf
      ? concOf
      : grab(
          /(?:\b|\.)\s*of\s+((?:[A-Z][A-Za-z0-9-]*)(?:\s+[\w().\-,°]+?)*)(?=\s*(?:,|measured|will|is\b|then|under|at|in\b|\.|\())/,
        ) ||
        /** "in|on" + proper noun (greedy) */
        grab(
          /(?:\bin|\bon)\s+((?:[A-Z][A-Za-z0-9-]*)(?:\s+[\w().\-,°/]+?)*)(?=\s*(?:,|and|or|then|using|at|under|in\b|on\b|for\b|measured|will|is\b|has\b|with\b|\.))/i,
        );

  const catab = tryCataboliteStyle(t);

  const independent =
    catab.independent ||
    (concOf ? `Concentration of ${concOf}` : "") ||
    grab(
      /(?:increasing|decreasing|varying|changing)\s+([\w().\-,°/]+?)(?=\s+(?:will|on|in|for|reduces?|increases?))/i,
    );

  const dependent =
    catab.dependent ||
    (rateOf ? (rateOf.includes(" activity") ? rateOf : `the rate of ${rateOf}`.replace(/^the the /i, "the ")) : "") ||
    grab(
      /(?:reduce|increase|affect|change)s?\s+(?:the\s+)?((?:[A-Z][A-Za-z0-9-]*\s+)?rate\s+of[\w().\-,°\s]+?)(?=\s+(?:of|above|below|when|under|due|in\b|measured))/i,
    ) ||
    grab(
      /(.+?)\s+will\s+(?:increase|decrease|reduce|change|increase|fall|rise|remain)/i,
    );

  // Subject: from "X activity" or avoid truncated "of SD"
  const subjByActivity = grab(/\b((?:[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*))\s+activity(?=\s*[\(,])/i);
  const subject = subjByActivity
    ? subjByActivity.split(/\s+/).slice(0, 1)[0]!
    : subjectFrom || grabSubjectOfPhrase(t);

  const conditions = catab.conditions || grabAssayConditions(t) || grab(
    /(?:under|at|in)\s+([\w\-,°/.\s]+?(?:conditions?|media|°\s*C|pH|environment|buffer))/i,
  );

  const expected = lower.includes("inverse")
    ? "Inverse relationship between the two variables"
    : lower.match(/\b(will|should)\s+(increase|decrease|improve|reduce)\b/)?.[2] === "increase" ||
        lower.includes("will increase")
      ? "Positive correlation expected"
      : lower.match(/\b(will|should)\s+(increase|decrease|improve|reduce)\b/)?.[2] === "decrease" ||
          lower.includes("will decrease")
        ? "Negative correlation expected"
        : lower.includes("increase")
          ? "Positive correlation expected"
          : lower.includes("reduce") || lower.includes("decrease")
            ? "Negative correlation expected"
            : "";

  return {
    subject: subject || "",
    independent: independent || "",
    dependent: dependent || "",
    conditions: conditions || "",
    expected,
  };
}

/**
 * Fills the five right-panel fields from free-form hypothesis prose.
 */
export function mockParseHypothesis(text: string): MockParsedFields {
  const t = text.trim();
  if (!t) return { ...EMPTY };
  const lower = t.toLowerCase();

  const ifThen = tryIfThenBecause(t);
  if (ifThen && (ifThen.independent || ifThen.dependent)) {
    if (!ifThen.subject) {
      const m = t.match(/\b([A-Z][A-Za-z0-9-]+)\s+activity\b/i);
      if (m && m[1]!.length >= 2) ifThen.subject = m[1]!;
    }
    const ex = grabAssayConditions(t);
    ifThen.conditions = ifThen.conditions
      ? mergeSnippets([ifThen.conditions, ex].filter(Boolean), { maxLen: 220 })
      : ex;
    return enrichParsed(t, ifThen);
  }

  return enrichParsed(t, legacyMockParse(t, lower));
}
