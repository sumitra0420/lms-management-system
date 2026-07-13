import { Injectable, signal } from '@angular/core';
import { PipelineResult } from './api.service';

export interface UploadedFile {
  name: string;
  size: number;
  uploadedAt: Date;
}

@Injectable({ providedIn: 'root' })
export class UploadStateService {
  uploadedFiles  = signal<UploadedFile[]>([]);
  pipelineResult = signal<PipelineResult | null>(null);
  pendingFile    = signal<File | null>(null);

  addFile(file: File) {
    this.pendingFile.set(file);
    this.uploadedFiles.update(files => [
      { name: file.name, size: file.size, uploadedAt: new Date() },
      ...files,
    ]);
  }

  setResult(result: PipelineResult) {
    this.pipelineResult.set(result);
    this.pendingFile.set(null);
  }
}
