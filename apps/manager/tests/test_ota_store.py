"""独立存储、输入边界与断裂对象的定向验证。"""
import os
import sqlite3
import pytest
from manager.ota_store import OtaStore, strict_json, digest

@pytest.fixture
def store(tmp_path):
    value=OtaStore(tmp_path/'ota');value.initialize();return value

def test_read_does_not_initialize(tmp_path):
    value=OtaStore(tmp_path/'absent')
    with pytest.raises(sqlite3.Error):
        with value.db():pass
    assert not value.root.exists()

def test_objects_backup_and_unknown_schema(store,tmp_path):
    key=store.put(b'fixed bytes','test');assert store.put(b'fixed bytes','test')==key
    assert store.read(key)==b'fixed bytes'
    copy=store.backup(tmp_path/'backup');assert copy.read(key)==b'fixed bytes'
    with sqlite3.connect(copy.root/'state.sqlite3') as db:
        db.execute('DROP TABLE ota_schema');db.execute('CREATE TABLE ota_schema(version INTEGER)');db.execute('INSERT INTO ota_schema VALUES(2)')
    with pytest.raises(ValueError):copy.verify()

def test_orphan_retry_and_hardlink_rejected(store):
    raw=b'orphan';key=digest(raw);path=store.root/'objects'/key;path.write_bytes(raw);path.chmod(0o600)
    assert store.put(raw,'test')==key
    os.link(path,store.root/'extra')
    with pytest.raises(ValueError):store.read(key)

def test_corruption_short_reads_symlinks_and_permissions(store,tmp_path):
    key=store.put(b'payload','wire');assert store.chunk(key,0)==b'payload'
    with pytest.raises(ValueError):store.chunk(key,1)
    path=store.root/'objects'/key;path.write_bytes(b'changed')
    with pytest.raises(ValueError):store.read(key)
    path.unlink();outside=tmp_path/'outside';outside.write_bytes(b'payload');path.symlink_to(outside)
    with pytest.raises(OSError):store.read(key)
    path.unlink();path.write_bytes(b'payload');path.chmod(0o644)
    with pytest.raises(ValueError):store.read(key)

@pytest.mark.parametrize('raw',[b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1.5}',b'"\xff"',b'{"n":9007199254740992}',b'[[[[[[[[[[0]]]]]]]]]]'])
def test_strict_json_rejects_non_contract_values(raw):
    with pytest.raises(ValueError):strict_json(raw)

def test_object_fsync_failure_never_registers(store,monkeypatch):
    def failed(_):raise OSError('fixture')
    monkeypatch.setattr(os,'fsync',failed)
    with pytest.raises(OSError):store.put(b'not committed','test')
    with store.db() as db:assert not db.execute('SELECT 1 FROM ota_objects').fetchone()

def test_explicit_restore_raises_sequence_to_independent_signing_ledger(store,tmp_path,monkeypatch):
    from manager.ota_publish import main
    import sys
    backup=tmp_path/'backup';store.put(b'baseline material','test');store.backup(backup)
    ledger=tmp_path/'ledger.sqlite3'
    with sqlite3.connect(ledger) as db:
        db.execute('CREATE TABLE signatures(model TEXT,channel TEXT,sequence INTEGER)');db.execute("INSERT INTO signatures VALUES('966U2','stable',42)")
    restored=tmp_path/'restored'
    monkeypatch.setattr(sys,'argv',['ota_publish','--root',str(restored),'restore',str(backup),'--signing-ledger',str(ledger)])
    main()
    with OtaStore(restored).db() as db:assert db.execute('SELECT next_sequence FROM ota_sequences').fetchone()[0]==43

def test_private_subdirectory_permissions_are_enforced(store):
    key=store.put(b'private','test');(store.root/'objects').chmod(0o755)
    with pytest.raises(ValueError):store.read(key)
