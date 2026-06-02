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

### Step 6 — 可信 Baseline ✅

GLM-5.1 × T001-T003 × 3 runs：

| 任务 | 通过率 | 平均耗时 | 改动量 |
|------|--------|----------|--------|
| T001 修复歌单数量限制 | **3/3 (100%)** | 87.1s | 1 file / 8 lines |
| T002 将 callback 改为 async/await | **3/3 (100%)** | 217.0s | 1 file / 94 lines |
| T003 提取 API 错误处理中间件 | **0/3 (0%)** | 42.4s | 1 file / 33 lines |

**T003 失败分析**：
- Run 0: filter 创建在 `src/filters/` 而非 `src/common/filters/`，scope_control FAIL + oracle FAIL
- Run 1: 模型输出了计划但未应用任何修改（0 files changed）
- Run 2: 同 Run 0，路径错误 + 错误响应格式不符合 `{ code, message, data: null }`

**核心问题**：T003 任务描述中指定了 `src/common/filters/` 路径，但模型选择自作主张放在 `src/filters/`。即使创建了 filter，NestJS 的错误响应格式转换也不正确。

### Step 7 — T003 失败复盘 + 修复 ✅

**失败根因分析**（三层问题）：

1. **Oracle 测试不加载 agent 的 filter**：oracle 自己创建 app 实例，只注册了 `ValidationPipe`，没有导入 agent 写的 filter。即使 agent 代码完全正确，oracle 也不会通过。
2. **任务描述路径不自然**：指定 `src/common/filters/` 但项目目录下没有 `common/`，模型自然选择 `src/filters/`。
3. **任务描述过于简略**：没有指定类名、装饰器、响应示例，模型行为不一致。

**修复措施**：

- Oracle 测试增加动态 require：尝试从 `src/filters/` 和 `src/common/filters/` 导入 filter 并注册到测试 app
- 任务描述精确化：指定路径 `src/filters/`、类名 `UnifiedExceptionFilter`、`@Catch()` 装饰器、包含响应示例
- `expected/allowed_changed_files` 从 `src/common/filters/**` 改为 `src/filters/**`
- eval_runner.py 添加 `--no-show-model-warnings` 抑制 Aider 警告弹窗

**验证结果**（GLM-5.1 × T003 × 3 runs, config=step7）：

| 指标 | Baseline (Step 6) | Step 7 改进后 |
|------|-------------------|---------------|
| 通过率 | 0/3 (0%) | **3/3 (100%)** |
| 平均耗时 | 42.4s | 46.7s |
| 改动量 | 1 file / 33 lines | 2 files / 52 lines |
| scope_control | 0/3 | **3/3** |
| correctness | 0/3 | **3/3** |

### Step 8 — Harness 分层优化架构实施 ✅

基于 HARNESS_CONFIGS_DESIGN.md 方案，完成四层优化架构实施：

**新增文件：**
- `harness_configs.yaml` — 7 个阶梯式实验配置（H0-H6），含 prompt 模板、context mode、feedback rounds
- `eval_runner.md` — runner 说明文档，与 .py 同步

**tasks.yaml 升级：**
- T001-T003 新增 `business_invariants` 字段（structured 模板需要）

**eval_runner.py 升级：**

1. **Harness config 支持**：`--harness-config` 参数，从 harness_configs.yaml 读取配置
2. **Prompt 渲染**：`render_prompt()` 按模板（raw/constrained/structured）生成 prompt
3. **Context mode**：`run_agent()` 根据 context_mode 决定传给 Aider 的文件（oracle_visible 时额外传入测试文件）
4. **Feedback loop**：`run_with_feedback()` 支持多轮反馈，oracle 失败时把测试输出喂回 agent
5. **Full audit**：audit_level=full 时保存 prompt.md、per_round_metrics.json
6. **结果按 config 分目录**：eval_results/H0_baseline/、eval_results/H4_feedback_2round/ 等
7. **报告对比**：`--report --compare H0 H2 H4` 横向对比不同 config

**四层实验变量：**

| 层 | 变量 | 实验范围 |
|---|---|---|
| Prompt Layer | prompt_template | raw → constrained → structured (H0→H2) |
| Context Layer | context_mode + map_tokens | file_args → oracle_visible → repo_map_4096 (H3, H6) |
| Execution Layer | feedback_rounds | 1 → 2 → 3 (H4→H5) |
| Control & Audit | scope_guard + audit_level | post_check + basic/full (H0→H6) |

### Step 9 — T004-T006 任务优化 ✅

原始 T004-T006 存在严重设计缺陷（无前端测试/验证形同虚设/描述问题不存在），全部重新设计：

**T004 替换**：前端瘦身 → 后端拒绝空歌单（bugfix, easy）
- 业务不变量：歌单必须 1-9 首歌曲，空数组无效
- Oracle 6 用例，包括 "PUT 只改 intro 不传 songs 仍可更新" 防退化

**T005 重写**：oracle 只检查导出 → 行为测试为主 + 静态分析辅助
- 主 oracle：vm.runInNewContext 强制走 container 模式，验证 401 清 JWT/user/globalData
- 辅助静态分析：containerRequest 函数体包含 401 分支

**T006 重定义**：描述不存在的 N+1 → 真实 upsertPlaylistSongs 批量优化
- Oracle：spy findOrCreate=0 + spy findOrCreateMany=1 + sortOrder + 混合新旧歌曲

**GLM-5.1 × T004-T006 × 3 runs (H0_baseline)：**

| 任务 | 通过率 | 平均耗时 | 改动量 |
|------|--------|----------|--------|
| T004 后端拒绝空歌单 | **3/3 (100%)** | 41.0s | 1 file / 4 lines |
| T005 container mode 401 | **3/3 (100%)** | 18.8s | 1 file / 7 lines |
| T006 批量歌曲 upsert | **3/3 (100%)** | 85.9s | 2 files / 78 lines |

**至此 T001-T006 全部 100% 通过。**

### 下一步：Harness 分层实验

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
