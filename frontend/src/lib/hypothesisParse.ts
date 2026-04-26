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

function grabAssayConditions(t: string): string {
  const s = t.match(
    /\b(\d{1,2}\s*°C|\d+\s*(?:mM|µM|nM|mM|pH)\b[^.,;)]{0,40})/i,
  );
  if (s) return trimPunct(s[1] ?? s[0]);
  const inBuffer = t.match(
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

  const indep = grab(
    /(?:increasing|decreasing|varying|changing)\s+([\w().\-,°\s]+?)(?=\s+(?:will|on|in|for|reduces?|increases?|is))/i,
  );
  if (indep) out.independent = indep;

  const dep1 = grab(
    /(?:reduce|increase|affect|change)s?\s+(?:the\s+)?((?:[A-Z][A-Za-z0-9-]*\s+)?rate\s+of[\w().\-,°\s]+?)(?=\s+(?:of|above|below|when|under|due|in\b))/i,
  );
  const dep2 = grab(
    /(?:will|should)\s+(?:increase|decrease|reduce|change|affect)\s+([\w().\-,°\s]+?)(?=\s+(?:under|when|at|in\b|due|because|\.)|$)/i,
  );
  out.dependent = dep1 || dep2;

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

  return out;
}

function escapeReg(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
    if (!ifThen.conditions) ifThen.conditions = grabAssayConditions(t);
    return ifThen;
  }

  return legacyMockParse(t, lower);
}
