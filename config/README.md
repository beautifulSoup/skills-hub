# config/

运行时配置目录。

- `tools.yaml` — 工具清单（id / name / supports / paths / install_methods），驱动安装目标（Claude Code、WorkBuddy 等）。容器内通过 `TOOLS_YAML_PATH` 指向此文件（默认 `/config/tools.yaml`）。
