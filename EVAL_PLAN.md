# DeathPlaylist Eval 方案

> 基于 Cursor 的线上线下评测理念，构建最小可运行的 Harness 评测流程

## 整体架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  任务定义    │────→│  Eval Runner │────→│  结果收集    │
│  (YAML)     │     │  (Python)    │     │  (JSON)     │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────┴───────┐
                    │  Coding Agent│
                    │  (Harness)   │
                    └──────┬───────┘
                           │
                    ┌──────┴───────┐
                    │  项目代码    │
                    │  (worktree)  │
                    └──────────────┘
```

## 第零步：选型

### Harness 选择

| 候选 | 语言 | 多模型支持 | CLI 可编程 | 适合程度 |
|------|------|-----------|-----------|---------|
| **Aider** | **Python** | **好（OpenAI 兼容 + 多 provider）** | **好** | **高** |
| 自建（API 直调） | Python | 完全自定义 | 完全 | 最高自由度 |

**选用 Aider**：Python 编写、活跃的开源社区、支持 OpenAI 兼容接口（可接入 GLM/DeepSeek 等）、`--yes-always` 非交互模式适合自动化评测、内置 git 集成（自动 commit 代码变更）。

安装：
```bash
pip install aider-chat
# 验证
aider --version
```


### 待测模型

```yaml
models:
  - deepseek/deepseek-v4-flash    # DeepSeek V4 Flash
  - deepseek/deepseek-v4-pro      # DeepSeek V4 Pro
  - zai/glm-5.1                # GLM-5.1
  - google/gemini-3.1-pro      # Gemini 3.1 Pro
  - anthropic/claude-sonnet-4.6   # Claude Sonnet 4.6
```

## 第一步：建立正确性基准（测试套件）

当前项目零测试。在开始任何 eval 之前，必须先有测试。

### 后端 API 集成测试（优先级最高）

利用 NestJS 已有的 Jest 基础设施，写 API 级别的集成测试：

```typescript
// deathplaylist_backends/test/eval-api.e2e-spec.ts
import { Test, TestingModule } from '@nestjs/testing';
import { INestApplication } from '@nestjs/common';
import * as request from 'supertest';

describe('Eval API Suite', () => {
  let app: INestApplication;

  beforeAll(async () => {
    // 使用独立的测试数据库
    process.env.DB_PATH = ':memory:';
    const moduleFixture = await Test.createTestingModule({
      // ... AppModule
    }).compile();
    app = moduleFixture.createNestApplication();
    await app.init();
  });

  // === 用户流程测试 ===

  it('完整流程：搜索 → 创建歌单 → 分享', async () => {
    // 1. 搜索歌曲
    const searchRes = await request(app.getHttpServer())
      .get('/api/songs/search?keyword=周杰伦')
      .expect(200);
    expect(searchRes.body.results.length).toBeGreaterThan(0);

    // 2. 创建歌单（需 auth）
    const playlistRes = await request(app.getHttpServer())
      .post('/api/playlists')
      .set('Authorization', `Bearer ${testToken}`)
      .send({ songs: [songId1, songId2], intro: 'test intro' })
      .expect(201);

    // 3. 获取歌单
    await request(app.getHttpServer())
      .get(`/api/playlists/${playlistRes.body.id}`)
      .expect(200);

    // 4. 分享链接
    await request(app.getHttpServer())
      .get(`/api/share/${playlistRes.body.id}/wxacode`)
      .expect(200);
  });

  // === 边界测试 ===

  it('歌单最多只能包含 9 首歌', async () => { /* ... */ });
  it('用户只能创建一个歌单', async () => { /* ... */ });
  it('未登录用户可以查看公开歌单', async () => { /* ... */ });
  it('歌单 intro 为空时使用默认文案', async () => { /* ... */ });
});
```

### 测试分类

```yaml
# test-cases.yaml — 测试用例定义
critical:  # 必须通过，否则任务失败
  - name: 搜索歌曲返回结果
    endpoint: GET /api/songs/search
  - name: 创建歌单成功
    endpoint: POST /api/playlists
  - name: 获取公开歌单
    endpoint: GET /api/playlists/:id
  - name: 微信登录流程
    endpoint: POST /api/auth/wechat

important:  # 重要但不是致命
  - name: 好友歌单列表
    endpoint: GET /api/playlists/friends
  - name: 用户信息更新
    endpoint: PATCH /api/users/me

nice_to_have:  # 锦上添花
  - name: 统计接口
    endpoint: GET /api/stats
```

### 验证测试套件可运行

```bash
cd deathplaylist_backends
npm install --save-dev supertest @types/supertest
# 写完测试后
npm run test:e2e
# 确保全部通过（这是 baseline）
```

## 第二步：定义评测任务

从 REFACTOR_PLAN.md 和已知 bug 中提取具体任务。每个任务必须：
- 独立可执行
- 有明确完成标准（测试通过）
- 可在 30 分钟内完成

```yaml
# tasks.yaml
tasks:
  - id: T001
    title: "修复歌单数量限制校验"
    description: |
      后端缺少歌单歌曲数量上限校验。当前用户可以添加超过 9 首歌。
      请在 playlist service 中添加校验：歌曲数量不超过 9 首，
      超出时返回 400 错误和明确的错误消息。
    files:
      - src/playlists/playlists.service.ts
      - src/playlists/playlists.controller.ts
    test_command: "cd deathplaylist_backends && npm run test:e2e -- --testPathPattern=playlist"
    pass_criteria: "测试套件全部通过"

  - id: T002
    title: "将 callback 改为 async/await"
    description: |
      recommend.js 中的关键词轮换引擎使用了嵌套 callback。
      请将所有 callback 改为 async/await，保持功能不变。
    files:
      - deathplaylist_miniprogram/utils/recommend.js
    test_command: "cd deathplaylist_miniprogram && node -e \"require('./utils/recommend.js')\""
    pass_criteria: "模块加载不报错，导出函数签名不变"

  - id: T003
    title: "提取 API 错误处理中间件"
    description: |
      后端各 controller 中存在重复的 try/catch 错误处理逻辑。
      请创建一个 NestJS exception filter，统一处理所有未捕获异常，
      返回标准化的错误响应格式 { code, message, data: null }。
      然后移除各 controller 中的重复 try/catch。
    files:
      - src/common/filters/
      - src/**/*.controller.ts
    test_command: "cd deathplaylist_backends && npm run test:e2e"
    pass_criteria: "所有 API 测试通过，手动验证错误返回格式"

  - id: T004
    title: "前端 App.tsx 瘦身"
    description: |
      App.tsx 仍有约 300 行代码，应进一步瘦身为 ~150 行的路由壳。
      将剩余的业务逻辑提取到对应的 hooks 和 views 中。
      功能不能有任何退化。
    files:
      - deathplaylist_frontend/src/App.tsx
      - deathplaylist_frontend/src/hooks/
      - deathplaylist_frontend/src/views/
    test_command: "cd deathplaylist_frontend && npx tsc --noEmit && npm run build"
    pass_criteria: "TypeScript 编译通过，Vite 构建成功"

  - id: T005
    title: "小程序 API 层统一错误处理"
    description: |
      api.js 中每个请求函数都有自己的错误处理逻辑，不一致且重复。
      请提取一个统一的 request 函数，处理认证 token 注入、
      错误码映射、网络异常重试（最多 1 次）。
      所有 API 调用改用这个统一函数。
    files:
      - deathplaylist_miniprogram/utils/api.js
    test_command: "cd deathplaylist_miniprogram && node -e \"const api = require('./utils/api.js'); console.log(Object.keys(api))\""
    pass_criteria: "模块导出不变，所有页面功能不退化"

  - id: T006
    title: "后端 TypeORM 查询优化"
    description: |
      friends 相关的查询存在 N+1 问题：获取好友歌单列表时，
      对每个好友单独查询歌单。请使用 JOIN 或 relations 选项
      优化为单次查询。
    files:
      - src/friends/friends.service.ts
      - src/playlists/playlists.service.ts
    test_command: "cd deathplaylist_backends && npm run test:e2e"
    pass_criteria: "测试通过，手动验证 SQL 查询数量减少"
```

## 第三步：Eval Runner 脚本

```python
#!/usr/bin/env python3
"""
eval_runner.py — DeathPlaylist Harness 评测运行器

使用方式：
  python eval_runner.py --model deepseek-v4-flash --task T001
  python eval_runner.py --model deepseek-v4-flash --all
  python eval_runner.py --compare  # 对比所有模型
"""

import argparse
import json
import os
import subprocess
import time
import yaml
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
TASKS_FILE = PROJECT_ROOT / "tasks.yaml"
RESULTS_DIR = PROJECT_ROOT / "eval_results"

# 模型 → Aider --model 参数映射
MODEL_MAP = {
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "glm-5.1": "openai/glm-5.1",           # GLM 通过 OpenAI 兼容接口
    "gemini-3.1-pro": "gemini/gemini-3.1-pro",
    "claude-sonnet": "anthropic/claude-sonnet-4-6",
}


def load_tasks():
    with open(TASKS_FILE) as f:
        return yaml.safe_load(f)["tasks"]


def _get_aider_extra_args(model_name: str) -> list:
    """根据模型生成 Aider 额外参数"""
    args = []
    if "glm" in model_name:
        # GLM 使用 OpenAI 兼容接口，需要指定 base URL
        base_url = os.environ.get("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
        args.extend(["--openai-api-base", base_url])
    elif "deepseek" in model_name:
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        args.extend(["--openai-api-base", base_url])
    return args


def create_worktree(task_id: str, model_name: str, run_index: int) -> Path:
    """为每次运行创建独立的 git worktree"""
    branch_name = f"eval/{task_id}/{model_name}/run-{run_index}"
    worktree_path = PROJECT_ROOT / f".eval_worktrees/{task_id}_{model_name}_{run_index}"

    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree_path)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    return worktree_path


def run_agent(task: dict, model_name: str, worktree_path: Path) -> dict:
    """在 worktree 中运行 Aider coding agent"""
    aider_model = MODEL_MAP[model_name]

    # 将任务描述写入文件（作为 Aider 的 prompt）
    task_file = worktree_path / ".eval_task.md"
    with open(task_file, "w") as f:
        f.write(f"# Task: {task['title']}\n\n{task['description']}")

    # 构建 Aider 命令
    cmd = [
        "aider",
        "--model", aider_model,
        "--yes-always",          # 非交互模式
        "--no-auto-commits",     # 由 eval_runner 管理提交
        "--message", task["description"],
    ]
    cmd.extend(_get_aider_extra_args(model_name))

    # 添加任务涉及的文件
    for f in task.get("files", []):
        file_path = worktree_path / f
        if file_path.exists():
            cmd.append(str(file_path))

    start_time = time.time()

    result = subprocess.run(
        cmd,
        cwd=worktree_path,
        capture_output=True,
        text=True,
        timeout=1800,  # 30 分钟超时
    )

    elapsed = time.time() - start_time

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": round(elapsed, 1),
    }


def run_validation(task: dict, worktree_path: Path) -> dict:
    """运行测试验证"""
    test_cmd = task["test_command"]
    result = subprocess.run(
        test_cmd,
        shell=True,
        cwd=worktree_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return {
        "passed": result.returncode == 0,
        "stdout": result.stdout[-2000:],  # 只保留最后 2000 字符
        "stderr": result.stderr[-1000:],
    }


def collect_metrics(task: dict, model_name: str, agent_result: dict,
                    validation: dict, run_index: int) -> dict:
    """收集评测指标"""
    return {
        "task_id": task["id"],
        "task_title": task["title"],
        "model": model_name,
        "run_index": run_index,
        "timestamp": datetime.now().isoformat(),
        "pass_rate": 1 if validation["passed"] else 0,
        "elapsed_seconds": agent_result["elapsed_seconds"],
        "agent_exit_code": agent_result["returncode"],
        "timeout": agent_result["elapsed_seconds"] >= 1800,
        "validation_output": validation["stdout"][-500:],
    }


def run_single(task_id: str, model_name: str, num_runs: int = 3):
    """运行单个任务的多次评测"""
    tasks = load_tasks()
    task = next(t for t in tasks if t["id"] == task_id)
    results = []

    for i in range(num_runs):
        print(f"\n{'='*60}")
        print(f"运行 {task_id} | {model_name} | 第 {i+1}/{num_runs} 次")
        print(f"{'='*60}")

        worktree_path = create_worktree(task_id, model_name, i)
        try:
            agent_result = run_agent(task, model_name, worktree_path)
            validation = run_validation(task, worktree_path)
            metrics = collect_metrics(task, model_name, agent_result, validation, i)
            results.append(metrics)

            status = "✓ 通过" if validation["passed"] else "✗ 失败"
            print(f"\n结果: {status} | 耗时: {metrics['elapsed_seconds']}s")
        except subprocess.TimeoutExpired:
            print(f"\n超时！")
            results.append({
                "task_id": task_id, "model": model_name, "run_index": i,
                "pass_rate": 0, "timeout": True, "elapsed_seconds": 1800,
            })
        finally:
            # 清理 worktree
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=PROJECT_ROOT, capture_output=True,
            )

    # 保存结果
    RESULTS_DIR.mkdir(exist_ok=True)
    result_file = RESULTS_DIR / f"{task_id}_{model_name}.json"
    with open(result_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 打印汇总
    passed = sum(r["pass_rate"] for r in results)
    avg_time = sum(r["elapsed_seconds"] for r in results) / len(results)
    print(f"\n{'='*60}")
    print(f"汇总: {task_id} | {model_name}")
    print(f"通过率: {passed}/{num_runs} ({passed/num_runs*100:.0f}%)")
    print(f"平均耗时: {avg_time:.1f}s")
    print(f"结果已保存: {result_file}")


def compare_models(task_id: str = None, num_runs: int = 3):
    """对比所有模型"""
    tasks = load_tasks()
    if task_id:
        tasks = [t for t in tasks if t["id"] == task_id]

    print(f"\n{'='*60}")
    print(f"开始对比评测 | {len(tasks)} 个任务 | {num_runs} 次运行")
    print(f"模型: {list(MODEL_MAP.keys())}")
    print(f"{'='*60}")

    for task in tasks:
        for model_name in MODEL_MAP:
            run_single(task["id"], model_name, num_runs)

    # 生成对比报告
    generate_report()


def generate_report():
    """生成对比报告"""
    all_results = []
    for f in RESULTS_DIR.glob("*.json"):
        with open(f) as fh:
            all_results.extend(json.load(fh))

    if not all_results:
        print("无结果数据")
        return

    print(f"\n\n{'='*60}")
    print("评测对比报告")
    print(f"{'='*60}\n")

    models = sorted(set(r["model"] for r in all_results))
    tasks = sorted(set(r["task_id"] for r in all_results))

    # 表头
    header = f"{'任务':<12}" + "".join(f"{m:<20}" for m in models)
    print(header)
    print("-" * len(header))

    # 每个任务的通过率
    for tid in tasks:
        row = f"{tid:<12}"
        for model in models:
            runs = [r for r in all_results if r["task_id"] == tid and r["model"] == model]
            if runs:
                pass_rate = sum(r["pass_rate"] for r in runs) / len(runs) * 100
                avg_time = sum(r["elapsed_seconds"] for r in runs) / len(runs)
                row += f"{pass_rate:.0f}% ({avg_time:.0f}s){'':>6}"
            else:
                row += f"{'N/A':<20}"
        print(row)

    # 总分
    print("-" * len(header))
    total_row = f"{'总分':<12}"
    for model in models:
        runs = [r for r in all_results if r["model"] == model]
        if runs:
            total_pass = sum(r["pass_rate"] for r in runs) / len(runs) * 100
            total_row += f"{total_pass:.0f}%{'':>15}"
    print(total_row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DeathPlaylist Eval Runner")
    parser.add_argument("--model", help="模型名称")
    parser.add_argument("--task", help="任务 ID (如 T001)")
    parser.add_argument("--all", action="store_true", help="运行所有任务")
    parser.add_argument("--compare", action="store_true", help="对比所有模型")
    parser.add_argument("--runs", type=int, default=3, help="每个任务运行次数")
    args = parser.parse_args()

    if args.compare:
        compare_models(task_id=args.task, num_runs=args.runs)
    elif args.model and args.task:
        run_single(args.task, args.model, args.runs)
    elif args.model and args.all:
        tasks = load_tasks()
        for t in tasks:
            run_single(t["id"], args.model, args.runs)
    else:
        parser.print_help()
```

## 第四步：Harness 变量实验

当 baseline（模型对比）跑完后，开始改 harness。每次只改一个变量：

```yaml
# harness_experiments.yaml
experiments:
  - id: H001
    name: "system prompt 优化"
    description: "在 system prompt 中加入项目的技术栈说明和代码规范"
    change: "修改 opencode.json 中的 instructions 字段"
    baseline: "默认 system prompt"

  - id: H002
    name: "上下文注入"
    description: "在任务描述中额外提供相关文件的当前内容"
    change: "任务描述前注入 file context"
    baseline: "H001"

  - id: H003
    name: "分步引导"
    description: "将任务拆成子步骤，每步执行后验证再继续"
    change: "多轮交互代替单次大 prompt"
    baseline: "H001"
```

## 第五步：执行流程

```bash
# 0. 安装依赖
pip install aider-chat pyyaml          # harness + eval runner 依赖
cd project/deathplaylist_backends && npm install --save-dev supertest @types/supertest

# 1. 写测试（手动完成，这是 baseline 的核心）
#    编辑 test/eval-api.e2e-spec.ts

# 2. 验证 baseline 测试通过
cd project/deathplaylist_backends && npm run test:e2e

# 3. 单任务单模型试跑
python eval_runner.py --model glm-5.1 --task T001 --runs 1

# 4. 确认流程通畅后，跑完整对比
python eval_runner.py --compare --runs 3

# 5. 查看报告
python eval_runner.py --report
```

## 目录结构

```
harness-eval/
├── .env                        # API 密钥（不入库）
├── eval_runner.py              # 评测运行器
├── tasks.yaml                  # 任务定义
├── test-cases.yaml             # 测试用例分类
├── harness_experiments.yaml    # Harness 变量实验定义
├── eval_results/               # 运行结果（JSON）
├── .eval_worktrees/            # 临时 worktree（git 自动管理）
├── project/                    # 被测项目（git clone，不入库）
│   ├── deathplaylist_backends/
│   │   └── test/
│   │       └── eval-api.e2e-spec.ts  # API 集成测试
│   ├── deathplaylist_frontend/
│   └── deathplaylist_miniprogram/
└── ...
```

## 注意事项

1. **API Key 管理**：各模型的 API key 通过环境变量注入，不硬编码
   ```bash
   export DEEPSEEK_API_KEY=sk-xxx
   export GOOGLE_API_KEY=xxx
   export ANTHROPIC_API_KEY=sk-xxx
   # GLM-5.1 通过 Z.AI 平台，使用 OPENAI_API_KEY + 自定义 base_url
   export OPENAI_API_KEY=sk-xxx
   export OPENAI_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4
   ```

2. **费用预估**：每个任务 ~3 次运行 × 6 个任务 × 5 个模型 = 90 次 agent 调用。先从 GLM-5.1（已配置）开始调试流程，再逐步接入其他模型。

3. **超时处理**：单个任务超过 30 分钟自动终止，记为失败。

4. **Aider 的适配**：Aider 对 TypeScript 后端的理解较好，但对小程序 (.js/.wxss/.wxml) 的支持需要验证。如果小程序任务效果不佳，考虑单独为小程序任务调整配置。
