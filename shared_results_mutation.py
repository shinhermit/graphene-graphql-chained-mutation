"""
This a self-contained module to test the idea of chaining GraphQL mutations
based on a Graph node+edge creation pattern, inspired by what is done with
Graphviz Dot for example.

Graphene required:

> pip install graphene


Run with:

> python shared_result_mutation.py

The principle is to use a Graphene middleware (ShareResultMiddleware)
to inject a result holder in the resolvers and then use these results
to allow referencing a mutation result in another mutation result of
the same query. See the test section below for an example of the type
of queries we want to resolve.
"""
import json
from typing import List, Dict, Tuple, Type
import graphene
from graphene import ObjectType

# Fake models

class FakeModel:
    pk : int = None
    name : str = None

    def __init__(self, pk: int, name: str, **kwargs):
        self.pk = pk
        self.name = name
        for key, val in kwargs.items():
            setattr(self, key, val)

class Parent(FakeModel):
    pass


class Child(FakeModel):
    parent : int = None
    siblings : List[int] = []


FakeParentDB: Dict[int, Parent] = {}
FakeChildDB: Dict[int, Child] = {}

class Counters:
    PARENT_COUNTER = 0
    CHILD_COUNTER = 0


#######################################
# GraphQL types
#######################################


class FakeModelFields:
    pk = graphene.Int()
    name = graphene.String(required=True)


class ParentType(graphene.ObjectType, FakeModelFields):
    pass


class ParentInput(graphene.InputObjectType, FakeModelFields):
    pass


class ChildType(graphene.ObjectType, FakeModelFields):
    parent = graphene.Field(ParentType)
    siblings = graphene.List(lambda: ChildType)

    @staticmethod
    def resolve_parent(root: Child, __: graphene.ResolveInfo):
        return FakeParentDB.get(root.parent)

    @staticmethod
    def resolve_siblings(root: Child, __: graphene.ResolveInfo):
        return [FakeChildDB[pk] for pk in root.siblings]


class ChildInput(graphene.InputObjectType, FakeModelFields):  # notice the difference of fields with ChildType
    parent = graphene.Int()
    siblings = graphene.List(graphene.Int)


#######################################
# New Sharing result assets
#######################################


class ShareResultMiddleware:

    shared_results = {}

    def resolve(self, next, root, info, **args):
        return next(root, info, shared_results=self.shared_results, **args)


class SharedResultMutation(graphene.Mutation):

    @classmethod
    def mutate(cls, root: None, info: graphene.ResolveInfo,
               shared_results: Dict[str, ObjectType], *args, **kwargs):
        result = cls.mutate_and_share_result(root, info, *args, **kwargs)
        if root is None:
            node = info.path[0]
            shared_results[node] = result
        return result

    @staticmethod
    def mutate_and_share_result(root: None, info: graphene.ResolveInfo, *_, **__):
        pass  # override me


class EdgeMutationBase(SharedResultMutation):

    ok = graphene.Boolean()

    @classmethod
    def set_link(cls, node1: ObjectType, node2: ObjectType):
        pass  # override me


def assert_input_node_types(shared_results: dict, node1: str, node2: str,
                            node1_type: Type[ObjectType],
                            node2_type: Type[ObjectType]) -> Tuple[ObjectType, ObjectType]:
    node1_ = shared_results.get(node1)
    node2_ = shared_results.get(node2)
    assert node1_ is not None, "Node 1 not found in mutation results."
    assert node2_ is not None, "Node 1 not found in mutation results."
    assert node1_type is not None, "A type must be specified for Node 1."
    assert node2_type is not None, "A type must be specified for Node 2."
    assert isinstance(node1_, node1_type), "%s is not instance of %s" % \
                                           (type(node1_), node1_type.__name__)
    assert isinstance(node2_, node2_type), "%s is not instance of %s" % \
                                           (type(node2_), node2_type.__name__)
    return node1_, node2_


class ParentChildEdgeMutation(EdgeMutationBase):

    parent_type: Type[ObjectType] = None
    child_type: Type[ObjectType] = None

    class Arguments:
        parent = graphene.String(required=True)
        child = graphene.String(required=True)

    @classmethod
    def mutate(cls, root: None, info: graphene.ResolveInfo,
               shared_results: dict, *_, parent: str="", child: str="", **__):
        parent_, child_ = assert_input_node_types(
            shared_results,
            node1=parent,
            node2=child,
            node1_type=cls.parent_type,
            node2_type=cls.child_type
        )
        cls.set_link(parent_, child_)
        return SetParent(ok=True)


class SiblingEdgeMutation(EdgeMutationBase):

    node1_type: Type[ObjectType] = None
    node2_type: Type[ObjectType] = None

    class Arguments:
        node1 = graphene.String(required=True)
        node2 = graphene.String(required=True)

    @classmethod
    def mutate(cls, root: None, info: graphene.ResolveInfo,
               shared_results: dict, *_, node1: str="", node2: str="", **__):
        node1_, node2_ = assert_input_node_types(
            shared_results,
            node1=node1,
            node2=node2,
            node1_type=cls.node1_type,
            node2_type=cls.node2_type
        )
        cls.set_link(node1_, node2_)
        return SetParent(ok=True)


#######################################
# GraphQL mutations
#######################################


class UpsertParent(SharedResultMutation, ParentType):
    class Arguments:
        data = ParentInput()

    @staticmethod
    def mutate_and_share_result(root: None, info: graphene.ResolveInfo, data: ParentInput, *_, **__):
        instance = FakeParentDB.get(data.pk)
        if instance is None:
            Counters.PARENT_COUNTER += 1
            data["pk"] = data.pk = Counters.PARENT_COUNTER
        parent = Parent(**data)
        FakeParentDB[data.pk] = parent
        return parent


class UpsertChild(SharedResultMutation, ChildType):
    class Arguments:
        data = ChildInput()

    @staticmethod
    def mutate_and_share_result(root: None, info: graphene.ResolveInfo, data: ChildInput, *_, **__):
        instance = FakeChildDB.get(data.pk)
        if instance is None:
            Counters.CHILD_COUNTER += 1
            data["pk"] = data.pk = Counters.CHILD_COUNTER
        child = Child(
            pk=data.pk
            ,name=data.name
            ,parent=FakeParentDB.get(data.parent)
            ,siblings=[FakeChildDB[pk] for pk in data.siblings or []]
        )
        FakeChildDB[data.pk] = child
        return child


class SetParent(ParentChildEdgeMutation):
    """Set a FK like relation between between Parent and Child"""

    parent_type = Parent
    child_type = Child

    @classmethod
    def set_link(cls, parent: ParentType, child: ChildType):
        FakeChildDB[child.pk].parent = parent.pk


class AddSibling(SiblingEdgeMutation):
    """Set a m2m like relation between between Parent and Child"""

    node1_type = Child
    node2_type = Child

    @classmethod
    def set_link(cls, node1: ChildType, node2: ChildType):
        FakeChildDB[node1.pk].siblings.append(node2.pk)
        FakeChildDB[node2.pk].siblings.append(node1.pk)


#######################################
# Schema
#######################################


class Query(graphene.ObjectType):
    parent = graphene.Field(ParentType, pk=graphene.Int())
    parents = graphene.List(ParentType)
    child = graphene.Field(ChildType, pk=graphene.Int())
    children = graphene.List(ChildType)

    @staticmethod
    def resolve_parent(_: None, __: graphene.ResolveInfo, pk: int):
        return FakeParentDB[pk]

    @staticmethod
    def resolve_parents(_: None, __: graphene.ResolveInfo):
        return FakeParentDB.values()

    @staticmethod
    def resolve_child(_: None, __: graphene.ResolveInfo, pk: int):
        return FakeChildDB[pk]

    @staticmethod
    def resolve_children(_: None, __: graphene.ResolveInfo):
        return FakeChildDB.values()


class Mutation(graphene.ObjectType):
    upsert_parent = UpsertParent.Field()
    upsert_child = UpsertChild.Field()
    set_parent = SetParent.Field()
    add_sibling = AddSibling.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)


#######################################
# Test
#######################################


GRAPHQL_MUTATION = """
mutation ($parent: ParentInput, $child1: ChildInput, $child2: ChildInput) {
    n1: upsertParent(data: $parent) {
        pk
        name
    }
    
    n2: upsertChild(data: $child1) {
        pk
        name
    }
    
    n3: upsertChild(data: $child2) {
        pk
        name
    }
    
    e1: setParent(parent: "n1", child: "n2") { ok }
    
    e2: setParent(parent: "n1", child: "n3") { ok }
    
    e3: addSibling(node1: "n2", node2: "n3") { ok }
}
"""

GRAPHQL_QUERY = """ 
query {
    parents {
        pk
        name
    }
    
    children {
        pk
        name
        parent { pk name }
        siblings { pk name }
    }
}
"""


def main():
    result = schema.execute(
        GRAPHQL_MUTATION
        ,variables = dict(
            parent = dict(
                name = "Emilie"
            )
            ,child1 = dict(
                name = "John"
            )
            ,child2 = dict(
                name = "Julie"
            )
        )
        ,middleware=[ShareResultMiddleware()]
    )
    print("="*50, "\nMutations\n", json.dumps(result.data, indent=4))
    print("Errors: ", result.errors)
    result = schema.execute(GRAPHQL_QUERY)
    print("="*50, "\nQuery\n", json.dumps(result.data, indent=4))
    print("Errors: ", result.errors)



if __name__ == "__main__":
    main()
