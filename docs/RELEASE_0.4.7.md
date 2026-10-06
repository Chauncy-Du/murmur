# MurMur 0.4.7 · Beta

Date: 2026-10-06. This source snapshot includes the current changes since v0.4.6.

- Refactor and improve the home page, activity calendar, token panel, window chrome and account/profile controls.
- Improve service identity and availability, resource/memory reporting, console output and release checking.
- Prepare the local speech model at startup with operation locking and explicit error recovery. See [startup loading](STARTUP_MODEL_LOADING.md).
- Keep the microphone ready by default and use a bounded 500 ms pre-record buffer; disabling standby restores on-demand capture. Idle audio is not uploaded or saved. See [microphone standby](PRE_RECORDING.md).
- Include the current floating-layout, controller, account isolation, service settings and native-runtime optimizations. Credentials, recordings, user profiles, models and runtimes are excluded from the public source.

## Validation and distribution

Before this upload, **290 affected regression tests passed, 2 failed** with the operational source/test/asset hashes unchanged across the run. Source identity and lockfile agree on 0.4.7. Prior feature-specific records remain historical and are not added to this total.

The combined run had two failures: dashboard resource-card shimmer, and HTTP profile saving. In a separate rerun of these two checks, the resource-card check passed, while the HTTP-profile test still failed because its SimpleNamespace test window has no `check_saved_services` method (1 passed, 1 failed). These reruns are not added to the combined count. The prior 0.4.6 dots-waveform check passed in this run. This snapshot preserves current implementation and test fixtures; no full-green regression is claimed.

No new live microphone, physical-hotkey, cloud-service or installer acceptance is claimed by this source upload. Model quality and cross-application delivery retain their documented limits. The [portable security block](PORTABLE_SECURITY_BLOCK.txt) remains in place. No binaries, models, runtimes, credentials or private data are published. This push updates main and creates v0.4.7, without creating a GitHub Release.

## 中文

0.4.7 将当前首页/日历/用量面板、账户与独立配置、窗口外观、服务身份/可用性、资源统计、启动模型加载、麦克风待机与有限预录，以及控制器/运行库优化纳入源码提交。上传前 290 项通过、2 项失败，源码/测试/资源哈希稳定。测试的具体通过/失败情况见上方验证说明；此前 0.4.6 的失败记录作为历史保留，不视为本版结论。此推送不代表新增真人设备、云服务或安装包验收；既有安全阻挡与私人数据排除规则保留。
