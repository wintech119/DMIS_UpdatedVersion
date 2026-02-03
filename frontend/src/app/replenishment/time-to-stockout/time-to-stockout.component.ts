import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SeverityLevel } from '../models/stock-status.model';

export interface TimeToStockoutData {
  hours: number | null;
  severity: SeverityLevel;
  hasBurnRate: boolean;
}

@Component({
  selector: 'app-time-to-stockout',
  standalone: true,
  imports: [
    CommonModule,
    MatIconModule,
    MatProgressBarModule,
    MatTooltipModule
  ],
  templateUrl: './time-to-stockout.component.html',
  styleUrl: './time-to-stockout.component.scss'
})
export class TimeToStockoutComponent {
  @Input() data!: TimeToStockoutData;

  getDisplayText(): string {
    if (!this.data.hasBurnRate || this.data.hours === null) {
      return '∞ - No current demand';
    }

    const hours = Math.floor(this.data.hours);
    const minutes = Math.floor((this.data.hours - hours) * 60);

    if (hours === 0 && minutes === 0) {
      return 'Stockout imminent!';
    }

    if (hours === 0) {
      return `${minutes}m until stockout`;
    }

    if (hours < 24) {
      return `${hours}h ${minutes}m until stockout`;
    }

    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;

    if (days === 1) {
      return `1d ${remainingHours}h until stockout`;
    }

    return `${days}d ${remainingHours}h until stockout`;
  }

  getSeverityClass(): string {
    return `severity-${this.data.severity.toLowerCase()}`;
  }

  shouldPulse(): boolean {
    return this.data.severity === 'CRITICAL' && this.data.hasBurnRate;
  }

  getProgressValue(): number {
    if (!this.data.hasBurnRate || this.data.hours === null) {
      return 100;
    }

    // Map time-to-stockout to progress bar (0-100%)
    // More time = fuller bar, less time = emptier bar
    const maxHours = 168; // 7 days
    const percentage = Math.min((this.data.hours / maxHours) * 100, 100);
    return percentage;
  }

  getProgressColorClass(): string {
    return `progress-${this.data.severity.toLowerCase()}`;
  }

  getActionIcon(): string {
    switch (this.data.severity) {
      case 'CRITICAL':
        return 'local_shipping'; // Truck for transfers
      case 'WARNING':
      case 'WATCH':
        return 'inventory_2'; // Box for donations
      case 'OK':
        return 'shopping_cart'; // Cart for procurement
      default:
        return 'help';
    }
  }

  getActionLabel(): string {
    switch (this.data.severity) {
      case 'CRITICAL':
        return 'Transfer (Horizon A)';
      case 'WARNING':
      case 'WATCH':
        return 'Donation (Horizon B)';
      case 'OK':
        return 'Procurement (Horizon C)';
      default:
        return 'Unknown';
    }
  }

  getTooltip(): string {
    if (!this.data.hasBurnRate) {
      return 'No active burn rate - demand is zero or unknown';
    }

    const actionLabel = this.getActionLabel();
    const severity = this.data.severity;

    let tooltip = `Status: ${severity}\n`;
    tooltip += `Recommended Action: ${actionLabel}\n\n`;

    switch (severity) {
      case 'CRITICAL':
        tooltip += 'URGENT: Use transfers (6-8 hour lead time)';
        break;
      case 'WARNING':
        tooltip += 'Use donations (2-7 day lead time)';
        break;
      case 'WATCH':
        tooltip += 'Monitor closely. Donations available if needed.';
        break;
      case 'OK':
        tooltip += 'Sufficient time for procurement (14+ day lead time)';
        break;
    }

    return tooltip;
  }

  getUrgencyBadge(): string | null {
    if (this.data.severity === 'CRITICAL' && this.data.hasBurnRate) {
      return 'URGENT';
    }
    return null;
  }
}
