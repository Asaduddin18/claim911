FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --chown=65532:65532 egress_proxy.py /app/egress_proxy.py
USER 65532:65532
ENTRYPOINT ["python", "-I", "/app/egress_proxy.py"]
