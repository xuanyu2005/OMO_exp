# OMO Exp

本仓库用于复现和记录 OpenCode + Oh-My-OpenAgent（OMO）在 SWE-bench Verified Mini 上的对照实验。

## 研究问题

1. 在同一模型下，带 OMO 插件是否比不带 OMO 插件更好？
2. 在带 OMO 插件时，所有角色配置单一模型是否比多模型角色分工更差？

## 实验组

| 组别 | 说明 |
| --- | --- |
| Baseline | 不启用 OMO，单模型直接修复 SWE-bench issue |
| OMO Single | 启用 OMO，但所有 agent/category 绑定同一模型 |
| OMO Multi | 启用 OMO，并按 parent/executor/reviewer/deep 等角色配置不同模型 |

当前报告重点比较 GPT-5.4 与 Claude Sonnet 4.6 两类正式 API 结果，并把 forced delegation、optional-on-uncertainty、post-patch-review 等 OMO multi 策略作为诊断实验单独分析。

## 仓库结构

```text
.
├── docs/
│   ├── 实验记录.md                  # 实验过程记录
│   ├── 实验分析.md                  # 主要结果与机制分析
│   └── swebench_local_environment.md # 本地评测环境说明
├── experiments/
│   ├── configs/                     # 正式 API / OMO 配置
│   └── data/swe-bench-verified-mini/ # 选题清单与小型数据集元信息
├── patches/
│   └── omo-task-id-continuation-fix.patch
├── scripts/                         # runner、proxy、metrics、summary 脚本
└── oh-my-openagent/                 # 上游 OMO 子模块
```

## 不纳入仓库的内容

以下内容为本地运行缓存或调试资产，不提交到 GitHub：

- API 密钥与本地环境文件：`.env`、`.env.*`
- 硅基流动调试配置、文档和指标
- SWE-bench 大型运行工作区：`experiments/workspaces/`
- 原始运行缓存、prediction、batch 临时目录、proxy 请求日志
- Python 虚拟环境和缓存目录

## 快速开始

```powershell
uv sync
uv run python scripts\check_swebench_env.py
```

复制 `.env.example` 并填入本地正式 API 环境变量后，可通过 `scripts/run_formal_swebench_case.py` 或 `scripts/run_formal_swebench_batch.py` 运行单题或批量实验。

## OMO 本地补丁

实验中发现 OMO 在新建 delegated task 时，如果模型误填 `task_id`，原逻辑可能误判为 continuation，导致子任务卡住。本仓库在 `patches/omo-task-id-continuation-fix.patch` 中保留了该修复。

如果使用未修复的 OMO 子模块，可在 `oh-my-openagent/` 下应用：

```powershell
git apply ..\patches\omo-task-id-continuation-fix.patch
```

## 报告入口

- `docs/实验记录.md`：记录实验背景、配置、运行过程和结果表。
- `docs/实验分析.md`：回答两个研究问题，并分析 OMO Single / OMO Multi 的收益边界。
- `docs/swebench_local_environment.md`：记录本地 SWE-bench harness 环境。
