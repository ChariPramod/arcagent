FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY arcagent ./arcagent
COPY evals ./evals
RUN pip install --no-cache-dir '.[agent]' && useradd --uid 10001 --create-home arcagent
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
USER 10001
EXPOSE 8000
CMD ["uvicorn", "arcagent.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
