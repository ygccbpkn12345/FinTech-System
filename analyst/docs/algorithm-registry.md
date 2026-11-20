# 算法注册与发现

在侧栏“算法管理”中添加、查询、编辑或删除算法。名称是创建后不变的唯一标识；描述和必填参数会提供给聊天路由。结果沿用统一 ToolResult，聊天展示不需要增加算法分支。添加 HTTP 算法和修改注册配置无需重启；安装新的 Python 插件后重启一次以加载实现。

## 本地 Python 算法

在 `Analyst/services/tools/plugins/` 增加模块，例如 `sentiment.py`：

```python
from services.chat_models import ToolResult

class SentimentTool:
    name = "sentiment"
    description = "分析财经新闻的情绪，输入 query，返回情绪评分"
    required_parameters = ("query",)

    def execute(self, arguments, context):
        # 替换为你的实际算法；支持请求级 context.background_tasks。
        text = arguments["query"]
        return ToolResult(
            tool=self.name, status="completed", summary=f"已收到 {len(text)} 个字符",
            data={"length": len(text)},
        )

def build_tool():
    return SentimentTool()
```

插件仅从服务端可信目录自动加载，不接受浏览器上传或任意模块路径。每个模块必须提供 `build_tool()`。工具名称不能重复；返回值必须是 ToolResult；必填参数统一校验，`None`/空白字符串视为缺失，`0`/`false` 是有效值。

未创建持久化配置时，首次启动默认注册内置工具和插件。已有配置时，在管理页选择“本地 Python”和新增实现完成注册；不会将已删除的算法自动加回。可修改描述或额外增加必填参数，但不能删除底层实现的必填参数。

## HTTP 算法

POST `/api/algorithms`：

```json
{
  "name": "sentiment_http",
  "description": "分析财经新闻情绪，query 是新闻文本",
  "kind": "http",
  "required_parameters": ["query"],
  "http": {
    "url": "http://127.0.0.1:9100/sentiment",
    "method": "POST",
    "timeout_seconds": 10,
    "request_mapping": {"query": "text"},
    "response_mapping": {"summary": "data.message", "score": "data.score"},
    "summary_field": "summary"
  }
}
```

只允许 HTTP/HTTPS，支持 POST JSON 和 GET 查询参数，超时为 0～300 秒（不含 0）。输入仅发送必填参数或 request_mapping 声明的字段。目标 URL 保存在服务端配置；模型提供的 url 参数不会改变请求目标。服务必须返回 2xx 和 JSON 对象；超时、状态码错误和无效 JSON 均转换为工具错误。HTTP 配置不支持从聊天参数拼接 URL、动态认证头或任意方法。

## API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/algorithms` | 列表，返回 `{items: [...]}` |
| GET | `/api/algorithms/local-tools` | 可选本地实现 |
| GET | `/api/algorithms/{name}` | 单项详情 |
| POST | `/api/algorithms` | 新增，201；重复名称 409 |
| PUT | `/api/algorithms/{name}` | 完整替换定义，名称不可更改 |
| DELETE | `/api/algorithms/{name}` | 删除，204 |

不存在返回 404；无效定义返回 422；保存失败返回 503 并保留旧配置。修改在下一轮对话生效，已启动的算法按原快照继续执行。等待补参的算法若被删除，聊天返回错误并清除等待状态。通用参数支持模型提取、JSON、`key=value`，或按追问顺序逐项回复。

## 持久化与部署

配置默认位于 `Analyst/algorithm_registry.json`（运行配置，不提交到 Git），可用 `ALGORITHM_REGISTRY_PATH` 指定位置，采用同目录临时文件和原子替换。删除全部算法后保存空列表，重启保持为空。文件损坏或引用未安装的插件时启动报错，修复文件或恢复插件后重启，避免静默丢失配置。

当前面向单个后端进程；多 worker/多副本不共享热更新。Docker 镜像将配置放在 `/app/Analyst/runtime/algorithm_registry.json`，持久化已有 runtime 目录即可保存。管理入口和其他系统配置入口一样，应部署在受信任的管理访问范围内。未新增独立账号权限系统。
