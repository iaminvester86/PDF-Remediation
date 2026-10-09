# Single-node image: app + Java runtime + veraPDF + OpenDataLoader. No AI model is bundled.
# Build:  docker build -t pdf-remediation .
# Run:    docker run -p 8765:8765 -v pdfrem-data:/data -e PDFREM_ACCESS_TOKEN=change-me pdf-remediation
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jre-headless maven \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scripts ./scripts
RUN pip install --no-cache-dir ".[odl]" \
 && mvn -q -B -f scripts/verapdf-pom.xml dependency:copy-dependencies -DoutputDirectory=/app/vendor/verapdf/lib \
 && apt-get purge -y maven && apt-get autoremove -y && rm -rf /root/.m2

ENV PDFREM_DATA_DIR=/data \
    PDFREM_VERAPDF_LIB=/app/vendor/verapdf/lib
RUN useradd --create-home --uid 10001 pdfrem && mkdir -p /data && chown pdfrem /data
USER pdfrem
EXPOSE 8765
CMD ["pdfrem", "serve", "--host", "0.0.0.0", "--port", "8765"]
