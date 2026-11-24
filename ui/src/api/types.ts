export type FindingStatus = "contradiction" | "consistent" | "unresolved";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type SolverOutcome = "sat" | "unsat" | "unknown";

export interface DocumentUploadResponse {
  doc_id: string;
  filename: string;
  file_format: string;
  char_length: number;
  created_at: string;
}

export interface AuditCreateRequest {
  doc_ids: string[];
  module: "legal" | "financial";
  system: "full" | "no_debate";
  config_overrides?: Record<string, unknown>;
}

export interface AuditCreateResponse {
  audit_id: string;
  status: string;
  created_at: string;
}

export interface AuditStatusResponse {
  audit_id: string;
  doc_id: string;
  module: string;
  system_type: string;
  status: string;
  progress: number;
  pairs_total: number;
  pairs_completed: number;
  total_tokens: number;
  total_cost_usd: number;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
}

export interface FindingSummary {
  finding_id: string;
  pair_id: string;
  status: FindingStatus;
  severity: Severity;
  confidence: number;
  title: string;
  spans_verified: boolean;
  judge_overruled: boolean;
}

export interface FindingDetail {
  finding_id: string;
  audit_id: string;
  pair_id: string;
  status: FindingStatus;
  severity: Severity;
  confidence: number;
  title: string;
  description: string;
  claim_a_text: string;
  claim_a_start: number;
  claim_a_end: number;
  claim_b_text: string;
  claim_b_start: number;
  claim_b_end: number;
  spans_verified: boolean;
  judge_overruled: boolean;
  overrule_reason?: string;
  unresolved_reason?: string;
  solver_outcome?: SolverOutcome;
  solver_backend?: string;
  solver_proof_trace?: string;
  unsat_core?: string[];
}

export interface DebateMessage {
  message_id: string;
  round_number: number;
  sender: string;
  argument_text: string;
  cited_claim_ids: string[];
  cost_usd: number;
}

export interface DebateTranscript {
  thread_id: string;
  pair_id: string;
  rounds_used: number;
  status: string;
  final_verdict?: string;
  messages: DebateMessage[];
}

export interface ExactTextResponse {
  doc_id: string;
  start: number;
  end: number;
  text: string;
}

export interface HumanReviewRequest {
  decision: "confirm" | "dismiss" | "needs_more_info";
  notes?: string;
}

export interface HumanReviewResponse {
  review_id: string;
  finding_id: string;
  decision: string;
  notes?: string;
  reviewed_at: string;
  message: string;
}
