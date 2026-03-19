import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class MasterEditGateService {
  private readonly skipGovernedEditWarning = signal(false);

  markDetailEditGatePassed(): void {
    this.skipGovernedEditWarning.set(true);
  }

  consumeGovernedEditWarningSkip(): boolean {
    const shouldSkip = this.skipGovernedEditWarning();
    this.skipGovernedEditWarning.set(false);
    return shouldSkip;
  }
}
