# 中文创作建议模型配置

CreatorLab 不配置模型也能生成带证据的本地方案、保存实验和复盘。模型仅补充待验证做法，不负责制造事实或评分。

## 从哪里配置

进入「做下一条 → 准备创作 → 可选模型与中文配置教程」，选择生成方式，填写文字模型名称与API Key。Key可仅在当前会话输入；关闭页面后重新填写，不写入方案、作品库或导出文件。

也可先设置本机环境变量，再关闭启动窗口并重新运行 `start_windows.bat`。`.env.example` 是说明模板，程序不会自动加载 `.env`；不要把密钥提交到仓库。

## DeepSeek

1. 在 [DeepSeek开放平台](https://platform.deepseek.com/) 登录自己的账号，创建API Key，并核对账户额度。
2. 在CreatorLab选择DeepSeek，粘贴Key。默认文字模型为 `deepseek-flash`，也可填账户实际可用的模型名称。
3. 环境变量方式使用 `DEEPSEEK_API_KEY` 与 `DEEPSEEK_MODEL`。
4. 应用固定向 `https://api.deepseek.com/chat/completions` 请求，不要求安装额外SDK。参见[官方首次调用说明](https://api-docs.deepseek.com/)。

PowerShell仅在当前窗口设置的示例（值请在自己电脑填写）：

```powershell
$env:DEEPSEEK_API_KEY='填写你自己的Key'
$env:DEEPSEEK_MODEL='deepseek-flash'
.\start_windows.bat
```

## 豆包／火山方舟

1. 在[火山方舟控制台](https://console.volcengine.com/ark/)开通账户可用的**文字生成**模型，并创建方舟API Key。豆包聊天App账号或聊天链接不能代替API Key。
2. 在CreatorLab选择「豆包（火山方舟）」。填写账户已开通的模型ID，或该文字模型的推理接入点ID。默认示例为 `doubao-seed-2-1-lite-260915`，实际可用名称以控制台为准。
3. 环境变量方式使用 `ARK_API_KEY` 与 `DOUBAO_MODEL`。
4. 应用固定使用北京区域 `https://ark.cn-beijing.volces.com/api/v3/chat/completions`。请使用有权限访问该区域文字模型的Key；不要填视频、图片生成模型ID。参见[官方Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=zh)及[鉴权说明](https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=zh)。

```powershell
$env:ARK_API_KEY='填写你自己的方舟Key'
$env:DOUBAO_MODEL='填写控制台已开通的文字模型ID或接入点ID'
.\start_windows.bat
```

可选将同名Key放在本机 `.streamlit/secrets.toml`，例如 `DEEPSEEK_API_KEY = "你的Key"`；不要共享该文件。环境变量优先于secrets配置，页面临时输入优先于两者。

## 发送前看清范围

点击模型按钮前，页面会展示拟发送的文字摘要：所选作品标题、已采集的数字、外部样本来源和标签、样本限制及已保存的本账号复盘经验。勾选同意后才发送；更换证据范围会重置同意状态。

「创作助手」只发送文字方案摘要，不发送视频、封面、Cookie、浏览器登录配置、数据库文件或API Key正文。

2.6.17起，「做下一条 → 检查视频」先在本机检测候选片段。用户之后主动选择AI、准备并预览最多4张关键帧、核对作品指标和文字，勾选同意后才发送这些素材。可选DeepSeek、豆包、Ollama或OpenAI的视觉模型；不隐式发送图片，不上传整段视频。豆包此入口默认使用支持视觉的 `doubao-seed-2-1-pro-260915`，DeepSeek默认 `deepseek-flash`；模型需在用户账户中可用。具体步骤见[视频体检指南](VIDEO_INSPECTION.md)。

模型输出必须引用存在的证据ID，五类建议完整。无效结构、未知引用和保证爆款／全站排名等输出会被拒绝，不替换本地方案。即使通过格式检查，模型建议仍可能错误，需由实验验证。

## 常见问题

- 401／403：检查Key、区域或模型权限，不要将Key发到聊天里排查。
- 404：核对模型名／接入点ID，不能用聊天App链接。
- 429：等待额度或限流恢复，不连续重试。
- 网络或超时：本地方案、保存和复盘仍可使用；不会静默切换其他云服务。
- 输出未采用：通常是证据引用或JSON结构无效；没有把模型文字当成观测事实。

接口与默认模型名称于2026-11-05按官方文档核对。模型权限和名称可能调整，以控制台为准；本轮自动测试模拟服务响应，不代表已用你的账户完成付费调用。
