# Harness Eval — AI Coding Agent 评测框架

基于 Aider 的 AI 编码能力评测框架，使用「死亡歌单」项目作为测试床，对 AI 模型的代码修改能力进行可复现、可审计的定量评估。

## 项目结构

```
harness-eval/
├── eval_runner.py                  # 评测运行器（核心）
├── tasks.yaml                      # 任务定义（v2 结构化）
├── harness_experiments.yaml        # Harness 实验变量定义
├── .env                            # API Keys（不入库）
├── .gitignore
├── README.md                       # 本文件
├── PROGRESS.md                     # 进展记录
├── EVAL_PLAN.md                    # 原始评测计划
├── HARNESS_EVAL_OPTIMIZATION_PLAN.md  # 优化技术方案
│
├── project/                        # 测试项目代码（broken baseline，不入库）
│   ├── deathplaylist_backends/     # NestJS 后端
│   ├── deathplaylist_frontend/     # React 前端
│   └── deathplaylist_miniprogram/  # 微信小程序
│
├── eval_results/                   # 评测结果（不入库）
│   ├── {task}_{model}_{config}.json    # 汇总结果
│   └── runs/                            # 每次 run 的 artifact
│       └── {timestamp}_{task}_{model}_{run}/
│           ├── metrics.json
│           ├── patch.diff
│           ├── agent_stdout.log
│           ├── baseline_stdout.log
│           ├── oracle_stdout.log
│           └── regression_stdout.log
│
└── .eval_worktrees/                # 运行时隔离工作区（不入库）
    └── failed/                     # 失败样本保留
```

## 核心概念

### 三段式验证

每个任务遵循：

```
broken_baseline_oracle_FAIL → agent_修改 → oracle_PASS + regression_PASS
```

- **Baseline check**：验证 broken baseline 的 oracle 测试确实失败
- **Agent run**：Aider 根据任务描述执行代码修改
- **Oracle + Regression**：任务专属测试 + 回归测试必须同时通过

### 多维 Scorecard

不再只看测试返回码，而是多维度判定：

| 维度 | 含义 |
|------|------|
| `agent_execution` | Agent 正常退出（exit code 0） |
| `baseline_valid` | Broken baseline 的 oracle 正确失败 |
| `correctness` | 任务专属 oracle 测试通过 |
| `regression` | 回归测试通过（未破坏现有功能） |
| `scope_control` | 只修改了 allowed 范围内的文件 |
| `minimality` | 改动量在阈值内 |
| `instruction_following` | 综合以上指标 |

只有所有维度全部通过，才计为 `final_pass`。

## 任务定义（tasks.yaml v2）

```yaml
tasks:
  - id: T001
    title: "修复歌单数量限制校验"
    category: "bugfix"              # bugfix / refactor
    difficulty: "easy"
    description: |                  # 给 agent 的任务描述
      ...
    files: [...]                    # 传给 agent 的文件列表
    expected_changed_files: [...]   # 至少应修改的文件
    allowed_changed_files: [...]    # 允许修改的范围
    forbidden_changed_files: [...]  # 禁止修改的文件/目录
    baseline_should_fail: true      # broken baseline 的 oracle 应失败
    baseline_check_command: "..."   # baseline 验证命令
    oracle_test_command: "..."      # 任务专属测试
    regression_test_command: "..."  # 回归测试
    max_files_changed: 1            # 最小改动约束
    max_lines_total: 60
```

## 当前任务

| ID | 标题 | 类型 | 难度 |
|----|------|------|------|
| T001 | 修复歌单数量限制校验 | bugfix | easy |
| T002 | 将小程序推荐引擎改为 async/await | refactor | medium |
| T003 | 提取 API 错误处理中间件 | refactor | medium |

T004-T006 暂停，等第一阶段完成后再启用。

## 快速开始

### 环境准备

```bash
# Python 虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate
pip install aider-chat pyyaml

# Node.js（后端测试需要）
nvm install 20 && nvm use 20

# 配置 API Key
cp .env.example .env
# 编辑 .env 填入 API Key
```

### 运行评测

```bash
source .venv/bin/activate

# 跑单个任务
python eval_runner.py --model glm-5.1 --task T001 --runs 3

# 跑所有任务
python eval_runner.py --model glm-5.1 --all --runs 3

# 查看报告
python eval_runner.py --report

# 指定配置标签（用于 harness 实验）
python eval_runner.py --model glm-5.1 --task T001 --config H001
```

### 手动验证 Oracle

```bash
# T001 — 后端歌单数量限制
cd project/deathplaylist_backends
export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
DB_DATABASE=:memory: npx jest --config test/jest-e2e.json \
  --testPathPattern=eval-task-T001 --forceExit

# T002 — 小程序 async/await
cd project/deathplaylist_miniprogram
node test/eval-task-T002.test.js

# T003 — 后端错误处理中间件
cd project/deathplaylist_backends
DB_DATABASE=:memory: npx jest --config test/jest-e2e.json \
  --testPathPattern=eval-task-T003 --forceExit
```

## 评测流程

```
1. create_worktree()     → 复制 project/ 到隔离工作区
2. baseline_check        → 运行 baseline oracle，验证 broken baseline 确实失败
3. run_agent()           → Aider 执行代码修改
4. oracle_validation     → 运行任务专属测试
5. regression_validation → 运行回归测试
6. scope_check           → 检查文件修改范围
7. build_scorecard       → 多维评分
8. save_artifacts        → 保存 patch.diff、日志、metrics
9. preserve_failed       → 失败样本保留到 .eval_worktrees/failed/
```

## 结果示例

```json
{
  "config": "baseline",
  "task_id": "T001",
  "model": "glm-5.1",
  "run_index": 0,
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
  "elapsed_seconds": 108.4,
  "files_changed": 1,
  "lines_total": 8,
  "changed_files": ["deathplaylist_backends/src/playlists/playlists.service.ts"]
}
```

## 后续计划

1. **Step 6**：T001-T003 × 3 runs 建立可信 baseline
2. **Step 7**：复盘失败样本
3. **H001-H003**：Harness 实验变量（system prompt / 上下文注入 / 分步引导）
4. **多模型对比**：接入 DeepSeek / Claude / Gemini
5. **T004-T006**：高阶任务恢复

## 技术栈

| 组件 | 技术 |
|------|------|
| Harness | Aider 0.86.2 |
| 运行器 | Python 3.12 |
| 后端测试 | Jest + NestJS Testing + supertest |
| 前端测试 | TypeScript 编译 + Vite 构建 |
| 小程序测试 | 纯 Node.js 脚本 + wx mock |
| 数据库 | SQLite (:memory:) |
| LLM API | OpenAI-compatible（GLM-5.1） |
