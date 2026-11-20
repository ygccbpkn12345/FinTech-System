# AnalystVerse 模块完成即输出设计

## 目标

分析任务不再等全部模块结束才向用户展示结果。任一模块完成并成功保存后，后端立即通过 Server-Sent Events（SSE）推送该模块的公开结果；前端在固定位置点亮并填充模块卡片。

## SSE 接口

新增 `GET /api/analyze/events/{task_id}`。响应类型为 `text/event-stream`，禁止缓存。每个数据事件包含 SSE `id`、`event` 和 JSON `data`：

- `module_completed`：模块名、完成时间、状态、公开模块结果。
- `completed`：任务全部模型及 I/O 工作成功收口。
- `failed`：任务失败及安全错误信息。

模块事件 ID 使用任务内单调递增序号。终止事件也拥有唯一递增 ID。事件不得包含 API Key、Tushare Token、配置快照、线程内部对象或异常堆栈。

## 回放与重连

浏览器使用原生 `EventSource`。自动重连时浏览器发送 `Last-Event-ID`；后端先回放该 ID 之后的内存事件，再等待新事件。首次连接从 ID 0 开始，回放任务已产生的全部事件。

若同一事件因重连重复抵达，前端按事件 ID 去重。任务已终止时，新连接回放遗漏事件和终止事件后立即关闭。

无新事件期间每 15 秒发送 SSE 注释心跳。心跳没有事件 ID，不进入历史，也不改变前端模块状态。

## 并发通知

每个任务持有一个 `threading.Condition`，与任务事件列表使用同一任务锁协调。I/O 工作线程完成模块保存后，在锁内追加事件并通知所有等待连接。SSE 生成器不持锁进行网络写入，只在读取快照或等待时持锁，避免阻塞模型和 I/O 线程。

任务完成或失败时，执行线程追加终止事件并通知连接。任务状态、模块状态、事件历史和终止事件必须在同一个临界区保持一致。

客户端断开时生成器及时退出，不删除任务事件；其他连接及后续重连不受影响。

## 前端展示

分析工作台预先渲染固定模块槽位。第一组为五个并行分析师；第二组为 router、manager、risk、final、environment simulation、reflection 和按需出现的 weekly reflection。

模块槽位状态为 `pending`、`running`、`completed` 或 `failed`。收到 `module_completed` 后只更新对应槽位，不按完成顺序重新排列。五分析师并行完成顺序可以变化，但页面布局保持稳定。

连接断开但任务未终止时显示“实时连接中断，正在重连”，保留已有模块结果。收到 `completed` 后关闭 EventSource，并请求一次完整结果校准最终决策、图表和历史记录。收到 `failed` 后关闭连接并显示安全错误信息。

页面卸载、启动新任务或更换 task ID 时必须关闭旧 EventSource，避免重复连接和跨任务写入。

## API 客户端边界

分析 API 模块提供 `subscribeAnalysisEvents(taskId, handlers)`，负责创建和关闭 EventSource、解析事件、将浏览器网络错误与任务失败区分开。React 页面只消费规范化事件，不直接拼接 SSE URL 或解析原始字符串。

现有状态轮询保留为兼容性兜底，但实时页面以 SSE 为主。完整结果接口仍是最终权威结果来源。

## Nginx

为 `/api/analyze/events/` 设置专用 location 或匹配规则，关闭 `proxy_buffering`、`proxy_cache` 和 gzip，传递 `Connection` 所需语义，并将 `proxy_read_timeout` 提高到覆盖长任务。其他 API 继续使用原有代理配置。

## 验证

测试覆盖：

- 首次连接按序回放已有模块事件。
- `Last-Event-ID` 只补发后续事件。
- 新模块事件唤醒正在等待的 SSE 连接。
- 空闲流产生心跳但不污染历史。
- completed 和 failed 终止事件在回放后关闭流。
- 事件内容不包含敏感字段。
- 前端按 ID 去重，模块完成不会改变固定布局。
- 断线状态不会误报任务失败，重连后能继续填充。
- 新任务或页面卸载会关闭旧连接。
- 最终事件触发完整结果校准。
- Nginx 配置检查、后端测试、Python 编译和前端生产构建通过。
