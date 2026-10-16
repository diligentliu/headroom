# Headroom → CC Switch：Codex、桌面编程会话与 Claude Code

此 fork 基于上游 `683c9a6120c309e84e4848378dbe3891d064f82e`，包含 0.41.0 之后的 main 更新。
改造是 Python 代理的可选功能；默认关闭，不更改上游用户原来的路由。

```text
Claude Code / Codex CLI / 桌面 Codex、Work 编程会话
                    ↓
              Headroom :8788
                    ↓
             CC Switch :15721
                    ↓
          个人官方订阅 / 公司渠道
```

普通 ChatGPT 聊天窗口不在支持范围内。Codex 会话必须读取配置中的模型请求地址。
Live 语音、模型目录、账户接口保留上游处理方式，不承诺经过 CC Switch。
压缩数字不等于 Plus 额度节省百分比，也不是实际账单。

## 给 agent 的首要约束

**没有用户在独立终端操作前，不运行 `switch`、`rollback`、`emergency-direct`，不停止 8788 服务。**
当前 agent 的连接可能依赖它。允许安装隔离环境、运行测试、准备部署、启动禁用配置监听的候选进程。
详见 [AGENT-HANDOFF.md](AGENT-HANDOFF.md)。

## 安装与兼容性

- 自动切换/恢复脚本只支持 **macOS**；已在本机 Apple Silicon、Python 3.13 验证。
- Linux 可运行 Python 代理；服务管理需要目标机器的 agent 另行配置，不执行 macOS 切换脚本。
- Windows 的部署/文件替换权限尚未验证，本交付不声称支持自动部署。
- 需要 `uv`、Python 3.13、已运行的 CC Switch，且 Codex 已能通过它请求目标供应商。
- 现有 Headroom、下载的其他版本及其虚拟环境均不覆盖。
- `.venv` 只属于这个 fork，`.runtime` 保存本机部署配置、日志、备份，两者均不提交。
- CLI 与桌面 Codex 共用的配置一般为 `~/.codex/config.toml`，自定义 `CODEX_HOME` 应在准备时指定。
- CC Switch 聚合模型别名、认证文件和供应商数据库不修改。
- 未验证已打开会话热更新地址；切换后重新打开 CLI 和桌面编程会话。

在仓库根目录执行（安装阶段不切换服务）：

```bash
python3 deploy/cc-switch-chain/install.py
python3 deploy/cc-switch-chain/manage.py prepare
python3 deploy/cc-switch-chain/manage.py status
```

`prepare` 默认网关 `http://127.0.0.1:15721/v1`、Headroom 端口 8788、cache 模式。
其他电脑必须核对实际端口，可用 `--gateway`、`--port`、`--codex-home`、`--claude-dir` 指定。
它只发送无凭证的本地 WebSocket 握手，不发模型请求。101 表示支持 WS；426 表示按 HTTP/SSE 兼容模式部署；其他状态应先排查。

隔离环境使用已发布的 0.41.0 wheel 提供原生扩展，再覆盖这个 fork 的 Python 源码。
已确认该上游提交的 `headroom-core` 与 `headroom-py` 源码和 0.41.0 完全一致；安装器核对哈希。
不会复用或升级旧版运行环境。仓库依赖锁用于此次验证；其他平台须重新验证 wheel 可用性。

## 测试和候选服务

```bash
.venv/bin/python -m pytest tests/test_provider_codex_endpoints.py tests/test_provider_codex_runtime.py tests/test_provider_codex_responses.py tests/test_proxy/test_cc_switch_reconciler.py tests/test_proxy/test_codex_cc_switch_chain.py tests/test_cc_switch_chain_deployment.py -q
python3 deploy/cc-switch-chain/manage.py foreground
```

`foreground` 在 **8789**（准备端口 + 1）运行候选服务，禁用两个配置监听器，并使用独立的候选 Codex/Claude 目录。
它不会接管现有客户端，也不会读取真实 Codex 凭证；Ctrl+C 停止候选进程。

另一个终端检查：

```bash
curl --noproxy '*' http://127.0.0.1:8789/health
curl --noproxy '*' http://127.0.0.1:8789/admin/upstream
```

## 用户手动切换

先结束候选进程。下面步骤会中断经过旧 Headroom 的连接，**由用户在独立终端执行**：

```bash
python3 deploy/cc-switch-chain/manage.py switch
```

脚本会：

1. 在私有 `.runtime/cc-switch-chain/backups/时间戳/` 备份当时的 Codex 配置、Claude 配置及旧 LaunchAgent。
2. 停止旧 LaunchAgent 和经过身份检查的旧 Headroom 代理/监督进程。
3. 把同一个 LaunchAgent 标签改成 fork 的隔离运行环境，仍监听 8788。
4. 启用 Codex 和 Claude 配置监听，后续 CC Switch 写回网关地址时自动恢复 Headroom 入口。
5. 等待就绪；启动失败时尝试自动恢复切换前的备份。

旧 `~/.headroom/deploy/default/manifest.json`、旧安装及日志不改写。
fork 的状态独立保存，所以旧历史节省量不自动合并到新面板。

切换后重新打开两个客户端。先各发一个小请求；在 Headroom `/stats` 和 CC Switch 中对照模型及供应商。
确认请求都经过后，再用实际工具输出观察压缩；短请求可能不压缩。
目前交付阶段不使用真实账号自动做这一步，以免中断当前会话或消耗用户额度。

## 应急恢复（不需要新 Headroom 可用）

恢复切换瞬间的旧服务与配置：

```bash
python3 deploy/cc-switch-chain/manage.py rollback
```

它只依赖 Python 标准库、旧安装及本机快照。**会恢复切换时的配置，切换后编辑的模型配置可能被覆盖。**

如果只想立刻绕过 Headroom，保留模型/认证选择，让客户端直连 CC Switch：

```bash
python3 deploy/cc-switch-chain/manage.py emergency-direct
```

它停止 Headroom、禁用对应 LaunchAgent，把客户端入口改回 CC Switch。随后重新打开客户端。
网关本身也故障时，这一步不能恢复供应商连接，应在 CC Switch 内排查。
必要时人工从 `.runtime/cc-switch-chain/last-backup` 指向的目录恢复文件；快照含敏感配置，不要上传。

## 实现边界

新增环境变量：

| 变量 | 含义 |
|---|---|
| `HEADROOM_CODEX_LOCAL_GATEWAY` | 显式指定 `http(s)://回环IP:端口/v1`，只接管订阅 Responses 和其子路径 |
| `HEADROOM_CODEX_GATEWAY_WEBSOCKETS=0` | 在接受连接前返回 426，保留 Codex 原有 HTTP 回退行为 |
| `HEADROOM_CC_SWITCH_RECONCILE_CODEX=1` | 监听 Codex 配置，只替换与上述网关完全相同的地址 |

默认不启用，也不接受请求头指定订阅出口。网关连接失败时不悄悄改走官方。
HTTP/WS 支持网关时使用同一订阅出口；HTTP-only 网关没有 WS→HTTP 协议转换，由客户端按 426 回退。
当前本机 CC Switch 实测返回 426，因此准备为 HTTP/SSE 模式。
监听器保留 TOML 注释、模型、provider ID、文件权限；替换前重读检查并发编辑。
外部 CC Switch 不参与同一个文件锁，因此不能保证消除所有最后瞬间的写入竞争。
现有 Claude 监听器维持上游行为，其进程级出口不支持多个相互独立的直连上游并发隔离；聚合模式应统一进 CC Switch。

## 跟进上游

```bash
git fetch upstream
git switch feat/cc-switch-chain
git rebase upstream/main
```

先在新目录/虚拟环境验证，再按手动流程部署。若 native 源码变动，旧 wheel 不再可直接覆盖：
使用更新的上游发布 wheel并重新生成验证清单，或用 `uv build --wheel` 编译 fork。
重新运行兼容测试，更新依赖锁、`build.json`、交付包和校验和，不要只修改哈希绕过原生兼容检查。
rebase 改写已发布分支历史后，如需更新个人 fork，只对该功能分支使用 `git push --force-with-lease`。
