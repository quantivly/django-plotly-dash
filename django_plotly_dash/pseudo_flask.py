from flask import Flask


class PseudoFlask(Flask):
    """Dummy implementation of a Flask instance, providing stub functionality."""

    def __init__(self):
        self.config = {"DEBUG": False}
        self.endpoints = {}
        self.name = "PseudoFlaskDummyName"
        self.blueprints = {}
        self._got_first_request = False
        self.before_request_funcs = {}

    # pylint: disable=unused-argument, missing-docstring

    def after_request(self, *args, **kwargs):
        pass

    def errorhandler(self, *args, **kwargs):  # pylint: disable=no-self-use
        def eh_func(f):
            return args[0]

        return eh_func

    def add_url_rule(self, *args, **kwargs):
        route = kwargs["endpoint"]
        self.endpoints[route] = kwargs

    def before_first_request(self, *args, **kwargs):
        pass

    def run(self, *args, **kwargs):
        pass

    def register_blueprint(self, *args, **kwargs):
        pass
