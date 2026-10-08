FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LITMCP_CACHE_DIR=/cache

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cache.py pdfs.py s2.py server.py ./

RUN useradd --create-home --uid 1000 litmcp \
    && mkdir -p /cache \
    && chown litmcp /cache
USER litmcp

EXPOSE 8000

CMD ["python", "server.py"]
