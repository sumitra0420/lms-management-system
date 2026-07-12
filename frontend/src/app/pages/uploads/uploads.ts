import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

interface RecentFile {
  id: string;
  filename: string;
  status: 'ready' | 'validating' | 'uploaded';
  questions: string;
  lastModified: string;
}

@Component({
  selector: 'app-uploads',
  imports: [CommonModule, FormsModule],
  templateUrl: './uploads.html',
  styleUrl: './uploads.scss'
})
export class Uploads {
  isDragging = false;
  selectedFile: File | null = null;

  recentFiles: RecentFile[] = [
    { id: 'DOC-9421', filename: 'Intro_to_Psychology_Final.docx', status: 'ready', questions: '42 Items', lastModified: '2 hours ago' },
    { id: 'DOC-9418', filename: 'Global_History_W2_Quiz.pdf', status: 'validating', questions: '15 Items', lastModified: '5 hours ago' },
    { id: 'DOC-9405', filename: 'Advanced_Calculus_Unit1.docx', status: 'uploaded', questions: '--', lastModified: 'Yesterday' },
  ];

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
    const file = event.dataTransfer?.files[0];
    if (file) this.selectedFile = file;
  }

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    if (input.files?.[0]) this.selectedFile = input.files[0];
  }

  uploadNow() {
    if (!this.selectedFile) return;
    console.log('Uploading:', this.selectedFile.name);
  }
}
