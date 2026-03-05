from django.db import models


class ItemIfrcSuggestLog(models.Model):
    """
    Immutable audit record for IFRC code generation suggestions.
    """

    MATCH_TYPE_GENERATED = "generated"
    MATCH_TYPE_FALLBACK = "fallback"
    MATCH_TYPE_NONE = "none"

    MATCH_TYPE_CHOICES = [
        (MATCH_TYPE_GENERATED, "Generated (code constructed)"),
        (MATCH_TYPE_FALLBACK, "Fallback (rule-based, LLM unavailable)"),
        (MATCH_TYPE_NONE, "No code generated"),
    ]

    item_name_input = models.CharField(
        max_length=120,
        help_text="Raw user input used for IFRC suggestion.",
    )
    suggested_code = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Suggested IFRC code returned by the assistant.",
    )
    suggested_desc = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Suggested IFRC description returned by the assistant.",
    )
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Confidence score between 0.000 and 1.000.",
    )
    match_type = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=MATCH_TYPE_CHOICES,
    )
    construction_rationale = models.TextField(blank=True, default="")
    selected_code = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Item code the user actually saved.",
    )
    user_id = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Authenticated user id associated with the suggestion request.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp when the suggestion was created.",
    )

    class Meta:
        db_table = "item_ifrc_suggest_log"
        ordering = ["-created_at"]
        verbose_name = "IFRC Suggest Log"
        verbose_name_plural = "IFRC Suggest Logs"

    def __str__(self) -> str:
        code = self.suggested_code or "none"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.item_name_input} -> {code}"
