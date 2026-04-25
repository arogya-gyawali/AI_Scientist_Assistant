import type { DOI, ISO8601 } from './shared';

export type ProtocolCacheRow = {
  doi: DOI;
  protocol_io_id: number;
  title: string;
  authors_json: string;
  raw_steps_json: string;
  raw_materials_json: string;
  fetched_at: ISO8601;
};

export type ProtocolChunkRow = {
  id: string;
  doi: DOI;
  chunk_type: 'step' | 'materials' | 'abstract';
  step_n?: number;
  text: string;
  embedding: number[];
  metadata_json: string;
};
