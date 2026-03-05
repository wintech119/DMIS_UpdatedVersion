export type IFRCMatchType = 'generated' | 'fallback' | 'none';

export interface IFRCSuggestion {
  suggestion_id: string | null;
  ifrc_code: string | null;
  ifrc_description: string | null;
  confidence: number;
  match_type: IFRCMatchType;
  construction_rationale: string;
  group_code: string;      // 1 letter
  family_code: string;     // 3 letters
  category_code: string;   // 4 letters
  spec_segment: string;    // 0-5 chars
  sequence: number;
  auto_fill_threshold: number;
}
