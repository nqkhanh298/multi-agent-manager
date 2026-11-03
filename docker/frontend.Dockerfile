FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/m3
COPY docker/frontend/package.json docker/frontend/package-lock.json ./
RUN npm ci
COPY docker/frontend/build.sh /opt/m3/build.sh
COPY docker/sandbox_entrypoint.py /opt/sandbox/entrypoint.py
ENTRYPOINT ["python3", "/opt/sandbox/entrypoint.py"]
