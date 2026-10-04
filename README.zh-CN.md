<div align="center">

![MurMur — Your voice, a clearer draft.](docs/assets/hero.svg)

**轻巧的 Windows 语音助手，让听写、翻译与文字编辑融入日常工作。**

[![Version](https://img.shields.io/badge/version-0.4.0-a7b6ff?style=flat-square)](pyproject.toml)
[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=flat-square)](#快速开始)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![MIT](https://img.shields.io/badge/license-MIT-65e4cc?style=flat-square)](LICENSE)
[![Speech](https://img.shields.io/badge/speech-offline%20%2B%20cloud-8b9bd9?style=flat-square)](#服务配置)

[English](README.md) · **简体中文**

[官网](https://murmur.icalculate.chatgpt.site)

[快速开始](#快速开始) · [功能](#功能) · [服务配置](#服务配置) · [隐私](#隐私与数据) · [开发](#开发与验证)

</div>

---

**当前工作目录（2026-10-04）：**启动、开发和测试统一使用 `D:\LocalProjects\MurMur`。语音模型位于 `models`，设置/历史/录音位于 `data`，本地语音运行库位于 `runtimes`。启动不再依赖旧 Dropbox 项目。日常使用可双击根目录的 `Start-MurMur.cmd`。详见[本地启动说明](LOCAL_RUN.md)和[存储与迁移记录](docs/LOCAL_STORAGE.md)。

点一次快捷键开始录音，说出想法，再点一次得到整理好的文字。MurMur 的悬浮胶囊陪伴录音过程；主窗口集中提供活动洞察、可搜索历史、个人词典和服务配置。

全新配置默认使用本机 SenseVoice 语音识别，并关闭 Demo。也可选择 Paraformer、Fun-ASR-Nano、Qwen3-ASR 或云端服务；文字处理可使用本机 Ollama 或 DeepSeek 等 OpenAI 兼容接口。通过预览与目标检查，决定哪些内容进入你的文档。

> **项目状态：**当前 v0.4.0 为源码阶段版本，安装包分发仍受安全阻挡。此前便携构建被开发环境的组织安全系统阻挡，当前没有可分发的便携 EXE 或二进制 ZIP 包。详见[验证记录](docs/VALIDATION.md)和[构建通知](docs/PORTABLE_SECURITY_BLOCK.txt)。构建脚本保留阻挡检查，等待审核处理。

## 功能

| 功能 | 说明 |
| --- | --- |
| **快捷键听写** | 点一次 Right Alt 或 F8 开始录音，再点一次结束；设置中仍可选择按住模式。 |
| **翻译与编辑** | 语音翻译；选区润色、翻译、总结、扩写及自定义编辑。 |
| **本地或云端** | 四种离线语音模型、DirectML / Vulkan 显卡加速、DashScope 百炼、Alibaba Speech NLS，以及本地或在线文字模型。 |
| **悬浮胶囊** | 默认 168 × 36，启动、录音、转录和润色时持续显示；真实音量波形切换为进度条，完成后展开成可复制的结果气泡。 |
| **个人词典** | 热词、字面替换规则，以及带历史原文依据的本地词汇建议。 |
| **洞察与历史** | 活动日历、搜索、JSON/CSV 导出及可配置保留期限。 |
| **统一配置** | 服务预设、高级参数、快捷键检查和独立语音/文字连接测试。 |
| **预览与控制** | 选区编辑需确认；目标无法核实时回退预览。 |

英文暗色界面包含 **Home、History、Dictionary、Settings**。Settings 采用分类侧栏、简洁的名称与控件双列设置行，以及始终可见的 **Save changes** 底栏。Services 的三个主模块无需滚动，详细参数在各自的 Advanced 子页面。首页集中展示紧凑洞察、正方形活动日历及当前配置的快捷键。原始转写与结果不同的历史记录提供 **Compare original and result**，短文本也能直接对照；长记录另有全文入口。详情分别保留完整结果、原始转写和 Ask 的选中文字。

主窗口固定为 **920 × 680** 逻辑像素，文字编辑窗口固定为 **680 × 440**。MurMur 自有窗口不支持手动缩放或最大化，详细设置在固定窗口内滚动，Services 主面板无需滚动。关闭主窗口进入托盘；通过 **Quit MurMur** 彻底退出。

从结果气泡进入 **Edit result** 后可以编辑、复制，选区替换按钮隐藏，再次生成也保留该上下文。历史保存失败时，当前文字仍可使用，操作按钮会恢复并明确提示。导出仅在新文件完整写入后替换旧文件。

## 快速开始

### 1. 安装与启动

首次从 GitHub 安装时，先安装 Python 3.12+、uv、Git 和 GitHub CLI，然后运行以下命令。当前默认数据、模型和运行库使用这个固定目录；仓库不包含这些私人文件或下载资源。

```powershell
gh repo clone Chauncy-Du/murmur 'D:\LocalProjects\MurMur'
Set-Location 'D:\LocalProjects\MurMur'
uv sync --locked
.\Start-MurMur.cmd
```

当前已安装的项目可直接双击 **`D:\LocalProjects\MurMur\Start-MurMur.cmd`**。它使用现有 `.venv` 和 `run.py` 启动，不同步或下载依赖。先从托盘选择 **Quit MurMur** 退出旧进程。

也可在 PowerShell 中运行：

```powershell
Set-Location 'D:\LocalProjects\MurMur'
.\scripts\start.ps1 -SkipSync
```

安装或更新依赖时运行不带 `-SkipSync` 的 `.\scripts\start.ps1`，先执行 `uv sync --locked` 再启动。此模式需要 Windows 10/11、Python 3.12 或更新版本及 [uv](https://docs.astral.sh/uv/)；实际录音还需要麦克风。已有环境也可直接执行 `uv run --no-sync murmur`。

### 2. 准备本地语音模型

全新配置默认选择 **Local speech model · offline → SenseVoice Small · multilingual (default)**、**CPU · compatible**，并关闭 **Demo mode**。打开 **Settings → Services → Speech to Text → Advanced**，选择模型与 **Run on**，点击 **Download model** 安装，或选择已有兼容模型目录。点击 **Load & test** 后再点 **Save changes**。无需语音 API Key；模型仅在主动安装时下载。

已保存的语音服务和 Demo 选择会保留。如需体验模拟结果，可在 **Settings → General** 开启 **Demo mode** 并保存，再使用 **Record to preview**；演示结果仅供预览或手动复制。

### 3. 配置真实录音

1. 在 **Settings → Services → Speech to Text → Advanced** 中选择 **Local speech model · offline**，再选择四种本地模型之一与 CPU / GPU；若使用在线语音服务，则填写该服务所需凭据。
2. 下载所选离线模型，或选择兼容模型目录。
3. 在 **Polish** 主卡片的下拉菜单选择整理、翻译或编辑所用模型；自定义地址、凭据和详细参数放在 **Advanced** 子页面。
4. 离线语音点击 **Load & test**；文字模型和在线语音点击 **Test connection**，再点击 **Save changes**；验证成功不会自动保存配置。
5. 若此前开启过 Demo，在 **Settings → General** 关闭 **Demo mode** 并保存。
6. 将焦点放在可编辑输入框，点一次 **Right Alt** 或 **F8**，等到 Recording 后说话，再点一次结束。

完全本地的听写方案：选择 **Local speech model · offline**，关闭 **Refine dictated text**，或在回环地址配置已安装的文字模型。整理、翻译和编辑使用独立的文字服务设置。

## 快捷键

| 默认按键 | 操作 |
| --- | --- |
| **Right Alt / F8** | 点一次开始听写，再点一次结束。 |
| **Alt + Shift** | 语音翻译。 |
| **Right Alt + Space** | 开始 Ask Anything 语音指令，再按 Right Alt 结束。 |
| **Left Alt + Space** | 捕获选区，预览并编辑。 |
| **Esc** | 取消当前操作。 |

可在设置中修改快捷键及按住/切换模式。其他应用占用 Alt + Space 时，可改为 **Ctrl + Shift + Space**。禁用听写快捷键也会禁用 F8，胶囊仍可启动录音。

**Record to preview** 完成后显示紧凑结果气泡。成功的真实听写/翻译默认将最终文本写入剪贴板；Demo 需手动 Copy。点击 **Edit** 打开编辑器，**Dismiss** 关闭结果。选区编辑也先预览，点击 **Replace** 时再次核对原目标与选区。

## 服务配置

**Settings → Services** 主面板包含 **Speech to Text、Polish、Ask Anything** 三个模块，每个模块直接提供模型下拉菜单、状态、**Test** 和 **Advanced**。主面板无需滚动，详细参数分别放在子页面。**Auto** 只有测试成功后才显示实际使用的模型；选择或测试模型不会自动保存，点击 **Save changes** 后应用草稿。

### Ask Anything：语音编辑、问答和起草

在 **Settings → Services → Ask Anything → Advanced** 中设置独立的外部 API 地址、模型名称和 API Key，点击 **Test connection**，再 **Save changes**。首次使用沿用已有外部服务的地址和模型；密钥单独存入 Windows Credential Manager。此接口需要 HTTPS、兼容 `/chat/completions` 并支持 JSON 输出，听写润色继续使用自己的配置。

**Remove Ask key** 仅清除 Ask 密钥；留空 API Key 会保留已保存的密钥。本轮自动测试及原生验证边界见 [Ask 验证记录](docs/ASK_ANYTHING_VALIDATION.md)。

选中文字后，先按 Right Alt，再按 Space，说“把这段改得更自然”或“翻译成英文”，再按 Right Alt 结束。目标和选区仍有效时自动替换；“总结这段”“解释这段”的答案显示在气泡中，明确要求替换为摘要时才替换。没有选区时可直接提问，或说“起草一封邮件”；草稿仅在确认原光标位置仍有效时自动插入。

Ask 固定采用点按录音，也可在 Shortcuts 中改为 **Ctrl + Shift + A** 或关闭。开始时释放组合键不会结束录音；再次按 Right Alt 或 Ask 快捷键结束，Esc 取消。主页 **Ask Anything** 按钮用于语音问答预览；胶囊右键菜单可结束 Ask。

模型仅收到本次口述请求和可确认的选中文字，每项最多 12,000 字符。第一版没有联网检索或连续对话。无法确认选区、光标或目标时，结果留在气泡中供 Copy；处理中有键鼠输入、焦点变化、密码字段或剪贴板无法安全恢复时，不自动写入。历史记录分别保存口述请求、选区来源和结果。

### 语音识别（ASR）

| 服务 | 运行位置 | 配置要求 |
| --- | --- | --- |
| **Local speech model · offline** | 本机 CPU / GPU | 使用下面的本地 ASR 模型进行离线听写，下载当前模型或选择兼容目录。 |
| **Bailian · online（百炼 / DashScope）** | 云端 | 在线语音识别，需区域匹配的 API Key 与端点；默认模型为 `fun-asr-realtime`。 |
| **Alibaba Speech · online（NLS）** | 云端 | 在线语音识别，语种按阿里项目配置；需项目 AppKey 与 Token，保存 AccessKey ID/Secret 可启用自动刷新。 |

停止录音后进行本地识别，首次加载与首次显卡转录较慢，包含模型初始化和着色器编译。下载校验固定大小与 SHA256，并包含 Silero VAD，按停顿切段，单段最多约 20 秒，整次录音最多 10 分钟。缺少模型、运行库或显卡支持时会提示本地错误；可手动改选 CPU，音频不会自动转发到云端。

| 本地模型 | MurMur 使用的格式 / 加速 | 下载大小 | 语言 | 建议场景 | 默认模型目录名 |
| --- | --- | --- | --- | --- | --- |
| **[SenseVoice Small](https://github.com/QwenAudio/SenseVoice)（默认）** | CPU：INT8 ONNX；GPU：分拆 FP16 ONNX / DirectML | CPU 约 240 MB；GPU 约 434 MB | 普通话、英文、粤语、日语、韩语，可指定语言 | 日常中英文听写可先用 CPU；也覆盖所列其他语种 | `sensevoice-small` / `sensevoice-small-dml` |
| **[Paraformer](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-paraformer/paraformer-models.html)** | INT8 ONNX，CPU | 约 244 MB | 自动识别中文与英文 | CPU 上的基础中英文转写；当前安装不带独立标点模型 | `paraformer-zh` |
| **[Fun-ASR-Nano](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512)** | FP16 ONNX + Q5_K GGUF；GPU：DirectML + Vulkan | 约 835 MB | 中文、英文、日语；上游 Nano 覆盖中文方言和地区口音 | 可尝试中文方言/口音，以及中英日听写 | `fun-asr-nano` |
| **[Qwen3-ASR 1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)** | 分拆 ONNX + Q4_K GGUF；GPU：DirectML + Vulkan | 约 1.41 GB | 自动识别 30 种语言，含中文、英文、粤语、日语 | 更广泛语种的语音转写 | `qwen3-asr` |

语言范围依据表中链接的上游原始模型资料；MurMur 使用列出的转换/量化版本，上游性能数据不代表本机安装的实测结果。这里的 Fun-ASR-Nano 是中英日 Nano，并非独立的 31 语种 MLT 模型。建议场景用于帮助选择，不是模型准确率排名。

模型默认存于 `D:\LocalProjects\MurMur\models`，保留现有 `sensevoice-small`、`sensevoice-small-dml`、`paraformer-zh`、`fun-asr-nano`、`qwen3-asr` 五个子目录。新配置、切换模型和命令行引擎覆盖统一使用此根目录；旧默认目录会迁移到这里，手动指定的其他目录继续保留。Fun-ASR-Nano 与 Qwen3-ASR 的 CPU / GPU 共用权重；首次安装还下载约 34 MB 的固定版 llama.cpp 运行库，保存在 `D:\LocalProjects\MurMur\runtimes\llama-b10621`。SenseVoice 切换到 GPU 时使用独立模型目录，旧 CPU 权重继续保留。SenseVoice 显卡模式需要 DirectML；两种 GGUF 引擎的显卡模式还需要 Vulkan 驱动。实际速度取决于硬件、音频长度及模型是否已加载，参考项目的星级和延迟不是本机测试结果。

Paraformer 目前没有独立标点模型，因此原始转写可能缺少标点。需要文字整理时可为所选文字模型开启 **Refine dictated text**；该步骤使用文字服务配置的接口。

手动导入时选择匹配的引擎与运行方式。SenseVoice CPU 与 Paraformer 使用 sherpa-onnx 格式的 `model.int8.onnx` 或 `model.onnx` 及 `tokens.txt`；其他三条路径使用 [CapsWriter-Offline 模型发布](https://github.com/HaujetZhao/CapsWriter-Offline/releases/tag/models)中对应归档的完整文件集合，选择解压后的模型目录。普通 Hugging Face / PyTorch 权重或其他 GGUF 转换不能直接导入。Fun-ASR-Nano / Qwen3-ASR 还需安装固定版本地运行库，可通过 **Download model** 完成。超过 30 秒的录音还需 `silero_vad.onnx`；没有 VAD 时应控制在 30 秒以内。

此接入提供纯文本听写与现有词典替换；没有接入上游的 CTC 热词对齐或 ForcedAligner 字级时间戳。文字润色、翻译与 Ask Anything 仍使用各自的文字服务。

**Bailian / DashScope 百炼：**默认端点为 `wss://dashscope.aliyuncs.com/api-ws/v1/inference`，Key 必须匹配区域。可使用模型支持的词汇上下文或 `vocabulary_id` 帮助识别术语。

**Alibaba Speech NLS：**默认端点为 `wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1`，语种遵从阿里项目配置。AppKey、NLS Token 和百炼 API Key 不能互换。保存 AccessKey 凭据后可自动取得 Token，并在临近过期时刷新；手动填写 Token 会覆盖缓存的自动 Token。

### 文字处理（LLM）

在 **Polish** 主卡片的模型下拉菜单选择 Local Auto、Qwen3.5 2B / 4B / 9B、DeepSeek Flash 或 Custom。**Advanced** 提供本地/在线来源、协议、地址、自定义模型和价格参数。预设只填写设置，不安装模型。已有地址、模型名称及凭据继续保留；选择新预设后，需要 **Save changes** 才应用草稿。

新配置默认本地来源和 **Auto · installed models**，初始地址为 `http://127.0.0.1:11434/v1`。选择 **Specify model** 可保留固定模型名称。通用接口通过 `/models` 获取模型列表；可选的 Ollama 协议使用 `/api/tags`。优先选择已知参数规模更小的模型，再比较文件大小；排除云端、远程和嵌入模型条目。需要已有本地服务和模型，MurMur 不直接加载 LLM 权重、不自动下载、不自动回退在线服务。Auto 测试成功后，顶部摘要才显示实际模型；仅获取模型列表不能证明模型已加载。

**API protocol** 位于 **Advanced**，同处还可填写 API 地址和可选 Token 单价。接口协议与 **Source** 分开选择：LM Studio、vLLM、Ollama 等本地服务都可以提供 OpenAI 兼容接口。确认本地服务为 Ollama 后，自动使用关闭思考的快速参数；未知服务保持通用请求格式。服务探测不发送个人文本。[Ollama 官方兼容说明](https://docs.ollama.com/api/openai-compatibility)。

**Source** 根据实际服务地址区分本机与在线；远程或局域网 Ollama 也显示为在线，因为文字离开本机。切换来源会保留两边的地址和模型草稿，保存时也保留备用在线配置。

| 服务 | 配置 |
| --- | --- |
| **DeepSeek · Flash** | 新预设使用 `https://api.deepseek.com/v1`、`deepseek-flash` 和自己的 API Key。[官方文档](https://api-docs.deepseek.com/)当前还列出 `deepseek-v4-pro`，可手动填写。旧保存模型名称不会自动替换。 |
| **Ollama** | `http://localhost:11434/v1`；启动本机服务并安装所选预设对应的模型。 |
| **其他兼容服务** | 填写完整 `/v1` 地址、模型名称和服务要求的 API Key。 |

| 文字模型选择 | 建议场景 | 前提 |
| --- | --- | --- |
| **Auto** | 从已安装的小型本地模型开始 | 本地服务已运行；测试成功后显示实际选择的模型 |
| **Qwen3.5 2B** | 轻量整理、短听写润色 | 本地服务已安装 `qwen3.5:2b` |
| **Qwen3.5 4B** | 日常整理、翻译与一般写作 | 本地服务已安装 `qwen3.5:4b` |
| **Qwen3.5 9B** | 较复杂的写作与编辑 | 已安装 `qwen3.5:9b`，需要更多内存与计算资源 |
| **DeepSeek Flash** | 在线整理、翻译与编辑 | 网络和 API Key；文字会发送至该服务 |
| **Custom / 已有模型** | 保留其他兼容本地或在线模型 | 填写接口地址、准确模型名并测试 |

2B / 4B / 9B 的场景建议是起步选择，不是实测速度或质量排名。已有 `qwen:latest`（4B）仍可在 **Specify model** 下继续使用；它不属于 Qwen3.5 预设，也不会被新预设提前选中。听写整理删除填充词、修正标点并保留原意。

再次点击 Right Alt 停止录音后，胶囊持续显示实际处理步骤：开启整理的听写为 **Transcribe → Polish**，语音翻译为 **Transcribe → Translate**，选中文字操作只显示其实际编辑步骤。紫色填充覆盖整个胶囊背景，百分比按已完成步骤数计算；两步流程为 0%、50%，取得有效结果后为 100%。它不估计模型内部进度，也不会随计时循环前进。完成后用 240 ms 动效展开为结果气泡。真实听写/翻译结果默认写入剪贴板，**Copy** 复制全文、**Edit** 打开编辑器、**Dismiss** 关闭；演示结果仍需手动复制。取消和下一次录音会终止旧动效，旧回调不会重新弹出气泡。

普通 Right Alt 听写将口语整理为清晰的书面表达：删除非语义填充词、无意重复和废弃开头，重组句子，并在原文已有层次时分段或列要点。明确的自我更正采用最后版本，包括术语和数值；保留真实的不确定性、否定、条件与观点，不把思考中的备选方案写成决定。中文仍是中文，中英混合保留应留下的英文术语；原有引文完整保留，原文中的问题或指令作为听写内容。关闭 **Refine transcription** 时直接使用识别文本，仍可应用个人字面替换规则。

翻译与 Ask 的编辑/写作共用同一套忠实表达标准：学术文字保持论证强度、术语、数值精度、单位和引用，日常沟通使用自然直接的措辞。翻译先整理非语义口语噪声，再表达为目标语言；原文中的问题仍译为问题。Ask 按语音要求执行任务，使用最后的明确更正，检查所要求的信息和排除项；改写保留选中文字的语言，除非要求翻译，普通问题仍按问答处理。默认使用连贯段落，不强制套用标题或列表。

统一标准位于 [提示词源码](murmur/prompts.py)，Ask 路由位于 [assistant.py](murmur/assistant.py)。重启应用后，旧的内置默认提示词会自动升级；自定义提示词、历史与凭据保留。已记录的本地样例检查及其限制见[文字整理验证记录](docs/SERVICES_AND_WRITING_VALIDATION.md)。

识别或整理失败时，原文保留在紧凑的错误气泡中，点击 **Copy／Edit** 才复制或打开编辑器；部分转写不会自动复制或上屏。没有转写时只显示原因和 **Dismiss**。已打开的选区编辑窗口在原位置显示错误。

离线语音使用 **Load & test** 检查文件并加载所选 ASR；在线语音和文字模型使用 **Test connection**。测试使用当前表单，不保存设置，也不录音。云端语音检查任务握手，文字服务发送固定短消息，在线测试可能消耗服务额度。测试进度与上次已完成的结果分开显示，重新检查期间保留旧结果，直到本次完成。顶部摘要和详情区分当前配置身份与成功测得的模型。修改相关草稿会使对应测试失效；保存凭据后密码框自动清空、继续使用相同已保存凭据时，不会误判为配置改变。

## Token 与费用

Home 直接显示累计本地 token，点击该计数进入 **Token usage** 查看服务实际返回的本机/外部文字模型 token、请求数和已知外部费用（USD）。从此版本开始累计，包括连接测试、润色、翻译和编辑；旧历史不能反推过去用量。缺失计数和未定价调用单独标注，不按文本长度猜测。`uv run murmur` 的终端在启动时打印累计本地用量，每次收到本地调用结果后打印输入、输出、合计和累计 token，不打印转写文本或凭据。

**Services → Polish → Advanced** 可选填输入、输出和缓存输入的 USD/百万 token 单价。显式填写输入/输出单价且缓存价留空时，输入价适用于全部输入 token。费用为估算，不代表账户余额或实际账单。保留的旧配置（如 `deepseek-chat`）不代表当前费率已知；没有手填单价或受支持的实际返回模型费率时，调用保持未定价，不套用旧价。服务返回的实际模型若已列明费率，按实际模型计价。音频识别计费、本机模型运行成本及 Codex/ChatGPT 用量不属于这些文字模型统计。

## 隐私与数据

- **凭据：**通过 Windows 凭据管理器保存，与普通 JSON 设置分开。密码字段留空表示保留已保存凭据。
- **本地文件：**设置、历史和可选录音默认位于 `D:\LocalProjects\MurMur\data`（`settings.json`、`history.db`、`audio`，以及出现相应错误时的 `startup-error.log`）。项目根的 `models` 保存语音模型，`runtimes\llama-b10621` 保存本地语音运行库。`--data-dir` 只覆盖应用数据位置，详见[存储说明](docs/LOCAL_STORAGE.md)。
- **凭据与文字模型：**服务凭据仍位于 Windows Credential Manager，Ollama 继续使用自己管理的原有模型存储。源码备份应排除私人应用数据、凭据、API.txt、模型权重和运行库。
- **音频：**默认不保存录音。离线语音在本机处理，云端语音会把音频发送给所选服务。
- **删除：**数据库删除失败时保留记录和音频；删除提交后才清理音频。被占用的文件持久排队，下次启动重试，历史页面会提示待清理状态。
- **词典存储：**旧设置的热词只初始化导入一次，之后以 SQLite 为准；设置缓存写入失败不会让已删除的词在重启后复活。
- **文字：**即使语音识别离线，云端文字服务仍会收到润色、翻译或编辑的文本。使用回环地址的 Ollama 或关闭润色可让听写保持本地处理；局域网或远程 Ollama 地址会把文本发送到对应服务器。
- **历史：**默认保留 90 天，设为 `0` 表示永久；删除和保留策略也会清理关联录音。
- **词汇分析：**在本机分析真实听写/翻译历史，逐条确认后加入词典，不分析演示记录。
- **仓库：**凭据、本地设置、历史数据库、录音、开发截图与构建产物通过 [`.gitignore`](.gitignore) 排除。

自动上屏核对原窗口和可编辑控件。焦点改变、用户修改内容、密码框、无法确认的控件或监听不可用时，回退预览。选区替换额外核对原选区位置和文字。成功的真实语音结果按默认行为覆盖剪贴板。随后自动粘贴会恢复该结果，除非用户已经复制了新内容。选区捕获/替换事务尽可能保留之前的纯文本；富文本等复杂格式回退预览。部分应用可能需要手动复制。

## 常见问题

| 情况 | 检查方法 |
| --- | --- |
| 出现模拟文字而非真实识别 | 配置语音服务，关闭 Demo mode 并保存。 |
| 无法自动上屏 | 从预览 Copy；检查目标控件、焦点、权限及快捷键监听。 |
| 云端鉴权失败 | 检查凭据类型、端点区域、服务状态，并运行 Test connection。 |
| 离线识别不可用 | 选择匹配的本地引擎，下载或选择该模型的完整目录，验证后保存。 |
| Paraformer 结果缺少标点 | 配置文字模型并启用 Refine dictated text 进行整理。 |
| Ollama 无法连接 | 启动本机服务，确认配置的模型已安装。 |
| 关闭窗口后仍在运行 | 从托盘选择 **Quit MurMur**。 |

## 开发与验证

```powershell
uv sync --group dev --locked
uv run pytest -q

# 隔离目录中的演示截图，禁用全局快捷键监听。
uv run murmur --no-hotkeys --data-dir work/qa-data --screenshots work/qa-screenshots
```

离线文件转写前需配置模型。输入必须为单声道、16 kHz、16-bit PCM WAV：

```powershell
uv run murmur --transcribe-wav sample.wav --output-file transcript.txt

# 先在 Settings 安装所选引擎；仅覆盖本次命令，不改保存配置。
uv run murmur --offline-engine qwen_asr --offline-acceleration gpu --transcribe-wav sample.wav --output-file transcript.txt
```

| 模块 | 源码 |
| --- | --- |
| 生命周期与会话控制 | [`app.py`](murmur/app.py) |
| 主窗口、胶囊与预览 | [`dashboard.py`](murmur/dashboard.py)、[`ui.py`](murmur/ui.py) |
| 语音与文字服务 | [`providers.py`](murmur/providers.py)、[`ali_nls.py`](murmur/ali_nls.py)、[`offline.py`](murmur/offline.py) |
| 存储与洞察 | [`storage.py`](murmur/storage.py)、[`insights.py`](murmur/insights.py) |
| Windows 集成 | [`hotkeys.py`](murmur/hotkeys.py)、[`windows.py`](murmur/windows.py)、[`clipboard.py`](murmur/clipboard.py) |

**2026-10-04** 此前记录的完整回归为 **927 项通过**，有三条上游依赖弃用警告。本次源码上传前，**95 项专项测试通过**，用时 8.71 秒。这是本地执行记录，不是 CI 徽章。源码启动、SenseVoice 与 Paraformer 官方样本离线识别和部分真实服务已验证；跨应用的完整真人听写到上屏、Windows 10、AltGr/输入法组合和混合 DPI 多屏仍需现场测试。[验证记录](docs/VALIDATION.md)包含此前测试结果，并区分真实、模拟与待验收项目。

通过 [GitHub Issues](https://github.com/Chauncy-Du/murmur/issues)反馈问题或建议。请提供版本、服务和复现步骤；分享日志或截图前去掉凭据、个人文本和可识别个人的路径。


正式版本、Beta 版本及后续 Windows 安装包要求见[发布规则](docs/RELEASING.md)。

## 许可证与致谢

MurMur 源码采用 [MIT 许可证](LICENSE)。依赖及模型权重各自遵循原许可证。SenseVoice 使用独立的 [FunASR 模型协议](docs/FunASR-MODEL_LICENSE.txt)；固定版本的 Paraformer 转换模型卡标注 Apache-2.0，安装时也保留 FunASR 模型家族协议。具体来源与条款见安装目录的许可文件和[第三方说明](THIRD_PARTY_NOTICES.md)。

感谢 CapsWriter-Offline 的架构启发，以及 SenseVoice、Paraformer、sherpa-onnx、Silero VAD、Qt/PySide6 和 Python 社区。MurMur 的应用代码独立编写，使用自有视觉素材。来源及许可证详见[第三方说明](THIRD_PARTY_NOTICES.md)。

---

<div align="center">

<img src="docs/assets/logo.svg" width="40" height="40" alt="MurMur Logo" />

**自然表达，掌控每一个字。**

[English](README.md) · [简体中文](README.zh-CN.md) · [反馈问题](https://github.com/Chauncy-Du/murmur/issues)

</div>


[v0.4.0 源码状态](docs/RELEASE_0.4.0.md)。
