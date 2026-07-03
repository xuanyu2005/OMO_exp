# Oh-My-OpenAgent Orchestration Experiment

本仓库用于提交“调研 Oh-My-OpenAgent 的 agent orchestration 机制，并设计小型实验验证其是否带来真实提升”的课程作业。

## 仓库结构

```text
.
├── docs/
│   ├── assignment_redacted.md      # 脱敏后的作业要求
│   └── report.md                   # 最终报告草稿
├── experiments/
│   ├── README.md                   # 实验设计说明
│   ├── tasks/task_suite.md         # 小型任务集与评分标准
│   ├── configs/                    # 三组对照配置模板
│   └── results/                    # 结果记录模板
├── scripts/
│   └── summarize_results.py        # 汇总评分表的小脚本
├── oh-my-openagent/                # 上游项目源码，作为 Git submodule
└── .env.example                    # API 环境变量模板，不含密钥
```

## 研究问题

本作业验证两个问题：

1. 带 Oh-My-OpenAgent orchestration 的 agent harness 是否优于不带 OMO 的单模型基线？
2. 在带 OMO 的条件下，多模型角色分工是否优于所有 agent 都使用同一模型？

## 对照组

| 组别 | 说明 | 目标 |
| --- | --- | --- |
| A. Single Model Baseline | 不使用 OMO，仅使用单一模型完成任务 | 衡量普通单模型表现 |
| B. OMO Single Model | 使用 OMO，但所有 agent/category 绑定同一模型 | 分离“编排机制”本身的收益 |
| C. OMO Multi Model | 使用 OMO，并按 planner/executor/search/reviewer 配置不同模型 | 检验模型互补与角色路由收益 |

## 快速开始

1. 克隆本仓库时拉取上游子模块：

```bash
git clone --recurse-submodules <your-repo-url>
```

2. 本地配置 API key：

```bash
cp .env.example .env
```

3. 按 `experiments/tasks/task_suite.md` 执行任务，并将结果填入：

```text
experiments/results/results_template.csv
```

4. 汇总结果：

```bash
python scripts/summarize_results.py experiments/results/results_template.csv
```

## 当前状态

- 已建立 GitHub 提交仓库骨架。
- 已将含有 API key 的原始作业文件加入 `.gitignore`，避免误提交。
- 已提供报告、实验设计、配置和评分模板。

