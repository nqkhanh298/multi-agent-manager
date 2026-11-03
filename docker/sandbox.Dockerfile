FROM python:3.11-slim@sha256:db20d8506e2f15b6db39b40b6015ca46bae855dec6dd326d462cfe79ae972893
RUN python -m pip install --no-cache-dir pytest==8.4.2
COPY docker/sandbox_entrypoint.py /opt/sandbox/entrypoint.py
ENTRYPOINT ["python", "/opt/sandbox/entrypoint.py"]
