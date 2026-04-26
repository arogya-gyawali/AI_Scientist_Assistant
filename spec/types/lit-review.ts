import type { Citation, ISO8601 } from './shared';

export type NoveltySignal =
  | 'novel'
  | 'similar_work_exists'
  | 'exact_match_found';

export type LitReviewOutput = {
  signal: NoveltySignal;
  description: string;            // 2-3 sentence explanation of the signal
  references: Citation[];         // 1-3 most relevant; each carries description + importance + matched_on
  searched_at: ISO8601;
  tavily_query: string;
  summary: string;                // 3-4 sentence holistic wrap-up: novelty + key literature + what to do next
};

export type LitReviewChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  cited_refs?: number[];
  timestamp: ISO8601;
};

export type LitReviewSession = {
  id: string;
  hypothesis_id: string;
  initial_result: LitReviewOutput;
  chat_history: LitReviewChatMessage[];
  cached_search_context: string;
  user_decision: 'pending' | 'proceed' | 'refine' | 'abandon';
};
