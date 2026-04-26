// Stage 3 (Materials) output. Consolidated/de-duplicated across all the
// procedures emitted by Stage 2. `vendor` and `sku` left empty until
// Stage 4 (Budget) backfills them from supplier lookups; this lets the
// FE render an actionable list now without a schema change later.

export type MaterialCategory =
  | 'reagent'
  | 'consumable'
  | 'equipment'
  | 'cell_line'
  | 'organism';

export type Material = {
  id: string;
  name: string;
  category: MaterialCategory;
  qty?: number;
  unit?: string;
  spec?: string;            // equipment only — e.g. 'benchtop centrifuge, >=3000g, refrigerated'
  purpose?: string;         // equipment only — e.g. 'cell pelleting'
  vendor?: string;          // backfilled by Stage 4
  sku?: string;             // backfilled by Stage 4
  storage?: string;
  hazard?: string;
  alternatives?: string[];
};

export type MaterialsOutput = {
  materials: Material[];
  total_unique_items: number;
  by_category: Record<MaterialCategory, number>;
  gaps: string[];           // items the LLM couldn't ground; researcher must resolve
  generated_at: string;     // ISO 8601
};
