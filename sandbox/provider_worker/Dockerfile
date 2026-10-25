FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN python -m pip install --no-cache-dir num2words==0.5.14 docopt==0.6.2
COPY azure_speech.py azure_model.py smoke.py model_smoke.py one_request.py network_diagnostics.py /app/
USER 65532:65532
ENTRYPOINT ["python", "-I", "/app/smoke.py"]
