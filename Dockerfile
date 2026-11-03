FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
# Copy source FIRST, then install. The package uses a src/ layout
# ([tool.setuptools.packages.find] where=["src"]), so `pip install -e .` must see src/kioku/
# to discover the package and create the `kioku` console script. Base deps only — local
# embeddings (torch, ~2GB) are an optional extra and stay OUT of the image.
COPY . .
RUN pip install --no-cache-dir -e .
# Run unprivileged. uid 1000 matches the usual first user on a host, so a bind-mounted vault
# stays writable; named volumes are chowned by the demo's seed step.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin kioku \
    && git config --system --add safe.directory /vault
USER kioku
