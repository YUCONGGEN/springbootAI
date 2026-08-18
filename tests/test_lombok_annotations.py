"""Behavioral coverage for Lombok-style model annotations."""

import pytest

from springbootai import Data, Get, Set, ToString
from springbootai.annotations.core import get_spring_annotations
from springbootai.orm import Entity, Id, Required


def test_data_generates_entity_accessors_constructor_string_and_equality():
    @Data
    @Entity("lombok_users")
    class User:
        id: int = Id()
        username: str = Required(default="guest")

    user = User(id=1)

    assert user.get_username() == "guest"
    assert user.set_username("alice") is user
    assert str(user) == "User(id=1, username='alice')"
    assert repr(user) == str(user)
    assert user == User(id=1, username="alice")
    assert any(type(annotation) is Data for annotation in get_spring_annotations(User))


def test_individual_annotations_allow_selected_fields_and_keep_explicit_methods():
    @Get(["code"])
    @Set(["code"])
    @ToString
    class Item:
        code: str
        hidden: str

        def get_hidden(self):
            return "custom"

    item = Item()
    item.code = "A"
    item.hidden = "secret"

    assert item.get_code() == "A"
    assert not hasattr(item, "set_hidden")
    assert item.get_hidden() == "custom"
    assert item.set_code("B") is item
    assert str(item) == "Item(code='B', hidden='secret')"


def test_to_string_does_not_replace_explicit_methods_and_can_exclude_fields():
    @ToString(exclude=["password_hash"])
    class Account:
        username: str
        password_hash: str

        def __str__(self):
            return "custom string"

    account = Account()
    account.username = "alice"
    account.password_hash = "not displayed"

    assert str(account) == "custom string"
    assert repr(account) == "Account(username='alice')"


def test_data_supports_entity_as_outer_decorator_and_rejects_unknown_values():
    @Entity("lombok_projects")
    @Data
    class Project:
        id: int = Id()
        name: str = Required()

    project = Project(id=10, name="framework")

    assert project.get_id() == 10
    assert repr(project) == "Project(id=10, name='framework')"
    with pytest.raises(TypeError, match="Unexpected"):
        Project(unknown=True)


def test_public_exports_are_available_from_both_annotation_namespaces():
    from springbootai import Data as RootData, Get as RootGet, Set as RootSet, ToString as RootToString
    from springbootai.annotations import Data as AnnotationData
    from springbootai.annotations import Get as AnnotationGet
    from springbootai.annotations import Set as AnnotationSet
    from springbootai.annotations import ToString as AnnotationToString

    assert (RootData, RootGet, RootSet, RootToString) == (
        AnnotationData,
        AnnotationGet,
        AnnotationSet,
        AnnotationToString,
    )
