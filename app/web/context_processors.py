from app.release import identity


def release(request):
    return {"release": identity()}
