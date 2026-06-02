# Eval Pipeline 进展记录

> 最后更新: 2026-06-02

## 已完成

- [x] Harness 选型：OpenCode → Aider 0.86.2（OpenCode 于 2025-09 归档）
- [x] EVAL_PLAN.md 更新（OpenCode → Aider 全部替换）
- [x] 项目配置文件：tasks.yaml, test-cases.yaml, harness_experiments.yaml, .gitignore
- [x] 后端 API 集成测试：20/20 通过（test/eval-api.e2e-spec.ts）
- [x] eval_runner.py 编写完成（含 .env 加载、node_modules symlink、Node 20 PATH）
- [x] 端到端验证：GLM-5.1 + T001 → PASS（15.3s）
- [x] Baseline 实验：GLM-5.1 × 6 tasks × 3 runs（83% 通过率，T004 失败）

## 优化方案执行（HARNESS_EVAL_OPTIMIZATION_PLAN.md）

### Step 2 — Oracle 测试 ✅

新增三个任务级 oracle 测试：
- `project/deathplaylist_backends/test/eval-task-T001.e2e-spec.ts` — 3 tests（歌单数量限制）
- `project/deathplaylist_miniprogram/test/eval-task-T002.test.js` — 10 tests（async/await 检测 + 行为验证）
- `project/deathplaylist_backends/test/eval-task-T003.e2e-spec.ts` — 5 tests（统一错误格式）

### Step 3 — Baseline 验证 ✅

发现 T001、T002 基线已被污染（代码已修复）。创建 broken baseline：
- T001：移除 `MAX_SONGS = 9` 及 create/update 中的两个校验
- T002：将 async/await 改回 callback 嵌套模式（fetchOne/fetchBatch/loadRecommendations）
- T003：无需修改（原代码无统一错误 filter）

验证结果：三个 broken baseline 全部 FAIL oracle ✅

### Step 4 — tasks.yaml v2 升级 ✅

- 只保留 T001-T003（T004-T006 暂停）
- 新增结构化字段：category, difficulty, expected_changed_files, allowed_changed_files, forbidden_changed_files
- 新增验证字段：baseline_should_fail, baseline_check_command, oracle_test_command, regression_test_command
- 新增约束字段：max_files_changed, max_lines_total

### Step 5 — Runner 升级 ✅

eval_runner.py 升级完成，新增功能：

1. **Baseline check**：agent 执行前验证 broken baseline oracle 是否失败
2. **Oracle + Regression 拆分**：独立运行 oracle_test_command 和 regression_test_command
3. **Scope check**：检查 expected/allowed/forbidden files（支持 `**` glob）
4. **Scorecard 多维评分**：agent_execution, baseline_valid, correctness, regression, scope_control, minimality, instruction_following
5. **Artifact 保存**：每次 run 保存到 `eval_results/runs/{timestamp}_{task}_{model}_{run}/`
   - metrics.json, patch.diff, agent_stdout/stderr.log
   - baseline/oracle/regression 的 stdout/stderr.log
6. **失败 worktree 保留**：FAIL 的 run 自动保存到 `.eval_worktrees/failed/`
7. **Report 升级**：显示 scorecard 百分比、failure reasons、review flags

**T001 验证通过**：GLM-5.1 × 1 run → final_pass=true, scorecard 全绿, 108.4s, 1 file/8 lines

### 下一步：Step 6 — 重新跑小规模可信 baseline

```bash
source .venv/bin/activate
python eval_runner.py --model glm-5.1 --task T001 --runs 3 --config baseline
python eval_runner.py --model glm-5.1 --task T002 --runs 3 --config baseline
python eval_runner.py --model glm-5.1 --task T003 --runs 3 --config baseline
python eval_runner.py --report
```

## 待解决

- [ ] DeepSeek / Anthropic / Google API Key 仍为占位值（当前仅用 GLM-5.1）
- [ ] Token usage 统计仍为 null（GLM-5.1 输出格式不匹配 regex）

## 环境依赖

| 工具 | 版本 | 路径 |
|------|------|------|
| Node (默认) | v26.0.0 | /opt/homebrew/bin/node |
| Node 20 (eval用) | v20.20.2 | /opt/homebrew/opt/node@20/bin/node |
| Python | 3.12.13 | .venv |
| Aider | 0.86.2 | .venv/bin/aider |
| GLM-5.1 API | 已配置 | .env |

## 运行命令

```bash
# 激活 venv
source .venv/bin/activate

# Oracle 测试验证
export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
cd project/deathplaylist_backends && DB_DATABASE=:memory: npx jest --config test/jest-e2e.json --testPathPattern=eval-task-T001 --forceExit

# 跑单个任务（升级后 runner）
python eval_runner.py --model glm-5.1 --task T001 --runs 1

# 跑所有任务
python eval_runner.py --model glm-5.1 --all --runs 3

# 查看报告
python eval_runner.py --report
```
