FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install
COPY learning/gemini/agents/projects/agency_os/webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the agency_os files to mimic google3 structure
# This allows 'import google3.learning.gemini.agents.projects.agency_os...' to work
COPY learning/gemini/agents/projects/agency_os /app/google3/learning/gemini/agents/projects/agency_os

# Set PYTHONPATH to include /app
ENV PYTHONPATH=/app

# Expose port (Cloud Run defaults to 8080, but can be overridden by PORT env var which Flask app handles)
EXPOSE 8080

# Run the app
CMD ["python", "google3/learning/gemini/agents/projects/agency_os/webapp/app.py"]
