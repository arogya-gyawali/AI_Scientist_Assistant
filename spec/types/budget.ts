import type { ISO8601, Money, URL } from './shared';
import type { MaterialCategory } from './materials';

export type BudgetSource =
  | 'protocols_io_listed'
  | 'supplier_lookup'
  | 'llm_estimate'
  | 'recent_quote';

export type SupplierQuote = {
  vendor: string;                 // 'thermo_fisher' | 'sigma_aldrich' | 'promega' | 'qiagen' | 'idt' | 'atcc' | 'addgene' | other
  product_name: string;
  catalog_number: string;
  pack_size?: string;             // e.g. "100mg", "1L", "50 reactions"
  price: Money;
  url: URL;                       // direct link to the product page
  in_stock?: boolean;
  scraped_at: ISO8601;
  source_via: 'tavily' | 'direct_api' | 'manual';
};

export type BudgetLineItem = {
  material_id: string;
  material_name: string;
  qty: number;
  unit_cost: Money;
  total: Money;
  source: BudgetSource;
  confidence: 'high' | 'medium' | 'low';
  notes?: string;
  supplier_quotes?: SupplierQuote[];   // all quotes found
  selected_quote?: SupplierQuote;      // which one drove unit_cost
};

export type BudgetOutput = {
  line_items: BudgetLineItem[];
  subtotals_by_category: Record<MaterialCategory, Money>;
  total: Money;
  contingency_pct: number;
  total_with_contingency: Money;
  disclaimer: string;
  assumptions: string[];
  preferred_suppliers?: string[];      // priority list, e.g. ['sigma_aldrich', 'thermo_fisher']
};
