# CLAUDE.md — harness-eval 项目

## 文件管理规则

- 所有文档类文件统一存放在 `docs/` 目录下，README.md 除外
- 不要在项目根目录创建 .md 文档文件（README.md 除外）

## 项目概述

AI 编码能力评测框架。以「死亡歌单」小程序项目（`project/`）作为测试床，通过 Aider 驱动 LLM 执行预定义的代码修改任务，对修改结果进行多维定量评估。

`project/` 目录是独立的 git 仓库（gitignored），有自己的 `CLAUDE.md`，不要修改原始 deathplaylist 项目——只通过 eval pipeline 操作 worktree 副本。

## 核心流程

每个任务遵循三段式验证：
```
broken_baseline_FAIL → agent_修改 → oracle_PASS + regression_PASS
```

7 维 scorecard 全部通过才计为 `final_pass`：agent_execution、baseline_valid、correctness、regression、scope_control、minimality、instruction_following。

## 环境依赖

| 工具 | 版本 | 路径 |
|------|------|------|
| Python | 3.12 | `.venv` |
| Node.js | 20（评测用，非系统默认） | `/opt/homebrew/opt/node@20/bin/node` |
| Aider | 0.86.2 | `.venv/bin/aider` |
| pip 包 | `aider-chat`, `pyyaml` | `.venv` |

系统默认 Node 是 v26，不要用于评测。eval_runner.py 自动将 Node 20 路径注入 PATH。

## 运行命令

```bash
source .venv/bin/activate

# 跑单个任务
python eval_runner.py --model glm-5.1 --task T001 --harness-config H0_baseline --runs 3

# 跑所有任务
python eval_runner.py --model glm-5.1 --all --harness-config H0_baseline --runs 3

# 查看报告
python eval_runner.py --report

# 对比不同配置
python eval_runner.py --report --compare H0_baseline H2_structured_prompt
```

## 关键文件

| 文件 | 职责 |
|------|------|
| `eval_runner.py` | 评测运行器（Python），调用 Aider、执行测试、生成 scorecard |
| `tasks.yaml` | 任务定义（v2 结构化），当前 T001-T006 |
| `harness_configs.yaml` | Harness 实验配置（H0-H6）+ prompt 模板 + context mode |
| `project/` | 测试项目代码（gitignored，不入库） |
| `eval_results/` | 评测结果（gitignored），按 config_id 分目录 |
| `.eval_worktrees/` | 运行时隔离工作区（gitignored） |

## 模型配置

`.env` 文件存放 API Key（gitignored），支持四个 LLM 提供商：

| 短名 | Aider 模型 ID | 状态 |
|------|--------------|------|
| `glm-5.1` | `openai/glm-5.1` | 已配置 |
| `deepseek-v4-flash` | `deepseek/deepseek-v4-flash` | 占位 |
| `deepseek-v4-pro` | `deepseek/deepseek-v4-pro` | 占位 |
| `gemini-3.1-pro` | `gemini/gemini-3.1-pro` | 占位 |
| `claude-sonnet` | `anthropic/claude-sonnet-4-6` | 占位 |

GLM-5.1 使用 OpenAI 兼容接口 `https://open.bigmodel.cn/api/coding/paas/v4`，eval_runner 自动添加 `--openai-api-base` 参数。当前仅维护 GLM API key，其他保持占位值。

## 任务结构

每个任务（tasks.yaml）包含：
- `description`：给 agent 的自然语言任务描述
- `files`：传给 Aider 的文件列表
- `allowed/expected/forbidden_changed_files`：scope 控制（支持 `**` glob）
- `baseline_check_command` / `oracle_test_command` / `regression_test_command`：三段式测试命令
- `max_files_changed` / `max_lines_total`：最小改动约束
- `business_invariants`：业务不变量描述

## Harness 四层架构

| 层 | 变量 | 范围 |
|----|------|------|
| Prompt Layer | prompt_template | raw → constrained → structured |
| Context Layer | context_mode + map_tokens | file_args_only → repo_map → oracle_visible |
| Execution Layer | feedback_rounds | 1 → 2 → 3（oracle 失败时回喂测试输出） |
| Control & Audit | scope_guard + audit_level | post_check + basic/full |

H0-H6 阶梯式实验，每次只多释放一个变量。

## 当前任务清单

| ID | 标题 | 类型 | 难度 |
|----|------|------|------|
| T001 | 修复歌单数量限制校验 | bugfix | easy |
| T002 | 将小程序推荐引擎改为 async/await | refactor | medium |
| T003 | 提取 API 错误处理中间件 | refactor | medium |
| T004 | 后端拒绝空歌单 | bugfix | easy |
| T005 | 修复小程序容器模式缺失 401 处理 | bugfix | medium |
| T006 | 批量歌曲 upsert | refactor | hard |

## Oracle 测试模式

- **后端任务**（T001/T003/T004/T006）：Jest e2e + NestJS Testing + supertest，`DB_DATABASE=:memory:` SQLite
- **小程序任务**（T002/T005）：纯 Node.js 脚本 + wx mock + vm.runInNewContext
- **动态加载**：oracle 测试通过动态 require/import agent 创建的文件，不硬编码路径

## Git 操作规范

- 推送到 GitHub 时不直接 push main，通过分支 + PR 方式
- commit message 使用中文
- 远程仓库：`git@github.com:chenerzhong123-cloud/harness-seek.git`
