import { Component, OnInit, computed, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { UploadStateService } from '../../services/upload-state.service';
import { ApiService } from '../../services/api.service';

type StepStatus = 'completed' | 'processing' | 'pending';

interface PipelineStep {
  label: string;
  status: StepStatus;
}

interface DisplayFile {
  name: string;
  date: string;
  status: 'validation-failed' | 'validated' | 'uploaded' | 'extracting';
}

@Component({
  selector: 'app-uploads',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './uploads.html',
  styleUrl: './uploads.scss'
})
export class Uploads implements OnInit {
  searchQuery  = '';
  activeJobId  = 'LV-8829';
  currentPage  = 1;
  readonly pageSize = 10;
  errorMessage   = '';
  processingDone = false;

  pipelineSteps: PipelineStep[] = [
    { label: 'Pre-processing',  status: 'completed'  },
    { label: 'Dual Extraction', status: 'processing' },
    { label: 'Validation',      status: 'pending'    },
    { label: 'Upload',          status: 'pending'    },
  ];

  constructor(
    private router: Router,
    private uploadState: UploadStateService,
    private api: ApiService,
    private cdr: ChangeDetectorRef,
  ) {}

  stats = computed(() => ({
    totalFiles:  this.uploadState.uploadedFiles().length,
    successRate: '98.4%',
  }));

  get allFiles(): DisplayFile[] {
    return this.uploadState.uploadedFiles().map(f => ({
      name:   f.name,
      date:   'Just now',
      status: this.processingDone ? 'validated' as const : 'extracting' as const,
    }));
  }

  get filteredFiles(): DisplayFile[] {
    if (!this.searchQuery) return this.allFiles;
    return this.allFiles.filter(f =>
      f.name.toLowerCase().includes(this.searchQuery.toLowerCase())
    );
  }

  get totalResults() { return this.allFiles.length; }
  get totalPages()   { return Math.ceil(this.filteredFiles.length / this.pageSize); }
  get pages()        { return Array.from({ length: this.totalPages }, (_, i) => i + 1); }

  getStatusLabel(status: DisplayFile['status']): string {
    const map: Record<DisplayFile['status'], string> = {
      'validation-failed': 'Validation Failed',
      'validated':         'Validation Passed',
      'uploaded':          'Uploaded to Canvas',
      'extracting':        'Extracting',
    };
    return map[status];
  }

  ngOnInit() {
    // If result already exists, restore completed state without re-calling API
    const existingResult = this.uploadState.pipelineResult();
    if (existingResult) {
      console.log('[Uploads] ngOnInit — result already exists, restoring completed state');
      this.pipelineSteps = [
        { label: 'Pre-processing',  status: 'completed' },
        { label: 'Dual Extraction', status: 'completed' },
        { label: 'Validation',      status: 'completed' },
        { label: 'Upload',          status: 'pending'   },
      ];
      this.processingDone = true;
      return;
    }

    const file = this.uploadState.pendingFile();
    console.log('[Uploads] ngOnInit — pendingFile:', file?.name ?? 'none');
    if (!file) return;

    console.log('[Uploads] Calling API for:', file.name);
    this.api.processDocument(file).subscribe({
      next: (result) => {
        console.log('[Uploads] API success — questions:', result.questions.length, 'consistent:', result.consistent);
        this.pipelineSteps = [
          { label: 'Pre-processing',  status: 'completed' },
          { label: 'Dual Extraction', status: 'completed' },
          { label: 'Validation',      status: 'completed' },
          { label: 'Upload',          status: 'pending'   },
        ];
        this.processingDone = true;
        this.uploadState.setResult(result);
        console.log('[Uploads] processingDone set to true, running detectChanges');
        this.cdr.detectChanges();
      },
      error: (err) => {
        console.error('[Uploads] API error:', err);
        this.pipelineSteps[1].status = 'pending';
        this.errorMessage = err.error?.detail ?? 'Processing failed. Please try again.';
        this.cdr.detectChanges();
      }
    });
  }
}
