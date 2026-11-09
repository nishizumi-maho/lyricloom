"""The worker side of the WSL model-copy preference: the first complete candidate wins."""
from lyricloom.workers.copies import first_checkpoint_dir, first_file, first_model_dir


def _sized(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_first_file_skips_a_wrong_size_and_falls_back(tmp_path):
    wrong = _sized(tmp_path / "wrong" / "model.pt", b"x")
    inside = _sized(tmp_path / "inside" / "model.pt", b"ok")
    mnt = _sized(tmp_path / "mnt" / "model.pt", b"ok")
    assert first_file([wrong, inside, mnt], 2) == inside
    assert first_file([wrong, tmp_path / "absent"], 2, fallback=mnt) == mnt


def test_first_checkpoint_dir_requires_the_expected_checkpoint(tmp_path):
    wrong = _sized(tmp_path / "wrong" / "checkpoints" / "checkpoint_MTL", b"x")
    inside = _sized(tmp_path / "inside" / "checkpoints" / "checkpoint_MTL", b"ok")
    mnt = _sized(tmp_path / "mnt" / "checkpoints" / "checkpoint_MTL", b"ok")
    assert first_checkpoint_dir([wrong.parent.parent, inside.parent.parent], 2) == inside.parent.parent
    assert first_checkpoint_dir([wrong.parent.parent], 2, fallback=mnt.parent.parent) == mnt.parent.parent


def test_first_model_directory_requires_every_file_and_size(tmp_path):
    inside = tmp_path / "inside"
    _sized(inside / "model.ckpt", b"ckpt")
    _sized(inside / "config.yaml", b"yaml")
    incomplete = tmp_path / "incomplete"
    _sized(incomplete / "model.ckpt", b"ckpt")
    mnt = tmp_path / "mnt"
    _sized(mnt / "model.ckpt", b"ckpt")
    _sized(mnt / "config.yaml", b"yaml")
    required = ["model.ckpt", "config.yaml"]
    sizes = {"model.ckpt": 4, "config.yaml": 4}
    assert first_model_dir([incomplete, inside, mnt], required, sizes) == inside
    assert first_model_dir([incomplete], required, sizes, fallback=mnt) == mnt
    assert first_model_dir([inside], required, {"model.ckpt": 999}, fallback=mnt) == mnt
