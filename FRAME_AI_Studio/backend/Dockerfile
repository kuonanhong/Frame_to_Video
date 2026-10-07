FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRAME_DATA_DIR=/app/data \
    FRAME_MODEL_CACHE=/app/model-cache \
    FRAME_LOW_MEMORY=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt

# Install the NVIDIA CUDA wheel explicitly. Filter only the torch pin from
# the second install so that its index cannot select a different wheel.
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
       --index-url https://download.pytorch.org/whl/cu128 torch==2.8.0 \
    && python -c "from pathlib import Path; lines = Path('requirements.txt').read_text().splitlines(); Path('/tmp/frame-requirements.txt').write_text('\n'.join(line for line in lines if not line.strip().startswith('torch==')) + '\n')" \
    && python -m pip install --no-cache-dir -r /tmp/frame-requirements.txt \
    && rm /tmp/frame-requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 frame \
    && mkdir -p /app/data /app/model-cache \
    && chown -R frame:frame /app

USER frame

EXPOSE 7860

# Keep one worker: job state and the model queue live in this process.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
