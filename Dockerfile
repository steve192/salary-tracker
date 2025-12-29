FROM python:3.12-slim

ARG BUILD_VERSION="dev"
ARG VCS_REF="local"
ARG BUILD_DATE="1970-01-01T00:00:00Z"
ARG IMAGE_SOURCE="https://github.com/your-org/salary-tracker"

LABEL org.opencontainers.image.title="Salary Tracker" \
    org.opencontainers.image.description="Self-hosted salary history dashboard with inflation tracking" \
    org.opencontainers.image.version="${BUILD_VERSION}" \
    org.opencontainers.image.revision="${VCS_REF}" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.source="${IMAGE_SOURCE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
