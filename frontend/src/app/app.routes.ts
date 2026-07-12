import { Routes } from '@angular/router';
import { Uploads } from './pages/uploads/uploads';
import { UploadNew } from './pages/upload-new/upload-new';
import { ViewDetail } from './pages/view-detail/view-detail';

export const routes: Routes = [
  { path: '', redirectTo: 'uploads', pathMatch: 'full' },
  { path: 'uploads', component: UploadNew },
  { path: 'uploads/processing', component: Uploads },
  { path: 'uploads/detail', component: ViewDetail, data: { mode: 'pass' } },
  { path: 'uploads/detail/fail', component: ViewDetail, data: { mode: 'fail' } },
];
