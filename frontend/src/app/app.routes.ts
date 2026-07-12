import { Routes } from '@angular/router';
import { Uploads } from './pages/uploads/uploads';
import { UploadNew } from './pages/upload-new/upload-new';

export const routes: Routes = [
  { path: '', redirectTo: 'uploads', pathMatch: 'full' },
  { path: 'uploads', component: UploadNew },
  { path: 'uploads/processing', component: Uploads },
];
