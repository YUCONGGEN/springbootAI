"""
用户数据仓库 — 测试 @Repository 注解
"""
from spring.annotations.core import Repository, Slf4j, PostConstruct


@Slf4j
@Repository
class UserRepository:
    """@Repository — 数据访问层（模拟数据库操作）"""

    @PostConstruct
    def init(self):
        self.logger.info("UserRepository 初始化完成")
        self._data = {}

    def save(self, user_id: int, user_data: dict) -> dict:
        self._data[user_id] = user_data
        return user_data

    def find(self, user_id: int) -> dict:
        return self._data.get(user_id)

    def find_all(self) -> list:
        return list(self._data.values())

    def delete(self, user_id: int) -> bool:
        if user_id in self._data:
            del self._data[user_id]
            return True
        return False

    def count(self) -> int:
        return len(self._data)
