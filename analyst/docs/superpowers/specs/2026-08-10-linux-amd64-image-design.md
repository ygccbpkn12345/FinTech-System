# AnalystVerse Linux x86-64 镜像设计

## 目标

将 AnalystVerse 的前端构建阶段和最终运行阶段固定为 Docker 平台 `linux/amd64`，确保产物适用于 Linux x86-64 服务器。

## 设计

- Dockerfile 使用默认目标平台行为；构建命令通过 `--platform linux/amd64` 固定最终架构。
- README 使用 `docker buildx build --platform linux/amd64 --load`。
- 所有主要运行示例使用 `docker run --platform linux/amd64`。
- 应用依赖、端口、数据目录和启动方式不变。

## 验收

- Dockerfile 不重复声明平台，避免空平台值和冗余平台警告。
- README 同时包含 x86-64 构建和运行参数。
- 前端仍能完成生产构建。
