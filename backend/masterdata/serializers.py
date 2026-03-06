from rest_framework import serializers


class IFRCSuggestionResponseSerializer(serializers.Serializer):
    suggestion_id = serializers.CharField(allow_null=True, required=False)
    ifrc_code = serializers.CharField(max_length=30, allow_null=True, required=False)
    ifrc_description = serializers.CharField(max_length=120, allow_null=True, required=False)
    confidence = serializers.FloatField(min_value=0.0, max_value=1.0)
    match_type = serializers.ChoiceField(choices=["generated", "fallback", "none"])
    construction_rationale = serializers.CharField(allow_blank=True, required=False)
    group_code = serializers.CharField(max_length=4, allow_blank=True, required=False)
    family_code = serializers.CharField(max_length=3, allow_blank=True, required=False)
    category_code = serializers.CharField(max_length=4, allow_blank=True, required=False)
    spec_segment = serializers.CharField(max_length=7, allow_blank=True, required=False)
    sequence = serializers.IntegerField(min_value=0, required=False)
    auto_fill_threshold = serializers.FloatField(min_value=0.0, max_value=1.0)
