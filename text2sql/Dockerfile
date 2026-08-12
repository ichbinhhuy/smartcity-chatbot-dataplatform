FROM python:3.10-slim

WORKDIR /app

# Pre-install CPU-only PyTorch with high timeout & retries
RUN pip install --default-timeout=1000 --retries 10 --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy requirements first for optimal layer caching
COPY requirements.txt .

RUN pip install --upgrade pip && pip install --default-timeout=1000 --retries 10 --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
