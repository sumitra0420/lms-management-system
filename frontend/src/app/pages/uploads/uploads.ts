import { Component, OnInit, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { interval } from 'rxjs';
import { map, startWith, switchMap, takeWhile } from 'rxjs/operators';
import { ApiService, CANONICAL_STATUS_LABEL, CanonicalStatus, canonicalStatus, JobStatus } from '../../services/api.service';
import { FileState, UploadStateService } from '../../services/upload-state.service';

type StepStatus = 'completed' | 'processing' | 'pending';

interface PipelineStep {
  label: string;
  status: StepStatus;
}

@Component({
  selector: 'app-uploads',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './uploads.html',
  styleUrl: './uploads.scss'
})
export class Uploads implements OnInit {
  searchQuery  = '';
  currentPage  = 1;
  readonly pageSize = 10;

  pipelineSteps: PipelineStep[] = [
    { label: 'Pre-processing',  status: 'completed'  },
    { label: 'Extraction & Verification', status: 'processing' },
    { label: 'Validation',      status: 'pending'    },
    { label: 'Upload',          status: 'pending'    },
  ];

  constructor(
    private uploadState: UploadStateService,
    private api: ApiService,
  ) {}

  stats = computed(() => ({
    totalFiles: this.uploadState.uploadedFiles().length,
  }));

  get allFiles(): FileState[] { return this.uploadState.fileStates(); }

  get filteredFiles(): FileState[] {
    if (!this.searchQuery) return this.allFiles;
    return this.allFiles.filter(f =>
      f.name.toLowerCase().includes(this.searchQuery.toLowerCase())
    );
  }

  get totalResults() { return this.allFiles.length; }
  get totalPages()   { return Math.ceil(this.filteredFiles.length / this.pageSize); }
  get pages()        { return Array.from({ length: this.totalPages }, (_, i) => i + 1); }

  get allDone(): boolean {
    const states = this.uploadState.fileStates();
    return states.length > 0 && states.every(f => f.status !== 'pending' && f.status !== 'processing');
  }

  getStatusLabel(status: CanonicalStatus): string {
    return CANONICAL_STATUS_LABEL[status];
  }

  ngOnInit() {
    const pendingFiles = this.uploadState.pendingFiles();

    // Back navigation: already started, restore state
    if (this.uploadState.processingStarted()) {
      if (this.allDone) {
        this.pipelineSteps = [
          { label: 'Pre-processing',  status: 'completed' },
          { label: 'Extraction & Verification', status: 'completed' },
          { label: 'Validation',      status: 'completed' },
          { label: 'Upload',          status: 'pending'   },
        ];
      }
      return;
    }

    if (!pendingFiles.length) return;

    this.uploadState.processingStarted.set(true);

    pendingFiles.forEach((file, i) => {
      this.api.presign(file.name).pipe(
        // Upload file directly to S3
        switchMap(({ job_id, presigned_url }) =>
          this.api.uploadToS3(presigned_url, file).pipe(map(() => job_id))
        ),
        // Start background processing
        switchMap(job_id =>
          this.api.startJob(job_id).pipe(map(() => job_id))
        ),
        // Poll for status every 3s until terminal
        switchMap(job_id => {
          this.uploadState.updateFileState(i, { jobId: job_id });
          return interval(3000).pipe(
            startWith(0),
            switchMap(() => this.api.pollJobStatus(job_id)),
            takeWhile(s => s.status === 'pending' || s.status === 'processing', true),
          );
        }),
      ).subscribe({
        next: (status: JobStatus) => {
          const cs = canonicalStatus(status.status, status.flag_count);
          console.log(`[Upload] ${file.name}: ${cs}`);
          this.uploadState.updateFileState(i, {
            status:       cs,
            errorMessage: cs === 'error' ? (status.error_message ?? undefined) : undefined,
          });
          if (cs === 'passed' || cs === 'needs_review' || cs === 'error') {
            this.checkAllDone();
          }
        },
        error: (err) => {
          console.error(`[Uploads] Error processing ${file.name}:`, err);
          this.uploadState.updateFileState(i, { status: 'error', errorMessage: err?.error?.detail ?? err?.message });
          this.checkAllDone();
        }
      });
    });
  }

  private checkAllDone() {
    if (!this.allDone) return;
    this.pipelineSteps = [
      { label: 'Pre-processing',  status: 'completed' },
      { label: 'Extraction & Verification', status: 'completed' },
      { label: 'Validation',      status: 'completed' },
      { label: 'Upload',          status: 'pending'   },
    ];
    this.uploadState.clearPending();
  }

}

