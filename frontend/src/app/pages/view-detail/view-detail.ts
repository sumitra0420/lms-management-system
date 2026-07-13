import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { UploadStateService } from '../../services/upload-state.service';
import { PipelineQuestion } from '../../services/api.service';

@Component({
  selector: 'app-view-detail',
  imports: [CommonModule, RouterLink],
  templateUrl: './view-detail.html',
  styleUrl: './view-detail.scss'
})
export class ViewDetail implements OnInit {
  mode: 'pass' | 'fail' = 'pass';

  filename = '';
  estimatedPoints = 0;
  consistencyScore = 0;
  questions: PipelineQuestion[] = [];
  copied = false;

  pipelineSteps = [
    { label: 'Upload',      status: 'completed' },
    { label: 'Extraction',  status: 'completed' },
    { label: 'Validation',  status: 'completed' },
    { label: 'Sync',        status: 'pending' },
  ];

  constructor(
    private route: ActivatedRoute,
    private uploadState: UploadStateService,
  ) {}

  get flagCount() {
    return this.questions.filter(q => q.flagged).length;
  }

  ngOnInit() {
    const result = this.uploadState.pipelineResult();
    if (result) {
      this.filename         = result.filename;
      this.estimatedPoints  = result.total_points;
      this.consistencyScore = result.consistency_score;
      this.mode             = result.consistent ? 'pass' : 'fail';

      const perQuestion: any[] = result.consistency_details?.per_question ?? [];
      this.questions = result.questions.map((q, i) => {
        const qScore = perQuestion[i]?.score ?? 1;
        return {
          ...q,
          flagged:   qScore < 0.75,
          flagReason: qScore < 0.75
            ? `Consistency score: ${qScore.toFixed(2)}. Models disagreed on this question.`
            : undefined,
        };
      });
    } else {
      this.mode = this.route.snapshot.data['mode'] ?? 'pass';
    }
  }

  get metadataJson() {
    const result = this.uploadState.pipelineResult();
    if (!result) return '';
    return JSON.stringify({
      filename:          result.filename,
      consistent:        result.consistent,
      consistency_score: result.consistency_score,
      total_questions:   result.questions.length,
      total_points:      result.total_points,
      attempt:           result.attempt,
    }, null, 2);
  }

  copyRaw() {
    navigator.clipboard.writeText(this.metadataJson);
    this.copied = true;
    setTimeout(() => this.copied = false, 2000);
  }
}
