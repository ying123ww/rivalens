import ast
from collections import defaultdict
from pathlib import Path
import unittest


def _app_routes():
    app_path = Path(__file__).resolve().parents[1] / "backend" / "server" / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    methods = {"get", "post", "put", "delete", "patch"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in methods
                and isinstance(func.value, ast.Name)
                and func.value.id == "app"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                yield func.attr.upper(), decorator.args[0].value, node.name


class ServerRoutesTest(unittest.TestCase):
    def test_app_routes_do_not_reuse_the_same_method_and_path(self):
        routes_by_method_path = defaultdict(list)
        for method, path, endpoint in _app_routes():
            routes_by_method_path[(method, path)].append(endpoint)

        duplicates = {
            route: endpoints
            for route, endpoints in routes_by_method_path.items()
            if len(endpoints) > 1
        }

        self.assertEqual(duplicates, {})

    def test_report_chat_post_route_has_single_persistence_handler(self):
        handlers = [
            endpoint
            for method, path, endpoint in _app_routes()
            if method == "POST" and path == "/api/reports/{research_id}/chat"
        ]

        self.assertEqual(handlers, ["add_report_chat_message"])

    def test_report_status_route_exists(self):
        handlers = [
            endpoint
            for method, path, endpoint in _app_routes()
            if method == "GET" and path == "/api/reports/{research_id}/status"
        ]

        self.assertEqual(handlers, ["get_report_status"])

    def test_trace_run_route_exists(self):
        handlers = [
            endpoint
            for method, path, endpoint in _app_routes()
            if method == "GET" and path == "/api/trace/runs/{run_id}"
        ]

        self.assertEqual(handlers, ["get_trace_run"])


if __name__ == "__main__":
    unittest.main()
