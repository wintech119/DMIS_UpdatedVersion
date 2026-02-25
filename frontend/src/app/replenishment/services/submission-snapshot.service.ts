import { Injectable } from '@angular/core';

import { NeedsListSummary } from '../models/needs-list.model';

const STORAGE_KEY = 'dmis_submission_snapshots';
const PRUNE_AGE_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

/** Statuses that represent an approver action worth highlighting. */
const APPROVER_ACTION_STATUSES: ReadonlySet<string> = new Set([
  'APPROVED',
  'REJECTED',
  'RETURNED'
]);

interface SubmissionSnapshot {
  status: string;
  last_updated_at: string | null;
  saved_at: number; // epoch ms, used for pruning
}

type SnapshotMap = Record<string, SubmissionSnapshot>;

@Injectable({ providedIn: 'root' })
export class SubmissionSnapshotService {
  /**
   * Returns the set of submission IDs whose status changed since the last
   * recorded snapshot.  Only flags transitions TO approver-action statuses
   * (APPROVED, REJECTED, RETURNED).
   */
  detectChanges(submissions: NeedsListSummary[]): Set<string> {
    const stored = this.getSnapshots();
    const changed = new Set<string>();

    for (const sub of submissions) {
      const prev = stored[sub.id];
      if (!prev) {
        // First time seeing this submission — don't flag
        continue;
      }

      if (!APPROVER_ACTION_STATUSES.has(sub.status)) {
        continue;
      }

      const statusChanged = prev.status !== sub.status;
      const updatedAtChanged =
        sub.last_updated_at !== null &&
        prev.last_updated_at !== null &&
        sub.last_updated_at !== prev.last_updated_at;

      if (statusChanged || updatedAtChanged) {
        changed.add(sub.id);
      }
    }

    return changed;
  }

  /**
   * Persists the current status + last_updated_at for every submission so that
   * the next page load can detect changes.  Also prunes entries older than 30 days.
   */
  markAsSeen(submissions: NeedsListSummary[]): void {
    const stored = this.getSnapshots();
    const now = Date.now();

    for (const sub of submissions) {
      stored[sub.id] = {
        status: sub.status,
        last_updated_at: sub.last_updated_at,
        saved_at: now
      };
    }

    // Prune stale entries
    const cutoff = now - PRUNE_AGE_MS;
    for (const key of Object.keys(stored)) {
      if (stored[key].saved_at < cutoff) {
        delete stored[key];
      }
    }

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    } catch {
      // Storage full or unavailable — silently ignore
    }
  }

  private getSnapshots(): SnapshotMap {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        return JSON.parse(raw) as SnapshotMap;
      }
    } catch {
      // Corrupt data — start fresh
    }
    return {};
  }
}
