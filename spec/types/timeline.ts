import type { Duration, ISO8601 } from './shared';

export type TimelineTask = {
  step_n: number;
  name: string;
  duration: Duration;
  hands_on_time?: Duration;
  can_parallel: boolean;
};

export type TimelinePhase = {
  id: string;
  name: string;
  duration: Duration;
  tasks: TimelineTask[];
  depends_on: string[];
  parallel_with?: string[];
};

export type TimelineOutput = {
  phases: TimelinePhase[];
  total_duration: Duration;
  critical_path: string[];
  assumptions: string[];
  earliest_completion_date?: ISO8601;
};
