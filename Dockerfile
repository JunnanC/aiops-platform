FROM python:3.12-slim

WORKDIR /app
# 零第三方依赖，直接拷贝源码即可
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple . || \
    pip install --no-cache-dir .

ENV PYTHONPATH=/app/src
CMD ["python", "-m", "aiops.cli", "status"]
