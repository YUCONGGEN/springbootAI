# i18n 国际化 —— 中英文自动切换

> SpringBootAI 2.3.10
> 返回 [README 模块导航](../README.md#模块文档导航)

---

## 你遇到了什么问题？

产品要出海了，网站需要根据用户语言自动显示中文或英文。你不想在代码里写满 `if lang == "zh": return "你好" else: return "Hello"`。

## ① 是什么

**让应用能说多种语言。** 根据用户浏览器的语言偏好，自动返回对应语言的文案。就像微信根据你手机设置的语言，自动显示中文或英文界面——中英文自动切换。

## ② 怎么用

第一步：创建语言文件

`./i18n/messages.properties`（默认，兜底用）：

```properties
greeting=Hello, {0}!
error.not_found=Resource not found
```

`./i18n/messages_zh_CN.properties`（中文）：

```properties
greeting=你好，{0}！
error.not_found=资源未找到
```

`./i18n/messages_en_US.properties`（英文）：

```properties
greeting=Hello, {0}!
error.not_found=Resource not found
```

第二步：在代码中使用：

```python
from springbootai.i18n import (
    ResourceBundleMessageSource, Locale, LOCALE_CHINA, LOCALE_US,
    AcceptHeaderLocaleResolver, LocaleResolverMiddleware,
)

# 1. 加载语言文件
src = ResourceBundleMessageSource(basenames=["messages"], base_dir="./i18n")

# 2. 按语言取消息（{0} 是占位符）
msg = src.getMessage("greeting", ["小明"], Locale("zh", "CN"))
print(msg)  # 输出: 你好，小明！

msg = src.getMessage("greeting", ["Tom"], Locale("en", "US"))
print(msg)  # 输出: Hello, Tom!

# 3. 安装中间件：自动从浏览器 Accept-Language 头解析语言
app.add_middleware(
    LocaleResolverMiddleware,
    locale_resolver=AcceptHeaderLocaleResolver(
        supported_locales=[Locale("zh", "CN"), Locale("en", "US")],
        default_locale=Locale("en"),  # 找不到匹配时用英文兜底
    ),
)
# 结果：浏览器发送 Accept-Language: zh-CN → 自动用中文
#       浏览器发送 Accept-Language: en-US → 自动用英文
```

## ③ 运行结果

用户浏览器语言是中文时，接口返回"你好，小明！"；英文时返回"Hello, Tom!"。你不需要在代码里写任何 if/else 判断。

## mini-FAQ

**Q：文件命名有格式要求吗？**
必须用 `basename_语言_国家.properties` 格式，如 `messages_zh_CN.properties`。不要写成 `messages_zh-CN` 或 `messages_chinese`。

**Q：占位符是 {0} 还是 {name}？**
用 `{0}``{1}` 数字索引（Java properties 风格），不是 Python 的 `{name}`。

**Q：编码用 UTF-8 吗？**
是的。中文内容直接写进去就行，不用 `\uXXXX` 转义。

**Q：`messages.properties` 是干什么的？**
是兜底文件。请求的语言找不到对应文件时，回退到这个默认文件。至少要有一个。

---

## 改进记录

### MessageFormat 参数插值不严谨 — 低 ⏳ 待处理 (v2.4.0)

**位置**：`springbootai/i18n/message_source.py` 消息参数格式化

**现象**：消息参数格式化中对 Java `MessageFormat` 语法（如 `{0,number,#.##}`）的剥离使用简单正则，遇到嵌套花括号或转义字符时可能解析错误，导致最终消息包含原始 `{0}` 占位符。

**改进方案**：使用 `string.Formatter` 或 `str.format_map()` 替代手写正则；对无法解析的占位符，回退为 `?` 并记录 WARNING 日志。
