from app.workflows import preparation
from .views import api
from .workflow_views import body, job_row


@api()
def detail(request, job_id):
    data = preparation.detail(request.user, job_id)
    data["job"] = job_row(data["job"])
    return data


@api("POST")
def queue(request, job_id):
    value = body(request, {"expected", "request_key", "sources", "question_id", "reason"})
    job, stage_id = preparation.queue(request.user, job_id, value)
    return {"job": job_row(job), "stage_id": stage_id}


def workspace(request, job_id):
    return queue(request, job_id) if request.method == "POST" else detail(request, job_id)


@api("POST")
def confirm(request, job_id, stage_id):
    value = body(request, {"expected", "request_key", "reason", "checked", "printed_text", "original_number", "sources", "answer", "nodes"})
    job, result = preparation.confirm(request.user, job_id, stage_id, value)
    return {"job": job_row(job), **result}


@api("POST")
def cancel(request, job_id, stage_id):
    value = body(request, {"expected", "request_key", "reason"})
    return {"job": job_row(preparation.cancel(request.user, job_id, stage_id, value))}
