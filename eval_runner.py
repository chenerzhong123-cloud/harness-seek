#!/usr/bin/env python3
"""
eval_runner.py — DeathPlaylist Harness 评测运行器

使用方式：
  python eval_runner.py --model glm-5.1 --task T001
  python eval_runner.py --model glm-5.1 --all
  python eval_runner.py --compare  # 对比所有模型
  python eval_runner.py --report   # 查看报告
"""

import argparse
import json
import os
import re
import subprocess
import shutil
import time
import yaml
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
TASKS_FILE = PROJECT_ROOT / "tasks.yaml"
RESULTS_DIR = PROJECT_ROOT / "eval_results"
RUNS_DIR = RESULTS_DIR / "runs"
PROJECT_CODE = PROJECT_ROOT / "project"
WORKTREES_DIR = PROJECT_ROOT / ".eval_worktrees"
FAILED_DIR = WORKTREES_DIR / "failed"
VENV_AIDER = PROJECT_ROOT / ".venv" / "bin" / "aider"
ENV_FILE = PROJECT_ROOT / ".env"
CONFIG_TAG = os.environ.get("EVAL_CONFIG", "baseline")


def load_env():
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v and v != "sk-xxx" and v != "xxx":
                    os.environ.setdefault(k, v)


MODEL_MAP = {
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "glm-5.1": "openai/glm-5.1",
    "gemini-3.1-pro": "gemini/gemini-3.1-pro",
    "claude-sonnet": "anthropic/claude-sonnet-4-6",
}


def load_tasks():
    with open(TASKS_FILE) as f:
        return yaml.safe_load(f)["tasks"]


def _get_aider_extra_args(model_name: str) -> list:
    args = []
    if "glm" in model_name:
        base_url = os.environ.get("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
        args.extend(["--openai-api-base", base_url])
    elif "deepseek" in model_name:
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        args.extend(["--openai-api-base", base_url])
    return args


def create_worktree(task_id: str, model_name: str, run_index: int) -> Path:
    worktree_path = WORKTREES_DIR / f"{task_id}_{model_name}_{run_index}"
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
    shutil.copytree(PROJECT_CODE, worktree_path, ignore=shutil.ignore_patterns('.git', '.venv', '.eval_worktrees'))
    for subdir in ['deathplaylist_backends', 'deathplaylist_frontend', 'deathplaylist_miniprogram']:
        src_modules = PROJECT_CODE / subdir / 'node_modules'
        dst_modules = worktree_path / subdir / 'node_modules'
        if src_modules.exists() and not dst_modules.exists():
            dst_modules.symlink_to(src_modules)
    # 初始化 git 仓库用于 diff 统计
    subprocess.run(["git", "init"], cwd=worktree_path, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=worktree_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "baseline", "--allow-empty"], cwd=worktree_path, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@test.com",
                        "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@test.com"})
    return worktree_path


def cleanup_worktree(worktree_path: Path):
    if worktree_path.exists():
        shutil.rmtree(worktree_path)


def parse_token_usage(stdout: str) -> dict:
    """从 Aider 输出中解析 token 使用量"""
    result = {"tokens_sent": None, "tokens_received": None}
    # Aider 输出格式: "Tokens: 593 sent, 220 received."
    m = re.search(r'Tokens:\s*(\d+)\s*sent,\s*(\d+)\s*received', stdout)
    if m:
        result["tokens_sent"] = int(m.group(1))
        result["tokens_received"] = int(m.group(2))
    # 多轮对话可能有多次 token 统计，取总和
    all_matches = re.findall(r'Tokens:\s*(\d+)\s*sent,\s*(\d+)\s*received', stdout)
    if len(all_matches) > 1:
        result["tokens_sent"] = sum(int(m[0]) for m in all_matches)
        result["tokens_received"] = sum(int(m[1]) for m in all_matches)
    return result


def collect_code_diff(worktree_path: Path) -> dict:
    """用 git diff 统计代码变更"""
    result = subprocess.run(
        ["git", "diff", "--numstat", "HEAD"],
        cwd=worktree_path, capture_output=True, text=True
    )
    files_changed = 0
    lines_added = 0
    lines_deleted = 0
    changed_file_list = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            files_changed += 1
            added = int(parts[0]) if parts[0] != "-" else 0
            deleted = int(parts[1]) if parts[1] != "-" else 0
            lines_added += added
            lines_deleted += deleted
            changed_file_list.append(parts[2])
    return {
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "lines_total": lines_added + lines_deleted,
        "changed_files": changed_file_list,
    }


def run_agent(task: dict, model_name: str, worktree_path: Path) -> dict:
    aider_model = MODEL_MAP[model_name]
    aider_bin = str(VENV_AIDER) if VENV_AIDER.exists() else "aider"

    task_file = worktree_path / ".eval_task.md"
    with open(task_file, "w") as f:
        f.write(f"# Task: {task['title']}\n\n{task['description']}")

    cmd = [
        aider_bin,
        "--model", aider_model,
        "--yes-always",
        "--no-auto-commits",
        "--message", task["description"],
    ]
    cmd.extend(_get_aider_extra_args(model_name))

    for f in task.get("files", []):
        file_path = worktree_path / f
        if file_path.exists():
            cmd.append(str(file_path))

    start_time = time.time()
    result = subprocess.run(cmd, cwd=worktree_path, capture_output=True, text=True, timeout=1800)
    elapsed = time.time() - start_time

    token_info = parse_token_usage(result.stdout)
    code_diff = collect_code_diff(worktree_path)

    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-5000:],
        "stderr": result.stderr[-2000:],
        "elapsed_seconds": round(elapsed, 1),
        **token_info,
        **code_diff,
    }


def run_validation(task: dict, worktree_path: Path) -> dict:
    """Legacy: run test_command for backward compat."""
    test_cmd = task.get("test_command")
    if not test_cmd:
        return {"passed": False, "stdout": "", "stderr": "no test_command defined"}
    return _run_test_command(test_cmd, worktree_path)


def _run_test_command(cmd: str, worktree_path: Path) -> dict:
    env = os.environ.copy()
    env["PATH"] = f"/opt/homebrew/opt/node@20/bin:{env.get('PATH', '')}"
    result = subprocess.run(cmd, shell=True, cwd=worktree_path,
                            capture_output=True, text=True, timeout=300, env=env)
    return {
        "passed": result.returncode == 0,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-1000:],
    }


def check_file_scope(task: dict, changed_files: list) -> dict:
    expected = task.get("expected_changed_files", [])
    allowed = task.get("allowed_changed_files", [])
    forbidden = task.get("forbidden_changed_files", [])

    touched_expected = all(
        any(_glob_match(f, p) for f in changed_files) for p in expected
    ) if expected else True

    forbidden_touched = [
        f for f in changed_files
        if any(_glob_match(f, p) for p in forbidden)
    ]

    outside_allowed = [
        f for f in changed_files
        if allowed and not any(_glob_match(f, p) for p in allowed)
    ]

    return {
        "touched_expected_files": touched_expected,
        "forbidden_touched": forbidden_touched,
        "outside_allowed": outside_allowed,
        "scope_passed": touched_expected and not forbidden_touched and not outside_allowed,
    }


def _glob_match(filepath: str, pattern: str) -> bool:
    if "**" in pattern:
        prefix = pattern.replace("/**", "/").rstrip("*")
        return filepath.startswith(prefix) or fnmatch(filepath, pattern)
    return fnmatch(filepath, pattern)


def collect_patch(worktree_path: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=worktree_path, capture_output=True, text=True,
    )
    return result.stdout


def _save_artifacts(artifact_dir: Path, agent_result: dict,
                    baseline_result: dict, oracle_result: dict,
                    regression_result: dict, patch: str):
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "agent_stdout.log").write_text(agent_result.get("stdout", ""))
    (artifact_dir / "agent_stderr.log").write_text(agent_result.get("stderr", ""))
    (artifact_dir / "patch.diff").write_text(patch)
    if baseline_result:
        (artifact_dir / "baseline_stdout.log").write_text(baseline_result.get("stdout", ""))
        (artifact_dir / "baseline_stderr.log").write_text(baseline_result.get("stderr", ""))
    if oracle_result:
        (artifact_dir / "oracle_stdout.log").write_text(oracle_result.get("stdout", ""))
        (artifact_dir / "oracle_stderr.log").write_text(oracle_result.get("stderr", ""))
    if regression_result:
        (artifact_dir / "regression_stdout.log").write_text(regression_result.get("stdout", ""))
        (artifact_dir / "regression_stderr.log").write_text(regression_result.get("stderr", ""))


def build_scorecard(task: dict, agent_result: dict, scope: dict,
                    baseline_valid: bool, oracle_passed: bool,
                    regression_passed: bool, code_diff: dict) -> dict:
    agent_ok = agent_result.get("returncode", -1) == 0
    expected_touched = scope["touched_expected_files"]
    scope_ok = scope["scope_passed"]

    max_files = task.get("max_files_changed", 999)
    max_lines = task.get("max_lines_total", 999999)
    minimal = code_diff["files_changed"] <= max_files and code_diff["lines_total"] <= max_lines

    # instruction_following: agent exited cleanly + touched expected files + no forbidden edits
    instruction_ok = agent_ok and expected_touched and scope_ok

    scorecard = {
        "agent_execution": agent_ok,
        "baseline_valid": baseline_valid,
        "correctness": oracle_passed,
        "regression": regression_passed,
        "scope_control": scope_ok,
        "minimality": minimal,
        "instruction_following": instruction_ok,
    }

    # Collect failure reasons
    failure_reasons = []
    if not agent_ok:
        failure_reasons.append("agent_exit_code_nonzero")
    if not baseline_valid:
        failure_reasons.append("baseline_oracle_already_passes")
    if not oracle_passed:
        failure_reasons.append("oracle_tests_failed")
    if not regression_passed:
        failure_reasons.append("regression_tests_failed")
    if not expected_touched:
        failure_reasons.append("expected_files_not_touched")
    if scope["forbidden_touched"]:
        failure_reasons.append(f"modified_forbidden_files: {scope['forbidden_touched']}")
    if scope["outside_allowed"]:
        failure_reasons.append(f"modified_outside_scope: {scope['outside_allowed']}")

    review_flags = []
    if not minimal:
        review_flags.append("large_diff")

    final_pass = all(scorecard.values())

    return {
        "final_pass": final_pass,
        "scorecard": scorecard,
        "failure_reasons": failure_reasons,
        "review_flags": review_flags,
    }


def run_single(task_id: str, model_name: str, num_runs: int = 3):
    tasks = load_tasks()
    task = next(t for t in tasks if t["id"] == task_id)
    results = []

    for i in range(num_runs):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_tag = f"{ts}_{task_id}_{model_name}_{i}"
        print(f"\n{'='*60}")
        print(f"[{CONFIG_TAG}] {task_id} | {model_name} | run {i+1}/{num_runs}")
        print(f"{'='*60}")

        worktree_path = create_worktree(task_id, model_name, i)
        artifact_dir = RUNS_DIR / run_tag
        baseline_result = None
        oracle_result = None
        regression_result = None
        agent_result = {"returncode": -1, "stdout": "", "stderr": "",
                        "elapsed_seconds": 0, "tokens_sent": None, "tokens_received": None}
        invalid_task = False

        try:
            # --- Baseline check ---
            baseline_cmd = task.get("baseline_check_command")
            baseline_valid = True  # assume valid unless check fails unexpectedly
            if baseline_cmd:
                print(f"  [baseline] running oracle on broken baseline...")
                baseline_result = _run_test_command(baseline_cmd, worktree_path)
                should_fail = task.get("baseline_should_fail", True)
                if should_fail:
                    if baseline_result["passed"]:
                        print(f"  [baseline] INVALID — oracle passes on baseline (task is polluted)")
                        invalid_task = True
                        baseline_valid = False
                    else:
                        print(f"  [baseline] OK — oracle correctly fails on broken baseline")
                        baseline_valid = True
                else:
                    baseline_valid = True

            if invalid_task:
                metrics = _build_invalid_result(task, model_name, i, baseline_valid)
                results.append(metrics)
                _save_artifacts(artifact_dir, agent_result, baseline_result, None, None, "")
                _preserve_failed(worktree_path, task_id, model_name, i)
                continue

            # --- Agent run ---
            agent_result = run_agent(task, model_name, worktree_path)

            # --- Code diff ---
            code_diff = collect_code_diff(worktree_path)
            patch = collect_patch(worktree_path)

            # --- Oracle test ---
            oracle_cmd = task.get("oracle_test_command")
            oracle_passed = False
            if oracle_cmd:
                oracle_result = _run_test_command(oracle_cmd, worktree_path)
                oracle_passed = oracle_result["passed"]
            else:
                # fallback: use legacy test_command
                legacy_result = run_validation(task, worktree_path)
                oracle_result = legacy_result
                oracle_passed = legacy_result["passed"]

            # --- Regression test ---
            regression_cmd = task.get("regression_test_command")
            regression_passed = True
            if regression_cmd:
                regression_result = _run_test_command(regression_cmd, worktree_path)
                regression_passed = regression_result["passed"]

            # --- Scope check ---
            scope = check_file_scope(task, code_diff["changed_files"])

            # --- Scorecard ---
            sc = build_scorecard(task, agent_result, scope, baseline_valid,
                                 oracle_passed, regression_passed, code_diff)

            # --- Build metrics ---
            metrics = {
                "config": CONFIG_TAG,
                "task_id": task["id"],
                "task_title": task["title"],
                "model": model_name,
                "run_index": i,
                "timestamp": datetime.now().isoformat(),
                "final_pass": sc["final_pass"],
                "pass_rate": 1 if sc["final_pass"] else 0,
                "scorecard": sc["scorecard"],
                "failure_reasons": sc["failure_reasons"],
                "review_flags": sc["review_flags"],
                "elapsed_seconds": agent_result["elapsed_seconds"],
                "agent_exit_code": agent_result["returncode"],
                "timeout": agent_result["elapsed_seconds"] >= 1800,
                "tokens_sent": agent_result.get("tokens_sent"),
                "tokens_received": agent_result.get("tokens_received"),
                "files_changed": code_diff.get("files_changed", 0),
                "lines_added": code_diff.get("lines_added", 0),
                "lines_deleted": code_diff.get("lines_deleted", 0),
                "lines_total": code_diff.get("lines_total", 0),
                "changed_files": code_diff.get("changed_files", []),
                "artifact_dir": str(artifact_dir),
            }
            results.append(metrics)

            # --- Print result ---
            status = "PASS" if sc["final_pass"] else "FAIL"
            reasons = " | ".join(sc["failure_reasons"]) if sc["failure_reasons"] else ""
            tokens_s = f" | tokens: {metrics['tokens_sent']}→{metrics['tokens_received']}" if metrics['tokens_sent'] else ""
            edits = f" | edits: {metrics['files_changed']} files, {metrics['lines_total']} lines"
            print(f"\n  {status} | {metrics['elapsed_seconds']}s{tokens_s}{edits}")
            if reasons:
                print(f"  reasons: {reasons}")
            if sc["review_flags"]:
                print(f"  review: {sc['review_flags']}")

            # --- Save artifacts ---
            _save_artifacts(artifact_dir, agent_result, baseline_result,
                           oracle_result, regression_result, patch)
            (artifact_dir / "metrics.json").write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2))

            # --- Preserve failed worktrees ---
            if not sc["final_pass"]:
                _preserve_failed(worktree_path, task_id, model_name, i)

        except subprocess.TimeoutExpired:
            print(f"\n  TIMEOUT")
            results.append({
                "config": CONFIG_TAG, "task_id": task_id, "model": model_name,
                "run_index": i, "final_pass": False, "pass_rate": 0,
                "timeout": True, "elapsed_seconds": 1800,
                "failure_reasons": ["timeout"],
                "tokens_sent": None, "tokens_received": None,
                "files_changed": 0, "lines_total": 0,
            })
            _preserve_failed(worktree_path, task_id, model_name, i)
        finally:
            cleanup_worktree(worktree_path)

    RESULTS_DIR.mkdir(exist_ok=True)
    result_file = RESULTS_DIR / f"{task_id}_{model_name}_{CONFIG_TAG}.json"
    with open(result_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    passed = sum(1 for r in results if r.get("final_pass"))
    avg_time = sum(r["elapsed_seconds"] for r in results) / len(results) if results else 0
    print(f"\n{'='*60}")
    print(f"汇总: {task_id} | {model_name} | config={CONFIG_TAG}")
    print(f"通过率: {passed}/{num_runs} ({passed/num_runs*100:.0f}%) | 平均耗时: {avg_time:.1f}s")
    print(f"结果: {result_file}")


def _build_invalid_result(task, model_name, run_index, baseline_valid):
    return {
        "config": CONFIG_TAG, "task_id": task["id"],
        "task_title": task["title"], "model": model_name,
        "run_index": run_index, "final_pass": False, "pass_rate": 0,
        "scorecard": {
            "agent_execution": False, "baseline_valid": baseline_valid,
            "correctness": False, "regression": False,
            "scope_control": False, "minimality": False,
            "instruction_following": False,
        },
        "failure_reasons": ["baseline_oracle_already_passes"],
        "review_flags": [], "elapsed_seconds": 0,
        "agent_exit_code": -1, "timeout": False,
        "tokens_sent": None, "tokens_received": None,
        "files_changed": 0, "lines_total": 0, "changed_files": [],
    }


def _preserve_failed(worktree_path: Path, task_id: str, model_name: str, run_index: int):
    if not worktree_path.exists():
        return
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    failed_path = FAILED_DIR / f"{task_id}_{model_name}_{run_index}"
    if failed_path.exists():
        shutil.rmtree(failed_path)
    shutil.copytree(worktree_path, failed_path)
    print(f"  preserved failed worktree: {failed_path}")


def generate_report():
    all_results = []
    for f in RESULTS_DIR.glob("*.json"):
        if f.name.startswith("report_"):
            continue
        with open(f) as fh:
            all_results.extend(json.load(fh))

    if not all_results:
        print("无结果数据")
        return

    configs = sorted(set(r.get("config", "unknown") for r in all_results))
    tasks = sorted(set(r["task_id"] for r in all_results))
    models = sorted(set(r["model"] for r in all_results))

    print(f"\n{'='*80}")
    print(f"评测报告 | {len(all_results)} 次运行 | configs: {configs} | models: {models}")
    print(f"{'='*80}\n")

    # Per-task breakdown
    for tid in tasks:
        print(f"--- {tid} ---")
        header = f"  {'config':<14} {'pass':>5} {'time':>7} {'sent':>7} {'recv':>7} {'files':>6} {'lines':>6}  failures"
        print(header)
        for model in models:
            for config in configs:
                runs = [r for r in all_results
                        if r["task_id"] == tid and r["model"] == model and r.get("config") == config]
                if not runs:
                    continue
                n = len(runs)
                pass_rate = _pct_final_pass(runs)
                avg_time = sum(r["elapsed_seconds"] for r in runs) / n
                avg_sent = _avg_none([r.get("tokens_sent") for r in runs])
                avg_recv = _avg_none([r.get("tokens_received") for r in runs])
                avg_files = _avg_none([r.get("files_changed", 0) for r in runs])
                avg_lines = _avg_none([r.get("lines_total", 0) for r in runs])

                # Collect unique failure reasons
                all_reasons = set()
                for r in runs:
                    all_reasons.update(r.get("failure_reasons", []))

                label = f"{config}/{model}" if len(models) > 1 else config
                reason_str = ", ".join(sorted(all_reasons)) if all_reasons else "-"
                print(f"  {label:<14} {pass_rate:>4.0f}% {avg_time:>6.1f}s {avg_sent:>7} {avg_recv:>7} {avg_files:>6.0f} {avg_lines:>6.0f}  {reason_str}")
        print()

    # Scorecard breakdown (per task/config)
    print("--- Scorecard ---")
    sc_fields = ["correctness", "regression", "scope_control", "minimality", "instruction_following"]
    header = f"  {'label':<18}" + "".join(f" {f:>6}" for f in sc_fields)
    print(header)
    for model in models:
        for config in configs:
            runs = [r for r in all_results if r["model"] == model and r.get("config") == config]
            if not runs:
                continue
            label = f"{config}/{model}" if len(models) > 1 else config
            vals = []
            for field in sc_fields:
                pct = sum(1 for r in runs if r.get("scorecard", {}).get(field)) / len(runs) * 100
                vals.append(f"{pct:>4.0f}%")
            print(f"  {label:<18}" + "".join(f" {v:>6}" for v in vals))
    print()

    # Total summary
    print("--- 总分 ---")
    header = f"  {'config':<14} {'pass':>5} {'time':>7} {'files':>6} {'lines':>6}"
    print(header)
    for model in models:
        for config in configs:
            runs = [r for r in all_results if r["model"] == model and r.get("config") == config]
            if not runs:
                continue
            n = len(runs)
            pass_rate = _pct_final_pass(runs)
            avg_time = sum(r["elapsed_seconds"] for r in runs) / n
            avg_files = _avg_none([r.get("files_changed", 0) for r in runs])
            avg_lines = _avg_none([r.get("lines_total", 0) for r in runs])

            label = f"{config}/{model}" if len(models) > 1 else config
            print(f"  {label:<14} {pass_rate:>4.0f}% {avg_time:>6.1f}s {avg_files:>6.0f} {avg_lines:>6.0f}")

    report_file = RESULTS_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {report_file}")


def _avg_none(values):
    valid = [v for v in values if v is not None]
    return int(sum(valid) / len(valid)) if valid else "-"


def _pct_final_pass(runs):
    return sum(1 for r in runs if r.get("final_pass")) / len(runs) * 100


if __name__ == "__main__":
    load_env()

    parser = argparse.ArgumentParser(description="DeathPlaylist Eval Runner")
    parser.add_argument("--model", help="模型名称 (如 glm-5.1)")
    parser.add_argument("--task", help="任务 ID (如 T001)")
    parser.add_argument("--all", action="store_true", help="运行所有任务")
    parser.add_argument("--compare", action="store_true", help="对比所有模型")
    parser.add_argument("--report", action="store_true", help="查看报告")
    parser.add_argument("--runs", type=int, default=3, help="每个任务运行次数")
    parser.add_argument("--config", default="baseline", help="配置标签 (默认: baseline)")
    args = parser.parse_args()

    CONFIG_TAG = args.config

    if args.report:
        generate_report()
    elif args.compare:
        compare_models(task_id=args.task, num_runs=args.runs)
    elif args.model and args.task:
        run_single(args.task, args.model, args.runs)
    elif args.model and args.all:
        tasks = load_tasks()
        for t in tasks:
            run_single(t["id"], args.model, args.runs)
    else:
        parser.print_help()
