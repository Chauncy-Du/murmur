# MurMur 0.4.6 · Beta

Date: 2026-10-06. This source snapshot includes the current changes since v0.4.5.

- Configurable floating capsule/result appearance, motion, placement, pointer following and draft previews. See [appearance](BUBBLE_APPEARANCE.md).
- Smooth estimated processing progress and task-specific stage hints. Estimates do not represent server-reported completion; 100% requires validated completion. See [progress](ESTIMATED_PROGRESS.md).
- Result review and smart delivery, paste receipts, storage-usage controls and model selection improvements.
- ProjectHub model discovery and asynchronous job recovery, plus dictation reconstruction and prompt/source isolation safeguards. See [ProjectHub configuration](PROJECTHUB_API.md). Credentials remain in Windows Credential Manager; recovery records belong to private application data.

## Validation and distribution

Before this upload, **492 affected regression tests passed, 1 failed** with the operational source/test/asset hashes unchanged across the run. Source identity and lockfile agree on 0.4.6. Prior feature-specific records remain historical and are not added to this total.

Known failing check: `test_wave_layout_styles.py::test_each_style_uses_real_input_and_silence_then_fades[12-dots]` at 125% offscreen scaling. The 12-pixel dots image did not differ from silence immediately after feeding levels. An isolated rerun also failed (33 passed, 1 failed). This snapshot retains the current implementation; no fix or full-green regression is claimed.

No new live microphone, physical-hotkey, cloud-service or installer acceptance is claimed by this source upload. Model quality and cross-application delivery retain their documented limits. The [portable security block](PORTABLE_SECURITY_BLOCK.txt) remains in place. No binaries, models, runtimes, credentials or private data are published. This push updates main and creates v0.4.6, without creating a GitHub Release.

## 中文

0.4.6 将当前气泡外观/动效、估算进度、结果审阅和交付保护、存储统计、模型选择、ProjectHub 接口及听写整理相关改动纳入源码提交。上传前 492 项通过、1 项失败，源码/测试/资源哈希稳定。失败为 125% 离屏缩放下 12 像素 dots 波形的图像对比，单独复测仍失败；本次保留当前实现，不宣称全绿。此推送不代表新增真人设备、云服务或安装包验收；既有安全阻挡与私人数据排除规则保留。
