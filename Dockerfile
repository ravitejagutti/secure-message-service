FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ server/

EXPOSE 8443

# Start through main.py so TLS paths and port come from the environment
# (docker-compose.yml), the same way as a local run.
CMD ["python", "-m", "server.app.main"]
