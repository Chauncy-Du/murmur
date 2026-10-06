# 私有 ProjectHub API：润色与 Ask Anything

按 [2026-10-05 接口说明](https://openclaw.icalculate.website/ai/agent-guide)适配。只在本地开发；未发布或构建便携版。

## 软件配置

1. 用 `Start-MurMur.cmd` 重启软件，在 Settings → Services 的 **Polish** 下选择 **ProjectHub · Private API**。
2. 打开 Polish 的 Advanced。地址自动填为 `https://openclaw.icalculate.website/ai`，协议为 OpenAI compatible，模型选择为 Specify model。此地址会启用专用的 ProjectHub 异步适配器。
3. 在 API key 输入你的**应用密钥**，离开密钥输入框后会自动刷新模型；也可点击模型旁的 **Refresh models**。无需先填写模型，刷新使用当前未保存的地址和密钥。下拉菜单显示服务端提供的友好名称，选中后自动使用对应的模型 ID。这里仅查询模型与能力，不消耗生成次数；没有友好名称时会显示 ID。
4. 在 Ask Anything 下也选择 **ProjectHub · Private API**，输入应用密钥（可以与润色相同），刷新并选择模型。两项使用独立的 Windows Credential Manager 槽位，需分别输入。刷新后也可以直接在 Services 概览的下拉菜单选择具体模型。点击 Save changes。
5. 确认 Demo mode 关闭、Polish 打开。语音识别仍由当前选择的 ASR 引擎完成。试一次听写润色，以及一次 Ask Anything 提问或选中文本后改写。原始识别结果仍保留在历史里。

是否包含你想使用的 Opus 4.8，以密钥查询结果为准。刷新保留当前模型选择；更换地址或密钥会清掉旧目录列表，避免串用其他服务或密钥的模型。密钥为空时刷新使用已有的保存密钥。鉴权失败、服务不在线或没有可用模型时会显示原因，可修正后再刷新。

## 调试与恢复

- 请求仅包含 `model/messages/stream:false`，不发送 temperature、max_tokens、response_format、tools 等不支持的参数。Ask 依靠提示词要求 action/text JSON，并继续严格校验；不合格输出会保留原文。
- 使用 `/jobs` 提交、`/jobs/{id}` 轮询。服务端串行排队，等待可能持续几分钟。本地取消只停止等待，不能取消已提交的服务器任务。
- 默认最多等待 16 分钟。提交前持久保存原请求和幂等键，拿到任务 ID 后保存 ID；超时、断网或退出后，重新执行**相同模型、提示词和文本**会恢复原任务，不创建新任务。改变输入视为新操作。
- 重启后也可以显式恢复（在项目目录执行）：

  ```powershell
  .\.venv\Scripts\python.exe -m murmur.projecthub list
  .\.venv\Scripts\python.exe -m murmur.projecthub resume --request-key <list显示的request_key> --credential ask_llm
  ```

  润色任务使用 `--credential llm`。必须保留原密钥；命令将输出结果供手动检查，不会自动写入其他应用。使用独立数据目录时补上 `--data-dir <目录>`。恢复不是自动启动任务。
- failed、indeterminate、cancelled 或已过期的任务停止自动提交替代任务。先与网关维护者确认原任务状态；不要盲目重试生成。
- 待恢复任务保存在应用数据目录的 `projecthub-tasks.sqlite3`，包含输入文本、提示词和幂等键，不包含 API 密钥。成功取回结果后删除该恢复记录；该文件属于私人应用数据，不能放入源码归档。网关 token 估计不会冒充供应商计量或账单。

接口模拟测试验证协议、恢复与原文保护；真实模型质量、网关登录状态和实时配额须用你的密钥在软件中确认。
