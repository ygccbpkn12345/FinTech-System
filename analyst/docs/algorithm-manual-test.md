# 算法注册与发现：手工测试流程

以下流程适用于当前 Windows 本地部署，前端 5173、后端 8000。准备了一个确定返回结果的 HTTP 服务和一个本地 Python 插件，便于把算法接入与股票数据、预测耗时分开验证。

## 一、准备

1. 保持前后端运行，打开 `http://127.0.0.1:5173/algorithms`。记录现有算法名称，通常为 `stock_prediction`、`market_data_crawler`。
2. 涉及聊天的用例需要在“系统配置”中配置可用的路由模型。若只回答“模型暂时不可用”，先检查模型连接；新增通用工具的选择依赖模型，离线关键词兜底只覆盖原来的股票预测和爬虫。每个独立聊天用例都点“新对话”，避免上一轮等待补参的状态干扰。
3. 新开 PowerShell，启动本地 HTTP 服务，窗口保持运行：

```powershell
Set-Location -LiteralPath 'D:\桌面\服务大赛\服务大赛'
& '.\Analyst\.venv\Scripts\python.exe' -X utf8 '.\output\algorithm-test-kit\http_test_server.py'
```

4. 浏览器打开 `http://127.0.0.1:9100/health`，应看到 `{"status":"ok"}`。若 9100 被其他进程占用，可加 `--port 9101`，并把下面所有 9100 同步换成 9101。

## 二、按顺序测试

### T01 查询、搜索和类型筛选

操作：刷新“算法管理”；搜索 `stock_prediction`；清空搜索；类型筛选选“Python”；再选“HTTP”。

预期：初始列表正常；搜索结果只包含匹配项；Python 显示本地工具；尚未注册 HTTP 工具时，HTTP 筛选显示空列表。空列表不应显示为请求失败。测试后清空搜索、选择“全部类型”。

### T02 添加 HTTP 算法

点击“添加算法”，填写：

| 表单字段 | 输入 |
| --- | --- |
| 算法名称 | `http_echo_test` |
| 算法描述 | `HTTP回声测试：当用户要求HTTP回声测试时调用，将用户提供的query文本原样返回` |
| 算法类型 | HTTP 服务 |
| 必填参数 | 输入 `query` 后按回车，确认形成一个标签 |
| 服务地址 | `http://127.0.0.1:9100/echo` |
| 请求方法 | POST · JSON |
| 超时 | 10 |
| 请求字段映射 | `{"query":"text"}` |
| 响应字段映射 | `{"summary":"data.message","received":"data.received"}` |
| 结果摘要字段 | `summary` |

保存，刷新页面，再搜索 `http_echo_test`。

预期：保存成功；列表出现且仅出现一个新算法，类型 HTTP，必填参数 query，执行目标为 POST 和刚填的地址；页面刷新后仍存在。此步骤不需要重启后端。

### T03 完整参数直接调用、请求/响应映射

1. 新对话发送：`请调用 http_echo_test 做HTTP回声测试，query=你好算法`。
2. 看聊天结果，同时看 9100 测试服务的终端日志。

预期：出现工具结果 `HTTP 回显：你好算法`；测试服务日志含 `"method": "POST"`、`"path": "/echo"`、`"received": {"text": "你好算法"}`。这同时验证了工具发现、执行、query→text 映射、data.message→summary 映射和现有前端结果展示。普通助手只说“我会调用”不算通过，必须看到工具结果和实际 HTTP 请求日志。

### T04 缺参追问和多轮补全

1. 新对话发送：`请调用 http_echo_test 做HTTP回声测试，我还没有提供query，请先询问我要回显的内容。`
2. 确认助手追问 `query`；此时 9100 终端不应有新增 `/echo` 请求。
3. 回复 `补参成功`。
4. 另开两个新对话重复步骤 1，分别用 `{"query":"JSON补参成功"}`、`query=键值补参成功` 补参。

预期：三种方式分别返回 `HTTP 回显：补参成功`、`HTTP 回显：JSON补参成功`、`HTTP 回显：键值补参成功`。每次只补参，不需要重新描述算法。

若首轮模型仍自行填入 query，先看该轮是否实际进入追问状态，不能把“直接调用成功”当作缺参测试通过；文末提供确定性的自动回归命令。

### T05 编辑配置即时生效

1. 编辑 `http_echo_test`，把服务地址改为 `http://127.0.0.1:9100/echo-v2`，描述末尾增加“第二版”，其余字段不变，保存。
2. 确认算法名称不能编辑。
3. 不重启，新对话发送：`请调用 http_echo_test，query=修改验证`。

预期：返回 `V2 HTTP 回显：修改验证`，测试服务日志请求 `/echo-v2`，刷新管理页后仍显示新地址和新描述。

### T06 GET 请求

1. 编辑同一算法：地址改回 `/echo`，方法改为 GET · 查询参数，其他字段保持原样。
2. 新对话发送：`请调用 http_echo_test，query=GET验证`。

预期：返回 `HTTP 回显：GET验证`，终端日志显示 `"method":"GET"`（空格多少不影响），收到 `{"text":"GET验证"}`。测试后可改回 POST。

### T07 重复名称与无效配置

逐项测试，每次只改变一项：

| 操作 | 预期 |
| --- | --- |
| 新增另一个 `http_echo_test`，其他字段合法 | 提示名称已存在，原算法保持不变 |
| 新增表单的名称填 `123bad` | 名称校验失败，不能保存 |
| 描述仅输入空格 | 提示补充描述 |
| 地址填 `file:///tmp/test` | 拒绝保存，仅支持 HTTP/HTTPS |
| 超时清空或设为 0 | 不能保存有效的 0 秒配置；控件可能自动限制到最小值 |
| 请求字段映射填 `{query:text}` | JSON 校验错误，不能保存 |
| 请求字段映射填 `[]` | 拒绝数组，要求 JSON 对象 |

每次失败后刷新列表，确认没有出现错误记录、原算法没有被覆盖。最后取消表单。

### T08 HTTP 异常处理及恢复

对 `http_echo_test` 逐项编辑，保存后用新对话发送 `请调用 http_echo_test，query=异常验证`：

| 地址 | 超时 | 预期 |
| --- | --- | --- |
| `http://127.0.0.1:9100/error` | 10 | 工具错误，说明异常状态码 503 |
| `http://127.0.0.1:9100/invalid-json` | 10 | 工具错误，说明响应不是有效 JSON |
| `http://127.0.0.1:9100/slow` | 1 | 工具请求发出后约 1 秒超时；模型路由耗时另计，不应长期卡死 |

三次测试后恢复地址 `/echo`、超时 10、POST，另开新对话调用。预期恢复正常回显，错误不会使后续对话永久失效。

### T09 重启恢复

1. 记录 `http_echo_test` 当前地址、方法、描述。
2. 停止并重新启动 FastAPI 后端（保留 9100 测试服务）。先等待正在运行的股票预测结束。若原后端在终端运行，在原终端 Ctrl+C；若是当前项目的后台启动进程，可在 PowerShell 运行下面的检查与停止命令（只停止确认是 api_server 的 8000 端口进程）：

```powershell
$backendListener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
foreach ($backendProcessId in @($backendListener.OwningProcess | Select-Object -Unique)) {
    $backendProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $backendProcessId"
    if ($backendProcess.CommandLine -notmatch 'uvicorn\s+api_server:app') {
        throw '8000 端口不是预期的项目后端，请先核对占用程序'
    }
    Stop-Process -Id $backendProcessId
}
```

随后在 PowerShell 启动后端，保持该窗口运行：

```powershell
Set-Location -LiteralPath 'D:\桌面\服务大赛\服务大赛\Analyst'
$env:CONFIG_ENCRYPTION_KEY = [Environment]::GetEnvironmentVariable('CONFIG_ENCRYPTION_KEY', 'User')
& '.\.venv\Scripts\python.exe' -X utf8 -m uvicorn api_server:app --host 127.0.0.1 --port 8000
```

3. 刷新管理页面，核对配置；新对话再次调用。

预期：配置完整保留，工具可以正常调用。聊天会话本身在内存中，重启后用新对话测试，不要求旧会话恢复。

### T10 本地 Python 插件发现与调用

1. 在项目根目录的 PowerShell 中复制测试插件：

```powershell
Set-Location -LiteralPath 'D:\桌面\服务大赛\服务大赛'
Copy-Item -LiteralPath '.\output\algorithm-test-kit\local_echo_plugin.py' -Destination '.\Analyst\services\tools\plugins\local_echo_plugin.py'
```

2. 按 T09 重启后端，然后刷新算法管理页。
3. 添加算法：名称 `local_echo_test`；描述 `本地回声测试：当用户要求本地回声测试时调用，将query原样返回`；类型“本地 Python”；选择本地实现 `local_echo_test`；必填参数应自动填入 `query`。保存。
4. 新对话发送：`请调用 local_echo_test 做本地回声测试，query=Python接入成功`。

预期：返回 `Python 回显：Python接入成功`，9100 HTTP 服务不产生对应请求。整个过程只增加插件文件与注册信息，没有修改 Chat.jsx 或聊天编排代码。

补充校验：编辑这个算法，删除必填参数 query 后保存，预期被后端拒绝，原配置保留。不能通过管理界面移除底层 Python 实现要求的参数。

### T11 删除算法、删除等待补参的算法

1. 针对 `http_echo_test` 按 T04 进入等待 query 的状态，暂不回复。
2. 进入算法管理，点击该测试算法的“删除”，先点“取消”。预期算法仍存在。
3. 再次删除并确认。预期列表移除此项，刷新也不会恢复。
4. 回到步骤 1 的原对话回复 `继续测试`。

预期：提示该算法已删除或暂不可用，清除等待状态，不报页面异常或服务端 500。可继续发送普通聊天消息。

5. 按 T09 重启后端，确认已删除的算法不会重新出现。新对话显式要求调用已删除的工具时，不应再产生对应 HTTP 请求；模型可以解释不可用或走普通聊天，措辞不固定。

### T12 表格文字重叠回归

1. 把浏览器或 Codex 浏览器面板缩窄，使表格出现横向滚动条。
2. 拖动到中间位置，让“执行目标”列从右侧“编辑/删除”下面经过。
3. 鼠标停在不同数据行、编辑按钮附近和操作列空白处，来回横向滚动。
4. 再拉宽窗口重复检查。

预期：红色编辑/删除始终清楚，下面的黑色文字不透出、不重叠；悬停浅红底正常，两个按钮分别可点。仅看滚动条最左端或最右端不足以覆盖原问题，必须经过中间位置。

## 三、清理

1. 在管理页删除本次创建的 `http_echo_test`、`local_echo_test`（若已删除则略过），保留原有工具。
2. 删除管理记录后，再移除复制到插件目录的测试文件并重启后端。顺序不能颠倒，否则持久化配置引用未安装的实现会导致启动校验失败。

```powershell
Set-Location -LiteralPath 'D:\桌面\服务大赛\服务大赛'
Remove-Item -LiteralPath '.\Analyst\services\tools\plugins\local_echo_plugin.py'
```

3. 在运行 9100 测试服务的终端按 Ctrl+C。
4. 刷新管理页面，确认恢复测试前算法列表。保留 output 下的测试素材，后续可复用。

## 四、自动回归（可选）

无需启动 9100 服务；这组测试会自行隔离配置、模型和 HTTP 返回值：

```powershell
Set-Location -LiteralPath 'D:\桌面\服务大赛\服务大赛\Analyst'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_algorithm_manager.py tests/test_algorithm_api.py tests/test_algorithm_chat.py tests/test_http_tool.py tests/test_http_tool_transport.py tests/test_tool_registry.py -q
```

它补充覆盖人工聊天难以稳定控制的情况：0/false 必填值、固定 URL 不受模型参数影响、磁盘写入失败保留旧配置、调用中注册表变化保持当前轮快照、删除等待算法、本地插件自动发现。人工 T03/T04 仍用于验证真实模型和浏览器的完整链路。

建议每个用例记录：编号、实际输入、实际结果、通过/失败、失败截图或 9100 终端日志。优先跑 T02→T03→T04→T05→T08→T11→T12，再补其余用例。
