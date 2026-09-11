FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
# Copy source FIRST, then install. The package uses a src/ layout
# ([tool.setuptools.packages.find] where=["src"]), so `pip install -e .` must see src/kioku/
# to discover the package and create the `kioku` console script. Installing before the source
# is copied (as PR #1 tried) fails package discovery and breaks the build. Base deps only —
# local embeddings (torch, ~2GB) are an optional extra and stay OUT of the image.
COPY . .
RUN pip install --no-cache-dir -e .
