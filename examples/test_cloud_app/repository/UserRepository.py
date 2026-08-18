from springbootai.annotations.core import Repository


@Repository
class UserRepository:
    """用户仓储类 - 测试 @Repository"""
    
    def __init__(self):
        self.users = {}
    
    def save(self, user_id: int, user: dict) -> None:
        """保存用户"""
        self.users[user_id] = user
    
    def find(self, user_id: int) -> dict:
        """查找用户"""
        return self.users.get(user_id, {"error": "User not found"})
    
    def find_all(self) -> list:
        """查找所有用户"""
        return list(self.users.values())
    
    def delete(self, user_id: int) -> bool:
        """删除用户"""
        if user_id in self.users:
            del self.users[user_id]
            return True
        return False
