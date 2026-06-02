# eval_runner.py 说明文档

## 概述

DeathPlaylist Harness 评测运行器。调用 Aider 执行 coding task，通过多层验证判定结果。

## 架构

```
eval_runner.py
  ├── 配置加载
  │   ├── tasks.yaml           — 任务定义
  │   └── harness_configs.yaml — 实验配置
  ├── 执行引擎
  │   ├── run_with_feedback()  — 多轮反馈循环
  │   ├── run_agent()          — 调用 Aider
  │   └── _run_test_command()  — 运行测试
  ├── 验证层
  │   ├── baseline check       — 验证 broken baseline
  │   ├── oracle test          — 任务专属测试
  │   ├── regression test      — 回归测试
  │   └── scope check          — 文件作用域检查
  ├── 评分
  │   └── build_scorecard()    — 多维 scorecard
  └── 输出
      ├── artifact 保存        — 日志、patch、prompt
      └── generate_report()    — 汇总报告
```

## 命令行用法

```bash
# 跑单个任务（指定 harness config）
python eval_runner.py --model glm-5.1 --task T001 --harness-config H0_baseline --runs 3

# 跑所有任务
python eval_runner.py --model glm-5.1 --all --harness-config H2_structured_prompt

# 查看报告
python eval_runner.py --report

# 对比指定 config
python eval_runner.py --report --compare H0_baseline H4_feedback_2round H6_repo_map_4096
```

## Harness Config 四层架构

| 层 | 配置项 | 说明 |
|---|---|---|
| Prompt Layer | `prompt_template` | raw / constrained / structured |
| Context Layer | `context_mode` + `map_tokens` | file_args_only / oracle_visible / repo_map / focused_context |
| Execution Layer | `feedback_rounds` | 1 / 2 / 3 轮反馈循环 |
| Control & Audit | `scope_guard` + `audit_level` | post_check / basic / full |

## 执行流程

```
1. 加载 tasks.yaml + harness_configs.yaml
2. create_worktree() — 复制项目到隔离目录
3. baseline check — 验证 broken baseline oracle 会失败
4. run_with_feedback():
   for round in feedback_rounds:
     a. render_prompt() — 按 config 模板渲染任务描述
     b. run_agent() — 调用 Aider 执行修改
     c. run oracle test
     d. 如果 oracle 通过 → run regression test → 结束
     e. 如果 oracle 失败且还有轮次 → 把测试输出喂回 agent
5. scope check — 检查文件作用域
6. build_scorecard() — 多维评分
7. 保存 artifact + 结果
```

## 结果目录结构

```
eval_results/
  H0_baseline/
    T001_glm-5.1.json           # 汇总
  H4_feedback_2round/
    T001_glm-5.1.json
    runs/
      20260603_120000_T001_glm-5.1_H4_feedback_2round_0/
        metrics.json
        patch.diff
        prompt.md                # audit_level=full 时
        agent_stdout.log
        agent_stderr.log
        oracle_stdout.log
        oracle_stderr.log
        regression_stdout.log
        regression_stderr.log
        per_round_metrics.json   # audit_level=full 时
```

## Scorecard 维度

| 维度 | 含义 |
|------|------|
| agent_execution | agent 正常退出 |
| baseline_valid | broken baseline oracle 正确失败 |
| correctness | oracle 测试通过 |
| regression | 回归测试通过 |
| scope_control | 文件作用域合规 |
| minimality | 改动量在阈值内 |
| instruction_following | agent 遵守指令 |

## 关键函数

| 函数 | 作用 |
|------|------|
| `render_prompt()` | 按 config 的 prompt_template 渲染任务描述 |
| `run_with_feedback()` | 多轮反馈循环执行 |
| `run_agent()` | 构建并执行 Aider 命令 |
| `check_file_scope()` | 检查 changed_files 是否合规 |
| `build_scorecard()` | 生成多维评分和 failure_reasons |
| `generate_report()` | 按 config 分组汇总结果 |

## Prompt 模板

三种模板，对应不同的任务表达方式：

- `raw`：直接传 task.description
- `constrained`：description + 约束文本（允许/禁止文件、改动量上限）
- `structured`：结构化模板（目标 + 不变量 + 修改范围 + 验证命令 + 约束条件）

## Context Mode

控制 Aider 能看到哪些文件：

- `file_args_only`：只传 task.files
- `repo_map`：启用 repo map
- `oracle_visible`：额外传入 oracle 测试文件
- `focused_context`：额外注入相关文件内容摘要

## 环境依赖

| 工具 | 路径 |
|------|------|
| Node 20 | /opt/homebrew/opt/node@20/bin/node |
| Python | .venv |
| Aider | .venv/bin/aider |
