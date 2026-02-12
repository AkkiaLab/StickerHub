import asyncio
import re

from stickerhub.services.binding import BindingService, BindingStore


async def _bind_flow(db_path: str) -> None:
    store = BindingStore(db_path)
    service = BindingService(store=store, magic_ttl_seconds=600)
    await service.initialize()

    first_reply = await service.handle_bind_command("telegram", "tg_user_1", None)
    match = re.search(r"/bind\s+([A-Z0-9]+)", first_reply)
    assert match is not None
    code = match.group(1)

    second_reply = await service.handle_bind_command("feishu", "ou_xxx", code)
    assert "绑定成功" in second_reply

    target = await service.get_target_user_id("telegram", "tg_user_1", "feishu")
    assert target == "ou_xxx"


async def _code_can_only_be_used_once(db_path: str) -> None:
    store = BindingStore(db_path)
    service = BindingService(store=store, magic_ttl_seconds=600)
    await service.initialize()

    first_reply = await service.handle_bind_command("telegram", "tg_user_2", None)
    match = re.search(r"/bind\s+([A-Z0-9]+)", first_reply)
    assert match is not None
    code = match.group(1)

    ok_reply = await service.handle_bind_command("feishu", "ou_aaa", code)
    assert "绑定成功" in ok_reply

    fail_reply = await service.handle_bind_command("feishu", "ou_bbb", code)
    assert "已被使用" in fail_reply


async def _rebind_current_account_to_new_hub(db_path: str) -> None:
    store = BindingStore(db_path)
    service = BindingService(store=store, magic_ttl_seconds=600)
    await service.initialize()

    # 先让 feishu:ou_user 绑定到 hub_a
    tg_a_reply = await service.handle_bind_command("telegram", "tg_a", None)
    code_a = re.search(r"/bind\s+([A-Z0-9]+)", tg_a_reply).group(1)  # type: ignore[union-attr]
    assert "绑定成功" in await service.handle_bind_command("feishu", "ou_user", code_a)

    # 再让同一个 feishu:ou_user 绑定到 hub_b，应该覆盖而不是拦截
    tg_b_reply = await service.handle_bind_command("telegram", "tg_b", None)
    code_b = re.search(r"/bind\s+([A-Z0-9]+)", tg_b_reply).group(1)  # type: ignore[union-attr]
    assert "绑定成功" in await service.handle_bind_command("feishu", "ou_user", code_b)

    assert await service.get_target_user_id("telegram", "tg_b", "feishu") == "ou_user"
    assert await service.get_target_user_id("telegram", "tg_a", "feishu") is None


async def _rebind_replaces_existing_account_on_same_hub(db_path: str) -> None:
    store = BindingStore(db_path)
    service = BindingService(store=store, magic_ttl_seconds=600)
    await service.initialize()

    # hub_x <- feishu:ou_old
    tg_reply = await service.handle_bind_command("telegram", "tg_x", None)
    code_x = re.search(r"/bind\s+([A-Z0-9]+)", tg_reply).group(1)  # type: ignore[union-attr]
    assert "绑定成功" in await service.handle_bind_command("feishu", "ou_old", code_x)

    # 同 hub_x 再绑定 feishu:ou_new，旧账号应让位
    tg_reply2 = await service.handle_bind_command("telegram", "tg_x", None)
    code_x2 = re.search(r"/bind\s+([A-Z0-9]+)", tg_reply2).group(1)  # type: ignore[union-attr]
    assert "绑定成功" in await service.handle_bind_command("feishu", "ou_new", code_x2)

    assert await service.get_target_user_id("telegram", "tg_x", "feishu") == "ou_new"


def test_bind_flow_with_sqlite(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_bind_flow(str(db_path)))


def test_magic_code_single_use(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_code_can_only_be_used_once(str(db_path)))


def test_rebind_current_account_to_new_hub(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_rebind_current_account_to_new_hub(str(db_path)))


def test_rebind_replaces_existing_account_on_same_hub(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_rebind_replaces_existing_account_on_same_hub(str(db_path)))
