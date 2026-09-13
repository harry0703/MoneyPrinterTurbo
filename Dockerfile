# Use an official Python runtime as a parent image
FROM python:3.11-slim-bullseye

# Set the working directory in the container
WORKDIR /MoneyPrinterTurbo

# 设置/MoneyPrinterTurbo目录权限为777
RUN chmod 777 /MoneyPrinterTurbo

ENV PYTHONPATH="/MoneyPrinterTurbo"

# 本地用户默认继续优先使用国内镜像；GitHub Actions 发布 GHCR 镜像时使用 default，
# 避免海外 runner 访问国内镜像过慢导致镜像发布长时间卡住。
ARG DOCKER_BUILD_MIRROR=china
ARG PIP_USE_OFFICIAL=0

# 系统依赖安装需要同时满足两点：国内环境保留镜像回退能力，所有镜像均
# 失败时必须让 Docker 构建立刻失败。旧循环最后执行的 sleep 总会返回 0，
# 导致 git/ffmpeg 未安装时仍生成不可用镜像。这里把“写入软件源”“安装”
# 和“三次重试”拆成边界清晰的 shell 函数，并用函数返回值决定是否继续。
# 所有软件源统一使用 HTTPS，避免部分网络环境直接拦截明文 HTTP 请求。
RUN set -u; \
    write_debian_sources() { \
        main_url="$1"; \
        security_url="$2"; \
        printf 'deb %s bullseye main\ndeb %s bullseye-updates main\ndeb %s bullseye-security main\n' \
            "$main_url" "$main_url" "$security_url" > /etc/apt/sources.list; \
        rm -rf /var/lib/apt/lists/*; \
    }; \
    install_system_dependencies() { \
        apt-get update && \
        apt-get install -y --no-install-recommends git ffmpeg libraqm0; \
    }; \
    retry_system_dependencies() { \
        attempt=1; \
        while [ "$attempt" -le 3 ]; do \
            echo "Attempt $attempt: installing system dependencies"; \
            if install_system_dependencies; then \
                return 0; \
            fi; \
            echo "Attempt $attempt failed" >&2; \
            if [ "$attempt" -lt 3 ]; then \
                echo "Retrying in 5 seconds..." >&2; \
                sleep 5; \
            fi; \
            attempt=$((attempt + 1)); \
        done; \
        return 1; \
    }; \
    if [ "$DOCKER_BUILD_MIRROR" = "china" ]; then \
        write_debian_sources \
            "https://mirrors.aliyun.com/debian" \
            "https://mirrors.aliyun.com/debian-security"; \
        if ! retry_system_dependencies; then \
            echo "Aliyun mirror failed, switching to Tsinghua mirror" >&2; \
            write_debian_sources \
                "https://mirrors.tuna.tsinghua.edu.cn/debian" \
                "https://mirrors.tuna.tsinghua.edu.cn/debian-security"; \
            if ! install_system_dependencies; then \
                echo "Tsinghua mirror failed, switching to default Debian mirror" >&2; \
                write_debian_sources \
                    "https://deb.debian.org/debian" \
                    "https://deb.debian.org/debian-security"; \
                if ! install_system_dependencies; then \
                    echo "Failed to install system dependencies from all configured mirrors" >&2; \
                    exit 1; \
                fi; \
            fi; \
        fi; \
    else \
        echo "Using default Debian mirrors"; \
        write_debian_sources \
            "https://deb.debian.org/debian" \
            "https://deb.debian.org/debian-security"; \
        if ! retry_system_dependencies; then \
            echo "Failed to install system dependencies from the default Debian mirror" >&2; \
            exit 1; \
        fi; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# Copy only the requirements.txt first to leverage Docker cache
COPY requirements.txt ./

# 本地默认优先国内 PyPI 镜像；GHCR 发布使用官方 PyPI，避免海外 runner 因跨境镜像访问变慢。
RUN if [ "$PIP_USE_OFFICIAL" = "1" ]; then \
        pip install --no-cache-dir --retries 3 --timeout 60 -r requirements.txt; \
    else \
        pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com --retries 3 --timeout 60 -r requirements.txt || \
        pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ --trusted-host mirrors.tuna.tsinghua.edu.cn --retries 3 --timeout 60 -r requirements.txt || \
        pip install --no-cache-dir --retries 3 --timeout 60 -r requirements.txt; \
    fi

# Now copy the rest of the codebase into the image
COPY . .

# Expose the port the app runs on
EXPOSE 8501

# 容器内部必须监听 0.0.0.0，宿主机仍通过 docker 端口映射限制为 127.0.0.1。
# browser.serverAddress 只决定浏览器展示的访问地址，不能替代 server.address。
CMD ["streamlit", "run", "./webui/Main.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.serverAddress=127.0.0.1", "--server.enableCORS=True", "--browser.gatherUsageStats=False", "--client.toolbarMode=minimal", "--logger.hideWelcomeMessage=True", "--server.showEmailPrompt=False"]

# 1. Build the Docker image using the following command
# docker build -t moneyprinterturbo .

# 2. Run the Docker container using the following command
## For Linux or MacOS:
# docker run -v $(pwd)/config.toml:/MoneyPrinterTurbo/config.toml -v $(pwd)/storage:/MoneyPrinterTurbo/storage -p 127.0.0.1:8501:8501 moneyprinterturbo
## For Windows:
# docker run -v ${PWD}/config.toml:/MoneyPrinterTurbo/config.toml -v ${PWD}/storage:/MoneyPrinterTurbo/storage -p 127.0.0.1:8501:8501 moneyprinterturbo
