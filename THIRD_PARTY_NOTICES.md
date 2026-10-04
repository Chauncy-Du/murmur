# 第三方及参考说明

CapsWriter-Offline：https://github.com/HaujetZhao/CapsWriter-Offline

参考版本：84912d5218ee5e51e216c54dc15a1cb0f466eb76（2026-10-04 获取）。MIT，Copyright (c) 2026 Haujet Zhao。许可证原文见 docs/CapsWriter-Offline-LICENSE.txt。已阅读 recorder.py、hot_rule.py、global_hotkey.py、tray.py、llm_clipboard.py、llm_message_builder.py。MurMur 的录音、界面和会话控制独立编写，借鉴分层、录音队列、字词修正、托盘和剪贴板保护思路。本次 ONNX/GGUF 接入改编上游的 llama、Fun-ASR-Nano、Qwen3-ASR、SenseVoice 推理辅助代码，保留在 murmur/vendor/capswriter；原文件映射、改动说明与完整 MIT 许可见该目录的 NOTICE.md 和 LICENSE。

公开视觉参考：https://www.typeless.com/ 。MurMur 使用自有界面图标及英文界面，不包含 Typeless 商标素材。Services 模型菜单使用经来源核对的提供商品牌标识；官方来源、保留的许可证、渲染适配与中性功能图标的区别见 [PROVIDER_ICONS.md](docs/PROVIDER_ICONS.md)。

语音协议参考：https://www.alibabacloud.com/help/en/model-studio/fun-asr-realtime-python-sdk （文档更新 2026-09-29）。使用 Recognition.start / send_audio_frame / stop 与 RecognitionCallback，PCM 16 kHz，每帧约 100 ms。

主要依赖：PySide6（LGPLv3/GPLv3/commercial，便携包动态链接）、sounddevice（MIT）、DashScope（Apache-2.0）、httpx（BSD-3-Clause）、keyring（MIT）、pynput（LGPLv3）、pywin32（PSF）、PyInstaller（GPL with bootloader exception）。最终版本见 uv.lock，便携包内附依赖 dist-info 许可证及 PySide6 LGPL/GPL 文件。修改版源码和构建方式随项目提供；商业分发前需按实际依赖许可证履行通知及可替换动态库等义务。


离线识别参考 CapsWriter-Offline 的本地模型选择和录音后识别流程，使用独立实现与 sherpa-onnx 官方 Python API：[SenseVoice](https://k2-fsa.github.io/sherpa/onnx/sense-voice/python-api.html)、[Paraformer](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-paraformer/paraformer-models.html)。sherpa-onnx 1.13.8 / sherpa-onnx-core 1.13.8（Apache-2.0），实际加载的 CPU ONNX Runtime 为 1.28.2（MIT，已通过 DLL GetVersionString 实测），Silero VAD（MIT）。本机 CPU 在录音停止后识别，不包含云端自动回退；下载仅发生在用户主动选择 Download model 时。

支持四种本地语音模型：SenseVoice Small、Paraformer、Fun-ASR-Nano 与 Qwen3-ASR 1.7B。全新配置默认 SenseVoice CPU、Demo 关闭；已明确保存的语音服务和 Demo 选择继续保留。SenseVoice CPU 与 Paraformer 使用 sherpa-onnx 格式；SenseVoice GPU 使用 CapsWriter 分拆 ONNX，Fun-ASR-Nano 与 Qwen3-ASR 使用对应 ONNX + GGUF 格式。长录音还需 silero_vad.onnx。推理辅助库只接受对应转换文件结构，不声明支持任意 GGUF 或 PyTorch 权重。

扩展推理依赖 gguf 0.19.0（MIT）、onnxruntime-directml 1.24.4（MIT）、sentencepiece 0.2.1（Apache-2.0）以及 llama.cpp b10621（MIT）。固定版官方 Windows Vulkan 归档校验后，只安装允许列表中的运行库及许可证，不安装其中的示例 EXE。运行库安装目录保留 LICENSE-llama.cpp.txt、LICENSE-LLVM-OpenMP 和来源 SHA256 清单。ONNX DirectML / GGUF Vulkan 在独立子进程运行，避免与父进程 sherpa 的 ONNX Runtime 1.28.2 DLL 冲突；VAD 保留 CPU 路径。CPU/GPU 加速检测失败提示错误，不自动请求云端。

SenseVoice GPU、Fun-ASR-Nano Q5_K 与 Qwen3-ASR 1.7B Q4_K 的转换归档来自 CapsWriter-Offline 的 models Release，大小和 SHA256 固定在 murmur/models.py。解压仅接受清单内文件，整个归档认证成功后记录每个成员的 SHA256。下载目录保留上游转换 MIT 许可、原模型许可、模型卡（适用时）、Silero 许可及 NOTICE。Fun-ASR-Nano 原模型来自 FunAudioLLM/Fun-ASR-Nano-2512，固定模型卡 revision 272c57b82523ada6fd87095e955f8e29100979ab；Qwen 来自 Qwen/Qwen3-ASR-1.7B，固定模型卡 revision 7278e1e70fe206f11671096ffdd38061171dd6e5；两者模型卡标注 Apache-2.0，具体文本随下载保留为 MODEL_LICENSE。此适配器提供纯文本听写，未接入上游 CTC 热词对齐或 ForcedAligner 字级时间戳。

SenseVoiceSmall 权重归 Alibaba Group；ONNX INT8 转换来自 csukuangfj/sherpa-onnx，固定 revision 2365baeacb507f821a0c8120fcee3d484dba7a07。转换仓库的 LICENSE 链接 FunASR Model Open Source License Agreement；权重不按源码 MIT/Apache 许可处理，实际模型条款见 docs/FunASR-MODEL_LICENSE.txt。下载目录保留模型名、作者、转换来源、LICENSE、MODEL_LICENSE、NOTICE.txt 和 SHA256 清单。模型不嵌入便携包，首次下载或手动导入后本地推理。

Paraformer Chinese + English INT8 使用 [csukuangfj/sherpa-onnx-paraformer-zh-2023-09-14](https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-2023-09-14/tree/def027084691107096b5ebba69785756d63de6c5)，固定 revision def027084691107096b5ebba69785756d63de6c5。模型来源为 Alibaba/FunASR，ONNX 转换由 csukuangfj/sherpa-onnx 提供。[固定模型卡](https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-2023-09-14/blob/def027084691107096b5ebba69785756d63de6c5/README.md)标注 Apache-2.0；下载目录保留该 README.md、Apache-2.0 LICENSE、FunASR 模型家族协议 MODEL_LICENSE、Silero 许可证及 NOTICE.txt，分别记录来源。模型、词表和 VAD 合计约 244 MB，逐文件验证固定大小与 SHA256。自动识别中文与英文；本实现没有加载独立标点模型，因此原始结果可能没有标点。文字整理使用用户配置的独立 LLM 服务。

Alibaba NLS 接口独立实现，协议来源：https://help.aliyun.com/zh/isi/user-guide/websocket 。通过 websocket-client（Apache-2.0）连接，不包含阿里云私有 SDK 代码。numpy（BSD-3-Clause）和 comtypes（MIT）用于离线处理及 Windows UI Automation。最终依赖版本以 uv.lock 为准。
