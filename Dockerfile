FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.lock
COPY src ./src
COPY run.py ./
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=2)"
# Sem --port: a porta vem de PORT quando a plataforma a define, 8000 caso contrário.
# Um valor fixo aqui venceria a variável e quebraria o health check da plataforma.
CMD ["python", "run.py", "--host", "0.0.0.0"]
