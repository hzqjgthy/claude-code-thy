from claude_code_thy.session.store import SessionStore


def test_session_store_round_trip(tmp_path):
    """测试 `session_store_round_trip` 场景。"""
    store = SessionStore(root_dir=tmp_path)
    session = store.create(cwd="/tmp/project")
    session.add_message("user", "hello")
    store.save(session)

    loaded = store.load(session.session_id)

    assert loaded.session_id == session.session_id
    assert loaded.cwd == "/tmp/project"
    assert len(loaded.messages) == 1
    assert loaded.messages[0].text == "hello"


def test_session_store_lists_recent_sessions(tmp_path):
    """测试 `session_store_lists_recent_sessions` 场景。"""
    store = SessionStore(root_dir=tmp_path)

    first = store.create(cwd="/tmp/project-a")
    first.add_message("user", "first title")
    store.save(first)

    second = store.create(cwd="/tmp/project-b")
    second.add_message("user", "second title")
    store.save(second)

    recent = store.list_recent()

    assert len(recent) == 2
    assert {item.session_id for item in recent} == {first.session_id, second.session_id}


def test_session_store_writes_summary_index(tmp_path):
    """测试 `session_store_writes_summary_index` 场景。"""
    store = SessionStore(root_dir=tmp_path)
    session = store.create(cwd="/tmp/project")
    session.add_message("user", "hello index")

    store.save(session)

    assert store.index_path.exists()


def test_session_store_lists_recent_from_index_without_reloading_transcripts(tmp_path):
    """测试 `session_store_lists_recent_from_index_without_reloading_transcripts` 场景。"""
    store = SessionStore(root_dir=tmp_path)

    first = store.create(cwd="/tmp/project-a")
    first.add_message("user", "first title")
    store.save(first)

    second = store.create(cwd="/tmp/project-b")
    second.add_message("user", "second title")
    store.save(second)

    # 模拟某个 transcript 文件损坏；recent 列表仍应能靠索引正常工作。
    store.path_for(first.session_id).write_text("{not-json", encoding="utf-8")

    reloaded_store = SessionStore(root_dir=tmp_path)
    recent = reloaded_store.list_recent()

    assert len(recent) == 2
    assert {item.session_id for item in recent} == {first.session_id, second.session_id}
