# Harness Eval 优化技术方案

最后更新：2026-06-02

## 1. 背景与目标

当前 `harness-eval` 已经具备最小运行能力：

- `tasks.yaml` 定义评测任务
- `eval_runner.py` 调用 Aider 执行 coding task
- `.eval_worktrees/` 隔离每次运行
- `eval_results/` 保存 JSON 结果
- 后端已有 `test/eval-api.e2e-spec.ts`
- 已完成 `GLM-5.1 + T001` 端到端验证

但当前方案存在一个核心问题：

> 当前 `PASS` 只能证明项目在某些测试下仍能运行，不能证明 agent 真正完成了指定任务。

已有结果已经暴露该问题：

- `T001` 中存在 `files_changed=0` 但 `PASS` 的 run
- `T002` 中存在修改了错误文件但仍 `PASS` 的 run
- 多个任务的 `test_command` 过于宽泛或过于弱，无法作为任务级 oracle

本方案目标：

1. 让每个任务拥有可验证的任务级 oracle
2. 让原始 baseline 在任务级 oracle 下必须失败
3. 让 agent 修改后必须同时满足正确性、作用域、回归测试、最小改动等条件
4. 让失败样本可审计、可回放、可归因
5. 为后续 harness 实验变量比较提供可信基础

## 2. 总体原则

### 2.1 先修 eval 可信度，再扩模型和任务

当前不要继续扩大模型、任务和运行次数。

优先级应为：

1. 修复 task oracle
2. 改造 runner scorecard
3. 保留失败样本
4. 重新跑小规模 baseline
5. 再扩展模型和 harness 实验变量

### 2.2 每个任务必须满足三段式验证

每个任务都应遵循：

```text
baseline_should_fail -> agent_run -> target_should_pass
```

含义：

- `baseline_should_fail`：原始项目在该任务专属测试下必须失败
- `agent_run`：agent 根据任务描述执行修改
- `target_should_pass`：修改后专属测试和必要回归测试必须通过

如果 baseline 本来就通过，该任务不能作为 bugfix eval，需要重写任务或调整基线。

### 2.3 任务评估不能只看测试返回码

最终判分应由多个维度组成：

- `correctness`
- `scope_control`
- `regression`
- `minimality`
- `instruction_following`
- `agent_execution`

只有这些维度都满足时，才应计为最终 PASS。

## 3. 当前问题诊断

### 3.1 T001 的问题

任务：

```yaml
id: T001
title: 修复歌单数量限制校验
```

当前基线代码已经包含：

- `MAX_SONGS = 9`
- `create()` 中超过 9 首返回 `BadRequestException`
- `update()` 中超过 9 首返回 `BadRequestException`

因此该任务已经被污染。

问题：

- agent 不修改代码也可能 PASS
- 当前 e2e 没有专门断言 “10 首歌应返回 400”
- 当前结果不能作为模型能力评估

处理方案：

必须二选一：

1. 重置基线，刻意移除 `MAX_SONGS` 校验，让任务重新成为真实 bugfix
2. 保留当前基线，但把 T001 改成新的未实现行为

推荐方案：

采用方案 1。为 eval 建立专用 broken baseline，不要直接拿已修复代码做 bugfix 评测。

### 3.2 T002 的问题

任务：

```yaml
id: T002
title: 将 callback 改为 async/await
```

当前问题：

- 测试命令只是 `require('./utils/recommend.js')`
- 只能证明模块加载不报错
- 不能证明 callback 被改成 async/await
- 不能证明行为保持一致
- 已有 run 中出现修改错误文件仍 PASS

处理方案：

- 加静态作用域检查
- 加行为测试
- 明确禁止修改 H5 `useRecommend.ts`

### 3.3 T003 的问题

任务：

```yaml
id: T003
title: 提取 API 错误处理中间件
```

当前问题：

- 回归 e2e 能通过，不代表错误响应格式符合要求
- 没有断言 `{ code, message, data: null }`
- 没有断言 400/404/500 的统一格式

处理方案：

- 新增错误格式专项 e2e
- 对至少 400、404、500 三类错误做格式验证
- runner 检查新增 filter 文件和 `main.ts` 注册情况

### 3.4 T004-T006 的问题

`T004` 属于结构重构，测试通过不代表重构质量。

`T005` 当前验证过弱，只检查 API 模块导出。

`T006` 需要 query count 或 repository mock，否则无法证明 N+1 被修复。

处理方案：

第一阶段暂停 `T004-T006`，只保留 `T001-T003` 做高质量 eval。

## 4. 第一阶段目标范围

第一阶段只做：

```text
T001 + T002 + T003
GLM-5.1
每个任务 3 runs
```

完成后再扩展：

- 多模型比较
- H001/H002/H003 harness 实验
- T004-T006 高阶任务

## 5. 任务定义结构升级

当前 `tasks.yaml` 字段不足，需要新增结构化字段。

### 5.1 推荐 schema

```yaml
tasks:
  - id: T001
    title: "修复歌单数量限制校验"
    category: "bugfix"
    difficulty: "easy"
    description: |
      ...

    files:
      - deathplaylist_backends/src/playlists/playlists.service.ts

    expected_changed_files:
      - deathplaylist_backends/src/playlists/playlists.service.ts

    allowed_changed_files:
      - deathplaylist_backends/src/playlists/playlists.service.ts
      - deathplaylist_backends/src/playlists/playlists.controller.ts
      - deathplaylist_backends/test/eval-task-T001.e2e-spec.ts

    forbidden_changed_files:
      - deathplaylist_frontend/**
      - deathplaylist_miniprogram/**

    baseline_check_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-task-T001 --forceExit"

    oracle_test_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-task-T001 --forceExit"

    regression_test_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-api --forceExit"

    success_conditions:
      - agent_exit_code_zero
      - oracle_tests_pass
      - regression_tests_pass
      - touched_expected_files
      - no_forbidden_files_changed
      - changed_files_within_allowed

    max_files_changed: 3
    max_lines_total: 120
```

### 5.2 字段说明

`category`

- `bugfix`
- `refactor`
- `architecture`

`expected_changed_files`

- 至少应修改的文件
- 用于发现 `files_changed=0` 但 PASS 的假阳性

`allowed_changed_files`

- 允许修改的文件或 glob
- 用于作用域控制

`forbidden_changed_files`

- 明确不允许修改的文件或目录

`baseline_check_command`

- 在 agent 执行前运行
- 对 bugfix 任务，预期应该失败

`oracle_test_command`

- 任务专属测试
- agent 修改后必须通过

`regression_test_command`

- 回归测试
- 防止修一个任务破坏主流程

`success_conditions`

- 最终 PASS 的条件列表

`max_files_changed` / `max_lines_total`

- 最小改动约束
- 超过阈值不一定直接失败，但应标记为 review needed

## 6. Oracle 测试设计

### 6.1 T001 oracle

新增文件：

```text
project/deathplaylist_backends/test/eval-task-T001.e2e-spec.ts
```

测试目标：

- 创建 10 首歌的歌单应返回 400
- 更新为 10 首歌应返回 400
- 错误消息包含 `最多只能添加9首音乐`
- 创建 9 首歌仍应成功

测试要点：

```typescript
describe('Eval Task T001 - playlist song limit', () => {
  it('rejects creating playlist with more than 9 songs', async () => {
    // login
    // POST /api/playlists with 10 songs
    // expect 400
    // expect message contains 最多只能添加9首音乐
  });

  it('allows creating playlist with exactly 9 songs', async () => {
    // POST /api/playlists with 9 songs
    // expect 201
  });

  it('rejects updating playlist to more than 9 songs', async () => {
    // create playlist with 1 song
    // PUT /api/playlists/:id with 10 songs
    // expect 400
  });
});
```

重要：

- 如果当前基线已经通过该测试，需要先创建 broken baseline
- 不能在已经修复的代码上评估 “修复缺失校验”

### 6.2 T002 oracle

新增文件：

```text
project/deathplaylist_miniprogram/test/eval-task-T002.test.js
```

如果小程序目录没有测试框架，第一版可以用纯 Node 脚本。

测试目标：

- mock `wx.getStorageSync`
- mock `wx.setStorageSync`
- mock `wx.removeStorageSync`
- mock `request`
- 调用 `loadRecommendations()`
- 验证返回数组
- 验证缓存写入
- 验证多次 visit 会轮转 keyword group

建议命令：

```bash
cd deathplaylist_miniprogram && node test/eval-task-T002.test.js
```

静态检查：

- `deathplaylist_miniprogram/utils/recommend.js` 应被修改
- `deathplaylist_frontend/src/hooks/useRecommend.ts` 不应被修改

可选静态检查：

- 文件中不应出现新的嵌套 callback 模式
- 允许保留小程序原生 API 的 callback，只评估推荐引擎内部流程

### 6.3 T003 oracle

新增文件：

```text
project/deathplaylist_backends/test/eval-task-T003.e2e-spec.ts
```

测试目标：

- 400 错误返回 `{ code, message, data: null }`
- 404 错误返回 `{ code, message, data: null }`
- 未授权 401 错误返回 `{ code, message, data: null }`
- 正常 API 响应不被错误 filter 包裹

示例断言：

```typescript
expect(res.body).toHaveProperty('code');
expect(res.body).toHaveProperty('message');
expect(res.body).toHaveProperty('data', null);
```

注意：

- 如果 Nest 默认错误结构与任务要求不一致，baseline 应失败
- agent 修改后 oracle 才应通过

## 7. Runner 改造方案

### 7.1 新增 baseline check

在 `run_single()` 中，执行 agent 前先运行：

```python
baseline = run_command(task["baseline_check_command"], worktree_path)
```

对于 `bugfix` 类任务：

```python
baseline_expected_failed = task.get("baseline_should_fail", True)
```

如果 baseline 没有失败：

- 标记 `invalid_task = True`
- 不继续 agent run
- 输出原因：`baseline oracle already passes`

### 7.2 拆分验证命令

新增：

```python
def run_oracle_validation(task, worktree_path) -> dict:
    ...

def run_regression_validation(task, worktree_path) -> dict:
    ...
```

不要再只有一个 `run_validation()`。

### 7.3 作用域检查

新增：

```python
from fnmatch import fnmatch

def check_file_scope(task: dict, changed_files: list[str]) -> dict:
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

注意：

- glob 匹配需要兼容 `**`
- 如果 `fnmatch` 对 `**` 支持不够，先使用简单前缀匹配策略

### 7.4 生成 patch

新增：

```python
def collect_patch(worktree_path: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    return result.stdout
```

保存到：

```text
eval_results/runs/{timestamp}_{task_id}_{model}_{run_index}/patch.diff
```

### 7.5 保存完整 run artifact

每次运行保存一个目录：

```text
eval_results/runs/
  20260602_223000_T001_glm-5.1_0/
    metrics.json
    patch.diff
    agent_stdout.log
    agent_stderr.log
    baseline_stdout.log
    baseline_stderr.log
    oracle_stdout.log
    oracle_stderr.log
    regression_stdout.log
    regression_stderr.log
```

失败时保留 worktree：

```text
.eval_worktrees/failed/T001_glm-5.1_0/
```

### 7.6 scorecard 结构

替换当前单一 `pass_rate`，新增：

```json
{
  "final_pass": true,
  "scorecard": {
    "agent_execution": true,
    "baseline_valid": true,
    "correctness": true,
    "regression": true,
    "scope_control": true,
    "minimality": true,
    "instruction_following": true
  },
  "failure_reasons": []
}
```

如果失败：

```json
{
  "final_pass": false,
  "failure_reasons": [
    "oracle_tests_failed",
    "modified_forbidden_file: deathplaylist_frontend/src/hooks/useRecommend.ts"
  ]
}
```

### 7.7 minimality 判断

建议第一版：

```python
minimality_passed = (
    code_diff["files_changed"] <= task.get("max_files_changed", 999)
    and code_diff["lines_total"] <= task.get("max_lines_total", 999999)
)
```

超过阈值：

- 初期可以不直接失败
- 但必须进入 `failure_reasons` 或 `review_flags`

推荐：

```json
"review_flags": ["large_diff"]
```

## 8. 结果文件格式升级

当前结果文件：

```text
eval_results/T001_glm-5.1_baseline.json
```

建议保留汇总文件，同时新增 run artifacts。

汇总文件结构：

```json
[
  {
    "config": "baseline",
    "task_id": "T001",
    "model": "glm-5.1",
    "run_index": 0,
    "timestamp": "...",
    "final_pass": true,
    "scorecard": {
      "agent_execution": true,
      "baseline_valid": true,
      "correctness": true,
      "regression": true,
      "scope_control": true,
      "minimality": true,
      "instruction_following": true
    },
    "failure_reasons": [],
    "review_flags": [],
    "elapsed_seconds": 123.4,
    "tokens_sent": 12345,
    "tokens_received": 678,
    "files_changed": 1,
    "lines_total": 42,
    "changed_files": [
      "deathplaylist_backends/src/playlists/playlists.service.ts"
    ],
    "artifact_dir": "eval_results/runs/20260602_223000_T001_glm-5.1_0"
  }
]
```

## 9. Task 文件建议版本

### 9.1 T001

```yaml
- id: T001
  title: "修复歌单数量限制校验"
  category: "bugfix"
  difficulty: "easy"
  description: |
    当前后端允许创建或更新包含超过 9 首歌的歌单。
    请在 playlist service 中添加校验：创建和更新时 songs 数量不能超过 9。
    超出时返回 400，并包含错误消息：最多只能添加9首音乐。
    不要修改前端或小程序代码。
  files:
    - deathplaylist_backends/src/playlists/playlists.service.ts
  expected_changed_files:
    - deathplaylist_backends/src/playlists/playlists.service.ts
  allowed_changed_files:
    - deathplaylist_backends/src/playlists/playlists.service.ts
  forbidden_changed_files:
    - deathplaylist_frontend/**
    - deathplaylist_miniprogram/**
  baseline_should_fail: true
  baseline_check_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-task-T001 --forceExit"
  oracle_test_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-task-T001 --forceExit"
  regression_test_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-api --forceExit"
  max_files_changed: 1
  max_lines_total: 60
```

### 9.2 T002

```yaml
- id: T002
  title: "将小程序推荐引擎改为 async/await"
  category: "refactor"
  difficulty: "medium"
  description: |
    deathplaylist_miniprogram/utils/recommend.js 中的推荐引擎需要从回调/嵌套异步流程改为 async/await。
    保持 module.exports = { loadRecommendations } 不变。
    保持推荐缓存、访问次数轮转、去重、相邻歌手规避逻辑不退化。
    不要修改 H5 前端 useRecommend.ts。
  files:
    - deathplaylist_miniprogram/utils/recommend.js
  expected_changed_files:
    - deathplaylist_miniprogram/utils/recommend.js
  allowed_changed_files:
    - deathplaylist_miniprogram/utils/recommend.js
  forbidden_changed_files:
    - deathplaylist_frontend/**
    - deathplaylist_backends/**
  baseline_should_fail: true
  baseline_check_command: "cd deathplaylist_miniprogram && node test/eval-task-T002.test.js"
  oracle_test_command: "cd deathplaylist_miniprogram && node test/eval-task-T002.test.js"
  regression_test_command: "cd deathplaylist_miniprogram && node -e \"const rec = require('./utils/recommend.js'); if (typeof rec.loadRecommendations !== 'function') process.exit(1)\""
  max_files_changed: 1
  max_lines_total: 120
```

### 9.3 T003

```yaml
- id: T003
  title: "提取 API 错误处理中间件"
  category: "refactor"
  difficulty: "medium"
  description: |
    请创建 NestJS exception filter，统一处理错误响应。
    错误响应必须为 { code, message, data: null }。
    至少覆盖 400、401、404。
    正常接口响应不要被包裹。
  files:
    - deathplaylist_backends/src/common/filters/
    - deathplaylist_backends/src/main.ts
  expected_changed_files:
    - deathplaylist_backends/src/common/filters/**
    - deathplaylist_backends/src/main.ts
  allowed_changed_files:
    - deathplaylist_backends/src/common/filters/**
    - deathplaylist_backends/src/main.ts
  forbidden_changed_files:
    - deathplaylist_frontend/**
    - deathplaylist_miniprogram/**
  baseline_should_fail: true
  baseline_check_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-task-T003 --forceExit"
  oracle_test_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-task-T003 --forceExit"
  regression_test_command: "cd deathplaylist_backends && DB_DATABASE=:memory: npm run test:e2e -- --testPathPattern=eval-api --forceExit"
  max_files_changed: 3
  max_lines_total: 160
```

## 10. Broken Baseline 管理

### 10.1 为什么需要 broken baseline

bugfix eval 必须满足：

```text
原始代码存在 bug -> agent 修复 bug -> oracle 通过
```

如果原始代码已经没有 bug，eval 就不成立。

### 10.2 推荐目录结构

当前：

```text
project/
```

建议改为：

```text
baselines/
  deathplaylist-clean/
  deathplaylist-broken-T001/
  deathplaylist-broken-T002/
  deathplaylist-broken-T003/
```

第一阶段可以先不大改目录，只在 `tasks.yaml` 增加：

```yaml
project_source: "project"
```

未来再支持：

```yaml
project_source: "baselines/deathplaylist-broken-T001"
```

runner 中：

```python
source_dir = PROJECT_ROOT / task.get("project_source", "project")
```

### 10.3 第一阶段最低要求

至少保证：

- `T001` 的基线代码没有 9 首歌校验
- `T002` 的基线代码确实含有待改造的异步结构
- `T003` 的基线代码确实没有统一错误 filter

否则对应任务应标记为 `invalid_task`。

## 11. Harness 实验变量落地

当前 `harness_experiments.yaml` 只是描述，没有执行能力。

第一阶段不要急着实现 H001-H003，但需要定义可执行结构。

推荐结构：

```yaml
experiments:
  - id: baseline
    name: "baseline"
    aider_args: []
    prompt_template: "default"
    context_mode: "file_args_only"
    step_mode: "single"

  - id: H001
    name: "system prompt 优化"
    aider_args:
      - "--system-message"
      - "你是一个严格遵循任务边界的 coding agent..."
    prompt_template: "default"
    context_mode: "file_args_only"
    step_mode: "single"

  - id: H002
    name: "上下文注入"
    aider_args: []
    prompt_template: "with_file_context"
    context_mode: "inline_file_context"
    step_mode: "single"

  - id: H003
    name: "分步引导"
    aider_args: []
    prompt_template: "stepwise"
    context_mode: "file_args_only"
    step_mode: "multi"
```

runner 后续支持：

```bash
python eval_runner.py --model glm-5.1 --task T001 --config H001
```

执行逻辑：

- 根据 `--config` 读取实验配置
- 修改 Aider args
- 修改 prompt template
- 修改 context injection
- 修改 step mode

## 12. 实现顺序

### Step 1：暂停无效 baseline

不要继续跑当前 T001-T006 全量。

### Step 2：新增任务级 oracle 测试

新增：

```text
project/deathplaylist_backends/test/eval-task-T001.e2e-spec.ts
project/deathplaylist_miniprogram/test/eval-task-T002.test.js
project/deathplaylist_backends/test/eval-task-T003.e2e-spec.ts
```

### Step 3：验证 baseline 是否有效

执行：

```bash
python eval_runner.py --model glm-5.1 --task T001 --runs 1 --baseline-only
```

如果不实现 `--baseline-only`，先手动执行 `baseline_check_command`。

要求：

- bugfix 任务 baseline oracle 必须失败
- 如果 baseline oracle 通过，任务标记为 invalid

### Step 4：升级 `tasks.yaml`

加入：

- `category`
- `expected_changed_files`
- `allowed_changed_files`
- `forbidden_changed_files`
- `baseline_should_fail`
- `baseline_check_command`
- `oracle_test_command`
- `regression_test_command`
- `success_conditions`
- `max_files_changed`
- `max_lines_total`

### Step 5：升级 runner

修改：

- `create_worktree()` 支持 task-level `project_source`
- 新增 baseline check
- 新增 oracle validation
- 新增 regression validation
- 新增 scope check
- 新增 scorecard
- 新增 artifact 保存
- 新增 failed worktree 保留

### Step 6：重新跑小规模可信 baseline

```bash
python eval_runner.py --model glm-5.1 --task T001 --runs 3 --config baseline
python eval_runner.py --model glm-5.1 --task T002 --runs 3 --config baseline
python eval_runner.py --model glm-5.1 --task T003 --runs 3 --config baseline
python eval_runner.py --report
```

### Step 7：复盘失败样本

对每个失败样本记录：

- agent 是否理解任务
- 是否改错文件
- 是否改动过大
- 是否测试失败
- 是否通过 oracle 但破坏 regression
- 是否触发 forbidden files

## 13. 验收标准

本优化方案完成后，应满足：

1. 每个任务有专属 oracle
2. bugfix 任务 baseline oracle 会失败
3. agent run 后 final pass 不再只依赖测试返回码
4. 修改错误文件不会再被判 PASS
5. 没有代码改动不会再被判 PASS
6. 每次 run 都有可审计 artifact
7. 失败样本可以回放
8. report 能显示多维 scorecard
9. 第一批可信结果只包含 `T001-T003`

## 14. 后续扩展

第一阶段完成后，再扩展：

1. 多模型对比
2. H001/H002/H003 harness 实验
3. T004-T006 高阶任务
4. 人工 review rubric
5. 失败归因自动分类
6. 成本与质量的 Pareto 分析

## 15. 给实现模型的执行约束

后续使用 GLM-5.1 实现时，应遵循：

1. 先读本文件，再读 `eval_runner.py`、`tasks.yaml`、`PROGRESS.md`
2. 不要一次性重写整个 runner
3. 优先实现 `T001-T003` 的可信 oracle 和 scorecard
4. 保留现有命令行用法
5. 不删除现有 `eval_results`
6. 不修改 `.env`
7. 不扩大任务范围
8. 每完成一个 step 后运行对应验证命令

## 16. 最小完成版本

如果时间有限，最低可接受版本是：

- `tasks.yaml` 支持新增结构化字段
- runner 能检查：
  - oracle pass
  - regression pass
  - expected files touched
  - forbidden files untouched
- 每次 run 保存 `patch.diff`
- `T001-T003` 只要有两个任务完成可信 oracle 即可

最低不可接受版本：

- 继续只用 `test_command` 返回码判定 PASS
- 继续允许 `files_changed=0` 时 PASS
- 继续允许改错文件时 PASS
