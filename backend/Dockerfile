FROM python:3.14-slim@sha256:656d12e70054d5fda18a045e2494c96701e9792dd1445f95b3d038df954f57e9

WORKDIR /app

# requirements.lock, not requirements.txt: the lock pins every transitive
# dependency to the exact version resolved and tested against, so the same
# commit installs the same bytes on every build. requirements.txt states
# intent (deliberate ranges); it is not what actually gets installed here.
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

# Run as an unprivileged user — a compromised app process can't write to the
# image filesystem or escalate
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
