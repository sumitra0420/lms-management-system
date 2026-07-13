import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

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

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private baseUrl = 'http://localhost:8000/api';

  processDocument(file: File): Observable<PipelineResult> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<PipelineResult>(`${this.baseUrl}/documents/process`, formData);
  }
}
