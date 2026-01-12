# Pre-built base image for Cycls
# Includes common dependencies to speed up builds

FROM python:3.12-slim

ENV PIP_ROOT_USER_ACTION=ignore \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install uv for fast package installs, then install common dependencies
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache \
    cloudpickle \
    grpcio \
    protobuf \
    cryptography \
    fastapi[standard] \
    pydantic \
    pyjwt \
    uvicorn[standard] \
    httpx \
    && mkdir -p io
