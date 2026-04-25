import type { StageName } from './shared';
import type { ExperimentPlan } from './summary';

// Fields on ExperimentPlan that stages read/write. Excludes lifecycle metadata.
// Each StageName is also the name of the field that stage writes, so PlanField
// is just StageName plus the input field 'hypothesis'.
export type PlanField = 'hypothesis' | StageName;

export type StageContract = {
  stage: StageName;
  reads: PlanField[];      // must be populated before this stage runs
  writes: PlanField[];     // fields this stage populates
  parallel_safe: boolean;  // can run alongside any other stage whose reads/writes don't overlap
};

// Declarative orchestration table. The runner walks ExperimentPlan, finds stages whose
// `reads` are all populated, runs them, writes results back. No inter-stage handoffs.
export const STAGE_CONTRACTS: Record<StageName, StageContract> = {
  lit_review: {
    stage: 'lit_review',
    reads: ['hypothesis'],
    writes: ['lit_review'],
    parallel_safe: true,
  },
  protocol: {
    stage: 'protocol',
    reads: ['hypothesis'],
    writes: ['protocol'],
    parallel_safe: true,
  },
  materials: {
    stage: 'materials',
    reads: ['protocol'],
    writes: ['materials'],
    parallel_safe: true,
  },
  timeline: {
    stage: 'timeline',
    reads: ['protocol'],
    writes: ['timeline'],
    parallel_safe: true,
  },
  validation: {
    stage: 'validation',
    reads: ['hypothesis', 'protocol'],
    writes: ['validation'],
    parallel_safe: true,
  },
  budget: {
    stage: 'budget',
    reads: ['materials'],
    writes: ['budget'],
    parallel_safe: true,
  },
  critique: {
    stage: 'critique',
    reads: ['hypothesis', 'protocol', 'materials', 'budget', 'timeline', 'validation'],
    writes: ['critique'],
    parallel_safe: true,
  },
  summary: {
    stage: 'summary',
    reads: ['hypothesis', 'lit_review', 'protocol', 'materials', 'budget', 'timeline', 'validation', 'critique'],
    writes: ['summary'],
    parallel_safe: false,
  },
};

// A stage is runnable when all its reads are populated and it isn't already running/complete.
export type RunnableStage = {
  contract: StageContract;
  plan: ExperimentPlan;
};
