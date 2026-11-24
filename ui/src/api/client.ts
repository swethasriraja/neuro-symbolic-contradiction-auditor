import {
  AuditCreateRequest,
  AuditCreateResponse,
  AuditStatusResponse,
  DebateTranscript,
  DocumentUploadResponse,
  ExactTextResponse,
  FindingDetail,
  FindingSummary,
  HumanReviewRequest,
  HumanReviewResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_KEY = import.meta.env.VITE_API_KEY || "test-api-key";

const headers = {
  "X-API-Key": API_KEY,
};

export const api = {
  async health(): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error("Healthcheck failed");
    return res.json();
  },

  async uploadDocument(file: File): Promise<DocumentUploadResponse> {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${API_BASE}/documents`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Upload failed");
    }
    return res.json();
  },

  async createAudit(req: AuditCreateRequest): Promise<AuditCreateResponse> {
    const res = await fetch(`${API_BASE}/audits`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error("Failed to start audit");
    return res.json();
  },

  async getAuditStatus(auditId: string): Promise<AuditStatusResponse> {
    const res = await fetch(`${API_BASE}/audits/${auditId}`, { headers });
    if (!res.ok) throw new Error("Failed to get audit status");
    return res.json();
  },

  async getFindings(
    auditId: string,
    filters?: { verdict?: string; severity?: string; min_confidence?: number }
  ): Promise<FindingSummary[]> {
    const params = new URLSearchParams();
    if (filters?.verdict) params.append("verdict", filters.verdict);
    if (filters?.severity) params.append("severity", filters.severity);
    if (filters?.min_confidence !== undefined)
      params.append("min_confidence", filters.min_confidence.toString());

    const res = await fetch(`${API_BASE}/audits/${auditId}/findings?${params.toString()}`, { headers });
    if (!res.ok) throw new Error("Failed to get findings");
    return res.json();
  },

  async getFindingDetail(findingId: string): Promise<FindingDetail> {
    const res = await fetch(`${API_BASE}/findings/${findingId}`, { headers });
    if (!res.ok) throw new Error("Failed to get finding detail");
    return res.json();
  },

  async getDebateTranscript(findingId: string): Promise<DebateTranscript> {
    const res = await fetch(`${API_BASE}/findings/${findingId}/transcript`, { headers });
    if (!res.ok) throw new Error("Failed to get transcript");
    return res.json();
  },

  async getExactText(docId: string, start: number, end: number): Promise<ExactTextResponse> {
    const res = await fetch(`${API_BASE}/documents/${docId}/text?start=${start}&end=${end}`, { headers });
    if (!res.ok) throw new Error("Failed to get exact text");
    return res.json();
  },

  async submitReview(findingId: string, req: HumanReviewRequest): Promise<HumanReviewResponse> {
    const res = await fetch(`${API_BASE}/findings/${findingId}/review`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error("Failed to submit review");
    return res.json();
  },

  getReportUrl(auditId: string, format: "json" | "html" | "md"): string {
    return `${API_BASE}/audits/${auditId}/report?format=${format}`;
  },
};
