# Release policy

[English](../README.md) · [简体中文](../README.zh-CN.md)

## Version channels

| Version change | Git tag example | GitHub Release | Distributed assets |
| --- | --- | --- | --- |
| Minor milestone (`0.x.0`) | `v0.4.0` | Regular release | Windows installer when packaging is available and validated. |
| Patch update (`0.x.y`, `y > 0`) | `v0.4.1` | **Pre-release / Beta** | Release notes only; no installer or portable executable. |

A patch update is Beta even if its tag has no `-beta` suffix. Each Release must explain the actual changes and any relevant limitations. GitHub's automatically generated source archives may remain available in either channel.

## Windows distribution

Future minor milestones must use an **installable Windows package**, such as a setup `.exe` or `.msi`. A standalone executable or portable ZIP does not satisfy the installer requirement. Validate installation, launch, upgrade, and uninstallation before publishing an installer; preserve user data and keep credentials out of every artifact.

Existing portable build scripts are development tooling, not the future release distribution format. Packaging work and the outstanding security review must be completed before installer delivery. Do not bypass security blocks or publish an unverified installer.

## Current source snapshot

**The current v0.4.5 upload is a source-only snapshot on `main`.** This upload does not create a GitHub Release or attach an installer, EXE or portable ZIP. It does not change the future minor-version installer requirement.

## 中文说明

- `0.x.0` 为阶段性正式版本，例如 `v0.4.0`；后续此类版本提供通过验证的 Windows 安装包。
- `0.x.y`（`y > 0`）为 Beta，例如 `v0.4.1`；在 GitHub 勾选 Pre-release，只说明更新内容，不上传安装包或便携 EXE。
- 安装包应为 setup `.exe` 或 `.msi`，支持安装、升级和卸载；不能用直接运行的 EXE 或便携 ZIP 代替。
- 发布说明必须对应已提交的实际改动，注明已知限制。GitHub 自动生成的源码归档不属于安装包。
- 当前 `v0.4.5` 仅将源码快照上传到 `main`，不创建 GitHub Release，不附加安装包、EXE 或便携 ZIP；后续阶段版本的安装包要求仍保留。现有便携构建脚本不代表安装包已经实现，组织安全阻挡仍需处理。
