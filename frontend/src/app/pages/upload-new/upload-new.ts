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
  isDragging    = false;
  selectedFiles: File[] = [];
  maxFileError  = '';
  readonly MAX_FILES = 3;

  constructor(
    private router: Router,
    private uploadState: UploadStateService,
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
}
