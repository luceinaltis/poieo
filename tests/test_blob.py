"""A keepsake is a copy, never a meaning: same content, same name, one
copy; a torn write cannot leave a wrong body under a right name; and
nothing here is worth raising over.
"""

import poieo.blob as blob
from poieo.blob import digest, keep, kept


def test_the_same_content_kept_twice_is_one_keepsake(tmp_path):
    one = tmp_path / "a.txt"
    other = tmp_path / "b.txt"
    one.write_text("the same bytes", encoding="utf-8")
    other.write_text("the same bytes", encoding="utf-8")

    first = keep(tmp_path, one)
    second = keep(tmp_path, other)
    assert first == second
    assert len(list((tmp_path / ".poieo" / "blobs").iterdir())) == 1


def test_a_kept_file_reads_back_byte_identical(tmp_path):
    source = tmp_path / "feeds.md"
    source.write_bytes(b"# feeds\x00\xffbinary-ish tail")

    name = keep(tmp_path, source)
    assert kept(tmp_path, name).read_bytes() == source.read_bytes()
    assert digest(source) == name


def test_an_over_cap_file_is_declined(tmp_path, monkeypatch):
    monkeypatch.setattr(blob, "KEEP_CAP", 10)
    fat = tmp_path / "fat.bin"
    fat.write_bytes(b"x" * 11)

    assert keep(tmp_path, fat) is None
    assert not (tmp_path / ".poieo" / "blobs").exists()


def test_the_name_always_matches_the_bytes_actually_kept(tmp_path, monkeypatch):
    # If the file changes between naming and copying, the store would hold
    # wrong bytes under a right name -- so both must come from one read.
    import hashlib

    source = tmp_path / "a.txt"
    source.write_text("first", encoding="utf-8")

    real_digest = blob.digest

    def racy_digest(path):
        name = real_digest(path)
        source.write_text("second", encoding="utf-8")  # the race, made certain
        return name

    monkeypatch.setattr(blob, "digest", racy_digest)
    name = keep(tmp_path, source)

    kept_bytes = kept(tmp_path, name).read_bytes()
    assert hashlib.sha256(kept_bytes).hexdigest() == name


def test_keep_never_raises(tmp_path):
    # A file where .poieo should be: every write must fail, quietly.
    (tmp_path / ".poieo").write_text("in the way", encoding="utf-8")
    source = tmp_path / "a.txt"
    source.write_text("bytes", encoding="utf-8")

    assert keep(tmp_path, source) is None
    assert keep(tmp_path, tmp_path / "missing.txt") is None
    assert kept(tmp_path, "0" * 64) is None


def test_a_file_that_grows_past_the_cap_mid_keep_is_declined(tmp_path, monkeypatch):
    monkeypatch.setattr(blob, "KEEP_CAP", 10)
    source = tmp_path / "a.txt"
    source.write_text("small", encoding="utf-8")  # passes the stat check

    real_read = type(source).read_bytes

    def grown(self):
        data = real_read(self)
        return data * 50 if self.name == "a.txt" else data

    monkeypatch.setattr(type(source), "read_bytes", grown)
    assert keep(tmp_path, source) is None
