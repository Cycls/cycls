# Pre-built base image for Cycls web agents
# Includes common dependencies to speed up builds from 60s to <5s

FROM python:3.12-slim

ENV PIP_ROOT_USER_ACTION=ignore \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install common web dependencies and create io directory
RUN pip install --no-cache-dir \
    cloudpickle \
    cryptography \
    fastapi[standard] \
    pydantic \
    pyjwt \
    uvicorn[standard] \
    httpx \
    && mkdir -p io
