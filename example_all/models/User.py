"""
数据模型 — 用于 ORM 映射
"""


class User:
    """用户模型"""

    def __init__(self, id: int = None, username: str = None, email: str = None,
                 phone: str = None, created_at: str = None, updated_at: str = None):
        self.id = id
        self.username = username
        self.email = email
        self.phone = phone
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        return {
            'id': self.id, 'username': self.username, 'email': self.email,
            'phone': self.phone, 'created_at': self.created_at, 'updated_at': self.updated_at,
        }

    def __repr__(self) -> str:
        return f"<User id={self.id}, username={self.username}>"


class Order:
    """订单模型"""

    def __init__(self, id: int = None, user_id: int = None, product_name: str = None,
                 amount: float = None, status: str = "pending", created_at: str = None):
        self.id = id
        self.user_id = user_id
        self.product_name = product_name
        self.amount = amount
        self.status = status
        self.created_at = created_at

    def to_dict(self) -> dict:
        return {
            'id': self.id, 'user_id': self.user_id, 'product_name': self.product_name,
            'amount': self.amount, 'status': self.status, 'created_at': self.created_at,
        }

    def __repr__(self) -> str:
        return f"<Order id={self.id}, product={self.product_name}, status={self.status}>"
