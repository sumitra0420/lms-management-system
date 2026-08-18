import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, from } from 'rxjs';
import { environment } from '../../environments/environment';

export interface VerificationIssue {
  field: string;
  problem: string;
}

export interface PipelineQuestion {
  id: string;
  type: string;
  text: string;
  choices: { text: string; correct: boolean }[];
  correct_answer: string;
  points: number | null;
  feedback: string;
  flagged?: boolean;
  consistency_score?: number;
  issues?: VerificationIssue[];
  schema_valid?: boolean;
  schema_errors?: string[];
  grounding_score?: number;
  hallucination_detected?: boolean;
  ungrounded_fields?: string[];
}

export interface PipelineResult {
  filename: string;
  consistent: boolean;
  consistency_score: number;
  attempt: number;
  total_points: number;
  questions: PipelineQuestion[];
  consistency_details: any;
}

export interface JobStatus {
  job_id: string;
  filename: string;
  status: 'pending' | 'processing' | 'passed' | 'flagged' | 'error';
  consistency_score: number | null;
  total_points: number | null;
  attempt: number;
  questions?: PipelineQuestion[];
  error_message?: string | null;
  flag_count?: number;
}

export interface PresignResponse {
  job_id: string;
  presigned_url: string;
  s3_key: string;
}

export interface JobDetail {
  job_id: string;
  filename: string;
  status: string;
  consistent: boolean;
  consistency_score: number;
  total_points: number;
  attempt: number;
  has_edits: boolean;
  file_type: string | null;
  questions: PipelineQuestion[];
  original_questions: PipelineQuestion[];
  error_message?: string | null;
  flag_count?: number;
  canvas_quiz_id?: number | null;
  canvas_url?: string | null;
  synced_at?: string | null;
}

export interface SyncFailure {
  question_id: string | null;
  error: string;
}

export interface SyncResult {
  job_id: string;
  canvas_quiz_id: number;
  canvas_url: string;
  total_questions: number;
  synced_questions: number;
  failures: SyncFailure[];
}

export interface RecentJob {
  job_id: string;
  filename: string;
  status: string;
  total_questions: number | null;
  file_type: string | null;
  flag_count: number;
  created_at: string;
  error_message?: string | null;
}

// ---------------------------------------------------------------------------
// Canonical job status — the single source of truth for what a job's state
// means, used by every page (dashboard, uploads, review, view-detail) so
// they can never disagree. A job that raw-passed but still has several
// low-confidence questions is NOT "ready" — it needs review, same as an
// outright flagged job.
// ---------------------------------------------------------------------------

export type CanonicalStatus = 'pending' | 'processing' | 'needs_review' | 'passed' | 'error';

const FLAG_COUNT_REVIEW_THRESHOLD = 2;

export function canonicalStatus(rawStatus: string, flagCount: number | null | undefined): CanonicalStatus {
  switch (rawStatus) {
    case 'pending':    return 'pending';
    case 'processing': return 'processing';
    case 'error':      return 'error';
    case 'flagged':    return 'needs_review';
    case 'passed':     return (flagCount ?? 0) > FLAG_COUNT_REVIEW_THRESHOLD ? 'needs_review' : 'passed';
    default:           return 'pending';
  }
}

export const CANONICAL_STATUS_LABEL: Record<CanonicalStatus, string> = {
  pending:      'Pending',
  processing:   'Processing',
  needs_review: 'Review Required',
  passed:       'Passed',
  error:        'Error',
};

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private baseUrl = environment.apiUrl;

  presign(filename: string): Observable<PresignResponse> {
    return this.http.post<PresignResponse>(`${this.baseUrl}/jobs/presign`, { filename });
  }

  uploadToS3(presignedUrl: string, file: File): Observable<Response> {
    return from(
      fetch(presignedUrl, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: file,
      }).then(res => {
        if (!res.ok) throw new Error(`S3 upload failed: ${res.status}`);
        return res;
      })
    );
  }

  startJob(jobId: string): Observable<{ job_id: string; status: string }> {
    return this.http.post<any>(`${this.baseUrl}/jobs/${jobId}/start`, {});
  }

  pollJobStatus(jobId: string): Observable<JobStatus> {
    return this.http.get<JobStatus>(`${this.baseUrl}/jobs/${jobId}/status`);
  }

  getRecentJobs(limit = 10): Observable<RecentJob[]> {
    return this.http.get<RecentJob[]>(`${this.baseUrl}/jobs/recent?limit=${limit}`);
  }

  getJobDetail(jobId: string): Observable<JobDetail> {
    return this.http.get<JobDetail>(`${this.baseUrl}/jobs/${jobId}/detail`);
  }

  saveEdits(jobId: string, questions: PipelineQuestion[]): Observable<{ status: string }> {
    return this.http.patch<{ status: string }>(`${this.baseUrl}/jobs/${jobId}/questions`, { questions });
  }

  syncToCanvas(jobId: string): Observable<SyncResult> {
    // No course_id sent yet — backend defaults to the Canvas test course
    // used to build this; becomes a real UI choice later.
    return this.http.post<SyncResult>(`${this.baseUrl}/jobs/${jobId}/sync`, {});
  }
}
