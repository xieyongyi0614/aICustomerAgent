scene_update_prompt = """你是角色扮演系统的场景状态更新器。根据上一轮场景、用户消息与 AI 回复，识别本轮"刚刚发生了什么"。只记录已经发生的事实，不要脑补接下来要发生的事情。

【上一轮场景】
{scene_snapshot}

【本轮用户消息】
{user_input}

【本轮 AI 回复】
{ai_reply}

输出要求：
- location / current_activity / current_action：仅当场景中明确变化为地点 / 活动 / 正在做的事时填写新值，未变化或不确定则留空（null）
- new_pending_action：仅当用户明确要求角色做一件新的事时才填写，否则为 null
- pending_action_done：当 AI 回复已包含完成待完成动作时才为 true，否则为 false
- current_action_done：当 AI 回复表明上一场景中的"正在做"已经完成时才为 true，否则为 false；"正在做"只代表进行中的事，做完必须置 true
- pending_action_cancel：保持 false，不要自行取消动作（取消由代码确定性处理）

只输出符合 SceneActionDecision 结构的数据。"""
