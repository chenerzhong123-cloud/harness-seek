# Aider 优化分层方案

基于 harness-eval 场景，Aider 的优化从易到难分为 4 层。

## 第1层：调 Aider 参数（不改源码）

`eval_runner.py` 通过命令行调用 Aider，可直接调整的参数：

| 方向 | 参数 | 作用 |
|------|------|------|
| 模型 | `--model` | 切换不同模型对比效果 |
| 系统提示 | `--system-message` | 约束 agent 行为边界 |
| 编辑模式 | `--edit-format` | diff/whole/udiff 等，影响代码修改方式 |
| 自动提交 | `--auto-commits` / `--no-auto-commits` | 控制是否自动 commit |
| 多文件 | `--file` | 控制传入哪些文件作为上下文 |
| map 模式 | `--map-tokens` | 控制代码仓库 map 的大小 |

对应 harness 实验中的 **H001（系统提示优化）** 和 **H002（上下文注入）**。

## 第2层：改 prompt 模板（不改源码）

在 `eval_runner.py` 里调整发给 Aider 的任务描述格式：

```python
# 当前
prompt = task["description"]

# 优化后
prompt = f"""
{task['description']}

约束条件：
- 只允许修改：{task['allowed_changed_files']}
- 禁止修改：{task['forbidden_changed_files']}
- 最多修改 {task['max_files_changed']} 个文件
"""
```

成本最低、见效最快，是**优先级最高的优化方向**。

## 第3层：改 Aider 源码（fork）

需要更深层的控制时：

- 限制 Aider 的文件修改范围（不允许自主选文件）
- 插入中间验证步骤（改一段代码后跑一次测试）
- 自定义 diff 生成逻辑
- 截获 Aider 的内部决策过程用于分析

需要 fork Aider，修改 Python 源码。

## 第4层：换掉 Aider

`eval_runner.py` 的本质是「给 agent 一个任务 → agent 改代码 → 验证结果」，Aider 只是其中一个 agent 实现。也可以替换为：

- Claude Code 的非交互模式
- 直接调 LLM API + 自己写工具调用逻辑
- OpenHands、SWE-Agent 等其他 agent

## 建议顺序

根据「先修 eval 可信度，再扩实验变量」的原则：

```
先做第2层（prompt 优化）→ 建立可信 baseline
再做第1层（参数对比）  → H001/H002/H003 实验
视需要做第3层（源码改动）
第4层是最后考虑的
```

第2层改动的 ROI 最高——不改任何基础设施，只改 prompt 模板就能看到效果差异。
