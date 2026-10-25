FROM python:3.14.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
ENV VIRTUAL_ENV=/app/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Upgrade pip and install Python dependencies
COPY requirements.txt .
# Install the audio stack from the CPU index so TorchCodec does not require CUDA.
RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch torchaudio torchcodec --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt && \
    pip check && \
    python -c "import torch, torchaudio, torchcodec; assert torch.version.cuda is None, 'CPU-only PyTorch is required'"

COPY . .

RUN mkdir -p /app/uploads /app/outputs

EXPOSE 5000

CMD ["python", "app.py"]
