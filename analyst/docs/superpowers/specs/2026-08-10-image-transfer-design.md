# AnalystVerse 离线镜像上传设计

## 目标

在本地构建 Linux x86-64 镜像，将其导出为 `analystverse.tar`，通过 SCP 上传到 Linux 服务器，再导入并启动容器。

## 流程

1. 使用 Buildx 构建并加载 `analystverse:latest`。
2. 检查镜像架构为 `linux/amd64`。
3. 使用 `docker save -o analystverse.tar` 导出。
4. 计算 SHA-256 校验值并使用 SCP 上传。
5. 在服务器使用 `sha256sum` 校验并执行 `docker load`。
6. 启动新容器，验证 `/api/health` 和浏览器访问地址。

## 安全与更新

- `.env` 不打入镜像，单独在服务器创建或上传。
- 更新时先停止并删除旧容器，不删除数据卷。
- `.dockerignore` 排除镜像归档，避免下次构建把 tar 发送进构建上下文。

