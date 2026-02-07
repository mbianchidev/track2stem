FROM python:3.13-slim

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
# Install CPU-only PyTorch first to avoid pulling in ~7GB of NVIDIA CUDA libraries.
# Demucs depends on torch but only needs CPU for inference in this app.
RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt && \
    # Safety net: remove any NVIDIA CUDA packages that transitive deps (e.g. torchcodec) may have pulled from PyPI
    pip uninstall -y nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 \
        nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 \
        nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 nvidia-nvtx-cu12 \
        nvidia-nvjitlink-cu12 triton 2>/dev/null || true

COPY . .

RUN mkdir -p /app/uploads /app/outputs

EXPOSE 5000

CMD ["python", "app.py"]
