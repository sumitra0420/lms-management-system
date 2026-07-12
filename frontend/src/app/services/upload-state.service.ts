import { Injectable, signal } from '@angular/core';

export interface UploadedFile {
  name: string;
  size: number;
  uploadedAt: Date;
}

@Injectable({ providedIn: 'root' })
export class UploadStateService {
  uploadedFiles = signal<UploadedFile[]>([]);

  addFile(file: File) {
    this.uploadedFiles.update(files => [
      {
        name: file.name,
        size: file.size,
        uploadedAt: new Date(),
      },
      ...files,
    ]);
  }
}
