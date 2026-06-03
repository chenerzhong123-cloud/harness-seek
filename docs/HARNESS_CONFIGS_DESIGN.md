# Harness Eval 分层优化方案（修订版）

最后更新：2026-06-03

## 1. 背景与目标

基于 HARNESS_EVAL_OPTIMIZATION_PLAN.md 的基础框架，本方案细化了 harness 实验变量的分层设计。

核心原则：

> 每一层都设计可控变量，但第一阶段每次只释放一个变量，保证结果可解释。

目标：固定模型（GLM-5.1）和任务（T001-T006），通过阶梯式实验测量不同 harness 配置对 agent 效率的影响。

### 实验目标说明

H0 baseline 已达 100% 通过率（T001-T006 全部 3/3），通过率维度无提升空间。因此实验目标调整为**代价效率测量**：

| 维度 | 说明 |
|------|------|
| **通过率稳定性** | 不同配置是否保持 100%，还是出现退化 |
| **Token 效率** | 达到通过所需的 token 消耗（sent/received） |
| **时间效率** | agent 执行耗时 |
| **反馈轮次** | multi-round feedback 是否减少单轮修改量 |
| **代码质量** | 改动量（files/lines）是否更精简 |

如果某配置在保持 100% 通过率的同时显著降低 token 消耗，则为更优配置。

## 2. 四层架构定义

### Layer 1: Prompt Layer（任务如何表达）

控制 agent 收到的任务描述的格式和内容。

| 变体 | 说明 |
|------|------|
| `raw` | 直接传 task.description，不做任何加工 |
| `constrained` | task.description + 允许修改范围 + 禁止修改范围 + 改动量上限 |
| `structured` | 结构化模板：目标 + 不变量 + 修改范围 + 验证命令 + 约束条件 |

`structured` 模板：

```markdown
## Task
{description}

## Invariants
{business_invariants}

## Allowed Files
{allowed_changed_files}

## Forbidden Files
{forbidden_changed_files}

## Verification
Oracle: {oracle_test_command}
Regression: {regression_test_command}

## Constraints
- Do not modify tests.
- Do not modify files outside allowed files.
- Keep the change minimal.
- Preserve existing public APIs unless the task explicitly requires changing them.
- If unsure, read the file first before modifying.
```

注意：不要写「只输出代码修改，不要输出解释」。Aider 本身是执行编辑的工具，不是让模型返回文本。这类指令不会稳定生效，可能干扰 agent 理解测试失败。

### Layer 2: Context Layer（给 agent 哪些上下文）

控制 agent 能看到哪些项目文件和仓库结构信息。

| 变体 | 说明 |
|------|------|
| `file_args_only` | 只把 task.files 传给 Aider 的 --file 参数 |
| `repo_map` | 启用 Aider 的 repo map，通过 map_tokens 控制大小 |
| `oracle_visible` | 把 oracle 测试文件和目标文件一起传给 Aider |
| `focused_context` | 额外注入相关 service/controller/test 的当前内容摘要 |

`map_tokens` 的取值：

| 值 | 说明 |
|----|------|
| `0` | 不给仓库地图，agent 盲改 |
| `1024` | 只给目录结构 + 函数签名 |
| `2048` | Aider 默认值 |
| `4096` | 更完整的上下文，消耗更多 token |

### Layer 3: Execution Layer（agent 如何执行）

控制 agent 的执行流程，包括编辑方式、是否多轮、是否中途测试。

```yaml
execution:
  edit_format: diff | whole          # 编辑表示方式，第一阶段固定 diff
  planning_mode: direct | architect  # 工作流模式，第一阶段固定 direct
  feedback_rounds: 1 | 2 | 3        # 反馈循环轮次
  stop_on_oracle_pass: true          # oracle 通过即停止
  run_regression_after_oracle_pass: true
```

执行逻辑：

```text
round 1:
  run aider with task prompt
  run oracle_test
  if oracle pass:
    run regression_test
    if regression pass: finish (PASS)
    else: finish (FAIL, regression_broken)
  else if feedback_rounds > 1:
    send oracle failure output back to aider

round 2:
  ask agent to fix based on oracle output
  run oracle again
  if pass: run regression
  ...

round N:
  同上，超过 feedback_rounds 则停止
```

关键区分：

- `edit_format`（diff/whole）是编辑表示方式
- `planning_mode`（direct/architect）是工作流模式，architect 会先规划再执行
- 两者不应并列，必须分开配置

`auto_commits` 固定为 `false`。它不影响 agent 能力，只影响 runner 如何收集 diff，不应作为实验变量。

### Layer 4: Control & Audit Layer（约束和记录）

控制如何约束 agent 行为、记录审计轨迹、评估输出。

**scope_guard（作用域约束）：**

| 值 | 说明 | 阶段 |
|----|------|------|
| `post_check` | 运行后检查 changed_files，违规则 final_pass=false | 第一阶段 |
| `pre_write` | 写入前拦截 forbidden file，从源头阻止 | 第二阶段 |

`post_check` 在 runner 层实现，不改 Aider 源码：

```python
def scope_post_check(task, changed_files):
    expected = task["expected_changed_files"]
    allowed = task["allowed_changed_files"]
    forbidden = task["forbidden_changed_files"]

    touched_expected = all(any(fnmatch(f, p) for f in changed_files) for p in expected)
    forbidden_touched = [f for f in changed_files if any(fnmatch(f, p) for p in forbidden)]
    outside_allowed = [f for f in changed_files if allowed and not any(fnmatch(f, p) for p in allowed)]

    return {
        "touched_expected_files": touched_expected,
        "forbidden_touched": forbidden_touched,
        "outside_allowed": outside_allowed,
        "scope_passed": touched_expected and not forbidden_touched and not outside_allowed,
    }
```

`pre_write` 需要改 Aider 源码或包装文件系统，实现成本高，放第二阶段。

**audit_level（审计级别）：**

| 级别 | 记录内容 |
|------|----------|
| `basic` | metrics.json、patch.diff |
| `full` | metrics.json、patch.diff、prompt.md、agent_stdout.log、agent_stderr.log、oracle_stdout.log、oracle_stderr.log、regression_stdout.log、regression_stderr.log、per_round_metrics.json |

`per_round_metrics.json` 记录每轮反馈的：
- turn index
- changed files
- patch
- test command
- test result
- stdout/stderr excerpt
- prompt sent to agent
- elapsed time
- token usage

不记录 reasoning（模型不输出可靠的原因信息，伪造 reasoning 无意义）。

## 3. 实验矩阵

### 第一阶段（H0-H6）

固定条件：
- model: `glm-5.1`
- tasks: `T001-T006`
- runs: `3`
- auto_commits: `false`
- edit_format: `whole`（GLM-5.1 不支持 diff 格式，model settings 固定为 whole）
- planning_mode: `direct`

```yaml
configs:
  H0_baseline:
    prompt_template: raw
    context_mode: file_args_only
    map_tokens: 2048
    edit_format: whole
    planning_mode: direct
    feedback_rounds: 1
    scope_guard: post_check
    audit_level: basic

  H1_constrained_prompt:
    prompt_template: constrained
    context_mode: file_args_only
    map_tokens: 2048
    edit_format: whole
    planning_mode: direct
    feedback_rounds: 1
    scope_guard: post_check
    audit_level: basic

  H2_structured_prompt:
    prompt_template: structured
    context_mode: file_args_only
    map_tokens: 2048
    edit_format: whole
    planning_mode: direct
    feedback_rounds: 1
    scope_guard: post_check
    audit_level: basic

  H3_oracle_context:
    prompt_template: structured
    context_mode: oracle_visible
    map_tokens: 2048
    edit_format: whole
    planning_mode: direct
    feedback_rounds: 1
    scope_guard: post_check
    audit_level: basic

  H4_feedback_2round:
    prompt_template: structured
    context_mode: oracle_visible
    map_tokens: 2048
    edit_format: whole
    planning_mode: direct
    feedback_rounds: 2
    scope_guard: post_check
    audit_level: full

  H5_feedback_3round:
    prompt_template: structured
    context_mode: oracle_visible
    map_tokens: 2048
    edit_format: whole
    planning_mode: direct
    feedback_rounds: 3
    scope_guard: post_check
    audit_level: full

  H6_repo_map_4096:
    prompt_template: structured
    context_mode: oracle_visible
    map_tokens: 4096
    edit_format: whole
    planning_mode: direct
    feedback_rounds: 3
    scope_guard: post_check
    audit_level: full
```

变量递进关系（每次只变一个变量）：

```text
H0 → H1 → H2    ：Prompt Layer 递进（raw → constrained → structured）
H2 → H3          ：Context Layer 引入 oracle 测试文件
H3 → H4 → H5    ：Execution Layer 递增反馈轮次（1 → 2 → 3）
H5 → H6          ：Context Layer 增大 repo map（2048 → 4096）
```

每一步的提升可归因到具体某一层的具体变量。

### 第二阶段（暂不实现）

待第一阶段结果稳定后：

```yaml
phase2_experiments:
  - edit_format_diff_vs_whole
  - planning_direct_vs_architect
  - scope_post_check_vs_pre_write
  - aider_vs_direct_api
  - focused_context_vs_oracle_visible
```

暂不纳入第一阶段的变量：
- `diff` edit format（GLM-5.1 不支持，换模型时可测试）
- `architect` planning mode
- `direct-api` agent engine
- `claude-code` agent engine
- Aider 源码改动（vendor/aider）
- `pre_write` scope guard
- `focused_context` context mode

## 4. 文件结构

```text
/Users/deuce/claudeproject/productlearning/harness-eval/
  ├── eval_runner.py               # runner 主程序
  ├── eval_runner.md                # runner 说明文档（与 .py 同步）
  ├── tasks.yaml                    # 任务定义
  ├── harness_configs.yaml          # harness 实验配置（本方案的核心配置文件）
  ├── vendor/
  │   └── aider/                    # Aider 源码（第二阶段用）
  ├── eval_results/
  │   ├── H0_baseline/
  │   │   ├── T001_glm-5.1.json
  │   │   └── runs/
  │   ├── H1_constrained_prompt/
  │   └── ...
  └── HARNESS_EVAL_OPTIMIZATION_PLAN.md  # 原始优化方案
```

## 5. harness_configs.yaml 格式

```yaml
# 全局固定配置
defaults:
  model: glm-5.1
  tasks: [T001, T002, T003, T004, T005, T006]
  runs: 3
  auto_commits: false
  edit_format: whole
  planning_mode: direct
  scope_guard: post_check

# Prompt 模板定义
prompt_templates:
  raw: |
    {description}

  constrained: |
    {description}

    【严格约束】
    - 只允许修改：{allowed_changed_files}
    - 禁止修改：{forbidden_changed_files}
    - 最多改动 {max_lines_total} 行
    - 不要修改测试文件以外的任何无关文件

  structured: |
    ## Task
    {description}

    ## Invariants
    {business_invariants}

    ## Allowed Files
    {allowed_changed_files}

    ## Forbidden Files
    {forbidden_changed_files}

    ## Verification
    Oracle: {oracle_test_command}
    Regression: {regression_test_command}

    ## Constraints
    - Do not modify tests.
    - Do not modify files outside allowed files.
    - Keep the change minimal.
    - Preserve existing public APIs unless the task explicitly requires changing them.
    - If unsure, read the file first before modifying.

# 上下文模式定义
context_modes:
  file_args_only:
    description: "只传 task.files"
    include_oracle_test: false
    include_regression_command: false

  repo_map:
    description: "启用 repo map"
    include_oracle_test: false
    include_regression_command: false

  oracle_visible:
    description: "传入 oracle 测试文件"
    include_oracle_test: true
    include_regression_command: true

  focused_context:
    description: "注入相关文件内容摘要"
    include_oracle_test: true
    include_regression_command: true
    include_related_files: true

# 实验配置
configs:
  - id: H0_baseline
    prompt_template: raw
    context_mode: file_args_only
    map_tokens: 2048
    feedback_rounds: 1
    audit_level: basic

  - id: H1_constrained_prompt
    prompt_template: constrained
    context_mode: file_args_only
    map_tokens: 2048
    feedback_rounds: 1
    audit_level: basic

  - id: H2_structured_prompt
    prompt_template: structured
    context_mode: file_args_only
    map_tokens: 2048
    feedback_rounds: 1
    audit_level: basic

  - id: H3_oracle_context
    prompt_template: structured
    context_mode: oracle_visible
    map_tokens: 2048
    feedback_rounds: 1
    audit_level: basic

  - id: H4_feedback_2round
    prompt_template: structured
    context_mode: oracle_visible
    map_tokens: 2048
    feedback_rounds: 2
    audit_level: full

  - id: H5_feedback_3round
    prompt_template: structured
    context_mode: oracle_visible
    map_tokens: 2048
    feedback_rounds: 3
    audit_level: full

  - id: H6_repo_map_4096
    prompt_template: structured
    context_mode: oracle_visible
    map_tokens: 4096
    feedback_rounds: 3
    audit_level: full
```

## 6. Runner 改动要点

### 6.1 新增 --harness-config 参数

```bash
python eval_runner.py --harness-config H0_baseline --task T001 --runs 3
```

### 6.2 Prompt 渲染

```python
def render_prompt(config, task):
    template = prompt_templates[config["prompt_template"]]
    return template.format(**task)
```

### 6.3 Context 构建

```python
def build_aider_args(config, task):
    args = ["aider", "--model", "glm-5.1", "--no-auto-commits"]
    args += ["--edit-format", config.get("edit_format", "whole")]
    args += ["--map-tokens", str(config.get("map_tokens", 2048))]

    # 文件参数
    args += ["--file"] + task["files"]

    # 上下文模式
    context = context_modes[config["context_mode"]]
    if context.get("include_oracle_test"):
        args += ["--file", oracle_test_path(task)]
    if context.get("include_regression_command"):
        args += ["--file", regression_test_path(task)]

    return args
```

### 6.4 Feedback Loop

```python
def run_with_feedback(config, task, worktree_path):
    max_rounds = config.get("feedback_rounds", 1)

    for round_idx in range(max_rounds):
        # 构建 prompt（第一轮用原始 prompt，后续轮加上测试反馈）
        prompt = render_prompt(config, task)
        if round_idx > 0:
            prompt += f"\n\n上一轮测试失败，输出如下：\n{last_oracle_output}\n请根据测试输出修复代码。"

        # 执行 agent
        run_agent(aider_args, prompt, worktree_path)

        # 跑 oracle
        oracle_result = run_oracle(task, worktree_path)
        if oracle_result["passed"]:
            # 跑 regression
            regression_result = run_regression(task, worktree_path)
            return {"oracle_passed": True, "regression_passed": regression_result["passed"], "rounds": round_idx + 1}

        last_oracle_output = oracle_result["stdout"]

    return {"oracle_passed": False, "rounds": max_rounds}
```

### 6.5 Scope Post Check

```python
def scope_post_check(task, changed_files):
    expected = task.get("expected_changed_files", [])
    allowed = task.get("allowed_changed_files", [])
    forbidden = task.get("forbidden_changed_files", [])

    touched_expected = all(any(fnmatch(f, p) for f in changed_files) for p in expected)
    forbidden_touched = [f for f in changed_files if any(fnmatch(f, p) for p in forbidden)]
    outside_allowed = [f for f in changed_files if allowed and not any(fnmatch(f, p) for p in allowed)]

    return {
        "touched_expected_files": touched_expected,
        "forbidden_touched": forbidden_touched,
        "outside_allowed": outside_allowed,
        "scope_passed": touched_expected and not forbidden_touched and not outside_allowed,
    }
```

### 6.6 结果目录结构

```text
eval_results/
  H0_baseline/
    T001_glm-5.1_summary.json
    runs/
      20260603_120000_T001_glm-5.1_0/
        metrics.json
        patch.diff
        prompt.md
        agent_stdout.log
        oracle_stdout.log
        regression_stdout.log
        per_round_metrics.json   # audit_level=full 时
```

## 7. 评分体系

采用四维向量，不做加权求和，避免丢失诊断信息。

```json
{
  "vector": {
    "correctness": 1.0,
    "scope_control": 0.8,
    "regression": 1.0,
    "minimality": 0.9
  },
  "label": "PASS",
  "review_flags": []
}
```

判定逻辑：

```
correctness = 1.0 且 regression = 1.0 → PASS（基本门槛）
其余维度异常 → 标记 review_flags
```

各维度打分方式：

| 维度 | 打分逻辑 |
|------|----------|
| correctness | oracle 测试通过率（N/M 个测试通过） |
| scope_control | 改了预期文件 = 1.0，触碰禁止文件 = 0.0 |
| regression | 回归测试通过率 |
| minimality | 改动量 / 阈值的比率，超标标 review_flags |

第一阶段不加权，等有足够 baseline 数据后再决定是否需要加权。

## 8. 报告格式

```bash
python eval_runner.py --report --compare H0_baseline H2_structured_prompt H4_feedback_2round
```

输出：

```text
=== Harness Config Comparison ===

T001 pass rate:
  H0_baseline:              1/3 (33%)
  H2_structured_prompt:     2/3 (67%)
  H4_feedback_2round:       3/3 (100%)

T001 avg scope score:
  H0_baseline:              0.4
  H2_structured_prompt:     0.9
  H4_feedback_2round:       0.9

T001 avg rounds used:
  H0_baseline:              1.0
  H2_structured_prompt:     1.0
  H4_feedback_2round:       1.7

T001 avg token usage:
  H0_baseline:              5200
  H2_structured_prompt:     6100
  H4_feedback_2round:       12400
```

## 9. 实现顺序

### Step 1：新建 harness_configs.yaml

按第 5 节格式创建完整配置文件。

### Step 2：升级 tasks.yaml

加入 structured 模板所需字段：

- business_invariants
- expected_changed_files
- allowed_changed_files
- forbidden_changed_files
- oracle_test_command
- regression_test_command
- max_files_changed
- max_lines_total

### Step 3：升级 eval_runner.py

- 支持 --harness-config 参数
- 实现 prompt 模板渲染
- 实现 context mode 构建
- 实现 feedback loop
- 实现 scope post check
- 实现 audit_level=full
- 结果按 harness config 分目录保存

### Step 4：同步维护 eval_runner.md

与 eval_runner.py 同步更新说明文档。

### Step 5：跑 H0 baseline 验证

```bash
python eval_runner.py --harness-config H0_baseline --model glm-5.1 --task T001 --runs 3
python eval_runner.py --harness-config H0_baseline --model glm-5.1 --task T002 --runs 3
python eval_runner.py --harness-config H0_baseline --model glm-5.1 --task T003 --runs 3
python eval_runner.py --harness-config H0_baseline --model glm-5.1 --task T004 --runs 3
python eval_runner.py --harness-config H0_baseline --model glm-5.1 --task T005 --runs 3
python eval_runner.py --harness-config H0_baseline --model glm-5.1 --task T006 --runs 3
python eval_runner.py --report
```

### Step 6：逐个跑 H1-H6

每个 config 跑完后对比前一 config 的结果。

## 10. 与原始方案的关系

本方案是 HARNESS_EVAL_OPTIMIZATION_PLAN.md 中第 11 节「Harness 实验变量落地」的细化版本。

原始方案定义了任务级 oracle、scorecard、broken baseline 等基础架构，本方案在此基础上：
- 重新定义了四层实验变量架构
- 设计了 H0-H6 阶梯式实验矩阵
- 细化了 runner 的实现方案
- 明确了第一阶段和第二阶段的边界

两者配合使用：先完成原始方案中的 oracle 和 scorecard 建设，再用本方案跑 harness 实验。
