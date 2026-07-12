import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { UploadStateService } from '../../services/upload-state.service';

@Component({
  selector: 'app-upload-new',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './upload-new.html',
  styleUrl: './upload-new.scss'
})
export class UploadNew {
  isDragging = false;
  selectedFiles: File[] = [];

  constructor(
    private router: Router,
    private uploadState: UploadStateService
  ) {}

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
    const files = Array.from(event.dataTransfer?.files ?? []);
    this.selectedFiles = files;
  }

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    this.selectedFiles = Array.from(input.files ?? []);
  }

  uploadNow() {
    if (!this.selectedFiles.length) return;
    this.selectedFiles.forEach(f => this.uploadState.addFile(f));
    this.router.navigate(['/uploads/processing']);
  }
}
