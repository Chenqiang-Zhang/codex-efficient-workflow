# Codex Efficient Workflow

[English](README.md) | [简体中文](README.zh-CN.md)

可自定义的 Codex 规划者—执行者 skill。目标是在验收质量达标的前提下减少重复思考、上下文搬运和无效重试。**MIT 开源，可复用；不承诺固定节省比例。**

版本：0.1.0。创建及运行时文档核对时间：2026-10-08T05:17:59Z。

## 你可以怎样使用

在 Codex 中输入：

```text
使用 $codex-efficient-workflow 完成这个任务。
规划者用 gpt-6-astra，执行者用 gpt-6-luna；只有遇到复杂集成或失败时才升级。
```

或自然语言配置：

```text
使用 $codex-efficient-workflow，把执行者固定为我指定的模型，关闭它的自动升级。
保留规划者的大版本更新；每 7 天检查一次，质量或用量检查不通过就保留旧模型。
```

默认角色：Astra 规划、Luna 执行、Sol 处理复杂执行/审查。它们是有时间戳的起点，**不是全市场性价比排名**。账号实际可用模型以当前 Codex 客户端为准。

简单任务直接完成；明确实现任务只使用执行者；需要设计时才使用规划者。默认最多 2 个并发子代理、6 次子代理派发/续跑、1 次原模型修复、1 次升级。规划和审查按需触发，避免为了省用量反而创造更多代理。

## 安装

需要 Codex 子代理能力，以及 Python 3.9+。辅助脚本只用标准库，不需要 API Key，不会调用收费模型或自动安装第三方依赖。

将本仓库 `skills/codex-efficient-workflow/` 整个目录复制到个人 skill 目录，例如 `~/.codex/skills/codex-efficient-workflow/`。当前官方文档也列出 `~/.agents/skills/` 作为用户级发现目录；发行版之间存在差异，请按你的客户端当前支持位置安装，**不要同时复制到多个位置造成重复发现**。

复制后在下一轮调用 `$codex-efficient-workflow`；若未发现，重开会话/客户端。安装不更改全局模型、供应商、凭据或权限。

以安装目录为 `SKILL_DIR`，项目为 `PROJECT_DIR`：

```sh
python3 "$SKILL_DIR/scripts/workflow.py" init --project "$PROJECT_DIR"
python3 "$SKILL_DIR/scripts/workflow.py" status --project "$PROJECT_DIR"
python3 "$SKILL_DIR/scripts/workflow.py" generate --project "$PROJECT_DIR"
```

生成的是项目自己的 `.codex/agents/cew-*.toml`；新代理是否立即可用取决于客户端的配置加载。主聊天模型不会被自动切换。有 per-spawn 模型参数时可以直接指定模型；否则仅使用客户端已经发现、可以选择的自定义角色。

## 配置

配置文件位于项目 `.codex-efficient-workflow/config.json`，支持角色模型、推理强度、角色指令、升级策略、并发/重试上限、时间间隔与质量/用量门槛。

```sh
# 手动指定默认会固定模型，避免未来升级覆盖你的选择
python3 "$SKILL_DIR/scripts/workflow.py" set-role --project "$PROJECT_DIR" \
  --role executor --model gpt-6-luna --effort high

# 明确允许该角色通过验证后自动升级
python3 "$SKILL_DIR/scripts/workflow.py" set-role --project "$PROJECT_DIR" \
  --role executor --update-mode auto_major

# 修改后同步项目代理文件
python3 "$SKILL_DIR/scripts/workflow.py" generate --project "$PROJECT_DIR"
```

跨供应商需配置 provider/family/generation，并核实运行层支持；填写模型名称不能替代真实供应商接入。详细字段与兼容说明见 [configuration.md](skills/codex-efficient-workflow/references/configuration.md)。

## 模型大版本更新

每次 skill 生效时检查上次成功核对的时间戳，默认 7 天到期后重新浏览官方资料；离线/失败后 24 小时再试。它不会在聊天关闭后后台监控，也不会自行建立定时任务。

发现同供应商、同继承系列的新大版本后，检查账号可用性和推理参数支持，再进行针对该角色的配对验收。默认至少 3 个案例、候选全部达标、验收率不下降、实际总用量不增加，才自动更新未固定的角色。3 个案例只是初始烟雾测试，重要工作建议更多代表性案例。

没有可用模型、没有真实评测、无法量化用量、发现预览版或只有传闻：候选记录为 pending，保留旧配置。API 价格与订阅额度分开计量；未知值不会伪装成 0。

每次更改记录 UTC 时间戳、官方来源、评测证据、配置指纹、备份和审计记录，可回滚。升级以当前任务结束后的新派发为边界。详细步骤见 [model-refresh.md](skills/codex-efficient-workflow/references/model-refresh.md)。

**限制：** helper 不联网，不独立验证收据真实性。Codex/操作者浏览官方来源并采集真实证据；helper 检查格式、时效、来源域名、配置一致性及门槛。小规模验收无法保证所有未来任务的质量；用量上限是编排指令，不是硬账单拦截。

## 开源与验证

此目录可直接作为开源仓库：skill、脚本、示例、测试、MIT License 和 CI 配置都在内。`skills/codex-efficient-workflow/assets/examples/` 中的示例是带 `fixture: true` 的虚构收据，禁止用于真实升级；正常安装不包含测试依赖。这是社区 skill，并非 OpenAI 官方产品。

```sh
python3 -m unittest discover -s tests -v
```

测试覆盖时间戳缓存/失败退避、固定模型、预览版/不可用模型、质量与用量门槛、配置变化、升级备份回滚、文件冲突和路径边界。首版在 Python 3.12 上通过 27 项行为测试及官方 skill 格式校验，详见 [验证记录](VALIDATION.md)。CI 配置覆盖 Python 3.9、3.11 和 3.13，尚未实际运行 GitHub 托管 CI。未运行收费模型的真实质量/额度对照试验，因此不报告节省百分比。

发布时只提交仓库源文件；项目运行记录可能涉及私有工作，应留在本地。参考 [.gitignore](.gitignore)。贡献建议：提供可复现的问题和脱敏样例；修改迁移逻辑时添加行为测试。

官方依据（核对日期 2026-10-08）：[子代理](https://learn.chatgpt.com/docs/agent-configuration/subagents)、[Skills](https://learn.chatgpt.com/docs/build-skills)、[配置](https://learn.chatgpt.com/docs/config-file/config-reference)。
