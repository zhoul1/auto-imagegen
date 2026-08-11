# 🎨 auto-imagegen

> 专为 **Codex / Codex++** 打造的零配置绘图 skill —— 不用抄 Key、不用改代码、复制即用。

---

## 这是什么？

auto-imagegen 是 **Codex 内置图片生成能力（OpenAI imagegen）的拓展**：它让你摆脱对 OpenAI 绘图模型的限制，**任何 OpenAI 兼容的绘图模型都可以用**——agnès、Stable Diffusion、Flux、以及各种中转聚合商提供的图片模型，全部开箱即用。画图时具体用哪个模型，由你本机的 `providers.json` 决定。

**前提：安装 Codex++。** 供应商的 Key 和配置主要来自 Codex++ 的中转设置，`--init` 会自动读取，不需要手动抄写；如果你本机还有其它 Key 来源（OpenAI 登录、环境变量等），`--init` 也会一并自动发现。

---

## 为什么你需要它？（痛点）

| 痛点 | 常见方案的死法 | auto-imagegen 的解法 |
|------|----------------|----------------------|
| **各家图片 API 端点不统一** | 每个模型写死一套代码，换个厂商就废 | `--init` 联网探测每个模型走 `/v1/images/generations` 还是 chat，端点写进 `providers.json`，随时可改 |
| **Key 藏在 Codex++ / config.toml 里** | 让你手动翻配置、复制粘贴 token | `--init` 自动读取 Codex++ relay、`config.toml`、`auth.json`、环境变量，**零手抄** |
| **大图 base64 撑爆上下文** | 画一张图对话就卡死、上下文直接满 | 生成后只输出路径，自动禁用 `view_image`，图永远不会塞回上下文 |
| **skill 不可移植** | 代码里写死你自己机器的 URL/Key，换台电脑就废 | 代码人人完全一致，每台机器只跑一次 `--init` 生成专属配置 |
| **探测供应商卡死** | 串行请求、没有超时，一跑就挂 | 并行探测 + 每个请求 10s 超时；离线还能 `--init --no-ping` |

**核心设计**：脚本零硬编码，所有厂商 URL / Key / 模型 / 端点都存于 `~/.codex/auto-imagegen/providers.json`。给任何人，跑一次 `--init`，他的环境自动适配。

---

## 🚀 30 秒上手

**第一步：安装**

直接克隆项目，或下载 ZIP 压缩包解压后把 `auto-imagegen` 文件夹放到 `~/.agents/skills/` 下：

```powershell
git clone https://github.com/zhoul1/auto-imagegen "$env:USERPROFILE\.agents\skills\auto-imagegen"
```

安装后 Codex 会自动识别这个 skill，之后在对话里 `@auto-imagegen` 直接说「画个…」就能用。

**第二步：初始化（每台机器只需一次）**

在终端里运行初始化命令，脚本会自动扫描你机器上的 Codex++ 中转配置、`~/.codex/config.toml`、`~/.codex/auth.json` 和环境变量，联网探测可用的图片模型，把结果写进 `providers.json`，全程不用手动抄 Key：

```powershell
python "$env:USERPROFILE\.agents\skills\auto-imagegen\scripts\image_gen.py" --init
```

**第三步：画图**

初始化完成后就可以直接画图了：

```powershell
python "$env:USERPROFILE\.agents\skills\auto-imagegen\scripts\image_gen.py" "一只柴犬在富士山下看日落"
```

图片生成后会自动在系统查看器中打开。也可以不敲命令，直接在 Codex 对话里说「画一只柴犬在富士山下看日落」。

**想指定供应商或模型？**

先看看本机有哪些可用的供应商和模型：

```powershell
python "$env:USERPROFILE\.agents\skills\auto-imagegen\scripts\image_gen.py" --inspect
```

然后生成时带上参数，比如指定 agnes 的 `agnes-image-2.1-flash` 模型，并把图片保存为 `sunset.png`：

```powershell
python "$env:USERPROFILE\.agents\skills\auto-imagegen\scripts\image_gen.py" "日落" --provider agnes-ai --model agnes-image-2.1-flash --out "sunset.png"
```

---

## 🔄 使用流程

**安装后必须先初始化。** 第一次使用前一定要跑一次 `--init`——它负责扫描本机可用的图片供应商、探测可用模型并生成 `providers.json`。不初始化直接画图会报错，因为脚本还没有任何供应商配置可用。

初始化完成后就能正常画图了，默认使用 `providers.json` 里选好的默认供应商和模型。

**修改了绘图提供商之后，再跑一次 `--init` 就行。** 比如你在 Codex++ 里新增、删除或更换了中转供应商（agnes、cliproxy 等），或者改了 `config.toml`、环境变量里的配置，重新执行 `--init` 会自动重新发现并刷新 `providers.json`；你手动设置过的默认供应商和模型会被保留，不会丢失。

---

## ✨ 特性

- **零硬编码**：不绑定任何厂商（OpenAI / agnes / cliproxy / DeepSeek…），URL、Key、模型、端点全部来自 `providers.json`
- **一键初始化**：`--init` 并行发现 Codex++ relayProfiles、`~/.codex/config.toml [model_providers.*]`、`~/.codex/auth.json`、环境变量，并跳过 Codex++ 聚合代理端口 `127.0.0.1:57321`
- **模型级端点探测**：`--init` 逐个探测图片模型，自动判断走 images API 还是 chat completions，写入配置可手动调整
- **防上下文爆炸**：自动禁用 `view_image`，只输出文件路径；生成后自动调用系统查看器打开图片
- **绝不卡死**：所有探测并行 + 10s 超时；`--init --no-ping` 支持完全离线初始化
- **开箱即用**：默认输出到当前工作目录 `generated_images/`，自动选择可达且有图片模型的供应商

---

## 📖 命令速览

| 命令 | 说明 |
|------|------|
| `image_gen.py --init` | 发现本机供应商并生成 `providers.json` |
| `image_gen.py --init --no-ping` | 离线初始化（跳过网络探测） |
| `image_gen.py --inspect` | 查看本机供应商与可用图片模型（脱敏） |
| `image_gen.py "<prompt>"` | 用默认供应商/模型生成图片 |
| `image_gen.py "<prompt>" --provider agnes-ai --model agnes-image-2.1-flash` | 指定供应商/模型 |
| `image_gen.py "<prompt>" --out sunset.png` | 自定义输出路径 |
| `image_gen.py "<prompt>" --size 1792x1024 --timeout 180` | 自定义尺寸/超时 |
| `image_gen.py "<prompt>" --no-open` | 生成后不自动打开 |

---

## 🔧 providers.json（唯一需要个性化/可修改的文件）

默认路径 `~/.codex/auto-imagegen/providers.json`（`--providers <path>` 可覆盖）：

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
          "image_endpoint": "https://apihub.agnes-ai.com/v1/images/generations" }
      ]
    }
  ]
}
```

- `status`：`ok` / `auth_failed` / `unreachable` / `no_image_models` / `no_key` / `unknown`
- 每个模型的 `image_api` / `image_endpoint` 由 `--init` 探测生成，**可手动编辑**后重跑 `--init` 保留你的修改
- ⚠️ 文件含明文 API Key，请勿提交或分享（已在 `.gitignore` 思路之外，默认路径也在 home 目录）

---

## ⚙️ 工作原理

1. **发现**：`--init` 扫描本机所有可能的 Key 来源（Codex++ relay、config.toml、auth.json、环境变量）
2. **探测**：并行请求各供应商 `/v1/models` 过滤图片模型（gpt-image / dall / flux / stable / image…），再对每个模型做最小请求判断 API 形态
3. **落盘**：把可达供应商与模型端点写入 `providers.json`，自动选第一个「可达 + 有图片模型」的作为默认
4. **生成**：标准 OpenAI `images/generations`（`response_format: b64_json`，兼容 url/b64 响应），输出结构化结果

---

## 🤝 兼容供应商

- **OpenAI 官方**：`~/.codex/auth.json` 登录 或 `OPENAI_API_KEY` + `OPENAI_BASE_URL`
- **Codex++ 中转**：`~/.codex-session-delete/settings.json` 中任意 `relayProfiles`（agnes、cliproxy、DeepSeek…）
- **Codex config.toml**：任意 `[model_providers.*]`（`base_url` + `experimental_bearer_token`）
- **环境变量**：`AGENT_API_KEY`、`CLIPROXY_API_KEY` 等及对应 `BASE_URL`

---

## ⚠️ 重要：不要对生成图调用 view_image

对生成的图片调用 `view_image` 会把 2-5MB 的 base64 塞进对话上下文，**直接撑爆上下文窗口**。看到 `IMG_PATH=<路径>` 时只回复纯文本路径，图片已自动在系统查看器打开。

## 📤 输出格式

| 行 | 含义 |
|----|------|
| `STATUS=SUCCESS` + `IMG_PATH=<path>` + `MODEL=<name>` | 生成成功 |
| `STATUS=FAILURE` + `REASON=<text>` | 失败原因 |
| `HINT=<text>`（stderr） | 修复建议（如 `--image-api chat`） |
| `ERROR_DETAIL=<text>`（stderr） | 完整 API 错误详情 |

---

## 📄 许可证

MIT
