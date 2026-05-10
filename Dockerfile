FROM python:3.12-slim

# Lean image — runtime only, no dev tools. Multi-arch via buildx.
WORKDIR /app

# System deps: curl for healthcheck only
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python deps first (cache-friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY varigrid_gateway/ ./varigrid_gateway/
COPY pyproject.toml README.md LICENSE ./

# Install the package itself so the entrypoint script exists
RUN pip install --no-cache-dir -e .

# Buffer dir
RUN mkdir -p /var/lib/varigrid

# Run as non-root
RUN useradd -m -u 1000 -s /usr/sbin/nologin varigrid \
    && chown -R varigrid:varigrid /var/lib/varigrid /app
USER varigrid

# Default config path; mount yours read-only at this location.
ENV VARIGRID_CONFIG=/etc/varigrid/gateway_config.yaml

ENTRYPOINT ["varigrid-gateway"]
CMD ["--config", "/etc/varigrid/gateway_config.yaml"]
