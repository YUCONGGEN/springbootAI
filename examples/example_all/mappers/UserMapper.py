"""
用户 Mapper 接口 — 测试 PyMyBatis ORM 所有注解（MySQL 版）
@Mapper, @Select, @Insert, @Update, @Delete
"""
from springbootai.orm import (
    Mapper, Select, Insert, Update, Delete,
)


@Mapper
class UserMapper:
    """用户数据访问 Mapper — 注解 + XML 混合模式"""

    @Select("SELECT id, username, email, phone, created_at, updated_at FROM users WHERE id = #{id}")
    def find_by_id(self, id: int):
        pass

    @Select("SELECT id, username, email, phone, created_at, updated_at FROM users")
    def find_all(self):
        pass

    @Select("""
        SELECT id, username, email, phone, created_at, updated_at FROM users
        <where>
            <if test="username != null">AND username LIKE CONCAT('%', #{username}, '%')</if>
            <if test="email != null">AND email = #{email}</if>
        </where>
        ORDER BY created_at DESC
    """)
    def find_by_condition(self, username=None, email=None):
        pass

    @Select("SELECT COUNT(*) as total FROM users")
    def count_all(self):
        pass

    @Insert(
        "INSERT INTO users (username, email, phone) VALUES (#{username}, #{email}, #{phone})",
        use_generated_keys=True,
        key_property="id",
    )
    def insert(self, username: str, email: str, phone: str = None):
        pass

    @Update("""
        UPDATE users
        <set>
            <if test="username != null">username = #{username},</if>
            <if test="email != null">email = #{email},</if>
            <if test="phone != null">phone = #{phone},</if>
            updated_at = NOW()
        </set>
        WHERE id = #{id}
    """)
    def update(self, id: int, username: str = None, email: str = None, phone: str = None):
        pass

    @Delete("DELETE FROM users WHERE id = #{id}")
    def delete(self, id: int):
        pass

    @Delete("DELETE FROM users WHERE id IN <foreach collection='ids' item='id' open='(' separator=',' close=')'>#{id}</foreach>")
    def delete_batch(self, ids: list):
        pass
