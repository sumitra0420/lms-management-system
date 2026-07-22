import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiService, CanonicalStatus, canonicalStatus, RecentJob } from '../../services/api.service';
import { UploadStateService } from '../../services/upload-state.service';

@Component({
  selector: 'app-upload-new',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './upload-new.html',
  styleUrl: './upload-new.scss'
})
export class UploadNew implements OnInit {
  isDragging    = false;
  selectedFiles: File[] = [];
  maxFileError  = '';
  recentJobs    = signal<RecentJob[]>([]);
  readonly MAX_FILES = 3;

  constructor(
    private router: Router,
    private uploadState: UploadStateService,
    private api: ApiService,
  ) {}

  ngOnInit() {
    this.api.getRecentJobs(5).subscribe({
      next: jobs => this.recentJobs.set(jobs),
      error: () => {},
    });
  }

  get totalFiles() {
    return this.uploadState.uploadedFiles().length;
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
    this.isDragging = true;
  }

  onDragLeave() {
    this.isDragging = false;
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    this.isDragging = false;
    this.setFiles(Array.from(event.dataTransfer?.files ?? []));
  }

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    this.setFiles(Array.from(input.files ?? []));
  }

  private setFiles(files: File[]) {
    if (files.length > this.MAX_FILES) {
      this.maxFileError = `Maximum ${this.MAX_FILES} files. Only the first ${this.MAX_FILES} will be processed.`;
      this.selectedFiles = files.slice(0, this.MAX_FILES);
    } else {
      this.maxFileError = '';
      this.selectedFiles = files;
    }
  }

  uploadNow() {
    if (!this.selectedFiles.length) return;
    this.uploadState.addFiles(this.selectedFiles);
    this.router.navigate(['/uploads/processing']);
  }

  shortId(jobId: string): string {
    return jobId.slice(0, 8).toUpperCase();
  }

  statusLabel(job: RecentJob): string {
    const map: Record<CanonicalStatus, string> = {
      passed:       'READY',
      needs_review: 'REVIEW REQUIRED',
      processing:   'VALIDATING',
      pending:      'PENDING',
      error:        'ERROR',
    };
    return map[canonicalStatus(job.status, job.flag_count)];
  }

  statusClass(job: RecentJob): string {
    const map: Record<CanonicalStatus, string> = {
      passed:       'badge-ready',
      needs_review: 'badge-flagged',
      processing:   'badge-validating',
      pending:      'badge-uploaded',
      error:        'badge-error',
    };
    return map[canonicalStatus(job.status, job.flag_count)];
  }

  timeAgo(iso: string): string {
    const diff = Date.now() - new Date(iso).getTime();
    const mins  = Math.floor(diff / 60000);
    const hours = Math.floor(mins / 60);
    const days  = Math.floor(hours / 24);
    if (days > 0)  return days === 1 ? 'Yesterday' : `${days} days ago`;
    if (hours > 0) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    if (mins > 0)  return `${mins} min${mins > 1 ? 's' : ''} ago`;
    return 'Just now';
  }
}
