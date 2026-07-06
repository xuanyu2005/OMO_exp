# SWE-bench Verified Mini 本地运行环境

本文档记录当前仓库中用于 OpenCode + OMO 实验的 SWE-bench 本地评测环境。

## 环境管理

Python 环境使用 UV 管理，项目固定使用 Python 3.11：

```powershell
uv sync
```

同步完成后，运行环境检查：

```powershell
uv run python scripts\check_swebench_env.py
```

该检查会确认：

- `uv` 可用；
- Docker CLI 和 Docker daemon 可用；
- Python 环境中可以导入 `swebench`；
- 本地 SWE-bench Verified Mini JSONL 数据存在，且默认有 50 条样本。

注意：Windows 原生 Python 可以用于数据准备脚本，但官方 `swebench.harness.run_evaluation` 依赖 Unix-only 的 `resource` 模块。因此正式评测建议在 WSL/Linux 中运行。当前机器已检测到 WSL2 发行版 `my-old-linux`，且其中有 `uv`、`python3`、`docker`，可以访问本仓库路径：

```text
/mnt/e/Research/深度内核
```

WSL 中建议使用单独的虚拟环境目录，避免覆盖 Windows 下的 `.venv`：

```bash
cd "/mnt/e/Research/深度内核"
UV_PROJECT_ENVIRONMENT=.venv-wsl uv sync
UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python scripts/check_swebench_env.py
```

## 数据集

本地数据集路径：

```text
experiments\data\swe-bench-verified-mini\test.jsonl
```

该数据集包含 50 条 SWE-bench Verified Mini 样本，其中 `django/django` 25 条，`sphinx-doc/sphinx` 25 条。

## Gold Patch Smoke Test

正式运行 OpenCode / OMO 之前，建议先用数据集自带的 gold patch 跑通一次 SWE-bench harness。先生成 1 条 prediction JSONL：

```powershell
uv run python scripts\make_gold_predictions.py --limit 1 --output experiments\results\predictions\gold_smoke.jsonl
```

然后在 WSL 中用官方 harness 评测该 prediction。这里使用本地 JSONL 路径作为 `--dataset_name`，避免每次评测都从 HuggingFace 在线拉取数据集元信息：

```bash
UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python -m swebench.harness.run_evaluation \
  --dataset_name experiments/data/swe-bench-verified-mini/test.jsonl \
  --split test \
  --predictions_path experiments/results/predictions/gold_smoke.jsonl \
  --instance_ids django__django-11790 \
  --max_workers 1 \
  --run_id verified-mini-gold-smoke-local \
  --report_dir experiments/results/reports
```

当前仓库已完成一次 gold patch smoke test，结果如下：

- 运行实例数：1
- 完成实例数：1
- resolved 实例数：1
- 实例 ID：`django__django-11790`

这说明 WSL + UV + Docker + SWE-bench harness 的本地评测链路已经跑通。

## 正式实验接入方式

OpenCode / OMO 每完成一个实例后，需要把最终 `git diff` 保存为 SWE-bench prediction JSONL 中的 `model_patch` 字段。每一行格式如下：

```json
{"instance_id":"django__django-11790","model_name_or_path":"opencode-gpt-5.4-mini","model_patch":"diff --git ..."}
```

推荐流程：

1. 用 OpenCode 或 OpenCode + OMO 在对应 `base_commit` 上生成修复。
2. 保存最终 patch。
3. 汇总成 prediction JSONL。
4. 用 `swebench.harness.run_evaluation` 统一评分。

这样可以把 agent 解题过程和 SWE-bench 官方判分过程分开，减少实验混淆。
