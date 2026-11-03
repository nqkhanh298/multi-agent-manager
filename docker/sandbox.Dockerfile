FROM python:3.11-slim
RUN python -m pip install --no-cache-dir pytest==8.4.2
COPY docker/sandbox_entrypoint.py /opt/sandbox/entrypoint.py
ENTRYPOINT ["python", "/opt/sandbox/entrypoint.py"]

\n