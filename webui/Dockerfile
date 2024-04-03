# ./webui/Dockerfile
FROM moneyprinterturbo-base:latest

WORKDIR /app

COPY . .

EXPOSE 8008

ENV PYTHONPATH "${PYTHONPATH}:/app/webui"

CMD ["streamlit", "run", "./webui/Main.py", "--server.port", "8008"]

# At runtime, mount the config.toml file from the host into the container
# using Docker volumes. Example usage:
# docker build -f .\webui\Dockerfile -t moneyprinterturbo-webui .
# docker run -p 8008:8008 -v /path/to/your/config.toml:/app/config.toml moneyprinterturbo-webui