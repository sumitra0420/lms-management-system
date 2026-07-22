import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService, canonicalStatus, PipelineQuestion } from '../../services/api.service';

interface ConflictEntry {
  field: string;
  valueA: any;
  valueB: any;
}

const CONFLICT_FIELD_LABELS: Record<string, string> = {
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
  consistencyScore = 0;
  questions: PipelineQuestion[] = [];
  copied   = false;
  jobId: string | null = null;

  editingIndex: number | null = null;
  editDraft: PipelineQuestion | null = null;
  saving    = false;
  hasEdits  = false;
  viewMode: 'edited' | 'original' = 'edited';
  private _originalQuestions: PipelineQuestion[] = [];
  private _editedQuestions: PipelineQuestion[] = [];
  private _backendMeta: object | null = null;

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

  get flagCount() { return this.questions.filter(q => (q.consistency_score ?? 1) < 0.90).length; }

  answerBullets(answer: string): string[] {
    return answer.includes(' | ') ? answer.split(' | ') : [];
  }

  scoreClass(score: number | undefined): 'high' | 'mid' | 'low' {
    const s = score ?? 1;
    if (s >= 0.90) return 'high';
    if (s >= 0.80) return 'mid';
    return 'low';
  }
  get isEditing()  { return this.editingIndex !== null; }

  // ── Conflict resolution (Model A vs Model B) ─────────────────────────────

  conflictEntries(q: PipelineQuestion): ConflictEntry[] {
    if (!q.conflicts) return [];
    return Object.entries(q.conflicts).map(([field, v]) => ({
      field, valueA: v.value_a, valueB: v.value_b,
    }));
  }

  fieldLabel(field: string): string {
    return CONFLICT_FIELD_LABELS[field] ?? field;
  }

  displayConflictValue(field: string, value: any): string {
    if (field === 'choices' && Array.isArray(value)) {
      return value.map((c: any) => `${c.correct ? '✓ ' : ''}${c.text}`).join('  •  ') || '(none)';
    }
    if (value === null || value === undefined || value === '') return '(empty)';
    return String(value);
  }

  resolveConflict(index: number, field: string, pick: 'a' | 'b') {
    const q = this.questions[index];
    const conflict = q.conflicts?.[field];
    if (!conflict) return;

    const value = pick === 'a' ? conflict.value_a : conflict.value_b;
    const remainingConflicts = { ...q.conflicts };
    delete remainingConflicts[field];

    const updated: PipelineQuestion = { ...q, [field]: value, conflicts: remainingConflicts };
    this.questions = this.questions.map((qq, i) => i === index ? updated : qq);
    this.hasEdits         = true;
    this._editedQuestions = [...this.questions];
    this.persistEdits();
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
        this.consistencyScore = detail.consistency_score;
        this.hasEdits         = detail.has_edits;
        const mapQ = (q: PipelineQuestion) => ({
          ...q,
          flagReason: q.flagged
            ? `Consistency score: ${(q.consistency_score ?? 0).toFixed(2)}. Models disagreed.`
            : undefined,
        });
        this._editedQuestions   = detail.questions.map(mapQ);
        this._originalQuestions = detail.original_questions.map(mapQ);
        this.questions          = this._editedQuestions;

        this.mode = canonicalStatus(detail.status, detail.flag_count) === 'passed' ? 'pass' : 'fail';

        this._backendMeta = {
          filename:          detail.filename,
          consistent:        detail.consistent,
          consistency_score: detail.consistency_score,
          total_questions:   detail.questions.length,
          total_points:      detail.total_points,
          attempt:           detail.attempt,
        };
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

  // ── Metadata panel ─────────────────────────────────────────────────────────

  get metadataJson() {
    if (!this._backendMeta) return '';
    return JSON.stringify(this._backendMeta, null, 2);
  }

  copyRaw() {
    navigator.clipboard.writeText(this.metadataJson);
    this.copied = true;
    setTimeout(() => this.copied = false, 2000);
  }
}
