# 私人电脑部署交接

目标：把本机 Claude Code、Codex CLI、桌面 Codex/Work 编程会话串联为：
客户端 → Headroom → CC Switch → 官方订阅/公司渠道。

先阅读同目录 README.zh-CN.md 和 build.json。

## 必须遵守

- 用户明确要求**不要由 agent 重启、停止或切换其正在使用的链路**。
- 完成安装、检查、独立端口测试、生成切换/恢复命令后，告诉用户在独立终端自行执行。
- 不覆盖其他 Headroom checkout、uv tool 环境、账号凭证、CC Switch 数据库。
- 不把原电脑的端口、用户名、公司渠道、认证文件直接复制到私人电脑。
- 只支持桌面端编程会话，不声称覆盖普通聊天或语音。

## 操作顺序

1. 检查系统/架构、Python/uv、现有 Headroom 和 CC Switch 服务、监听端口与 LaunchAgents。
2. 阅读 Claude settings、Codex config 的网络地址，输出时隐藏 token/key；不要读取 auth.json 内容。
3. 确认 CC Switch 能独立请求用户目标模型，并确认使用 routing/aggregation 模式。
4. 运行 install.py，在此 fork 独立 .venv 安装，核对 native-source 校验结果。
5. 运行 manage.py prepare，传入实际网关/端口/配置目录；确认 WebSocket 101 或 426。
6. 检查已有 Headroom LaunchAgent 标签是否为 com.headroom.default。若不是，先适配服务管理再继续；不能只杀进程让旧监督器把它拉起。
7. 跑 README 中的离线测试和 foreground 候选服务，确认健康、出口正确、监听器关闭。
8. 停止自己启动的候选进程；核对现有链路仍可用。
9. 把用户手动执行的 switch、rollback、emergency-direct 三条命令和仓库绝对路径交付。
10. 用户切换后再验证真实请求计数、供应商归属及压缩记录。不能把模拟测试当成真实账号验收。

## 交付后的维护

功能分支 feat/cc-switch-chain；upstream 是 headroomlabs-ai/headroom，origin 是用户个人 fork。
此包不携带 .git/.venv/.runtime/账号/日志；如需保留 git 历史，优先 clone fork 并切换分支。
归档为 git archive 生成的源码；配套 SHA256SUMS 检查传输完整性。
发生上游更新先 rebase，再重新验证依赖和原生 ABI，不直接替换正在服务的目录。
