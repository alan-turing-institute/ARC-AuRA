FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LITMCP_CACHE_DIR=/cache

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cache.py pdfs.py s2.py server.py ./
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# No USER line: the container starts as root so entrypoint.sh can match the server's
# user to the owner of the /cache bind mount, then it drops to that user (non-root).
RUN chmod 755 /usr/local/bin/entrypoint.sh \
    && useradd --create-home --uid 1000 litmcp \
    && mkdir -p /cache \
    && chown litmcp /cache

EXPOSE 8000

ENTRYPOINT ["entrypoint.sh"]
CMD ["python", "server.py"]
