import pytest
from streamlit.testing.v1 import AppTest

from app.services import auth_store

# login gate na webui bloqueia toda a UI atrás de autenticação. Testes de
# outras telas instanciam AppTest esperando a UI completa direto, sem passar
# pelo form de login; pré-autenticar aqui evita reescrever cada um deles.
# O próprio teste do gate (test_webui_login_gate) precisa do estado
# não-autenticado por padrão, então fica de fora.
_LOGIN_GATE_TEST_MODULE = "test_webui_login_gate"


@pytest.fixture(autouse=True)
def _webui_apptest_starts_authenticated(request, tmp_path, monkeypatch):
    if request.module.__name__.rsplit(".", 1)[-1] == _LOGIN_GATE_TEST_MODULE:
        # Esse módulo isola o próprio db (via utils.storage_dir) e precisa do
        # estado não-autenticado por padrão para testar o gate em si.
        yield
        return

    # ensure_account() roda toda vez que webui/Main.py é importado. Sem isolar
    # o db aqui, qualquer teste que instancia AppTest cria um storage/auth.db
    # real no repo do desenvolvedor, com senha que nunca é vista.
    monkeypatch.setattr(
        auth_store, "_default_db_path", lambda: str(tmp_path / "auth.db")
    )

    original_from_file = AppTest.from_file.__func__

    def patched_from_file(cls, *args, **kwargs):
        app = original_from_file(cls, *args, **kwargs)
        app.session_state["authenticated"] = True
        return app

    monkeypatch.setattr(AppTest, "from_file", classmethod(patched_from_file))
    yield
