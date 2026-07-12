import { Component, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { UploadStateService } from '../../services/upload-state.service';

interface PipelineStep {
  label: string;
  status: 'completed' | 'processing' | 'pending';
}

interface UploadFile {
  name: string;
  date: string;
  status: 'validation-failed' | 'uploaded' | 'extracting';
}

@Component({
  selector: 'app-uploads',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './uploads.html',
  styleUrl: './uploads.scss'
})
export class Uploads {
  searchQuery = '';
  activeJobId = 'LV-8829';
  currentPage = 1;
  readonly pageSize = 10;

  get totalPages() {
    return Math.ceil(this.filteredFiles.length / this.pageSize);
  }

  get pages() {
    return Array.from({ length: this.totalPages }, (_, i) => i + 1);
  }

  constructor(private uploadState: UploadStateService) {}

  stats = computed(() => ({
    totalFiles: this.uploadState.uploadedFiles().length,
    successRate: '98.4%'
  }));

  pipelineSteps: PipelineStep[] = [
    { label: 'Pre-processing', status: 'completed' },
    { label: 'Dual Extraction', status: 'processing' },
    { label: 'Validation', status: 'pending' },
    { label: 'Upload', status: 'pending' },
  ];

  get allFiles(): UploadFile[] {
    return this.uploadState.uploadedFiles().map(f => ({
      name: f.name,
      date: 'Just now',
      status: 'extracting' as const,
    }));
  }

  get filteredFiles() {
    const files = this.allFiles;
    if (!this.searchQuery) return files;
    return files.filter(f => f.name.toLowerCase().includes(this.searchQuery.toLowerCase()));
  }

  get totalResults() {
    return this.uploadState.uploadedFiles().length;
  }

  getStatusLabel(status: UploadFile['status']): string {
    const map: Record<UploadFile['status'], string> = {
      'validation-failed': 'Validation Failed',
      'uploaded': 'Uploaded to Canvas',
      'extracting': 'Extracting',
    };
    return map[status];
  }
}
