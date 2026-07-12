import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';

interface Choice {
  text: string;
  correct: boolean;
}

interface Question {
  number: number;
  type: 'Multiple Choice' | 'True/False';
  text: string;
  choices: Choice[];
  flagged?: boolean;
  flagReason?: string;
}

@Component({
  selector: 'app-view-detail',
  imports: [CommonModule],
  templateUrl: './view-detail.html',
  styleUrl: './view-detail.scss'
})
export class ViewDetail implements OnInit {
  mode: 'pass' | 'fail' = 'pass';

  filename = 'midterm_history_v2.docx';
  estimatedPoints = 50.0;
  course = 'HIST101_Fall_2024';
  flagCount = 2;

  pipelineSteps = [
    { label: 'Upload', status: 'completed' },
    { label: 'Validation', status: 'completed' },
    { label: 'Preview', status: 'active' },
    { label: 'Sync', status: 'pending' },
  ];

  questions: Question[] = [
    {
      number: 1,
      type: 'Multiple Choice',
      text: 'Which event is considered the primary catalyst for the start of World War I?',
      choices: [
        { text: 'The sinking of the Lusitania', correct: false },
        { text: 'The assassination of Archduke Franz Ferdinand', correct: true },
        { text: 'The signing of the Treaty of Versailles', correct: false },
        { text: 'The Russian Revolution', correct: false },
      ]
    },
    {
      number: 2,
      type: 'True/False',
      text: 'The Great Depression was primarily caused by the collapse of the London Stock Exchange in 1929.',
      choices: [
        { text: 'True', correct: false },
        { text: 'False', correct: true },
      ],
      flagged: true,
      flagReason: 'Confidence Score: 0.62. Ambiguous formatting detected in source document.'
    },
    {
      number: 3,
      type: 'Multiple Choice',
      text: 'Who was the leader of the Soviet Union during the majority of World War II?',
      choices: [
        { text: 'Joseph Stalin', correct: true },
        { text: 'Vladimir Lenin', correct: false },
        { text: 'Nikita Khrushchev', correct: false },
      ]
    },
  ];

  metadataPass = `{
  "quiz_id": "midterm_hist_101",
  "metadata": {
    "source_file": "midterm_history_v2.docx",
    "extraction_engine": "Vault-AI-v4.2",
    "confidence_score": 0.984
  },
  "structure": {
    "sections": [
      {
        "id": "sec_01",
        "title": "Modern History Basics",
        "questions": [
          { "id": "q1", "status": "valid" },
          { "id": "q2", "status": "valid" },
          { "id": "q3", "status": "valid" }
        ]
      }
    ]
  }
}`;

  metadataFail = `{
  "quiz_id": "midterm_hist_101",
  "metadata": {
    "source_file": "midterm_history_v2.docx",
    "extraction_engine": "Vault-AI-v4.2",
    "confidence_score": 0.62
  },
  "structure": {
    "sections": [
      {
        "id": "sec_01",
        "title": "Modern History Basics",
        "questions": [
          { "id": "q1", "status": "valid" },
          { "id": "q2", "status": "flagged" },
          { "id": "q3", "status": "valid" },
          { "id": "q4", "status": "flagged" }
        ]
      }
    ]
  }
}`;

  copied = false;

  constructor(private route: ActivatedRoute) {}

  ngOnInit() {
    this.mode = this.route.snapshot.data['mode'] ?? 'pass';
  }

  get metadata() {
    return this.mode === 'pass' ? this.metadataPass : this.metadataFail;
  }

  get flaggedQuestions() {
    return this.questions.filter(q => q.flagged);
  }

  copyRaw() {
    navigator.clipboard.writeText(this.metadata);
    this.copied = true;
    setTimeout(() => this.copied = false, 2000);
  }
}
