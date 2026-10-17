FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY tests/ ./tests/
COPY pytest.ini ./pytest.ini

# 교육용 시뮬레이터도 최소권한 원칙: 비루트 사용자로 실행
RUN useradd -m sim && chown -R sim:sim /app
USER sim

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('CONTROL_API_PORT', '8090') + '/health', timeout=4)" || exit 1

EXPOSE 8090

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${CONTROL_API_PORT:-8090}"]
