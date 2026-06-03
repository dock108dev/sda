FROM python:3.13-alpine
COPY server.py /app/server.py
WORKDIR /app
USER nobody
EXPOSE 9999
CMD ["python", "server.py"]
