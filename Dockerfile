FROM python:3.12-slim

WORKDIR /app

# copy only requirements.txt
COPY requirements.txt .

# install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# install necessary system packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    tzdata \
    procps && \
    rm -rf /var/lib/apt/lists/*

# copy the rest of the application files
COPY . .

ENV GRABBY_CONFIG_PATH=/config \
    LOG_LEVEL=INFO

VOLUME /config

HEALTHCHECK --interval=1m CMD pgrep -f "grabby.py" > /dev/null || exit 1

CMD ["python", "grabby.py"]
