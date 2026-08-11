# auto-imagegen

零硬编码的 Codex 图片生成 skill。脚本代码在所有人电脑上完全一致，每台机器运行一次 `--init` 自动探测本机可用的 OpenAI 兼容供应商（Codex++ / config.toml / auth.json / 环境变量），生成专属的 `providers.json`，之后即可生成图片。

## 特性

- **零硬编码**：不绑定任何厂商（agnes / cliproxy / OpenAI / DeepSeek... 都可），所有 URL / key / 模型 / 端点都在 `providers.json` 里
- **每机一份配置**：`--init` 自动发现本机供应商（Codex++ relayProfiles、`~/.codex/config.toml [model_providers.*]`、`~/.codex/auth.json`、环境变量），跳过 Codex++ 聚合代理端口 `127.0.0.1:57321`
- **按模型探测 API 形态**：`--init` 联网探测每个图片模型走 `/v1/images/generations` 还是 chat completions，端点写入 providers.json，可手动修改
- **并行探测不卡死**：每个请求 10s 超时，并行执行；支持 `--init --no-ping` 离线模式
- **自动打开图片**：生成成功后自动用系统查看器打开（`--no-open` 关闭）
- **view_image 保护**：自动禁用 `view_image`，防止大图 base64 撑爆上下文

## 安装

```powershell
# 方式一：git clone 到 Codex skills 目录
git clone https://github.com/zhoul1/auto-imagegen "$env:USERPROFILE\.agents\skillsuto-imagegen"

# 方式二：手动复制 auto-imagegen 文件夹到 ~/.agents/skills/
```

> 安装后 Codex 会自动识别 `~/.agents/skills/auto-imagegen/SKILL.md`，对话中可用 `@auto-imagegen` 调用。

## 使用

```powershell
# 1. 每台机器首次使用：初始化（自动发现供应商并写入 providers.json）
python "$env:USERPROFILE\.agents\skillsuto-imagegen\scripts\image_gen.py" --init

# 2. 查看本机可用供应商/模型
python "$env:USERPROFILE\.agents\skillsuto-imagegen\scripts\image_gen.py" --inspect

# 3. 生成图片（默认使用 providers.json 里的 default_provider / default_model）
python "$env:USERPROFILE\.agents\skillsuto-imagegen\scripts\image_gen.py" "一只在公园里的金毛犬"

# 指定供应商/模型/输出
python "$env:USERPROFILE\.agents\skillsuto-imagegen\scripts\image_gen.py" "日落" --provider agnes-ai --model agnes-image-2.1-flash --out "sunset.png"
```

图片默认保存到当前工作目录的 `generated_images/`（不可写时回退 `~/.codex/generated_images/`）。

### 常用参数

| 参数 | 说明 |
|------|------|
| `--init` | 发现本机供应商并生成 providers.json |
| `--no-ping` | 配合 `--init`：跳过网络探测（离线） |
| `--inspect` / `-I` | 列出 providers.json 中的供应商与模型 |
| `--provider <name>` | 指定供应商（名称/来源/URL 子串） |
| `--model <id>` | 指定模型 |
| `--image-api images|chat` | 临时覆盖 API 形态 |
| `--size <size>` | 图片尺寸（默认 1024x1024） |
| `--timeout <secs>` | 请求超时（默认 120） |
| `--out <path>` / `--img-dir <dir>` | 输出路径/目录 |
| `--no-open` | 生成后不自动打开图片 |
| `--providers <path>` | 指定 providers.json 路径 |

## providers.json

默认路径：`~/.codex/auto-imagegen/providers.json`（`--providers` 可覆盖）。

```json
{
  "default_provider": "agnes-ai",
  "default_model": "agnes-image-2.1-flash",
  "providers": [
    {
      "name": "agnes-ai",
      "source": "codex++",
      "base_url": "https://apihub.agnes-ai.com",
      "api_key": "sk-...",
      "status": "ok",
      "image_models": [
        { "id": "agnes-image-2.1-flash", "image_api": "images",
          "image_endpoint": "https://apihub.agnes-ai.com/v1/images/generations",
          "probe_note": "images endpoint exists, missing prompt (HTTP 500)" }
      ]
    }
  ]
}
```

- `status`：`ok` / `auth_failed` / `no_models_endpoint` / `unreachable` / `no_image_models` / `no_key` / `unknown`（`--no-ping`）
- 每个模型的 `image_api` / `image_endpoint` 由 `--init` 探测生成，可手动编辑
- 重跑 `--init` 会保留你手动设置的 `default_provider` / `default_model`（若仍可用）
- 注意：文件包含明文 API key，请勿提交或分享

## 发现来源（--init）

1. Codex++ `~/.codex-session-delete/settings.json` → `relayProfiles`（供应商名、`upstreamBaseUrl`、`configContents` 里的 token）
2. Codex `~/.codex/config.toml` → `[model_providers.*]`（`base_url` + `experimental_bearer_token`）
3. `~/.codex/auth.json` → `OPENAI_API_KEY` 或 ChatGPT `access_token`（候选 `openai`，base `https://api.openai.com`）
4. 环境变量：`OPENAI_API_KEY`+`OPENAI_BASE_URL`、`AGENT_API_KEY`+`AGENT_BASE_URL`、`CLIPROXY_API_KEY`+`CLIPROXY_BASE_URL`

指向 Codex++ 聚合代理端口 `127.0.0.1:57321` 的候选会被自动跳过。

## ⚠️ 重要：不要调用 view_image

对生成的图片调用 `view_image` 会把完整 base64 图片（2-5MB）嵌入对话上下文，直接撑爆上下文窗口导致对话崩溃。脚本输出 `IMG_PATH=<路径>` 后，**只回复纯文本路径**，不要用 `![alt](路径)`，不要调用 view_image。图片已自动在系统查看器中打开。

## 输出格式

脚本 stdout 输出结构化标记，便于 Codex 解析：

| 行 | 含义 |
|----|------|
| `STATUS=SUCCESS` + `IMG_PATH=<path>` + `MODEL=<name>` | 生成成功 |
| `STATUS=FAILURE` + `REASON=<text>` | 生成失败原因 |
| `HINT=<text>`（stderr） | 某些失败下的修复建议（如 `--image-api chat`） |
| `ERROR_DETAIL=<text>`（stderr） | 完整 API 错误 |

## 许可证

MIT
