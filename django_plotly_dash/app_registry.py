from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from django_plotly_dash.utils import stateless_app_lookup_hook

if TYPE_CHECKING:
    from django_plotly_dash.django_dash import DjangoDash


class AppRegistry:
    """A registry for stateless apps."""

    _stateless_app_lookup_func: Callable | None = None

    def __init__(self):
        self.apps: dict[str, DjangoDash] = {}

    def get(self, name: str) -> DjangoDash:
        """Get a stateless app by name.

        Parameters
        ----------
        name : str
            The name of the app to retrieve.

        Returns
        -------
        DjangoDash
            The stateless app.

        Raises
        ------
        KeyError
            If the app is not found.
        """
        app = self.apps.get(name)
        if app is None:
            app = self.lookup_stateless_app(name)
        if not app:
            # TODO wrap this in raising a 404 if not found
            raise KeyError(f"Unable to find stateless DjangoApp called {name}!")
        return app

    @property
    def lookup_stateless_app(self) -> Callable:
        """Get the stateless app lookup function.

        Returns
        -------
        Callable
            The stateless app lookup function.
        """
        if self._stateless_app_lookup_func is None:
            self._stateless_app_lookup_func = stateless_app_lookup_hook()
        return self._stateless_app_lookup_func


registry = AppRegistry()
