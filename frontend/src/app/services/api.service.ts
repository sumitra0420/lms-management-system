import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, from } from 'rxjs';

export interface PipelineQuestion {
  id: string;
  type: string;
  text: string;
  choices: { text: string; correct: boolean }[];
  correct_answer: string;
  points: number;
  feedback: string;
  flagged?: boolean;
  flagReason?: string;
  consistency_score?: number;
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
}

export interface RecentJob {
  job_id: string;
  filename: string;
  status: string;
  total_questions: number | null;
  file_type: string | null;
  flag_count: number;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private baseUrl = 'http://localhost:8000/api';

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
}
