from app.web import content_confirmation as content
from .views import api
from .workflow_views import body


@api()
def detail(request, material_id):
    return content.detail(request.user, material_id)


@api("POST")
def save(request, material_id):
    value = body(request, {"expected", "request_key", "reason", "checked", "question_id", "printed_text",
                           "original_number", "sources", "answer", "nodes"})
    return content.save(request.user, material_id, value)


def material_content(request, material_id):
    return save(request, material_id) if request.method == "POST" else detail(request, material_id)


@api("POST")
def draft(request, material_id):
    value = body(request, {"expected", "request_key", "reason", "question_id", "printed_text", "original_number", "sources"})
    return content.draft(request.user, material_id, value)


@api("POST")
def erratum(request, material_id):
    value = body(request, {"expected", "question_id", "corrected_text", "basis", "checked", "reason", "request_key"})
    return content.erratum(request.user, material_id, value)


@api()
def reading_detail(request, page_id):
    return content.reading_detail(request.user, page_id)


@api("POST")
def reading_save(request, page_id):
    value = body(request, {"expected", "request_key", "reading", "coverage", "partitions", "pending_items", "basis"})
    return content.reading_save(request.user, page_id, value)


def reading(request, page_id):
    return reading_save(request, page_id) if request.method == "POST" else reading_detail(request, page_id)
