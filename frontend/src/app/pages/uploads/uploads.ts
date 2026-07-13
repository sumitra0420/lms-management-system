import { Component, OnInit, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { UploadStateService, FileState } from '../../services/upload-state.service';
import { ApiService } from '../../services/api.service';

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
  activeJobId  = 'LV-8829';
  currentPage  = 1;
  readonly pageSize = 10;

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
  ) {}

  stats = computed(() => ({
    totalFiles: this.uploadState.uploadedFiles().length,
  }));

  get allFiles(): FileState[] {
    return this.uploadState.fileStates();
  }

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
    return states.length > 0 && states.every(f => f.status !== 'extracting');
  }

  getStatusLabel(status: FileState['status']): string {
    const map: Record<FileState['status'], string> = {
      'validation-failed': 'Validation Failed',
      'validated':         'Validation Passed',
      'error':             'Error',
      'extracting':        'Extracting',
    };
    return map[status];
  }

  ngOnInit() {
    const pendingFiles = this.uploadState.pendingFiles();

    // Back navigation (or mid-flight return): processing already started, don't restart
    if (this.uploadState.processingStarted()) {
      if (this.allDone) {
        this.pipelineSteps = [
          { label: 'Pre-processing',  status: 'completed' },
          { label: 'Dual Extraction', status: 'completed' },
          { label: 'Validation',      status: 'completed' },
          { label: 'Upload',          status: 'pending'   },
        ];
      }
      return;
    }

    if (!pendingFiles.length) return;

    // Fresh upload: mark started and process all files concurrently
    this.uploadState.processingStarted.set(true);
    pendingFiles.forEach((file, i) => {
      this.api.processDocument(file).subscribe({
        next: (result) => {
          const resultIndex = this.uploadState.pipelineResults().length;
          this.uploadState.addResult(result);
          this.uploadState.updateFileState(i, {
            status: result.consistent ? 'validated' : 'validation-failed',
            resultIndex,
          });
          this.checkAllDone();
        },
        error: (err) => {
          console.error(`[Uploads] Error processing ${file.name}:`, err);
          this.uploadState.updateFileState(i, { status: 'error' });
          this.checkAllDone();
        }
      });
    });
  }

  private checkAllDone() {
    if (!this.allDone) return;
    this.pipelineSteps = [
      { label: 'Pre-processing',  status: 'completed' },
      { label: 'Dual Extraction', status: 'completed' },
      { label: 'Validation',      status: 'completed' },
      { label: 'Upload',          status: 'pending'   },
    ];
    this.uploadState.clearPending();
  }
}
