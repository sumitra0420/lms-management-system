import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-sidebar',
  imports: [CommonModule, RouterLink, RouterLinkActive],
  templateUrl: './sidebar.html',
  styleUrl: './sidebar.scss'
})
export class Sidebar {
  navItems = [
    { label: 'Uploads',  route: '/uploads', icon: 'upload' },
    { label: 'Review',   route: '/review',  icon: 'review' },
    { label: 'API Settings', route: '/settings', icon: 'api' },
  ];
}
