import type { Hypothesis, Citation, ISO8601 } from './shared';

export type LitReviewInput = {
  hypothesis: Hypothesis;
};

export type LitReviewOutput = {
  signal: 'not_found' | 'similar_work_exists' | 'exact_match_found';
  signal_explanation: string;
  refs: Citation[];
  searched_at: ISO8601;
  tavily_query: string;
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
  cached_tavily_context: string;
  user_decision: 'pending' | 'proceed' | 'refine' | 'abandon';
};
