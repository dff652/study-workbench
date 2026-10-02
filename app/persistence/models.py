import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Household(models.Model):
    id = models.CharField(max_length=160, primary_key=True)
    schema_version = models.CharField(max_length=80, default="study-workbench.core.v0.1")

    class Meta:
        db_table = "swb_household"


class HouseholdMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        REVIEWER = "reviewer", "Reviewer"
        VIEWER = "viewer", "Viewer"

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="study_workbench_memberships")
    role = models.CharField(max_length=16, choices=Role.choices)

    class Meta:
        db_table = "swb_householdmember"
        constraints = [
            models.UniqueConstraint(fields=("household", "user"), name="swb_member_house_user_uniq"),
            models.CheckConstraint(condition=models.Q(role__in=("owner", "reviewer", "viewer")), name="swb_member_role_valid"),
        ]


class ImageRecord(models.Model):
    id = models.BigAutoField(primary_key=True)
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="images")
    stable_id = models.CharField(max_length=160)
    sha256 = models.CharField(max_length=64)
    payload = models.JSONField()

    class Meta:
        db_table = "swb_imagerecord"
        constraints = [
            models.UniqueConstraint(fields=("household", "stable_id"), name="swb_image_house_stable_uniq"),
            models.UniqueConstraint(fields=("household", "sha256"), name="swb_image_house_sha_uniq"),
            models.CheckConstraint(condition=models.Q(sha256__regex=r"^[0-9a-f]{64}$"), name="swb_image_sha_valid"),
        ]


class EntityRecord(models.Model):
    class EntityKind(models.TextChoices):
        KNOWLEDGE = "knowledge", "Knowledge"
        METHOD = "method", "Method"
        QUESTION_TYPE = "question_type", "Question type"
        QUESTION = "question", "Question"
        OBSERVATION = "observation", "Observation"
        ATTEMPT = "attempt", "Attempt"
        ASSESSMENT = "assessment", "Assessment"
        ERRATUM = "erratum", "Erratum"
        REGION = "region", "Region"
        KNOWLEDGE_QUESTION = "knowledge_question", "Knowledge question link"
        METHOD_QUESTION = "method_question", "Method question link"
        QUESTION_TYPE_LINK = "question_type_link", "Question type link"
        LEARNER = "learner", "Learner"

    id = models.BigAutoField(primary_key=True)
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="entities")
    kind = models.CharField(max_length=32, choices=EntityKind.choices)
    stable_id = models.CharField(max_length=160)
    identity = models.JSONField()
    head_revision = models.ForeignKey(
        "RevisionRecord", null=True, blank=True, on_delete=models.PROTECT, related_name="head_for_entities"
    )
    published_revision = models.ForeignKey(
        "RevisionRecord", null=True, blank=True, on_delete=models.PROTECT, related_name="published_for_entities"
    )

    class Meta:
        db_table = "swb_entityrecord"
        constraints = [
            models.UniqueConstraint(fields=("household", "kind", "stable_id"), name="swb_entity_identity_uniq"),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=(
                        "knowledge", "method", "question_type", "question", "observation", "attempt",
                        "assessment", "erratum", "region", "knowledge_question", "method_question",
                        "question_type_link", "learner",
                    )
                ),
                name="swb_entity_kind_valid",
            ),
        ]


class RevisionRecord(models.Model):
    revision_id = models.CharField(max_length=160, primary_key=True)
    entity = models.ForeignKey(EntityRecord, on_delete=models.PROTECT, related_name="revisions")
    revision_no = models.PositiveIntegerField()
    previous = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="next_revisions"
    )
    content_hash = models.CharField(max_length=64)
    payload = models.JSONField()
    dependency_heads = models.JSONField(default=list)
    original_image = models.ForeignKey(
        ImageRecord, null=True, blank=True, on_delete=models.PROTECT, related_name="region_revisions"
    )

    class Meta:
        db_table = "swb_revisionrecord"
        constraints = [
            models.UniqueConstraint(fields=("entity", "revision_no"), name="swb_rev_entity_number_uniq"),
            models.CheckConstraint(condition=models.Q(revision_no__gt=0), name="swb_rev_number_positive"),
            models.CheckConstraint(condition=models.Q(content_hash__regex=r"^[0-9a-f]{64}$"), name="swb_rev_hash_valid"),
        ]


class RevisionDependency(models.Model):
    class Role(models.TextChoices):
        PARENT_QUESTION = "parent_question", "Parent question"
        PARENT_METHOD = "parent_method", "Parent method"
        QUESTION_ERRATUM = "question_erratum", "Question erratum"
        ATTEMPT_QUESTION = "attempt_question", "Attempt question"
        ATTEMPT_OBSERVATION = "attempt_observation", "Attempt observation"
        ASSESSMENT_ATTEMPT = "assessment_attempt", "Assessment attempt"
        ASSESSMENT_QUESTION = "assessment_question", "Assessment question"
        ASSESSMENT_ERRATUM = "assessment_erratum", "Assessment erratum"
        ERRATUM_TARGET = "erratum_target", "Erratum target"
        LINK_QUESTION = "link_question", "Link question"
        LINK_KNOWLEDGE = "link_knowledge", "Link knowledge"
        LINK_METHOD = "link_method", "Link method"
        LINK_QUESTION_TYPE = "link_question_type", "Link question type"

    id = models.BigAutoField(primary_key=True)
    source = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT, related_name="outgoing_dependencies")
    target = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT, related_name="incoming_dependencies")
    role = models.CharField(max_length=32, choices=Role.choices)
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "swb_revisiondependency"
        constraints = [
            models.UniqueConstraint(fields=("source", "role", "position"), name="swb_dep_source_role_pos_uniq"),
            models.CheckConstraint(
                condition=models.Q(
                    role__in=(
                        "parent_question", "parent_method", "question_erratum", "attempt_question",
                        "attempt_observation", "assessment_attempt", "assessment_question", "assessment_erratum",
                        "erratum_target", "link_question", "link_knowledge", "link_method", "link_question_type",
                    )
                ),
                name="swb_dep_role_valid",
            ),
            models.CheckConstraint(condition=models.Q(position__gte=0), name="swb_dep_position_nonneg"),
        ]


class EvidenceRecord(models.Model):
    class Slot(models.TextChoices):
        SOURCE = "source", "Source"
        ANSWER = "answer", "Answer"
        METHOD = "method", "Method"
        PROCESS = "process", "Process"
        CALCULATION = "calculation", "Calculation"
        NOTATION = "notation", "Notation"

    class Purpose(models.TextChoices):
        QUESTION = "question", "Question"
        HANDWRITING = "handwriting", "Handwriting"
        FORMULA = "formula", "Formula"
        DIAGRAM = "diagram", "Diagram"
        DEFINITION = "definition", "Definition"
        OTHER = "other", "Other"

    class Granularity(models.TextChoices):
        WHOLE_IMAGE = "whole_image", "Whole image"
        REGION = "region", "Region"

    id = models.BigAutoField(primary_key=True)
    source = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT, related_name="evidence")
    image = models.ForeignKey(ImageRecord, on_delete=models.PROTECT, related_name="evidence")
    region = models.ForeignKey(
        RevisionRecord, null=True, blank=True, on_delete=models.PROTECT, related_name="evidence_regions"
    )
    slot = models.CharField(max_length=16, choices=Slot.choices)
    sequence = models.PositiveIntegerField()
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    granularity = models.CharField(max_length=16, choices=Granularity.choices)
    region_missing = models.BooleanField()
    gaps = models.JSONField(default=list)

    class Meta:
        db_table = "swb_evidencerecord"
        constraints = [
            models.UniqueConstraint(fields=("source", "slot", "sequence"), name="swb_evid_source_slot_seq_uniq"),
            models.CheckConstraint(
                condition=models.Q(slot__in=("source", "answer", "method", "process", "calculation", "notation")),
                name="swb_evid_slot_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(purpose__in=("question", "handwriting", "formula", "diagram", "definition", "other")),
                name="swb_evid_purpose_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(granularity__in=("whole_image", "region")),
                name="swb_evid_gran_valid",
            ),
            models.CheckConstraint(condition=models.Q(sequence__gt=0), name="swb_evid_sequence_positive"),
        ]


class ReviewDecision(models.Model):
    class Action(models.TextChoices):
        ACCEPT = "accept", "Accept"
        REJECT = "reject", "Reject"
        WITHDRAW = "withdraw", "Withdraw"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="review_decisions")
    revision = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT, related_name="review_decisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="study_workbench_review_decisions")
    action = models.CharField(max_length=16, choices=Action.choices)
    reason = models.TextField()
    expected_head = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT, related_name="expected_by_decisions")
    expected_decision = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="successors"
    )
    expected_dependencies = models.JSONField(default=list)
    request_key = models.CharField(max_length=160)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "swb_reviewdecision"
        constraints = [
            models.UniqueConstraint(fields=("household", "request_key"), name="swb_dec_house_request_uniq"),
            models.UniqueConstraint(
                fields=("revision", "expected_decision"),
                name="swb_dec_revision_expected_uniq",
                nulls_distinct=False,
            ),
            models.CheckConstraint(condition=models.Q(action__in=("accept", "reject", "withdraw")), name="swb_dec_action_valid"),
        ]


class ReviewProjection(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        STALE = "stale", "Stale"
        WITHDRAWN = "withdrawn", "Withdrawn"

    revision = models.OneToOneField(
        RevisionRecord, primary_key=True, on_delete=models.PROTECT, related_name="review_projection"
    )
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    decision = models.ForeignKey(
        ReviewDecision, null=True, blank=True, on_delete=models.PROTECT, related_name="projections"
    )

    class Meta:
        db_table = "swb_reviewprojection"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=("draft", "accepted", "rejected", "stale", "withdrawn")),
                name="swb_projection_state_valid",
            ),
        ]


class RequestReceipt(models.Model):
    class Operation(models.TextChoices):
        STAGE = "stage", "Stage"
        REVIEW = "review", "Review"
        WEB_MATERIAL = "web_material", "Material"
        WEB_UPLOAD = "web_upload", "Upload"
        WEB_ORDER = "web_order", "Page order"
        WEB_QUESTION = "web_question", "Question"
        WEB_RECORD = "web_record", "Business record"

    id = models.BigAutoField(primary_key=True)
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="request_receipts")
    request_key = models.CharField(max_length=160)
    operation = models.CharField(max_length=16, choices=Operation.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="study_workbench_request_receipts")
    request_hash = models.CharField(max_length=64)
    result = models.JSONField()

    class Meta:
        db_table = "swb_requestreceipt"
        constraints = [
            models.UniqueConstraint(fields=("household", "request_key"), name="swb_receipt_house_request_uniq"),
            models.CheckConstraint(condition=models.Q(operation__in=("stage", "review", "web_material", "web_upload", "web_order", "web_question", "web_record")), name="swb_receipt_op_valid"),
            models.CheckConstraint(condition=models.Q(request_hash__regex=r"^[0-9a-f]{64}$"), name="swb_receipt_hash_valid"),
        ]
