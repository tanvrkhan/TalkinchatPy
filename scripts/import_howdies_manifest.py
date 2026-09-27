#!/usr/bin/env python3
"""Generate the pinned command inventory from a clean Howdies commands.py."""

import argparse
import ast
import json
from pathlib import Path


def literal(node, variables=None):
    variables = variables or {}
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [literal(item, variables) for item in node.elts]
    if isinstance(node, ast.Name) and node.id in variables:
        return variables[node.id]
    if isinstance(node, ast.JoinedStr):
        pieces = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                pieces.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                pieces.append(str(literal(value.value, variables)))
        return "".join(pieces)
    raise ValueError(f"unsupported manifest expression: {ast.dump(node)}")


def aliases(node):
    if isinstance(node, (ast.List, ast.Tuple)):
        return [str(literal(item)) for item in node.elts]
    if isinstance(node, ast.ListComp) and len(node.generators) == 1:
        generator = node.generators[0]
        if not isinstance(generator.target, ast.Name):
            raise ValueError("unsupported alias comprehension target")
        call = generator.iter
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "range"):
            raise ValueError("only range alias comprehensions are supported")
        bounds = [int(literal(arg)) for arg in call.args]
        values = range(*bounds)
        return [str(literal(node.elt, {generator.target.id: value})) for value in values]
    raise ValueError("unsupported aliases expression")


def inventory(source):
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    commands = []
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "command"):
                continue
            values = {item.arg: item.value for item in decorator.keywords}
            name = str(literal(decorator.args[0]))
            command_aliases = aliases(values["aliases"]) if "aliases" in values else []
            commands.append({
                "name": name,
                "aliases": command_aliases,
                "category": str(literal(values["category"])) if "category" in values else "General",
                "permission": str(literal(values["level"])) if "level" in values else "user",
                "capabilities": [],
                "fallback": "Text response; capability-specific actions report unsupported.",
                "status": "planned",
            })
    return commands


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = {
        "source_repository": "tanvrkhan/howdiesbot",
        "source_commit": "f2567a1",
        "primary_prefix": ",",
        "accepted_prefixes": [",", "!"],
        "commands": inventory(args.source),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
