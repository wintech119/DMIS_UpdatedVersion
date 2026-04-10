from django.core.exceptions import ValidationError
from django.db import models


_APPEND_ONLY_ERROR = (
    "ItemIfrcSuggestLog is append-only; existing rows cannot be modified or deleted."
)


class ItemIfrcSuggestLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(_APPEND_ONLY_ERROR)

    def delete(self):
        raise ValidationError(_APPEND_ONLY_ERROR)

    def _raw_delete(self, using):
        raise ValidationError(_APPEND_ONLY_ERROR)


class ItemIfrcSuggestLogManager(models.Manager.from_queryset(ItemIfrcSuggestLogQuerySet)):
    pass


class ItemIfrcSuggestLog(models.Model):
    """
    Immutable audit record for IFRC code generation suggestions.

    Runtime protections enforce append-only behavior at the ORM layer.
    Add a database-level safeguard in a migration (trigger and/or DB
    permissions) for defense in depth.
    """

    objects = ItemIfrcSuggestLogManager()

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
        blank=False,
        default="none",
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
        get_latest_by = "created_at"
        verbose_name = "IFRC Suggest Log"
        verbose_name_plural = "IFRC Suggest Logs"

    def __str__(self) -> str:
        code = self.suggested_code or "none"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.item_name_input} -> {code}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(_APPEND_ONLY_ERROR)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_APPEND_ONLY_ERROR)


class ParishProximityMatrix(models.Model):
    proximity_id = models.BigAutoField(primary_key=True)
    source_parish_code = models.CharField(max_length=2)
    candidate_parish_code = models.CharField(max_length=2)
    proximity_rank = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "parish_proximity_matrix"
        indexes = [
            models.Index(fields=["source_parish_code", "proximity_rank"]),
            models.Index(fields=["candidate_parish_code"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_parish_code", "candidate_parish_code"],
                name="uq_parish_proximity_source_candidate",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.source_parish_code}->{self.candidate_parish_code}"
            f" (rank {self.proximity_rank})"
        )
