import asyncio
import logging
import random
from datetime import datetime
from typing import Optional
from aiocqhttp import CQHttp
import aiocqhttp
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
import astrbot.api.message_components as Comp
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.permission import PermissionType
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# 点赞成功回复
success_responses = [
    "👍{total_likes}",
    "赞了赞了",
    "点赞成功！",
    "给{username}点了{total_likes}个赞",
    "赞送出去啦！一共{total_likes}个哦！",
    "为{username}点赞成功！总共{total_likes}个！",
    "点了{total_likes}个，快查收吧！",
    "赞已送达，请注意查收~ 一共{total_likes}个！",
    "给{username}点了{total_likes}个赞，记得回赞哟！",
    "赞了{total_likes}次，看看收到没？",
    "点了{total_likes}赞，没收到可能是我被风控了",
    "✨ {total_likes}个赞已到账，请查收~",
    "叮咚！{total_likes}个赞已送达{username}",
    "赞力全开！给{username}送了{total_likes}个赞",
    "biu~ {total_likes}个赞发射成功！",
    "{username}的赞+{total_likes}，声望提升！",
    "赞赞赞！一口气点了{total_likes}个",
    "今日份的{total_likes}个赞已安排~",
    "赞不完，根本赞不完！又点了{total_likes}个",
    "赞气满满！{total_likes}个赞请收好",
    "赞力觉醒！给{username}狂点{total_likes}个赞",
    "赞到成功！{total_likes}个赞已送达",
    "赞不绝口！又给{username}点了{total_likes}个",
    "赞力爆棚！今日{total_likes}个赞已送出",
]

# 点赞数到达上限回复
limit_responses = [
    "今天给{username}的赞已达上限",
    "赞了那么多还不够吗？",
    "{username}别太贪心哟~",
    "今天赞过啦！",
    "今天已经赞过啦~",
    "已经赞过啦~",
    "还想要赞？不给了！",
    "已经赞过啦，别再点啦！",
    "今日赞力已耗尽，明天再来吧~",
    "{username}今天已经收获满满啦！",
    "赞力不足，请明日再战！",
    "今日点赞任务已完成✓",
    "赞力恢复中，请稍后再试",
    "今日份的赞已经给{username}啦",
    "赞力有限，明天继续哦~",
    "{username}今天已经被赞爆啦！",
    "赞力CD中，请耐心等待",
    "今日点赞额度已用完",
    "赞力值归零，需要重新充能",
    "{username}今天太受欢迎啦！",
    "赞力过载，系统保护启动",
    "今日点赞成就已达成！",
]

# 陌生人点赞回复
stranger_responses = [
    "不加好友不赞",
    "我和你有那么熟吗？",
    "你谁呀？",
    "你是我什么人凭啥要我赞你？",
    "不想赞你这个陌生人",
    "我不认识你，不赞！",
    "加我好友了吗就想要我赞你？",
    "滚！",
]

# 黑名单回复
blacklist_responses = [
    "❌ 你在黑名单中，无法使用点赞功能",
    "🚫 黑名单用户禁止使用本插件",
    "⛔ 抱歉，你在黑名单中，无法点赞",
    "🔒 黑名单限制，请联系管理员",
    "🚷 禁止访问：你在黑名单中",
    "⚡ 权限被拒绝：你在黑名单中",
    "🛑 操作被阻止：你在黑名单中",
    "⏸️ 暂停服务：你在黑名单中",
    "🔐 访问受限：黑名单用户",
    "🚨 安全警告：黑名单用户禁止操作",
]


@register(
    "astrbot_plugin_zanwo",
    "Futureppo",
    "发送 赞我 自动点赞",
    "1.0.8",
    "https://github.com/Internet1235/astrbot_plugin_zanwo",
)
class zanwo(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.success_responses: list[str] = success_responses
        self._auto_like_tasks = set()

        # 群聊白名单
        self.white_list_groups: list[str] = config.get("white_list_groups", [])
        # 订阅点赞的用户ID列表
        self.subscribed_users: list[str] = config.get("subscribed_users", [])
        # 点赞日期
        self.zanwo_date: Optional[str] = config.get("zanwo_date", None)
        
        # 新增配置项
        self.likes_per_user: int = config.get("likes_per_user", 20)  # 每人点赞次数，默认20
        self.blacklist_users: list[str] = config.get("blacklist_users", [])  # 黑名单
        self.enable_friend_check: bool = config.get("enable_friend_check", False)  # 是否启用好友检查
        
        # 缓存好友列表
        self.friend_list: list[str] = []
        self.last_friend_check: datetime = None

    def _is_group_allowed(self, event: AiocqhttpMessageEvent) -> bool:
        group_id = event.get_group_id()
        if group_id and self.white_list_groups:
            return str(group_id) in self.white_list_groups
        return True

    def _is_blacklisted(self, user_id: str) -> bool:
        """检查用户是否在黑名单中"""
        return user_id in self.blacklist_users

    async def _refresh_friend_list(self, client: CQHttp) -> bool:
        """刷新好友列表 - 添加缓存机制"""
        try:
            # 检查缓存是否过期（5分钟）
            if (self.last_friend_check and 
                (datetime.now() - self.last_friend_check).total_seconds() < 300):
                return True
                
            friends = await client.get_friend_list()
            self.friend_list = [str(friend['user_id']) for friend in friends]
            self.last_friend_check = datetime.now()
            logger.info(f"好友列表已刷新，共 {len(self.friend_list)} 个好友")
            return True
        except Exception as e:
            logger.error(f"刷新好友列表失败: {e}")
            return False

    async def _is_friend(self, client: CQHttp, user_id: str) -> bool:
        """检查是否为好友 - 使用缓存"""
        if not self.enable_friend_check:
            return True  # 如果不启用好友检查，默认返回True
            
        # 确保好友列表是最新的
        await self._refresh_friend_list(client)
        return user_id in self.friend_list

    async def _run_like(
        self, event: AiocqhttpMessageEvent, target_ids: list[str]
    ) -> Optional[str]:
        if not self._is_group_allowed(event):
            return None
        if not target_ids:
            return None
        return await self._like(event.bot, target_ids)

    def _save_zanwo_date(self, date_value: str) -> None:
        self.zanwo_date = date_value
        self.config["zanwo_date"] = date_value
        self.config.save_config()

    async def _trigger_auto_like(self, client: CQHttp):
        today = datetime.now().date().strftime("%Y-%m-%d")
        subscribed_users = list(self.subscribed_users)
        if not subscribed_users or self.zanwo_date == today:
            return
        self._save_zanwo_date(today)
        await self._like(client, subscribed_users)

    def _handle_auto_like_task(self, task: asyncio.Task) -> None:
        self._auto_like_tasks.discard(task)
        try:
            task.result()
        except Exception:
            logger.exception("Auto-like task failed")

    def _schedule_auto_like(self, client: CQHttp) -> None:
        if not self.subscribed_users:
            return
        task = asyncio.create_task(self._trigger_auto_like(client))
        self._auto_like_tasks.add(task)
        task.add_done_callback(self._handle_auto_like_task)

    async def _execute_like_for_user(self, client: CQHttp, user_id: str) -> tuple[int, str]:
        """执行单个用户的点赞逻辑 - 核心点赞函数（从第一个插件合并）"""
        total_likes = 0
        error_reply = ""
        
        remaining_likes = self.likes_per_user
        
        while remaining_likes > 0:
            try:
                like_times = min(10, remaining_likes)
                await client.send_like(user_id=int(user_id), times=like_times)
                total_likes += like_times
                remaining_likes -= like_times
                await asyncio.sleep(1)  # 每次调用后适当休眠，防止风控
                
            except aiocqhttp.exceptions.ActionFailed as e:
                error_message = str(e)
                if "已达" in error_message:
                    error_reply = random.choice(limit_responses)
                elif "权限" in error_message:
                    error_reply = "你设了权限不许陌生人赞你"
                else:
                    error_reply = random.choice(stranger_responses)
                break
            except Exception as e:
                logger.error(f"点赞失败: {e}")
                error_reply = f"点赞失败: {str(e)}"
                break

        return total_likes, error_reply

    async def _like(self, client: CQHttp, ids: list[str]) -> str:
        """
        点赞的核心逻辑（改进版）
        :param client: CQHttp客户端
        :param ids: 用户ID列表
        """
        replys = []
        
        # 如果启用好友检查，先刷新好友列表
        if self.enable_friend_check:
            await self._refresh_friend_list(client)
        
        for id in ids:
            # 检查黑名单
            if self._is_blacklisted(id):
                reply = random.choice(blacklist_responses)
                replys.append(reply)
                continue
            
            # 检查好友（如果启用）
            if self.enable_friend_check and not await self._is_friend(client, id):
                reply = random.choice(stranger_responses)
                replys.append(reply)
                continue
            
            # 获取用户信息
            try:
                user_info = await client.get_stranger_info(user_id=int(id))
                username = user_info.get("nickname", "未知用户")
            except Exception:
                username = "未知用户"
            
            # 执行点赞
            total_likes, error_reply = await self._execute_like_for_user(client, id)
            
            # 生成回复
            if total_likes > 0:
                reply = random.choice(self.success_responses)
            elif error_reply:
                reply = error_reply
            else:
                reply = "点赞失败"
            
            # 替换模板变量
            if "{username}" in reply:
                reply = reply.replace("{username}", username)
            if "{total_likes}" in reply:
                reply = reply.replace("{total_likes}", str(total_likes))
            
            replys.append(reply)

        return "\n".join(replys).strip()

    @staticmethod
    def get_ats(event: AiocqhttpMessageEvent) -> list[str]:
        """获取被at者们的id列表"""
        messages = event.get_messages()
        self_id = event.get_self_id()
        return [
            str(seg.qq)
            for seg in messages
            if (isinstance(seg, Comp.At) and str(seg.qq) != self_id)
        ]

    @filter.regex(r"^赞.*")
    async def like_me(self, event: AiocqhttpMessageEvent):
        """给用户点赞"""
        target_ids = []
        if event.message_str == "赞我":
            target_ids.append(event.get_sender_id())
        if not target_ids:
            target_ids = self.get_ats(event)
        result = await self._run_like(event, target_ids)
        if not result:
            return
        yield event.plain_result(result)
        self._schedule_auto_like(event.bot)

    @filter.llm_tool(name="like_qq_profile")
    async def like_qq_profile(self, event: AiocqhttpMessageEvent, target: str = "self"):
        """给 QQ 名片点赞。

        Args:
            target(string): 点赞目标，可填 self、me、我，或明确的 QQ 号。未明确提供时默认给当前发言者点赞。
        """
        normalized_target = target.strip().lower() if target else "self"
        if normalized_target in {"", "self", "me", "我", "自己", "我自己"}:
            target_ids = [event.get_sender_id()]
        elif target.strip().isdigit():
            target_ids = [target.strip()]
        else:
            return "只能给当前发言者点赞，或给明确提供的 QQ 号点赞。"

        result = await self._run_like(event, target_ids)
        if not result:
            return "当前会话不允许使用点赞功能。"
        self._schedule_auto_like(event.bot)
        return result

    @filter.command("订阅点赞")
    async def subscribe_like(self, event: AiocqhttpMessageEvent):
        """订阅点赞"""
        sender_id = event.get_sender_id()
        
        # 检查黑名单
        if self._is_blacklisted(sender_id):
            yield event.plain_result(random.choice(blacklist_responses))
            return
            
        if sender_id in self.subscribed_users:
            yield event.plain_result("你已经订阅点赞了哦~")
            return
        self.subscribed_users.append(sender_id)
        self.config.save_config()
        yield event.plain_result("订阅成功！我将每天自动为你点赞")

    @filter.command("取消订阅点赞")
    async def unsubscribe_like(self, event: AiocqhttpMessageEvent):
        """取消订阅点赞"""
        sender_id = event.get_sender_id()
        if sender_id not in self.subscribed_users:
            yield event.plain_result("你还没有订阅点赞哦~")
            return
        self.subscribed_users.remove(sender_id)
        self.config.save_config()
        yield event.plain_result("已取消订阅！我将不再自动给你点赞")

    @filter.command("订阅点赞列表")
    async def like_list(self, event: AiocqhttpMessageEvent):
        """查看订阅点赞的用户ID列表"""

        if not self.subscribed_users:
            yield event.plain_result("当前没有订阅点赞的用户哦~")
            return
        users_str = "\n".join(self.subscribed_users).strip()
        yield event.plain_result(f"当前订阅点赞的用户ID列表：\n{users_str}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("谁赞了bot", alias={"谁赞了你"})
    async def get_profile_like(self, event: AiocqhttpMessageEvent):
        """获取bot自身点赞列表"""
        client = event.bot
        data = await client.get_profile_like()
        reply = ""
        user_infos = data.get("favoriteInfo", {}).get("userInfos", [])
        for user in user_infos:
            if (
                "nick" in user
                and user["nick"]
                and "count" in user
                and user["count"] > 0
            ):
                reply += f"\n【{user['nick']}】赞了我{user['count']}次"
        if not reply:
            reply = "暂无有效的点赞信息"
        url = await self.text_to_image(reply)
        yield event.image_result(url)

    # 新增管理命令
    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置点赞次数")
    async def set_like_count(self, event: AiocqhttpMessageEvent, count: str):
        """设置每次点赞次数"""
        try:
            count_int = int(count)
            if count_int <= 0 or count_int > 100:
                yield event.plain_result("❌ 点赞次数必须在 1-100 之间")
                return
            
            self.likes_per_user = count_int
            self.config["likes_per_user"] = count_int
            self.config.save_config()
            
            yield event.plain_result(f"✅ 已设置每次点赞 {count_int} 次")
        except ValueError:
            yield event.plain_result("❌ 请输入正确的数字")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("添加黑名单")
    async def add_blacklist(self, event: AiocqhttpMessageEvent, user_id: str):
        """添加用户到黑名单"""
        try:
            if not user_id.isdigit():
                yield event.plain_result("❌ 格式错误\n💡 请输入正确的QQ号")
                return
                
            if user_id in self.blacklist_users:
                yield event.plain_result(f"❌ 用户 {user_id} 已在黑名单中")
                return
            
            self.blacklist_users.append(user_id)
            self.config["blacklist_users"] = self.blacklist_users
            self.config.save_config()
            
            # 如果用户在订阅列表中，自动取消订阅
            if user_id in self.subscribed_users:
                self.subscribed_users.remove(user_id)
                self.config.save_config()
                logger.info(f"用户 {user_id} 被加入黑名单，已自动取消订阅")
                yield event.plain_result(f"✅ 已添加用户 {user_id} 到黑名单\n⚠️ 已自动取消该用户的订阅")
            else:
                yield event.plain_result(f"✅ 已添加用户 {user_id} 到黑名单")
                
            logger.info(f"管理员添加用户 {user_id} 到黑名单")
            
        except Exception as e:
            logger.error(f"添加黑名单失败: {e}")
            yield event.plain_result(f"❌ 添加黑名单失败\n💡 错误: {e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("移除黑名单")
    async def remove_blacklist(self, event: AiocqhttpMessageEvent, user_id: str):
        """从黑名单移除用户"""
        try:
            if not user_id.isdigit():
                yield event.plain_result("❌ 格式错误\n💡 请输入正确的QQ号")
                return
                
            if user_id not in self.blacklist_users:
                yield event.plain_result(f"❌ 用户 {user_id} 不在黑名单中")
                return
            
            self.blacklist_users.remove(user_id)
            self.config["blacklist_users"] = self.blacklist_users
            self.config.save_config()
            
            yield event.plain_result(f"✅ 已从黑名单移除用户 {user_id}")
            
            logger.info(f"管理员从黑名单移除用户 {user_id}")
            
        except Exception as e:
            logger.error(f"移除黑名单失败: {e}")
            yield event.plain_result(f"❌ 移除黑名单失败\n💡 错误: {e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("查看黑名单")
    async def view_blacklist(self, event: AiocqhttpMessageEvent):
        """查看黑名单用户列表"""
        try:
            if not self.blacklist_users:
                yield event.plain_result("📝 黑名单当前为空")
                return
                
            blacklist_str = "\n".join([f"• {user_id}" for user_id in self.blacklist_users])
            response = f"📋 黑名单用户列表（共 {len(self.blacklist_users)} 人）：\n{blacklist_str}"
            yield event.plain_result(response)
            
        except Exception as e:
            logger.error(f"查看黑名单失败: {e}")
            yield event.plain_result(f"❌ 查看黑名单失败\n💡 错误: {e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("点赞状态")
    async def like_status(self, event: AiocqhttpMessageEvent):
        """查看点赞插件状态"""
        status_info = f"🤖 点赞插件状态\n🔢 每人点赞: {self.likes_per_user} 次\n👥 订阅用户: {len(self.subscribed_users)} 人\n🚫 黑名单用户: {len(self.blacklist_users)} 人\n✅ 好友检查: {'已开启' if self.enable_friend_check else '已关闭'}\n📅 最后点赞日期: {self.zanwo_date or '无'}"
        
        yield event.plain_result(status_info)
