# SpringBootAI Sphinx 配置文件
# 对齐 Java Javadoc，使用 Sphinx 自动生成 API 参考文档
#
# 构建命令：
#   pip install sphinx sphinx-rtd-theme
#   sphinx-build -b html docs/ docs/_build/html
#
# 或使用 SpringBootAI CLI：
#   springbootai docs

import os
import sys

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.abspath('..'))

# -- 项目信息 ---------------------------------------------------------------
project = 'SpringBootAI'
copyright = '2026, YuConggen'
author = 'YuConggen'

# 从 springbootai 包读取版本号
try:
    from springbootai import __version__ as version
except ImportError:
    version = '2.3.10'

release = version

# -- 通用配置 ---------------------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',       # 自动从 docstring 生成 API 文档
    'sphinx.ext.viewcode',      # 添加 "[source]" 链接
    'sphinx.ext.napoleon',      # 支持 Google/NumPy 风格 docstring
    'sphinx.ext.intersphinx',   # 跨项目链接
    'sphinx.ext.todo',          # 支持 .. todo:: 指令
    'sphinx.ext.coverage',      # 覆盖率检查
]

# 模板路径
templates_path = ['_templates']

# 排除的文件
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# 语言
language = 'zh_CN'

# -- HTML 输出配置 ----------------------------------------------------------
html_theme = 'sphinx_rtd_theme'  # ReadTheDocs 主题
# 当前未提供自定义静态资源；避免 Sphinx 对不存在的 _static 目录告警。
html_static_path = []

# 主题选项
html_theme_options = {
    'navigation_depth': 4,
    'collapse_navigation': False,
    'sticky_navigation': True,
}

# -- autodoc 配置 -----------------------------------------------------------
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__',
}

# -- Napoleon 配置（Google 风格 docstring）---------------------------------
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = True

# -- intersphinx 配置 -------------------------------------------------------
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'fastapi': ('https://fastapi.tiangolo.com', None),
}
