"""The model catalog served from ``GET /v1/models``.

A static, single-entry catalog built from configuration. It makes no network
call, so the model dropdown renders even when the Upstream is unreachable or
misconfigured — see ``docs/design-decisions.md`` for the reasoning. The
advertised id is the real upstream model name, not an alias: it is forwarded
unchanged, so there is nothing here to rewrite.
"""

from app.models import ModelList, ModelObject
from app.ports import ModelCatalog


class StaticCatalog(ModelCatalog):
    """Implements the ``ModelCatalog`` Protocol with exactly one entry.

    The model id is injected via the constructor rather than read from
    ``Settings`` directly, keeping this class free of any dependency on how
    configuration is loaded.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def list_models(self) -> ModelList:
        return ModelList(data=[ModelObject(id=self._model_id)])
