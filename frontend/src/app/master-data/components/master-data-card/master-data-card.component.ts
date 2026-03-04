import {
  ChangeDetectionStrategy,
  Component,
  input,
  output,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'dmis-master-data-card',
  standalone: true,
  imports: [MatIconModule],
  templateUrl: './master-data-card.component.html',
  styleUrl: './master-data-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterDataCardComponent {
  title = input.required<string>();
  description = input<string>('');
  editable = input<boolean>(true);
  canCreate = input<boolean>(true);

  viewClicked = output<void>();
  createClicked = output<void>();
}
