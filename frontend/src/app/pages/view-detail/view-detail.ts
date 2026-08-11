import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService, canonicalStatus, PipelineQuestion, SyncResult } from '../../services/api.service';

const FIELD_LABELS: Record<string, string> = {
  text:            'Question Text',
  correct_answer:  'Model Answer',
  choices:         'Choices',
  feedback:        'Feedback',
  type:            'Question Type',
  points:          'Points',
};

@Component({
  selector: 'app-view-detail',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './view-detail.html',
  styleUrl: './view-detail.scss'
})
export class ViewDetail implements OnInit {
  mode: 'pass' | 'fail' = 'pass';
  filename        = '';
  estimatedPoints = 0;
  questions: PipelineQuestion[] = [];
  jobId: string | null = null;

  editingIndex: number | null = null;
  editDraft: PipelineQuestion | null = null;
  saving    = false;
  hasEdits  = false;
  viewMode: 'edited' | 'original' = 'edited';
  private _originalQuestions: PipelineQuestion[] = [];
  private _editedQuestions: PipelineQuestion[] = [];

  syncing    = false;
  syncResult: SyncResult | null = null;
  syncError:  string | null = null;

  // From a previous session (loaded via GET job detail), distinct from
  // syncResult (a live sync just performed in THIS session, which also
  // has per-question failure detail this doesn't).
  previouslySyncedUrl: string | null = null;
  previouslySyncedAt:  string | null = null;

  pipelineSteps = [
    { label: 'Upload',     status: 'completed' },
    { label: 'Extraction', status: 'completed' },
    { label: 'Validation', status: 'completed' },
    { label: 'Sync',       status: 'pending'   },
  ];

  constructor(
    private route: ActivatedRoute,
    private api: ApiService,
    private cdr: ChangeDetectorRef,
  ) {}

  get flagCount() { return this.questions.filter(q => q.flagged).length; }

  answerBullets(answer: string): string[] {
    return answer.includes(' | ') ? answer.split(' | ') : [];
  }

  get isEditing()  { return this.editingIndex !== null; }

  groundedFieldLabel(field: string): string {
    const bulletMatch = field.match(/^correct_answer\[(\d+)\]$/);
    if (bulletMatch) return `Model Answer (bullet ${+bulletMatch[1] + 1})`;
    const choiceMatch = field.match(/^choices\[(\d+)\]\.text$/);
    if (choiceMatch) return `Choice ${+choiceMatch[1] + 1}`;
    return FIELD_LABELS[field] ?? field;
  }

  ngOnInit() {
    const jobId = this.route.snapshot.queryParamMap.get('jobId');
    if (jobId) {
      this.loadFromBackend(jobId);
    }
  }

  private loadFromBackend(jobId: string) {
    this.jobId = jobId;
    this.api.getJobDetail(jobId).subscribe({
      next: detail => {
        this.filename         = detail.filename;
        this.estimatedPoints  = detail.total_points;
        this.hasEdits         = detail.has_edits;
        this._editedQuestions   = detail.questions;
        this._originalQuestions = detail.original_questions;
        this.questions          = this._editedQuestions;

        this.mode = canonicalStatus(detail.status, detail.flag_count) === 'passed' ? 'pass' : 'fail';

        // Reflect a sync from a PREVIOUS session/page load, not just a
        // live click — without this, refreshing the page after a
        // successful sync loses all trace of it (canvas_quiz_id is saved
        // in the DB, but nothing here read it back).
        if (detail.canvas_quiz_id) {
          this.previouslySyncedUrl = detail.canvas_url ?? null;
          this.previouslySyncedAt  = detail.synced_at ?? null;
          this.pipelineSteps[3].status = 'completed';
        }

        this.cdr.detectChanges();
      },
    });
  }

  setViewMode(mode: 'edited' | 'original') {
    this.viewMode = mode;
    this.questions = mode === 'original' ? this._originalQuestions : this._editedQuestions;
  }

  // ── Editing ────────────────────────────────────────────────────────────────

  startEdit(index: number) {
    this.editingIndex = index;
    this.editDraft = JSON.parse(JSON.stringify(this.questions[index]));
  }

  cancelEdit() {
    this.editingIndex = null;
    this.editDraft    = null;
  }

  setCorrectChoice(choiceIndex: number) {
    if (!this.editDraft) return;
    this.editDraft.choices = this.editDraft.choices.map((c, i) => ({
      ...c, correct: i === choiceIndex,
    }));
    this.editDraft.correct_answer = this.editDraft.choices[choiceIndex].text;
  }

  updateChoiceText(choiceIndex: number, value: string) {
    if (!this.editDraft) return;
    this.editDraft.choices = this.editDraft.choices.map((c, i) =>
      i === choiceIndex ? { ...c, text: value } : c
    );
    if (this.editDraft.choices[choiceIndex].correct) {
      this.editDraft.correct_answer = value;
    }
  }

  saveEdit() {
    if (this.editingIndex === null || !this.editDraft) return;
    this.questions = this.questions.map((q, i) =>
      i === this.editingIndex ? { ...this.editDraft! } : q
    );
    this.editingIndex   = null;
    this.editDraft      = null;
    this.hasEdits       = true;
    this._editedQuestions = [...this.questions];
    this.persistEdits();
  }

  private persistEdits() {
    if (!this.jobId) return;
    this.saving = true;
    this.api.saveEdits(this.jobId, this.questions).subscribe({
      next: () => this.saving = false,
      error: () => this.saving = false,
    });
  }

  // ── Manual override ───────────────────────────────────────────────────────

  // Client-side only: a reviewer confirming "I've checked the flagged
  // questions, they're fine" unlocks Sync for this session. Per-question
  // flag markers (issues, tile grid) stay visible as a record of what was
  // reviewed — this doesn't clear them, only lifts the job-level gate.
  resolveAllFlags() {
    this.mode = 'pass';
  }

  // ── Canvas sync ───────────────────────────────────────────────────────────

  syncToCanvas() {
    if (!this.jobId || this.syncing) return;
    this.syncing    = true;
    this.syncResult = null;
    this.syncError  = null;
    this.api.syncToCanvas(this.jobId).subscribe({
      next: (result) => {
        this.syncing    = false;
        this.syncResult = result;
        this.pipelineSteps[3].status = result.failures.length === 0 ? 'completed' : 'error';
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.syncing   = false;
        this.syncError = err?.error?.detail ?? 'Sync failed — check the backend logs.';
      },
    });
  }

}
