# 实验说明

本目录保存小型实验的任务集、三组配置模板和结果记录。

## 三组实验

1. `baseline_single_model.md`
   - 不使用 Oh-My-OpenAgent。
   - 用单一模型直接完成每个任务。

2. `omo_single_model.jsonc`
   - 使用 Oh-My-OpenAgent。
   - 所有 agent 和 category 都绑定同一模型。

3. `omo_multi_model.jsonc`
   - 使用 Oh-My-OpenAgent。
   - planner / executor / search / reviewer 使用不同模型或不同 category。

## 执行原则

- 每个任务对三组条件使用同一 prompt。
- 每次运行保存输出和验证结果。
- 不把 API key、完整 token 日志或敏感请求头提交到仓库。
- 若某组失败，记录真实失败原因，不手动修正结果。

