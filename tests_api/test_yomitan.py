"""Yomitan's legacy version-2 request shapes against native Anki services.

Reviewed against yomidevs/yomitan ext/js/comm/anki-connect.js and its
backend, note builder, and settings deck generator. Qt scheduling is controlled;
GUI effects and network sync belong to the disposable-profile smoke scenarios.
"""
import base64
import json
from pathlib import Path

import pytest

from plugin.web import WebRequest, WebServer
from plugin.protocol import completed
from tests_api.test_runtime import admitted, call, native


def exchange(owner, drain, request):
    pending = owner.server.handlerWrapper(WebRequest(b'POST', {
        b'origin': b'chrome-extension://yomitan',
    }, json.dumps(request).encode()))
    drain()
    response = pending.value if hasattr(pending, 'value') else pending
    headers, body = response.split(b'\r\n\r\n', 1)
    assert headers.startswith(b'HTTP/1.1 200 OK')
    assert b'Content-Length: ' + str(len(body)).encode() in headers
    return json.loads(body)


@pytest.mark.parametrize('api_key', [None, 'test-key'])
def test_yomitan_mining_lookup_overwrite_media_and_suspension(admitted, monkeypatch, api_key):
    from plugin import util
    owner, service, drain, work, notifications = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', api_key)

    def request(action, **params):
        return {'action': action, 'version': 2, 'params': params, 'key': api_key}

    def invoke(action, **params):
        return exchange(owner, drain, request(action, **params))

    assert invoke('version') == 6
    assert 'Default' in invoke('deckNames')
    assert 'Basic' in invoke('modelNames')
    assert invoke('modelFieldNames', modelName='Basic') == ['Front', 'Back']
    assert invoke('apiReflect', scopes=['actions'], actions=['guiEditNote']) == {
        'scopes': ['actions'], 'actions': ['guiEditNote']}
    audio = b'yomitan audio'
    filename = invoke('storeMediaFile', filename='yomitan_audio_hash.mp3',
                      data=base64.b64encode(audio).decode())
    assert filename == 'yomitan_audio_hash.mp3'
    assert (Path(service.col.media.dir()) / filename).read_bytes() == audio
    source = {'deckName': 'Default', 'modelName': 'Basic', 'tags': ['yomitan'],
              'fields': {'Front': '日本語', 'Back': '[sound:' + filename + ']'},
              'options': {'allowDuplicate': True, 'duplicateScope': 'deck',
                          'duplicateScopeOptions': {'deckName': None, 'checkChildren': False,
                                                    'checkAllModels': False}}}
    id = invoke('addNote', note=source)
    assert type(id) is int
    probe = {**source, 'fields': {'Front': '日本語'}, 'options': {**source['options'], 'allowDuplicate': False}}
    assert invoke('canAddNotesWithErrorDetail', notes=[probe]) == [{
        'canAdd': False, 'error': 'cannot create note because it is a duplicate'}]
    assert invoke('canAddNotes', notes=[probe]) == [False]
    # findNoteIds uses a union query followed by multi entries without versions.
    query = '("deck:Default" "front:日本語") or ("deck:Default" "front:other")'
    assert invoke('findNotes', query=query) == [id]
    actions = [{'action': 'findNotes', 'key': api_key, 'params': {
        'query': 'nid:' + str(id) + ' ("deck:Default" "front:' + word + '")'}}
        for word in ('日本語', 'other')]
    assert invoke('multi', actions=actions) == [[id], []]
    infos = invoke('notesInfo', notes=[id, 999])
    assert infos[0]['noteId'] == id and infos[0]['modelName'] == 'Basic'
    assert infos[0]['tags'] == ['yomitan'] and infos[1] == {}
    assert infos[0]['fields']['Front'] == {'value': '日本語', 'order': 0}
    cards = invoke('findCards', query='nid:' + str(id))
    assert cards == infos[0]['cards'] and all(type(card) is int for card in cards)
    info = invoke('cardsInfo', cards=[*cards, 999])
    assert info[0]['note'] == id and type(info[0]['flags']) is int and info[1] == {}
    assert invoke('suspend', cards=cards) is True
    assert invoke('cardsInfo', cards=cards)[0]['queue'] == -1
    # Yomitan spreads the complete note input into its overwrite request.
    assert invoke('updateNoteFields', note={**source, 'id': id,
                  'fields': {'Front': '日本語', 'Back': 'overwritten'}, 'tags': ['ignored']}) is None
    updated = invoke('notesInfo', notes=[id])[0]
    assert updated['fields']['Back']['value'] == 'overwritten'
    assert updated['tags'] == ['yomitan']
    # The settings deck generator submits groups of 100 notes.
    sources = [{**source, 'fields': {'Front': 'bulk ' + str(index), 'Back': 'answer'}} for index in range(100)]
    ids = invoke('addNotes', notes=sources)
    assert len(ids) == 100 and len(set(ids)) == 100 and all(type(value) is int for value in ids)
    assert service.col.note_count() == 101
    assert invoke('addNotes', notes=[]) == []
    assert invoke('canAddNotesWithErrorDetail', notes=[]) == []
    owner.window().pm.sync_auth = lambda: None
    assert invoke('sync') == {'result': None, 'error': 'sync: auth not configured'}
    assert invoke('notAnAction') == {'result': None, 'error': 'unsupported action'}
    assert notifications and owner.window()._background_op_count == 0


def test_yomitan_root_deck_and_all_models_duplicate_options(admitted):
    owner, service, drain, work, notifications = admitted
    call(service, 'decks.create', name='Parent::Source')
    call(service, 'decks.create', name='Parent::Destination')
    call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Parent::Source'},
         fields={'Front': 'root duplicate', 'Back': 'answer'})
    call(service, 'noteTypes.create', name='Other', fields=[{'name': 'Front'}],
         templates=[{'name': 'Card', 'questionHtml': '{{Front}}', 'answerHtml': '{{Front}}'}])
    call(service, 'notes.create', noteType={'name': 'Other'}, deck={'name': 'Default'},
         fields={'Front': 'other model duplicate'})

    def probe(front, scope, deck, children=False, all_models=False):
        source = {'deckName': 'Parent::Destination', 'modelName': 'Basic', 'fields': {'Front': front},
                  'options': {'allowDuplicate': False, 'duplicateScope': scope,
                              'duplicateScopeOptions': {'deckName': deck, 'checkChildren': children,
                                                        'checkAllModels': all_models}}}
        return exchange(owner, drain, {'action': 'canAddNotesWithErrorDetail', 'version': 2,
                                       'params': {'notes': [source]}})[0]

    duplicate = {'canAdd': False, 'error': 'cannot create note because it is a duplicate'}
    assert probe('root duplicate', 'deck', 'Parent', children=True) == duplicate
    assert probe('root duplicate', 'deck', 'Parent') == {'canAdd': True}
    assert probe('other model duplicate', 'collection', None) == {'canAdd': True}
    assert probe('other model duplicate', 'collection', None, all_models=True) == duplicate


@pytest.mark.parametrize('version', [2, 4, 6])
def test_legacy_null_result_is_json_and_notification_and_preflight_are_empty(version, monkeypatch):
    from plugin import util
    monkeypatch.setattr(util, 'setting', lambda key: util.DEFAULT_CONFIG[key])
    value = None if version <= 4 else {'result': None, 'error': None}
    server = WebServer(lambda request: completed(value), lambda request, context: completed(None))
    raw = server.handlerWrapper(WebRequest(b'POST', {}, json.dumps({
        'action': 'updateNoteFields', 'version': version, 'params': {'note': {}}}).encode())).value
    headers, body = raw.split(b'\r\n\r\n', 1)
    assert json.loads(body) == value
    if version <= 4:
        assert body == b'null' and b'Content-Length: 4\r\n' in headers + b'\r\n'
    for request in [WebRequest(b'OPTIONS', {}, b''),
                    WebRequest(b'POST', {}, b'{"jsonrpc":"2.0","method":"collection.get"}', b'/api/v1')]:
        reply = server.handlerWrapper(request)
        raw = reply.value if hasattr(reply, 'value') else reply
        assert raw.split(b'\r\n\r\n', 1)[1] == b''

