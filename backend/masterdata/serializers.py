from rest_framework import serializers


class IFRCSuggestionCandidateSerializer(serializers.Serializer):
    ifrc_item_ref_id = serializers.IntegerField(min_value=1)
    ifrc_family_id = serializers.IntegerField(min_value=1)
    ifrc_code = serializers.CharField(max_length=30)
    reference_desc = serializers.CharField(max_length=255)
    group_code = serializers.CharField(max_length=4)
    group_label = serializers.CharField(max_length=120, allow_blank=True, required=False)
    family_code = serializers.CharField(max_length=6)
    family_label = serializers.CharField(max_length=160)
    category_code = serializers.CharField(max_length=6)
    category_label = serializers.CharField(max_length=160)
    spec_segment = serializers.CharField(max_length=7, allow_blank=True, required=False)
    rank = serializers.IntegerField(min_value=1)
    score = serializers.FloatField(min_value=0.0, max_value=1.0)
    auto_highlight = serializers.BooleanField()
    match_reasons = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
    )


class IFRCSuggestionResponseSerializer(serializers.Serializer):
    suggestion_id = serializers.CharField(allow_null=True, required=False)
    ifrc_code = serializers.CharField(max_length=30, allow_null=True, required=False)
    ifrc_description = serializers.CharField(max_length=120, allow_null=True, required=False)
    confidence = serializers.FloatField(min_value=0.0, max_value=1.0)
    match_type = serializers.ChoiceField(choices=["generated", "generated_fallback", "fallback", "none"])
    construction_rationale = serializers.CharField(allow_blank=True, required=False)
    group_code = serializers.CharField(max_length=4, allow_blank=True, required=False)
    family_code = serializers.CharField(max_length=3, allow_blank=True, required=False)
    category_code = serializers.CharField(max_length=4, allow_blank=True, required=False)
    spec_segment = serializers.CharField(max_length=7, allow_blank=True, required=False)
    sequence = serializers.IntegerField(min_value=0, required=False)
    auto_fill_threshold = serializers.FloatField(min_value=0.0, max_value=1.0)
    resolution_status = serializers.ChoiceField(choices=["resolved", "ambiguous", "unresolved"])
    resolution_explanation = serializers.CharField(allow_blank=True, required=False)
    ifrc_family_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    resolved_ifrc_item_ref_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    candidate_count = serializers.IntegerField(min_value=0)
    auto_highlight_candidate_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    direct_accept_allowed = serializers.BooleanField(required=False)
    candidates = IFRCSuggestionCandidateSerializer(many=True, required=False)
