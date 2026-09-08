name: "Bug report"
description: 报告使用中遇到的问题
labels: ["bug"]
body:
  - type: input
    attributes:
      label: 版本/运行方式
      description: 如 v1.0.0，Web / TUI / CLI 哪一种
      placeholder: v1.0.0 + Web
    validations:
      required: true
  - type: textarea
    attributes:
      label: 现象
      description: 看到了什么？期望发生什么？
    validations:
      required: true
  - type: textarea
    attributes:
      label: 关键输出（脱敏）
      description: 贴终端输出或 report.json 片段。注意删掉 Cookie、学号等个人信息
      render: text
  - type: checkboxes
    attributes:
      label: 自查
      options:
        - label: 已确认不是查询限频（`查询请求频率过高`，等几分钟重试）
        - label: 已确认会话有效（重新登录后问题依旧）
        - label: 输出中不含个人隐私信息
