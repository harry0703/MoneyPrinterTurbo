# ./app/Dockerfile
FROM moneyprinterturbo-base:latest

WORKDIR /app

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]

# At runtime, mount the config.toml file from the host into the container
# using Docker volumes. Example usage:
# docker build -f .\app\Dockerfile -t moneyprinterturbo-app .
# docker run -v /path/to/your/config.toml:/usr/src/app/config.toml -p 8080:8080 moneyprinterturbo-app
