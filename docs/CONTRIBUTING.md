# 反馈与参与改进

## 使用问题

先查看[使用与排障](USAGE.md)和[当前验证范围](RELEASE_CHECKS.md)。仓库发布后，在GitHub的 **Issues → New issue → 使用问题** 填写版本、系统、复现步骤和预期／实际结果。

版本位于页面标题下方。需要更多信息时，可在「同步与设置 → 备份与诊断」生成脱敏报告。不要上传原始日志、数据备份、登录目录、Cookie、密钥或未遮挡的私人截图。

改进建议使用 **改进建议** 模板，描述个人创作中的困难和理想操作即可。当前没有团队／MCN分区。

仓库尚未发布时，可将这些信息整理给项目维护者；本文不预设尚未创建的GitHub仓库地址。

## 提交代码

阅读根目录AGENTS.md和HANDOFF.md。修改前保留个人数据，测试使用临时数据库。不要改变全部有效历史默认参照、数量／转化双线、平台隔离或图文规则。

```bash
python -m pytest -q
python tools/release.py
# 暂存实际文件后
python tools/release.py --tracked
```

说明实际验证和未验证的边界；界面截图使用内置示例或明确标注的合成数据。自动测试通过不等于真实跨天、不同操作系统或付费模型已验证。

Issue表单按[GitHub官方语法](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)编写；发布后仍需检查仓库的Issues功能和模板选择页是否正常。
