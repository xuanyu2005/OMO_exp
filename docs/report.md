# Oh-My-OpenAgent Agent Orchestration 机制调研与小型实验报告

## 摘要

本文调研 Oh-My-OpenAgent 的 agent orchestration 机制，并通过小型对照实验评估其相较单模型基线是否带来真实收益。实验设置三组条件：不使用 OMO 的单模型基线、使用 OMO 但所有 agent 绑定同一模型、使用 OMO 且按角色绑定不同模型。评价维度包括任务成功率、输出质量、验证通过率、耗时和 API 成本。

> 当前报告为实验前骨架。完成实验后，需要将 `experiments/results/results_template.csv` 的结果填入本文。

## 1. 背景与研究问题

大语言模型 agent 在真实开发任务中常见失败模式包括：上下文过载、规划与执行混杂、检索不充分、局部修改后缺少验证、以及长任务中的目标漂移。Oh-My-OpenAgent 的核心主张是通过多 agent 编排、角色分工、工具增强和模型路由，将复杂任务拆成更稳定的工作流。

本文关注两个问题：

1. 使用 OMO 编排后，是否比不使用 OMO 的单模型 agent 更好？
2. 在使用 OMO 的情况下，多模型角色分工是否比所有 agent 使用同一模型更好？

## 2. Oh-My-OpenAgent 编排机制概述

根据仓库文档，OMO 的 orchestration 机制主要由以下部分构成：

- **规划层**：Prometheus 负责访谈、澄清需求并生成计划；Metis 用于发现计划缺口；Momus 用于高精度计划审查。
- **执行层**：Atlas 读取计划、拆解任务、调度 worker，并在执行过程中积累经验与验证结果。
- **工作层**：Sisyphus-Junior 执行具体代码任务；Oracle 偏架构/调试；Explore 偏代码检索；Librarian 偏文档和外部资料检索。
- **类别路由**：用户或上层 agent 不直接指定模型，而是指定 `quick`、`deep`、`ultrabrain`、`visual-engineering` 等语义类别，再映射到具体模型。
- **并发与 fallback**：后台任务可以按 provider/model 限制并发；模型失败时可进入 fallback 链。

这种设计的核心不是简单“多调用几个模型”，而是将规划、检索、实现、审查、验证分成更小的认知角色，并通过 prompt、权限和工具约束降低长任务漂移。

## 3. 实验设计

### 3.1 对照组

| 组别 | 配置 | 目的 |
| --- | --- | --- |
| A | 不使用 OMO，单一模型 | 建立普通 agent 基线 |
| B | 使用 OMO，所有 agent/category 使用同一模型 | 隔离 orchestration 机制收益 |
| C | 使用 OMO，planner/executor/search/reviewer 使用不同模型 | 检验多模型互补收益 |

### 3.2 任务集

任务集见 `experiments/tasks/task_suite.md`。任务覆盖代码理解、bug 修复、测试补全、重构方案、文档检索与结果解释。

### 3.3 指标

- **Success**：是否完成任务要求。
- **Verification**：测试、构建或人工检查是否通过。
- **Quality Score**：人工 1-5 分，衡量正确性、完整性、可维护性。
- **Time Seconds**：完成耗时。
- **Estimated Cost USD**：估算 API 成本。
- **Failure Mode**：失败原因分类，如理解错误、修改错误、遗漏验证、过度修改、工具失败等。

## 4. 实验结果

待填入实验结果。

| 组别 | 成功率 | 平均质量分 | 平均耗时 | 平均成本 | 主要失败模式 |
| --- | ---: | ---: | ---: | ---: | --- |
| A. Single Model Baseline | TBD | TBD | TBD | TBD | TBD |
| B. OMO Single Model | TBD | TBD | TBD | TBD | TBD |
| C. OMO Multi Model | TBD | TBD | TBD | TBD | TBD |

## 5. 分析

完成实验后重点分析：

- 如果 B 优于 A，说明收益主要来自 orchestration：规划-执行分离、上下文隔离、专门检索、持续验证等。
- 如果 C 优于 B，说明收益进一步来自模型互补：强推理模型适合规划/审查，快速低成本模型适合检索和局部执行。
- 如果 C 没有优于 B，需要检查是否任务太简单、调度开销过大、模型路由不合理，或评分指标没有捕捉复杂任务收益。
- 如果 OMO 组成本显著更高，需要讨论“质量提升是否值得成本”。

## 6. 初步结论

当前仓库已完成实验框架搭建。最终结论应以实际运行结果为准，不能仅根据 OMO 的设计主张下判断。

## 7. 可复现性说明

- 上游源码作为 Git submodule 保留在 `oh-my-openagent/`。
- API key 不提交；本地通过 `.env` 配置。
- 实验任务、配置和结果模板均在 `experiments/` 下。

