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
from typing import List, Dict, Tuple, Type, Union
import graphene
from graphene import ObjectType, Int


Integers = Union[Int, int]  # fix type checks warnings


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
    siblings : List[Integers] = []

    def __init__(self, pk: int, name: str, parent: int=None,
                 siblings: List[Integers] = None, **kwargs):
        super().__init__(pk, name, **kwargs)
        self.parent = parent
        self.siblings = siblings if siblings is not None else []


FakeParentDB: Dict[Integers, Parent] = {}
FakeChildDB: Dict[Integers, Child] = {}


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
    def resolve_parent(root: Child, _: graphene.ResolveInfo):
        return FakeParentDB.get(root.parent)

    @staticmethod
    def resolve_siblings(root: Child, _: graphene.ResolveInfo):
        return [FakeChildDB[pk] for pk in root.siblings]


class ChildInput(graphene.InputObjectType, FakeModelFields):  # notice the difference of fields with ChildType
    parent = graphene.Int()
    siblings = graphene.List(graphene.Int)


#######################################
# Sharing result features
#######################################


class ShareResultMiddleware:

    shared_results = {}

    def resolve(self, next_resolver, root, info, **kwargs):
        return next_resolver(root, info, shared_results=self.shared_results, **kwargs)


class SharedResultMutation(graphene.Mutation):

    @classmethod
    def mutate(cls, root: None, info: graphene.ResolveInfo,
               shared_results: Dict[str, ObjectType], **kwargs):
        result = cls.mutate_and_share_result(root, info, **kwargs)
        assert root is None, "SharedResultMutation must be a root mutation." \
                             " Current mutation has a %s parent" % type(root)
        node = info.path[0]
        shared_results[node] = result
        return result

    @staticmethod
    def mutate_and_share_result(root: None, info: graphene.ResolveInfo, **kwargs):
        raise NotImplementedError("This method must be implemented in subclasses.")


class EdgeMutationBase(SharedResultMutation):

    ok = graphene.Boolean()

    @classmethod
    def set_link(cls, node1: ObjectType, node2: ObjectType):
        raise NotImplementedError("This method must be implemented in subclasses.")

    @staticmethod
    def mutate_and_share_result(root: None, info: graphene.ResolveInfo, **__):
        raise AttributeError("This method is not used in edge mutations.")


def assert_input_node_types(shared_results: dict, node1: str, node2: str,
                            node1_type: Type[ObjectType],
                            node2_type: Type[ObjectType]) -> Tuple[ObjectType, ObjectType]:
    node1_ = shared_results.get(node1)
    node2_ = shared_results.get(node2)
    assert node1_ is not None, "Node 1 not found in mutation results."
    assert node2_ is not None, "Node 2 not found in mutation results."
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
               shared_results: dict, parent: str="", child: str="", **__):
        parent_, child_ = assert_input_node_types(
            shared_results,
            node1=parent,
            node2=child,
            node1_type=cls.parent_type,
            node2_type=cls.child_type
        )
        cls.set_link(parent_, child_)
        cls.set_link(parent_, child_)
        return cls(ok=True)

    @classmethod
    def set_link(cls, node1: ObjectType, node2: ObjectType):
        raise NotImplementedError("This method must be implemented in subclasses.")


class SiblingEdgeMutation(EdgeMutationBase):

    node1_type: Type[ObjectType] = None
    node2_type: Type[ObjectType] = None

    class Arguments:
        node1 = graphene.String(required=True)
        node2 = graphene.String(required=True)

    @classmethod
    def mutate(cls, root: None, info: graphene.ResolveInfo,
               shared_results: dict, node1: str="", node2: str="", **__):
        node1_, node2_ = assert_input_node_types(
            shared_results,
            node1=node1,
            node2=node2,
            node1_type=cls.node1_type,
            node2_type=cls.node2_type
        )
        cls.set_link(node1_, node2_)
        return cls(ok=True)

    @classmethod
    def set_link(cls, node1: ObjectType, node2: ObjectType):
        raise NotImplementedError("This method must be implemented in subclasses.")


#######################################
# GraphQL mutations
#######################################


class UpsertParent(SharedResultMutation, ParentType):
    class Arguments:
        data = ParentInput()

    @staticmethod
    def mutate_and_share_result(root: None, info: graphene.ResolveInfo,
                                data: ParentInput = None, **__) -> 'UpsertParent':
        instance = FakeParentDB.get(data.pk)
        if instance is None:
            Counters.PARENT_COUNTER += 1
            data["pk"] = data.pk = Counters.PARENT_COUNTER
        FakeParentDB[data.pk] = Parent(**data.__dict__)
        return UpsertParent(**data.__dict__)


class UpsertChild(SharedResultMutation, ChildType):
    class Arguments:
        data = ChildInput()

    @staticmethod
    def mutate_and_share_result(root: None, info: graphene.ResolveInfo,
                                data: ChildInput = None, **__) -> 'UpsertChild':
        instance = FakeChildDB.get(data.pk)
        if instance is None:
            Counters.CHILD_COUNTER += 1
            data["pk"] = data.pk = Counters.CHILD_COUNTER
        FakeChildDB[data.pk] = Child(**data.__dict__)
        return UpsertChild(**data.__dict__)


class SetParent(ParentChildEdgeMutation):
    """Set a FK like relation between between Parent and Child"""

    parent_type = ParentType
    child_type = ChildType

    @classmethod
    def set_link(cls, parent: ParentType, child: ChildType):
        FakeChildDB[child.pk].parent = parent.pk


class AddSibling(SiblingEdgeMutation):
    """Set a m2m like relation between between Parent and Child"""

    node1_type = ChildType
    node2_type = ChildType

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
