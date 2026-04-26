import type { Citation, DOI } from './shared';

export type MaterialCategory = string; // 'reagent' | 'consumable' | 'equipment' | 'cell_line' | 'organism' | ...

export type MaterialAlternative = {
  vendor: string;
  sku: string;
  notes?: string;
};

export type Material = {
  id: string;
  name: string;
  category: MaterialCategory;
  vendor: string;
  sku: string;
  qty: number;
  unit: string;
  cited_doi?: DOI;
  alternatives?: MaterialAlternative[];
  storage?: string;
  hazard?: string;
  citation: Citation;
};

export type MaterialsOutput = {
  materials: Material[];
  total_unique_items: number;
  by_category: Record<MaterialCategory, number>;
  gaps: string[];
};
