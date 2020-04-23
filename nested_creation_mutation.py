"""
This a self-contained module to test the idea of using nested mutation
in only one use case, namely creating a new object and link another
object to the newly created one. It appears this is the only case
where nested mutation is really required, otherwise we could query
the objects before mutating them.

Graphene required:

> pip install graphene


Run with:

> python create_related_mutation.py

The principle is to rely on GraphQL resolution capabilities to simplify
the nesting and reuse existing (root) mutations (along with their technical
features such as permission checks).

We can see that, in contract to what was possible with the node+edge pattern,
(shared_result_mutation.py) we cannot set the parent of the new sibling in
the same mutation. The obvious reason is that we don't have its data
(its pk in particular). The other reason is because order is not guaranteed
for nested mutations. So cannot create, for example, a data-less mutation
`assignParentToSiblings` that would set the parent of all siblings of the
current *root* child, because the nested sibling may be created before the
nested parent.

However, in most practical cases, we just need to create a new data and
and then link it to an exiting object. Nesting can satisfy these use cases.
"""
import json
from typing import List, Dict
import graphene

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

    create_parent = graphene.Field(ParentType, data=graphene.Argument(ParentInput))
    create_sibling = graphene.Field(ParentType, data=graphene.Argument(lambda: ChildInput))

    @staticmethod
    def resolve_parent(root: Child, __: graphene.ResolveInfo):
        return FakeParentDB.get(root.parent)

    @staticmethod
    def resolve_siblings(root: Child, __: graphene.ResolveInfo):
        return [FakeChildDB[pk] for pk in root.siblings]

    @staticmethod
    def resolve_create_parent(child: Child, __: graphene.ResolveInfo, data: ParentInput):
        parent = UpsertParent.mutate(None, __, data)
        child.parent = parent.pk
        return parent

    @staticmethod
    def resolve_create_sibling(node1: Child, __: graphene.ResolveInfo, data: 'ChildInput'):
        node2 = UpsertChild.mutate(None, __, data)
        node1.siblings.append(node2.pk)
        node2.siblings.append(node1.pk)
        return node2


class ChildInput(graphene.InputObjectType, FakeModelFields):  # notice the difference of fields with ChildType
    parent = graphene.Int()
    siblings = graphene.List(graphene.Int)


#######################################
# GraphQL mutations
#######################################


class UpsertParent(graphene.Mutation, ParentType):
    class Arguments:
        data = ParentInput()

    @staticmethod
    def mutate(_: None, __: graphene.ResolveInfo, data: ParentInput):
        instance = FakeParentDB.get(data.pk)
        if instance is None:
            Counters.PARENT_COUNTER += 1
            data["pk"] = data.pk = Counters.PARENT_COUNTER
        parent = Parent(**data)
        FakeParentDB[data.pk] = parent
        return parent


class UpsertChild(graphene.Mutation, ChildType):
    class Arguments:
        data = ChildInput()

    @staticmethod
    def mutate(_: None, __: graphene.ResolveInfo, data: ChildInput):
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


schema = graphene.Schema(query=Query, mutation=Mutation)


#######################################
# Test
#######################################


GRAPHQL_MUTATION = """
mutation ($parent: ParentInput, $child1: ChildInput, $child2: ChildInput) {
    n1: upsertChild(data: $child1) {
        pk
        name
        siblings { pk name }
        
        parent: createParent(data: $parent) { pk name }
        
        newSibling: createSibling(data: $child2) { pk name }
        
        
        # in contract to what was possible with the node+edge pattern,
        # we cannot set the parent of the new sibling in this mutation
        # because order is not guaranted for nested mutations
    }
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
    )
    print("="*50, "\nMutations\n", json.dumps(result.data, indent=4))
    print("Errors: ", result.errors)
    result = schema.execute(GRAPHQL_QUERY)
    print("="*50, "\nQuery\n", json.dumps(result.data, indent=4))
    print("Errors: ", result.errors)



if __name__ == "__main__":
    main()
