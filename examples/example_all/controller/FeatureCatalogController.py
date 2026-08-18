"""实时框架功能目录的 HTTP 查询接口。

启动 example_all 后可访问 GET /api/catalog/search?q=GetMapping。该接口本身展示
RestController、RequestMapping、GetMapping 和框架 Result 的处理方式。
"""

from springbootai.annotations import GetMapping, RequestMapping, RestController
from springbootai.web.result import Result

from example_all.feature_catalog import search, summary


@RestController
@RequestMapping("/api/catalog")
class FeatureCatalogController:
    """向学习应用提供注解和功能使用位置查询。"""

    @GetMapping("/summary")
    def catalog_summary(self):
        return Result.success(data=summary())

    @GetMapping("/search")
    def catalog_search(self, q: str = "", limit: int = 20):
        return Result.success(data={"query": q, "items": search(q, limit)})
