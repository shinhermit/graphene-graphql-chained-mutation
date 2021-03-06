# graphene-graphql-chained-mutation
Testing a pattern to better chain GraphQL mutations using a Graphene-Python backend

I created this repo in order to test ideas after [a question on Stackoverflow](https://stackoverflow.com/questions/61340137/graphene-graphql-how-to-chain-mutations) and a [suggestion of a pattern](https://stackoverflow.com/a/61364567).

## Motivation

I have been thinking about this problem of chainin mutations and also the fact that it seems to be a recurring question among developers. I have come to conclude that may we miss something in the way we want to edit our graph, namely edge operations. I think we try to do edges operations with node operations. To illustrate this, a graph creation in a language like dot (Graphviz) may look like:

```graphviz
digraph D {

  /* Nodes */
  A 
  B
  C

  /* Edges */

  A -> B
  A -> C
  A -> D

}
```

Following this pattern, maybe the graphql mutation in the question should look like:

```graphql
mutation {

    # Nodes

    n1: createUser(username: "new user", password: "secret"){
        uid
        username
    }

    n2: updateGroup(gid: "group id"){
        gid
        name
    }

    # Edges

    addUserToGroup(user: "n1", group: "n2"){
        status
    }
}
```

The inputs of the _"edge operation"_ `addUserToGroup` would be the aliases of the previous nodes in the mutation query.

This would also allow to decorate edge operations with permission checks (permissions to create a relation may differ from permissions on each object).

We can definitely resolve a query like this already. What is less sure is if backend frameworks, Graphene-python in particular, provide mechanisms to allow the implementation of `addUserToGroup` (having the previous mutation results in the resolution context). I'm thinking of injecting a `dict` of the previous results in the Graphene context. I'll try and complete the answer with technical details if successful.

Maybe there exist way to achieve something like this already, I will also look for that and complete the answer if found.

## Shared results middleware


In the file [shared_result_mutations.py](https://github.com/shinhermit/graphene-graphql-chained-mutation/blob/master/shared_results_mutation.py), I tested a way of resolving a query like above, using a [Graphene-python middleware](https://docs.graphene-python.org/en/latest/execution/middleware/) and a base mutation class to handle sharing the results.


The middleware is quite simple and adds a dict as `kwarg` parameter to the resolvers:

```python
class ShareResultMiddleware:

    shared_results = {}

    def resolve(self, next, root, info, **args):
        return next(root, info, shared_results=self.shared_results, **args)

```

The base class is also quite simple and manages the insertion of results in the dictionary:

```python
class SharedResultMutation(graphene.Mutation):

    @classmethod
    def mutate(cls, root: None, info: graphene.ResolveInfo, shared_results: dict, *args, **kwargs):
        result = cls.mutate_and_share_result(root, info, *args, **kwargs)
        if root is None:
            node = info.path[0]
            shared_results[node] = result
        return result

    @staticmethod
    def mutate_and_share_result(*_, **__):
        return SharedResultMutation()  # override
```

A node-like mutation that need to comply with the shared result pattern would inherit from `SharedResultMutation` in stead of `Mutation` and override `mutate_and_share_result` instead of `mutate`:

```python
class UpsertParent(SharedResultMutation, ParentType):
    class Arguments:
        data = ParentInput()

    @staticmethod
    def mutate_and_share_result(root: None, info: graphene.ResolveInfo, data: ParentInput, *___, **____):
        return UpsertParent(id=1, name="test")
```

The edge-like mutations need to access the `shared_results` dict, so they override `mutate` directly:

```python
class AddSibling(SharedResultMutation):
    class Arguments:
        node1 = graphene.String(required=True)
        node2 = graphene.String(required=True)

    ok = graphene.Boolean()

    @staticmethod
    def mutate(root: None, info: graphene.ResolveInfo, shared_results: dict, node1: str, node2: str):  # ISSUE: this breaks type awareness
        node1_ : ChildType = shared_results.get(node1)
        node2_ : ChildType = shared_results.get(node2)
        assert node1_ is not None
        assert node2_ is not None
        FakeChildDB[node1_.pk].siblings.append(node2_.pk)
        FakeChildDB[node2_.pk].siblings.append(node1_.pk)
        return AddSibling(ok=True)
```

And that's basically it (the rest is common Graphene boilerplate and test mocks).

The issue with this is that the edge-like mutation arguments do not satisfy the _type awareness_ that GraphQL promotes: in the GraphQL spirit, `node1` and `node2` should be typed `graphene.Field(ChildType)`, instead of `graphene.String()` as in this implementation.

## Nested sibling creation

For comparison, I also implemented a nesting pattern where only creations are resolved (it the only case where we cannot have the data in previous query), [one-file program available on Github](https://github.com/shinhermit/graphene-graphql-chained-mutation/blob/master/nested_creation_mutation.py).

It is classic Graphene, except for the mutation `UpsertChild` were we add field to solve nested creations *and* their resolvers:

```python
class UpsertChild(graphene.Mutation, ChildType):
    class Arguments:
        data = ChildInput()

    create_parent = graphene.Field(ParentType, data=graphene.Argument(ParentInput))
    create_sibling = graphene.Field(ParentType, data=graphene.Argument(lambda: ChildInput))

    @staticmethod
    def mutate(_: None, __: graphene.ResolveInfo, data: ChildInput):
        return Child(
            pk=data.pk
            ,name=data.name
            ,parent=FakeParentDB.get(data.parent)
            ,siblings=[FakeChildDB[pk] for pk in data.siblings or []]
        )  # <-- example

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
```

So the quantity of extra _stuff_ is small compared to to the node+edge pattern. We can now execute a query like:

```graphql
mutation ($parent: ParentInput, $child1: ChildInput, $child2: ChildInput) {
    n1: upsertChild(data: $child1) {
        pk
        name
        siblings { pk name }
        
        parent: createParent(data: $parent) { pk name }
        
        newSibling: createSibling(data: $child2) { pk name }
    }
}
```

However, we can see that, in contrast to what was possible with the node+edge pattern,(shared_result_mutation.py) we cannot set the parent of the new sibling in the same mutation. The obvious reason is that we don't have its data (its pk in particular). The other reason is because order is not guaranteed for nested mutations. So cannot create, for example, a data-less mutation `assignParentToSiblings` that would set the parent of all siblings of the current *root* child, because the nested sibling may be created before the nested parent.

In some practical cases though, we just need to create a new object and
and then link it to an exiting object. Nesting can satisfy these use cases.
