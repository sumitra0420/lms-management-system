import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService, PipelineQuestion } from '../../services/api.service';

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

        const questionFlagCount = this._editedQuestions.filter(q => (q.consistency_score ?? 1) < 0.90).length;
        this.mode = (detail.consistent && questionFlagCount <= 2) ? 'pass' : 'fail';

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
