"""JSON adapters for native append-only study plans and read-only progress."""
from django.db import transaction
from app.study import services as study
from . import evidence, progress
from .views import api, household
from .workflow_views import body


@api()
def materials(request):
    return progress.materials(request.user, household(request))


@api()
def learner(request, learner_id):
    return progress.learner(request.user, household(request), learner_id)


@api()
def schedule_list(request, learner_id):
    return progress.schedules(request.user, household(request), learner_id)


def schedules(request, learner_id):
    return create(request, learner_id) if request.method == "POST" else schedule_list(request, learner_id)


@api()
@transaction.atomic
def options(request, learner_id):
    profile = evidence.scope(request.user, household(request), learner_id)
    data = study.new_schedule_context(request.user, profile.pk)
    return {"context": data["context"], "questions": [{"revision_id": row["revision_id"],
        "label": row["label"]}
        for row in data["questions"]]}


@api("POST")
@transaction.atomic
def create(request, learner_id):
    profile = evidence.scope(request.user, household(request), learner_id)
    value = body(request, {"question_revision_id", "due_date", "goal", "prompt_plan", "reason", "expected", "request_key"})
    result = study.create_schedule(request.user, profile.pk,
        question_revision_id=value.get("question_revision_id"), due_date=value.get("due_date"),
        goal=value.get("goal"), prompt_plan=value.get("prompt_plan", ""), reason=value.get("reason"),
        context=value.get("expected"), request_key=value.get("request_key"))
    return {"schedule_id": result["schedule_pk"]}


@api("POST")
def action(request, schedule_id):
    value = body(request, {"action", "expected", "reason", "request_key", "due_date", "goal", "prompt_plan", "attempt_revision_id"})
    result = study.append_schedule_event(request.user, schedule_id, action=value.get("action"),
        context=value.get("expected"), reason=value.get("reason"), request_key=value.get("request_key"),
        **{key: value[key] for key in ("due_date", "goal", "prompt_plan", "attempt_revision_id") if key in value})
    return {"schedule_id": result["schedule_pk"]}
