from stickerhub.adapters.feishu_longconn import _parse_bind_command


def test_parse_bind_without_arg() -> None:
    assert _parse_bind_command("/bind") == (True, None)


def test_parse_bind_with_arg() -> None:
    assert _parse_bind_command("/bind F3D6A205") == (True, "F3D6A205")


def test_parse_bind_with_mention_prefix() -> None:
    assert _parse_bind_command("@机器人 /bind F3D6A205") == (True, "F3D6A205")


def test_parse_bind_not_matched() -> None:
    assert _parse_bind_command("hello world") == (False, None)
