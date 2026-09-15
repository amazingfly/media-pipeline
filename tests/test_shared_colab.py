from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import Mock

from requests.exceptions import ReadTimeout
from media_workspace.colab_tunnel import ping_tunnel
from media_workspace.colab_token import refresh_session_state
from media_workspace.colab_artifact import stream_text
import pytest


def test_tunnel_read_timeout_still_counts_as_keepalive():
    session=SimpleNamespace(endpoint='fixture')
    state=SimpleNamespace(store=Mock(),client=SimpleNamespace(colab_domain='https://example.test',session=Mock()))
    state.store.get.return_value=session
    state.client.session.get.side_effect=ReadTimeout()
    args=Namespace(session='test',authuser=0,request_timeout=1)
    result=ping_tunnel(args,state)
    assert result['ok'] and result['read_timeout']
    assert state.client.session.get.call_args.kwargs['headers']=={'X-Colab-Tunnel':'Google'}


def test_missing_session_does_not_request_network():
    state=SimpleNamespace(store=Mock(),client=Mock())
    state.store.get.return_value=None
    assert not ping_tunnel(Namespace(session='missing'),state)['ok']
    state.client.session.get.assert_not_called()


def test_refresh_keeps_session_identity_and_updates_proxy():
    session=SimpleNamespace(endpoint='same',token='old',url='old-url')
    proxy=SimpleNamespace(token='new',url='new-url',token_expires_in_seconds=10)
    state=SimpleNamespace(store=Mock(),client=Mock())
    state.store.get.return_value=session
    state.client.list_assignments.return_value=[SimpleNamespace(endpoint='same',runtime_proxy_info=proxy)]
    assert refresh_session_state(state,'test')==(True,10)
    state.store.add.assert_called_once_with(session)
    assert session.endpoint=='same'


def test_artifact_kernel_errors_cannot_be_treated_as_data():
    assert stream_text([{'output_type':'stream','text':'hello'}])=='hello'
    with pytest.raises(RuntimeError,match='failed'):
        stream_text([{'output_type':'error','evalue':'failed'}])


def test_frontend_reconnect_uses_same_connection_path():
    import asyncio
    from unittest.mock import AsyncMock, patch
    from media_workspace import colab_frontend
    page = SimpleNamespace(wait_for_timeout=AsyncMock())
    with patch.object(colab_frontend, 'connect_text', AsyncMock(side_effect=['Reconnect','Connected'])):
        with patch.object(colab_frontend, 'click_connect', AsyncMock()) as connect:
            assert asyncio.run(colab_frontend.wait_until_connected(page)) == 'Connected'
            connect.assert_awaited_once_with(page)
