# 在本地运行 MurMur

当前版本的默认数据、语音模型及原生运行库根目录为 `D:\LocalProjects\MurMur`。首次安装步骤见 [README.zh-CN.md](README.zh-CN.md)。

首次安装或更新依赖时，在项目目录运行 `uv sync --locked`。日常使用双击 `Start-MurMur.cmd`，或运行 `.\scripts\start.ps1 -SkipSync`；两者均使用已有环境，不同步依赖。脚本默认模式 `.\scripts\start.ps1` 会先同步锁定依赖。

先从托盘选择 **Quit MurMur** 退出先前实例。正常启动入口不传入 `--data-dir`，保留单实例行为。模型需要在 Settings 中另行下载或导入；凭据保存在 Windows Credential Manager。

存储位置见 [LOCAL_STORAGE.md](docs/LOCAL_STORAGE.md)。源码不包含私人配置、历史、录音、模型、原生运行库或内部迁移证据。便携构建的安全阻挡继续保留。
