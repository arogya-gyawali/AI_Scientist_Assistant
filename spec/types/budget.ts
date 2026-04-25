import type { Money } from './shared';
import type { MaterialCategory } from './materials';

export type BudgetSource = 'protocols_io_listed' | 'llm_estimate' | 'recent_quote';

export type BudgetLineItem = {
  material_id: string;
  material_name: string;
  qty: number;
  unit_cost: Money;
  total: Money;
  source: BudgetSource;
  confidence: 'high' | 'medium' | 'low';
  notes?: string;
};

export type BudgetOutput = {
  line_items: BudgetLineItem[];
  subtotals_by_category: Record<MaterialCategory, Money>;
  total: Money;
  contingency_pct: number;
  total_with_contingency: Money;
  disclaimer: string;
  assumptions: string[];
};
