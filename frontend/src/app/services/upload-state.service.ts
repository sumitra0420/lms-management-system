import { Injectable, signal } from '@angular/core';
import { PipelineResult } from './api.service';

export interface UploadedFile {
  name: string;
  size: number;
  uploadedAt: Date;
}

export interface FileState {
  name: string;
  date: string;
  status: 'extracting' | 'validated' | 'validation-failed' | 'error';
  resultIndex: number | null;
  jobId: string | null;
  errorMessage?: string;
}

@Injectable({ providedIn: 'root' })
export class UploadStateService {
  uploadedFiles      = signal<UploadedFile[]>([]);
  pipelineResults    = signal<PipelineResult[]>([]);
  pendingFiles       = signal<File[]>([]);
  fileStates         = signal<FileState[]>([]);
  processingStarted  = signal<boolean>(false);

  addFiles(files: File[]) {
    this.pendingFiles.set(files);
    this.pipelineResults.set([]);
    this.processingStarted.set(false);
    this.fileStates.set(files.map(f => ({
      name: f.name, date: 'Just now', status: 'extracting' as const, resultIndex: null, jobId: null,
    })));
    this.uploadedFiles.update(existing => [
      ...files.map(f => ({ name: f.name, size: f.size, uploadedAt: new Date() })),
      ...existing,
    ]);
  }

  updateFileState(index: number, update: Partial<FileState>) {
    this.fileStates.update(states =>
      states.map((s, i) => i === index ? { ...s, ...update } : s)
    );
  }

  addResult(result: PipelineResult) {
    this.pipelineResults.update(results => [...results, result]);
  }

  clearPending() {
    this.pendingFiles.set([]);
  }
}
