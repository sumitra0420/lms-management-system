import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService, CANONICAL_STATUS_LABEL, CanonicalStatus, canonicalStatus, RecentJob } from '../../services/api.service';

@Component({
  selector: 'app-review',
  imports: [CommonModule, FormsModule],
  templateUrl: './review.html',
  styleUrl: './review.scss'
})
export class Review implements OnInit {
  jobs      = signal<RecentJob[]>([]);
  loading   = signal(true);
  searchQuery = '';

  constructor(private api: ApiService, private router: Router) {}

  ngOnInit() {
    this.api.getRecentJobs(50).subscribe({
      next: jobs => { this.jobs.set(jobs); this.loading.set(false); },
      error: ()  => this.loading.set(false),
    });
  }

  get filtered(): RecentJob[] {
    const q = this.searchQuery.toLowerCase();
    return q
      ? this.jobs().filter(j => j.filename.toLowerCase().includes(q))
      : this.jobs();
  }

  openReview(job: RecentJob) {
    this.router.navigate(['/uploads/detail'], { queryParams: { jobId: job.job_id } });
  }

  effectiveStatus(job: RecentJob): CanonicalStatus {
    return canonicalStatus(job.status, job.flag_count);
  }

  statusLabel(status: CanonicalStatus): string {
    return CANONICAL_STATUS_LABEL[status];
  }

  statusClass(status: CanonicalStatus): string {
    const map: Record<CanonicalStatus, string> = {
      passed:       'badge-passed',
      needs_review: 'badge-flagged',
      processing:   'badge-processing',
      pending:      'badge-pending',
      error:        'badge-error',
    };
    return map[status];
  }

  fileTypeLabel(type: string | null): string {
    const map: Record<string, string> = {
      quiz_short_answer:    'Short Answer',
      quiz_multiple_choice: 'Multiple Choice',
      assessor_guide:       'Assessor Guide',
      unknown:              '—',
    };
    return type ? (map[type] ?? type) : '—';
  }

  timeAgo(iso: string): string {
    if (!iso) return '—';
    const diff  = Date.now() - new Date(iso).getTime();
    const mins  = Math.floor(diff / 60000);
    const hours = Math.floor(mins / 60);
    const days  = Math.floor(hours / 24);
    if (days > 0)  return days === 1 ? 'Yesterday' : `${days} days ago`;
    if (hours > 0) return `${hours}h ago`;
    if (mins > 0)  return `${mins}m ago`;
    return 'Just now';
  }
}
