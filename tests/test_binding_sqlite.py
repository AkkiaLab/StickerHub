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


async def _bind_webhook_flow(db_path: str) -> None:
    store = BindingStore(db_path)
    service = BindingService(store=store, magic_ttl_seconds=600)
    await service.initialize()

    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test_webhook"
    reply = await service.handle_bind_webhook("telegram", "tg_webhook", webhook_url)
    assert "绑定成功" in reply

    target = await service.get_feishu_target("telegram", "tg_webhook")
    assert target is not None
    assert target.mode == "webhook"
    assert target.target == webhook_url
    assert await service.get_target_user_id("telegram", "tg_webhook", "feishu") is None


async def _switch_from_bot_to_webhook(db_path: str) -> None:
    store = BindingStore(db_path)
    service = BindingService(store=store, magic_ttl_seconds=600)
    await service.initialize()

    tg_reply = await service.handle_bind_command("telegram", "tg_switch", None)
    code = re.search(r"/bind\s+([A-Z0-9]+)", tg_reply).group(1)  # type: ignore[union-attr]
    assert "绑定成功" in await service.handle_bind_command("feishu", "ou_switch_old", code)

    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/switch_webhook"
    assert "绑定成功" in await service.handle_bind_webhook("telegram", "tg_switch", webhook_url)

    target = await service.get_feishu_target("telegram", "tg_switch")
    assert target is not None
    assert target.mode == "webhook"
    assert target.target == webhook_url
    assert await service.get_target_user_id("telegram", "tg_switch", "feishu") is None


async def _switch_from_webhook_to_bot(db_path: str) -> None:
    store = BindingStore(db_path)
    service = BindingService(store=store, magic_ttl_seconds=600)
    await service.initialize()

    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/switch_back"
    assert "绑定成功" in await service.handle_bind_webhook("telegram", "tg_back", webhook_url)

    tg_reply = await service.handle_bind_command("telegram", "tg_back", None)
    code = re.search(r"/bind\s+([A-Z0-9]+)", tg_reply).group(1)  # type: ignore[union-attr]
    assert "绑定成功" in await service.handle_bind_command("feishu", "ou_new", code)

    target = await service.get_feishu_target("telegram", "tg_back")
    assert target is not None
    assert target.mode == "bot"
    assert target.target == "ou_new"


async def _bind_webhook_invalid_url(db_path: str) -> None:
    store = BindingStore(db_path)
    service = BindingService(store=store, magic_ttl_seconds=600)
    await service.initialize()

    reply = await service.handle_bind_webhook("telegram", "tg_invalid", "http://example.com/abc")
    assert "格式不合法" in reply


async def _test_bind_webhook_domain_whitelist(db_path: str) -> None:
    """测试域名白名单校验（SSRF 防护）"""
    store = BindingStore(db_path)
    # 自定义白名单，仅允许 open.feishu.cn
    service = BindingService(
        store=store, magic_ttl_seconds=600, webhook_allowed_hosts=["open.feishu.cn"]
    )
    await service.initialize()

    # 合法域名应通过
    valid_url = "https://open.feishu.cn/open-apis/bot/v2/hook/valid_token"
    reply = await service.handle_bind_webhook("telegram", "tg_whitelist_ok", valid_url)
    assert "绑定成功" in reply

    # 不在白名单的域名应被拒绝（防止 SSRF）
    blocked_url = "https://evil.com/open-apis/bot/v2/hook/malicious"
    reply = await service.handle_bind_webhook("telegram", "tg_whitelist_block", blocked_url)
    assert "白名单" in reply or "格式不合法" in reply

    # open.larksuite.com 不在自定义白名单中，应被拒绝
    larksuite_url = "https://open.larksuite.com/open-apis/bot/v2/hook/token"
    reply = await service.handle_bind_webhook("telegram", "tg_whitelist_lark", larksuite_url)
    assert "白名单" in reply or "格式不合法" in reply


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


def test_bind_webhook_flow(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_bind_webhook_flow(str(db_path)))


def test_switch_from_bot_to_webhook(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_switch_from_bot_to_webhook(str(db_path)))


def test_switch_from_webhook_to_bot(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_switch_from_webhook_to_bot(str(db_path)))


def test_bind_webhook_invalid_url(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_bind_webhook_invalid_url(str(db_path)))


def test_bind_webhook_domain_whitelist(tmp_path) -> None:
    db_path = tmp_path / "binding.db"
    asyncio.run(_test_bind_webhook_domain_whitelist(str(db_path)))
