FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12.14-slim-bookworm@sha256:d5ae74acb8026b32a2f6deea45003c5bd4e2880700c19c44bda54670ad3eff90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-dejavu-core=2.37-6 \
        fonts-noto-cjk=1:20220127+repack1-1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-container.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt -r requirements-container.txt

RUN groupadd --gid 10001 swb \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin swb \
    && install -d --owner=10001 --group=10001 --mode=0700 /var/lib/study-workbench/private

COPY --chown=10001:10001 app ./app
COPY --from=frontend --chown=10001:10001 /build/dist ./frontend/dist
COPY --chown=10001:10001 frontend/LICENSE ./licenses/shadcn-admin-MIT.txt
COPY --chown=10001:10001 frontend/DEPENDENCY_LICENSES.txt ./licenses/frontend-dependency-notices.txt
COPY --chown=10001:10001 licenses ./licenses
COPY --chown=10001:10001 manage.py ./manage.py
COPY --chown=10001:10001 scripts/container_entrypoint.sh ./scripts/container_entrypoint.sh
COPY --chown=10001:10001 scripts/run_model_tasks.py ./scripts/run_model_tasks.py
COPY --chown=10001:10001 scripts/manage_private_retention.py ./scripts/manage_private_retention.py
RUN cp /usr/share/doc/fonts-noto-cjk/copyright /app/licenses/Noto-Debian-container.txt \
    && cp /usr/share/doc/fonts-dejavu-core/copyright /app/licenses/DejaVu-Debian-container.txt \
    && chmod 0755 /app/scripts/container_entrypoint.sh

ENV DJANGO_SETTINGS_MODULE=app.production \
    SWB_DATA_ROOT=/var/lib/study-workbench/private

USER 10001:10001
EXPOSE 8000

ARG SWB_RESOURCE_OWNER=manual
LABEL com.study-workbench.resource-owner=${SWB_RESOURCE_OWNER}
ARG SWB_SOURCE_REVISION=working-tree
LABEL org.opencontainers.image.revision=${SWB_SOURCE_REVISION}
ARG SWB_BUILD_DATE=
ENV SWB_SOURCE_REVISION=${SWB_SOURCE_REVISION} SWB_BUILD_DATE=${SWB_BUILD_DATE}

ENTRYPOINT ["./scripts/container_entrypoint.sh"]
CMD ["gunicorn", "app.wsgi:application", "--bind=0.0.0.0:8000", "--workers=1", "--threads=4", "--timeout=60", "--error-logfile=-"]
