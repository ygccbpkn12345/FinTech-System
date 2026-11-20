# 模型配置保存没有反馈：排查与修复

本次本机问题有两部分：

1. React 19 配合 Ant Design 5 的静态 message 渲染没有适配，导致保存成功或失败消息不可见。入口已加载官方 `@ant-design/v5-patch-for-react-19`，系统配置页另外保留保存结果 Alert，避免只依赖短暂消息。
2. 后端缺少 `CONFIG_ENCRYPTION_KEY`，提交 API Key 时会拒绝加密保存并返回 422。已为此 Windows 用户配置该环境变量，重启后的后端继承它。密钥没有写入项目文件或日志。

“大模型配置”表单已预渲染，与顶部保存按钮保持连接。校验失败会切换到模型页签并说明原因；没有 API Key 时，保存普通模型参数会明确提示还需要填写密钥。保存成功只表示配置写入完成，不代表模型服务网络、API Key 权限或余额已验证。

## 使用

系统配置 → 大模型配置 → 填写模型名称、对应的 Base URL、你自己的 API Key → 保存配置。看到“模型配置已保存”并且密钥栏下出现已保存状态后，再回聊天页面新建对话验证。

API Key 保存在后端加密配置中，保存成功后输入框会清空，页面仅显示脱敏状态，这是正常行为。

## 本机后端重启

旧终端可能没有继承新设置的用户级环境变量。停止此项目原来的后端后，可显式读取用户级变量，再启动：

```powershell
Set-Location -LiteralPath 'D:\桌面\服务大赛\服务大赛\Analyst'
$env:CONFIG_ENCRYPTION_KEY = [Environment]::GetEnvironmentVariable('CONFIG_ENCRYPTION_KEY', 'User')
& '.\.venv\Scripts\python.exe' -X utf8 -m uvicorn api_server:app --host 127.0.0.1 --port 8000
```

已有凭据依赖此加密密钥，重新生成密钥无法解密旧配置。迁移环境时应同时安全迁移该环境变量与加密后的运行配置。

参考：Ant Design 官方 React 19 兼容文档： https://5x-ant-design.antgroup.com/docs/react/v5-for-19
