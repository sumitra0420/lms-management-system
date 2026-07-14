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
}
