"""demo3-web / crawler —— Playwright 登录会话爬虫（本人合法账号）。

模块划分：
    main.py          CLI 入口与全流程编排
    browser_ctx.py   浏览器/上下文封装：无头切换、storage_state 登录态恢复
    session.py       登录判定 + 首次人工登录引导 + Cookie 持久化
    page_utils.py    页面等待/弹窗/人机验证(人工)/延时/按钮扫描/权限红线检查
    download_mgr.py  下载事件监听与捕获、自定义保存路径
    config*.json     站点配置（URL、选择器、延时、红线文案）

合规：仅自动化本人账号有权执行的操作；不做越权破解（详见 README）。
"""
