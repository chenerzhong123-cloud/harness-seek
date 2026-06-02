#!/usr/bin/env python3
"""测试 API 连通性"""
import urllib.request
import json
import os
from pathlib import Path

def load_env(env_path):
    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v and v != "sk-xxx" and v != "xxx":
                    env[k] = v
    return env

def test_glm(env):
    url = env.get("OPENAI_BASE_URL", "") + "/chat/completions"
    key = env.get("OPENAI_API_KEY", "")
    if not url or not key:
        print("GLM: 跳过（未配置）")
        return False

    payload = json.dumps({
        "model": "glm-5.1",
        "messages": [{"role": "user", "content": "say hi"}],
        "max_tokens": 20
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            data = json.loads(raw)
            print(f"GLM-5.1 原始响应: {raw[:500]}")
            content = data["choices"][0]["message"].get("content", "")
            reasoning = data["choices"][0]["message"].get("reasoning_content", "")
            print(f"GLM-5.1: OK")
            if reasoning:
                print(f"  reasoning: {reasoning[:100]}")
            if content:
                print(f"  content: {content.strip()}")
            return True
    except Exception as e:
        print(f"GLM-5.1: 失败 — {e}")
        return False

def test_deepseek(env):
    url = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com") + "/chat/completions"
    key = env.get("DEEPSEEK_API_KEY", "")
    if not key or key == "sk-xxx":
        print("DeepSeek: 跳过（未配置）")
        return False
    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "say hi"}],
        "max_tokens": 20
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            print(f"DeepSeek: OK — {content.strip()}")
            return True
    except Exception as e:
        print(f"DeepSeek: 失败 — {e}")
        return False

def test_anthropic(env):
    key = env.get("ANTHROPIC_API_KEY", "")
    if not key or key == "sk-xxx":
        print("Anthropic: 跳过（未配置）")
        return False
    print("Anthropic: 跳过（未配置）")
    return False

def test_gemini(env):
    key = env.get("GOOGLE_API_KEY", "")
    if not key or key == "xxx":
        print("Gemini: 跳过（未配置）")
        return False
    print("Gemini: 跳过（未配置）")
    return False

if __name__ == "__main__":
    env_path = Path(__file__).parent / ".env"
    env = load_env(env_path)
    print("=== API 连通性测试 ===\n")
    test_glm(env)
    test_deepseek(env)
    test_anthropic(env)
    test_gemini(env)
