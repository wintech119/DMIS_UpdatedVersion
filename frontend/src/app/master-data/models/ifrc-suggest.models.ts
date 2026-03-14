export type IFRCMatchType = 'generated' | 'generated_fallback' | 'fallback' | 'none';
export type IFRCSuggestionResolutionStatus = 'resolved' | 'ambiguous' | 'unresolved';

export interface IFRCSuggestionCandidate {
  ifrc_item_ref_id: number;
  ifrc_family_id: number;
  ifrc_code: string;
  reference_desc: string;
  group_code: string;
  group_label?: string;
  family_code: string;
  family_label: string;
  category_code: string;
  category_label: string;
  spec_segment?: string;
  size_weight?: string;
  form?: string;
  material?: string;
  rank: number;
  score: number;
  auto_highlight: boolean;
  match_reasons?: string[];
}

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
  sequence?: number | null;
  auto_fill_threshold: number;
  resolution_status?: IFRCSuggestionResolutionStatus;
  resolution_explanation?: string;
  ifrc_family_id?: number | null;
  resolved_ifrc_item_ref_id?: number | null;
  candidate_count?: number;
  auto_highlight_candidate_id?: number | null;
  direct_accept_allowed?: boolean;
  candidates?: IFRCSuggestionCandidate[];
}
