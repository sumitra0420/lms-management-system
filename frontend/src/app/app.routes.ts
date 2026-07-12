import { Routes } from '@angular/router';
import { Uploads } from './pages/uploads/uploads';

export const routes: Routes = [
  { path: '', redirectTo: 'uploads', pathMatch: 'full' },
  { path: 'uploads', component: Uploads },
];
