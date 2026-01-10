# Pre-built base image for Cycls web agents
# Includes common dependencies to speed up builds from 60s to <5s

FROM python:3.12-slim

ENV PIP_ROOT_USER_ACTION=ignore
ENV PYTHONUNBUFFERED=1

# Install common web dependencies
RUN pip install --no-cache-dir \
    cloudpickle \
    cryptography \
    fastapi[standard] \
    pydantic \
    pyjwt \
    uvicorn[standard] \
    httpx

# Create app directories
RUN mkdir -p /app/io
WORKDIR /app
